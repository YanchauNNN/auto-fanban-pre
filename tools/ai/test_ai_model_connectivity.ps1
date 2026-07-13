param(
    [string]$ConfigPath = "",
    [string]$Profile = "",
    [string]$OutputPath = "",
    [string]$BaseUrl = "",
    [string]$ChatModel = "",
    [string]$ApiKeyEnvVar = "",
    [switch]$SkipModels,
    [switch]$SkipChat,
    [switch]$SkipStream,
    [switch]$SkipAdvanced,
    [switch]$SkipMultimodal,
    [int]$Concurrency = -1,
    [string]$McpUrl = "",
    [string]$McpSseUrl = "",
    [string]$McpStdioCommand = "",
    [string[]]$McpStdioArguments = @(),
    [switch]$SslNoRevoke
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-UtcIsoTimestamp {
    return (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
}

function Get-FileSha256 {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

function ConvertTo-StringArray {
    param([object]$Value)

    if ($null -eq $Value) {
        return @()
    }
    if ($Value -is [System.Array]) {
        return @($Value | ForEach-Object { [string]$_ })
    }

    $text = ([string]$Value).Trim()
    if ([string]::IsNullOrWhiteSpace($text)) {
        return @()
    }
    if ($text.StartsWith("[") -and $text.EndsWith("]")) {
        try {
            return @($text | ConvertFrom-Json | ForEach-Object { [string]$_ })
        } catch {
            return @($text)
        }
    }
    return @($text)
}

function Resolve-FullPathOrRaw {
    param([string]$PathText)

    if ([string]::IsNullOrWhiteSpace($PathText)) {
        return ""
    }

    try {
        return (Resolve-Path -LiteralPath $PathText -ErrorAction Stop).Path
    } catch {
        try {
            return [System.IO.Path]::GetFullPath($PathText)
        } catch {
            return $PathText
        }
    }
}

function Resolve-RepoOrPackageRoot {
    $candidates = @(
        (Join-Path $PSScriptRoot ".."),
        (Join-Path $PSScriptRoot "..\.."),
        (Get-Location).Path
    )

    foreach ($candidate in $candidates) {
        $resolved = Resolve-FullPathOrRaw $candidate
        if ([string]::IsNullOrWhiteSpace($resolved)) {
            continue
        }
        if ((Test-Path -LiteralPath (Join-Path $resolved "documents") -PathType Container) -or
            (Test-Path -LiteralPath (Join-Path $resolved "backend-runtime") -PathType Container)) {
            return $resolved
        }
    }

    return Resolve-FullPathOrRaw (Get-Location).Path
}

function Resolve-DefaultConfigPath {
    $root = Resolve-RepoOrPackageRoot
    $candidates = @(
        (Join-Path $root "documents\AI\ai_model_gateway.yaml"),
        (Join-Path $PSScriptRoot "..\documents\AI\ai_model_gateway.yaml"),
        (Join-Path $PSScriptRoot "..\..\documents\AI\ai_model_gateway.yaml"),
        (Join-Path (Get-Location).Path "documents\AI\ai_model_gateway.yaml")
    )

    foreach ($candidate in $candidates) {
        $resolved = Resolve-FullPathOrRaw $candidate
        if (Test-Path -LiteralPath $resolved -PathType Leaf) {
            return $resolved
        }
    }

    return Resolve-FullPathOrRaw $candidates[0]
}

function Convert-SimpleYamlScalar {
    param([string]$Raw)

    $value = $Raw.Trim()
    if ($value.StartsWith('"') -and $value.EndsWith('"') -and $value.Length -ge 2) {
        return $value.Substring(1, $value.Length - 2)
    }
    if ($value.StartsWith("'") -and $value.EndsWith("'") -and $value.Length -ge 2) {
        return $value.Substring(1, $value.Length - 2)
    }
    if ($value -match '^(?i:true|false)$') {
        return [System.Convert]::ToBoolean($value)
    }
    $intValue = 0
    if ([int]::TryParse($value, [ref]$intValue)) {
        return $intValue
    }
    return $value
}

function Read-ModelAccessConfig {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "AI model access config not found: $Path"
    }

    $root = @{}
    $profiles = @{}
    $inProfiles = $false
    $currentProfile = ""

    foreach ($rawLine in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $line = $rawLine.TrimEnd()
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        if ($line.TrimStart().StartsWith("#")) {
            continue
        }

        if ($line -match '^profiles:\s*$') {
            $inProfiles = $true
            $currentProfile = ""
            continue
        }

        if ($inProfiles -and $line -match '^  ([A-Za-z0-9_.-]+):\s*$') {
            $currentProfile = $Matches[1]
            $profiles[$currentProfile] = @{}
            continue
        }

        if ($inProfiles -and $line -match '^    ([A-Za-z0-9_]+):\s*(.*)$') {
            if ([string]::IsNullOrWhiteSpace($currentProfile)) {
                continue
            }
            $profiles[$currentProfile][$Matches[1]] = Convert-SimpleYamlScalar $Matches[2]
            continue
        }

        if ($line -match '^([A-Za-z0-9_]+):\s*(.*)$') {
            $inProfiles = $false
            $currentProfile = ""
            $root[$Matches[1]] = Convert-SimpleYamlScalar $Matches[2]
            continue
        }
    }

    return [PSCustomObject]@{
        root = $root
        profiles = $profiles
    }
}

function Join-EndpointUrl {
    param(
        [string]$BaseUrl,
        [string]$Path
    )

    $base = $BaseUrl.TrimEnd("/")
    $suffix = $Path
    if ([string]::IsNullOrWhiteSpace($suffix)) {
        return $base
    }
    if (-not $suffix.StartsWith("/")) {
        $suffix = "/" + $suffix
    }
    return $base + $suffix
}

function Get-SecretFingerprint {
    param([string]$Secret)

    if ([string]::IsNullOrEmpty($Secret)) {
        return $null
    }

    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Secret)
        $hash = $sha.ComputeHash($bytes)
        $hex = -join ($hash | ForEach-Object { $_.ToString("x2") })
        return $hex.Substring(0, 12)
    } finally {
        $sha.Dispose()
    }
}

function Get-UrlHostAndPort {
    param([string]$Url)

    $uri = [System.Uri]$Url
    $port = $uri.Port
    if ($port -lt 0) {
        if ($uri.Scheme -eq "https") {
            $port = 443
        } elseif ($uri.Scheme -eq "http") {
            $port = 80
        }
    }

    return [PSCustomObject]@{
        scheme = $uri.Scheme
        host = $uri.Host
        port = $port
    }
}

function Get-SanitizedUrl {
    param([string]$Url)

    if ([string]::IsNullOrWhiteSpace($Url)) {
        return ""
    }

    try {
        $uri = [System.Uri]$Url
        $builder = [System.UriBuilder]$uri
        $builder.UserName = ""
        $builder.Password = ""
        $builder.Query = ""
        $builder.Fragment = ""
        return $builder.Uri.AbsoluteUri.TrimEnd("/")
    } catch {
        return "<invalid-url>"
    }
}

function Invoke-CurlJson {
    param(
        [string]$Url,
        [string]$Method = "GET",
        [string]$Body = "",
        [hashtable]$Headers = @{},
        [int]$TimeoutSec = 60,
        [switch]$UseSslNoRevoke
)

    if ($UseSslNoRevoke) {
        [void]$null
    }
    return Invoke-HttpRequest -Url $Url -Method $Method -Body $Body -Headers $Headers -TimeoutSec $TimeoutSec
}

function Invoke-CurlStream {
    param(
        [string]$Url,
        [string]$Body,
        [hashtable]$Headers = @{},
        [int]$TimeoutSec = 60,
        [switch]$UseSslNoRevoke
    )

    if ($UseSslNoRevoke) {
        [void]$null
    }
    $response = Invoke-HttpRequest -Url $Url -Method "POST" -Body $Body -Headers $Headers -TimeoutSec $TimeoutSec
    $response | Add-Member -NotePropertyName data_line_count -NotePropertyValue @($response.body -split "`r?`n" | Where-Object { $_ -like "data:*" }).Count
    return $response
}

function Invoke-HttpRequest {
    param(
        [string]$Url,
        [string]$Method = "GET",
        [string]$Body = "",
        [hashtable]$Headers = @{},
        [int]$TimeoutSec = 60
    )

    [System.Net.ServicePointManager]::SecurityProtocol = (
        [System.Net.SecurityProtocolType]::Tls12 -bor
        [System.Net.SecurityProtocolType]::Tls11 -bor
        [System.Net.SecurityProtocolType]::Tls
    )

    $request = [System.Net.HttpWebRequest]::Create($Url)
    $request.Method = $Method.ToUpperInvariant()
    $request.Timeout = [Math]::Max(1, $TimeoutSec) * 1000
    $request.ReadWriteTimeout = [Math]::Max(1, $TimeoutSec) * 1000
    $request.UserAgent = "fanban-ai-connectivity/0.1"

    foreach ($key in $Headers.Keys) {
        $value = [string]$Headers[$key]
        if ($key -ieq "Accept") {
            $request.Accept = $value
            continue
        }
        if ($key -ieq "Content-Type") {
            $request.ContentType = $value
            continue
        }
        $request.Headers[$key] = $value
    }

    if ($request.Method -eq "POST") {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Body)
        $request.ContentLength = $bytes.Length
        $stream = $request.GetRequestStream()
        try {
            $stream.Write($bytes, 0, $bytes.Length)
        } finally {
            $stream.Dispose()
        }
    }

    $response = $null
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $response = $request.GetResponse()
        $status = [int]([System.Net.HttpWebResponse]$response).StatusCode
        $reader = [System.IO.StreamReader]::new($response.GetResponseStream(), [System.Text.Encoding]::UTF8)
        $content = $reader.ReadToEnd()
        $reader.Dispose()
        $stopwatch.Stop()
        $responseHeaders = [ordered]@{}
        foreach ($headerName in $response.Headers.AllKeys) {
            $responseHeaders[$headerName] = [string]$response.Headers[$headerName]
        }
        return [PSCustomObject]@{
            status_code = $status
            body = $content
            body_preview = if ($content.Length -gt 1000) { $content.Substring(0, 1000) } else { $content }
            content_type = [string]$response.ContentType
            content_length = [long]$response.ContentLength
            final_url = [string]$response.ResponseUri.AbsoluteUri
            elapsed_ms = [long]$stopwatch.ElapsedMilliseconds
            response_headers = [PSCustomObject]$responseHeaders
        }
    } catch [System.Net.WebException] {
        $errorResponse = $_.Exception.Response
        if ($null -ne $errorResponse) {
            $status = [int]([System.Net.HttpWebResponse]$errorResponse).StatusCode
            $reader = [System.IO.StreamReader]::new($errorResponse.GetResponseStream(), [System.Text.Encoding]::UTF8)
            $content = $reader.ReadToEnd()
            $reader.Dispose()
            $stopwatch.Stop()
            $responseHeaders = [ordered]@{}
            foreach ($headerName in $errorResponse.Headers.AllKeys) {
                $responseHeaders[$headerName] = [string]$errorResponse.Headers[$headerName]
            }
            return [PSCustomObject]@{
                status_code = $status
                body = $content
                body_preview = if ($content.Length -gt 1000) { $content.Substring(0, 1000) } else { $content }
                content_type = [string]$errorResponse.ContentType
                content_length = [long]$errorResponse.ContentLength
                final_url = [string]$errorResponse.ResponseUri.AbsoluteUri
                elapsed_ms = [long]$stopwatch.ElapsedMilliseconds
                response_headers = [PSCustomObject]$responseHeaders
            }
        }
        throw
    } finally {
        $stopwatch.Stop()
        if ($null -ne $response) {
            $response.Dispose()
        }
    }
}

function ConvertTo-JsonObjectOrNull {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return $null
    }
    try {
        return $Text | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Get-JsonPropertyValue {
    param(
        [object]$Object,
        [string]$Name
    )

    if ($null -eq $Object) {
        return $null
    }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }
    return $property.Value
}

function ConvertFrom-StreamResponse {
    param([string]$Body)

    $parts = [System.Collections.ArrayList]::new()
    $parsedEventCount = 0
    $invalidDataLineCount = 0
    $doneReceived = $false
    $toolFragments = @{}
    foreach ($line in ($Body -split "`r?`n")) {
        $trimmed = $line.Trim()
        if (-not $trimmed.StartsWith("data:")) {
            continue
        }
        $payload = $trimmed.Substring(5).Trim()
        if ([string]::IsNullOrWhiteSpace($payload)) {
            continue
        }
        if ($payload -eq "[DONE]") {
            $doneReceived = $true
            continue
        }

        $json = ConvertTo-JsonObjectOrNull $payload
        if ($null -eq $json) {
            $invalidDataLineCount += 1
            continue
        }
        $parsedEventCount += 1
        $choices = Get-JsonPropertyValue $json "choices"
        if ($null -eq $choices) {
            continue
        }
        foreach ($choice in @($choices)) {
            $delta = Get-JsonPropertyValue $choice "delta"
            $content = Get-JsonPropertyValue $delta "content"
            if ($null -ne $content) {
                [void]$parts.Add([string]$content)
            }
            $deltaToolCalls = Get-JsonPropertyValue $delta "tool_calls"
            foreach ($toolCall in @($deltaToolCalls)) {
                if ($null -eq $toolCall) {
                    continue
                }
                $indexValue = Get-JsonPropertyValue $toolCall "index"
                $index = if ($null -eq $indexValue) { "0" } else { [string]$indexValue }
                if (-not $toolFragments.ContainsKey($index)) {
                    $toolFragments[$index] = [ordered]@{
                        index = [int]$index
                        id = ""
                        name = ""
                        arguments_raw = ""
                    }
                }
                $fragment = $toolFragments[$index]
                $id = Get-JsonPropertyValue $toolCall "id"
                if ($null -ne $id) {
                    $fragment.id += [string]$id
                }
                $function = Get-JsonPropertyValue $toolCall "function"
                $name = Get-JsonPropertyValue $function "name"
                if ($null -ne $name) {
                    $fragment.name += [string]$name
                }
                $arguments = Get-JsonPropertyValue $function "arguments"
                if ($null -ne $arguments) {
                    $fragment.arguments_raw += [string]$arguments
                }
            }
        }
    }

    $toolCalls = [System.Collections.ArrayList]::new()
    foreach ($key in @($toolFragments.Keys | Sort-Object { [int]$_ })) {
        $fragment = $toolFragments[$key]
        $parsedArguments = ConvertTo-JsonObjectOrNull $fragment.arguments_raw
        [void]$toolCalls.Add([PSCustomObject]@{
            index = $fragment.index
            id = $fragment.id
            name = $fragment.name
            arguments_raw = $fragment.arguments_raw
            arguments = $parsedArguments
            arguments_valid = $null -ne $parsedArguments
        })
    }

    return [PSCustomObject]@{
        content = ($parts -join "")
        tool_calls = @($toolCalls)
        parsed_event_count = $parsedEventCount
        invalid_data_line_count = $invalidDataLineCount
        done_received = $doneReceived
    }
}

function Add-DiagnosticError {
    param(
        [System.Collections.ArrayList]$Errors,
        [string]$Stage,
        [string]$Message
    )

    [void]$Errors.Add([PSCustomObject]@{
        stage = $Stage
        message = $Message
    })
}

function New-ReadinessResult {
    param(
        [ValidateSet("passed", "failed", "unsupported", "inconclusive", "not_configured", "not_installed", "skipped")]
        [string]$Status,
        [string]$Summary,
        [string[]]$Checks = @()
    )

    return [PSCustomObject]@{
        status = $Status
        summary = $Summary
        checks = @($Checks)
    }
}

function New-CapabilityResult {
    param(
        [string]$Name,
        [bool]$Required = $false,
        [string]$Status = "skipped"
    )

    return [PSCustomObject]@{
        name = $Name
        status = $Status
        required = $Required
        attempted = $false
        status_code = $null
        elapsed_ms = $null
        content_preview = ""
        body_preview = ""
        finish_reason = $null
        tool_calls = @()
        usage = $null
        error = $null
    }
}

function ConvertFrom-ToolCalls {
    param([object]$Message)

    $items = [System.Collections.ArrayList]::new()
    $rawCalls = Get-JsonPropertyValue $Message "tool_calls"
    foreach ($rawCall in @($rawCalls)) {
        if ($null -eq $rawCall) {
            continue
        }
        $function = Get-JsonPropertyValue $rawCall "function"
        $argumentsRaw = [string](Get-JsonPropertyValue $function "arguments")
        $arguments = ConvertTo-JsonObjectOrNull $argumentsRaw
        [void]$items.Add([PSCustomObject]@{
            id = [string](Get-JsonPropertyValue $rawCall "id")
            type = [string](Get-JsonPropertyValue $rawCall "type")
            name = [string](Get-JsonPropertyValue $function "name")
            arguments_raw = $argumentsRaw
            arguments = $arguments
            arguments_valid = $null -ne $arguments
        })
    }
    return @($items)
}

function Invoke-ChatCapabilityProbe {
    param(
        [string]$Name,
        [string]$Url,
        [string]$Model,
        [object[]]$Messages,
        [hashtable]$Headers,
        [int]$TimeoutSec,
        [hashtable]$ExtraPayload = @{},
        [string]$ExpectedContains = "",
        [string]$ExpectedToolName = "",
        [bool]$Required = $false,
        [bool]$Stream = $false,
        [switch]$UseSslNoRevoke
    )

    $result = New-CapabilityResult -Name $Name -Required $Required
    $result.attempted = $true
    $payload = @{
        model = $Model
        stream = $Stream
        messages = @($Messages)
        temperature = 0
        max_tokens = 192
    }
    foreach ($key in $ExtraPayload.Keys) {
        $payload[$key] = $ExtraPayload[$key]
    }
    $requestHeaders = $Headers.Clone()
    $requestHeaders["Content-Type"] = "application/json"
    if ($Stream) {
        $requestHeaders["Accept"] = "text/event-stream"
    }

    try {
        $body = $payload | ConvertTo-Json -Depth 24 -Compress
        $response = if ($Stream) {
            Invoke-CurlStream -Url $Url -Headers $requestHeaders -Body $body -TimeoutSec $TimeoutSec -UseSslNoRevoke:$UseSslNoRevoke
        } else {
            Invoke-CurlJson -Url $Url -Method "POST" -Headers $requestHeaders -Body $body -TimeoutSec $TimeoutSec -UseSslNoRevoke:$UseSslNoRevoke
        }
        $result.status_code = $response.status_code
        $result.elapsed_ms = $response.elapsed_ms
        $result.body_preview = $response.body_preview
        if ($response.status_code -ne 200) {
            $result.status = if ($response.status_code -in @(400, 404, 405, 415, 422)) { "unsupported" } else { "failed" }
            $result.error = "HTTP $($response.status_code)"
            return $result
        }

        if ($Stream) {
            $parsedStream = ConvertFrom-StreamResponse $response.body
            $result.content_preview = if ($parsedStream.content.Length -gt 600) { $parsedStream.content.Substring(0, 600) } else { $parsedStream.content }
            $result.tool_calls = @($parsedStream.tool_calls)
        } else {
            $json = ConvertTo-JsonObjectOrNull $response.body
            $choices = Get-JsonPropertyValue $json "choices"
            $choice = if (@($choices).Count -gt 0) { @($choices)[0] } else { $null }
            $message = Get-JsonPropertyValue $choice "message"
            $content = Get-JsonPropertyValue $message "content"
            $contentText = if ($null -eq $content) { "" } else { [string]$content }
            $result.content_preview = if ($contentText.Length -gt 600) { $contentText.Substring(0, 600) } else { $contentText }
            $result.finish_reason = Get-JsonPropertyValue $choice "finish_reason"
            $result.tool_calls = @(ConvertFrom-ToolCalls $message)
            $result.usage = Get-JsonPropertyValue $json "usage"
        }

        if (-not [string]::IsNullOrWhiteSpace($ExpectedToolName)) {
            $matching = @($result.tool_calls | Where-Object { $_.name -eq $ExpectedToolName -and $_.arguments_valid })
            $result.status = if ($matching.Count -gt 0) { "passed" } else { "inconclusive" }
        } elseif (-not [string]::IsNullOrWhiteSpace($ExpectedContains)) {
            $result.status = if ($result.content_preview.Contains($ExpectedContains)) { "passed" } else { "inconclusive" }
        } else {
            $result.status = "passed"
        }
    } catch {
        $result.status = "failed"
        $result.error = $_.Exception.Message
    }
    return $result
}

function Invoke-ResponsesCapabilityProbe {
    param(
        [string]$Url,
        [string]$Model,
        [hashtable]$Headers,
        [int]$TimeoutSec,
        [switch]$UseSslNoRevoke
    )

    $result = New-CapabilityResult -Name "responses_api"
    if ([string]::IsNullOrWhiteSpace($Url)) {
        $result.status = "not_configured"
        return $result
    }
    $result.attempted = $true
    $requestHeaders = $Headers.Clone()
    $requestHeaders["Content-Type"] = "application/json"
    $payload = @{
        model = $Model
        input = "Reply exactly: RESPONSES_API_OK_7319"
        max_output_tokens = 64
    } | ConvertTo-Json -Depth 8 -Compress
    try {
        $response = Invoke-CurlJson -Url $Url -Method "POST" -Headers $requestHeaders -Body $payload -TimeoutSec $TimeoutSec -UseSslNoRevoke:$UseSslNoRevoke
        $result.status_code = $response.status_code
        $result.elapsed_ms = $response.elapsed_ms
        $result.body_preview = $response.body_preview
        if ($response.status_code -ne 200) {
            $result.status = if ($response.status_code -in @(400, 404, 405, 415, 422)) { "unsupported" } else { "failed" }
            $result.error = "HTTP $($response.status_code)"
            return $result
        }
        $json = ConvertTo-JsonObjectOrNull $response.body
        $content = [string](Get-JsonPropertyValue $json "output_text")
        if ([string]::IsNullOrWhiteSpace($content)) {
            $parts = [System.Collections.ArrayList]::new()
            foreach ($outputItem in @(Get-JsonPropertyValue $json "output")) {
                foreach ($contentItem in @(Get-JsonPropertyValue $outputItem "content")) {
                    $text = Get-JsonPropertyValue $contentItem "text"
                    if ($null -ne $text) { [void]$parts.Add([string]$text) }
                }
            }
            $content = $parts -join ""
        }
        $result.content_preview = if ($content.Length -gt 600) { $content.Substring(0, 600) } else { $content }
        $result.status = if ($content.Contains("RESPONSES_API_OK_7319")) { "passed" } else { "inconclusive" }
    } catch {
        $result.status = "failed"
        $result.error = $_.Exception.Message
    }
    return $result
}

function Get-ReadinessStatus {
    param([object[]]$Results)

    $statuses = @($Results | ForEach-Object { $_.status })
    if ($statuses.Count -eq 0 -or @($statuses | Where-Object { $_ -eq "skipped" }).Count -eq $statuses.Count) {
        return "skipped"
    }
    if ($statuses -contains "failed") {
        return "failed"
    }
    if ($statuses -contains "inconclusive") {
        return "inconclusive"
    }
    if ($statuses -contains "unsupported") {
        return "unsupported"
    }
    if (@($statuses | Where-Object { $_ -eq "passed" }).Count -gt 0) {
        return "passed"
    }
    return "inconclusive"
}

function New-ProbeImageDataUrl {
    Add-Type -AssemblyName System.Drawing -ErrorAction Stop
    $bitmap = [System.Drawing.Bitmap]::new(640, 240)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $font = $null
    $stream = $null
    try {
        $graphics.Clear([System.Drawing.Color]::White)
        $graphics.FillRectangle([System.Drawing.Brushes]::Red, 20, 20, 120, 120)
        $font = [System.Drawing.Font]::new("Arial", 30, [System.Drawing.FontStyle]::Bold)
        $graphics.DrawString("VISION_MARKER_7319", $font, [System.Drawing.Brushes]::Black, 155, 62)
        $stream = [System.IO.MemoryStream]::new()
        $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
        return "data:image/png;base64," + [Convert]::ToBase64String($stream.ToArray())
    } finally {
        if ($null -ne $stream) { $stream.Dispose() }
        if ($null -ne $font) { $font.Dispose() }
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

function Get-PythonRuntimeInventory {
    param([string]$Root)

    $candidatePaths = [System.Collections.ArrayList]::new()
    foreach ($path in @(
        (Join-Path $Root "python-runtime\python.exe"),
        (Join-Path $Root "backend\.venv\Scripts\python.exe"),
        (Join-Path $Root "backend-runtime\.venv\Scripts\python.exe")
    )) {
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            [void]$candidatePaths.Add((Resolve-FullPathOrRaw $path))
        }
    }
    $command = Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $command) {
        [void]$candidatePaths.Add((Resolve-FullPathOrRaw $command.Source))
    }
    $uniqueCandidates = @($candidatePaths | Select-Object -Unique)
    $packages = [PSCustomObject]@{
        openai = [PSCustomObject]@{ installed = $false; version = $null }
        agents = [PSCustomObject]@{ installed = $false; version = $null }
        mcp = [PSCustomObject]@{ installed = $false; version = $null }
    }
    $selectedPython = if ($uniqueCandidates.Count -gt 0) { $uniqueCandidates[0] } else { $null }
    $pythonVersion = $null
    $errorText = $null
    if ($null -ne $selectedPython) {
        $pythonCode = @'
import importlib.metadata as md
import importlib.util
import json
import platform

items = {}
for module, distribution in (("openai", "openai"), ("agents", "openai-agents"), ("mcp", "mcp")):
    installed = importlib.util.find_spec(module) is not None
    version = None
    if installed:
        try:
            version = md.version(distribution)
        except Exception:
            version = "unknown"
    items[module] = {"installed": installed, "version": version}
print(json.dumps({"python_version": platform.python_version(), "packages": items}))
'@
        try {
            $output = & $selectedPython -c $pythonCode 2>&1
            if ($LASTEXITCODE -eq 0) {
                $parsed = ConvertTo-JsonObjectOrNull (($output | Out-String).Trim())
                if ($null -ne $parsed) {
                    $pythonVersion = [string]$parsed.python_version
                    $packages = $parsed.packages
                }
            } else {
                $errorText = (($output | Out-String).Trim())
            }
        } catch {
            $errorText = $_.Exception.Message
        }
    }

    return [PSCustomObject]@{
        powershell_version = $PSVersionTable.PSVersion.ToString()
        os_version = [Environment]::OSVersion.VersionString
        timezone = (Get-TimeZone).Id
        local_time = (Get-Date).ToString("o")
        utc_time = Get-UtcIsoTimestamp
        python_candidates = @($uniqueCandidates)
        selected_python = $selectedPython
        python_version = $pythonVersion
        packages = $packages
        error = $errorText
    }
}

function Invoke-LowLoadConcurrencyProbe {
    param(
        [string]$Url,
        [string]$Model,
        [hashtable]$Headers,
        [int]$TimeoutSec,
        [int]$Count
    )

    $result = [PSCustomObject]@{
        status = if ($Count -gt 1) { "inconclusive" } else { "skipped" }
        attempted = $Count -gt 1
        requested = [Math]::Max(0, $Count)
        succeeded = 0
        failed = 0
        throttled = 0
        status_codes = @()
        elapsed_ms = $null
        error = $null
    }
    if ($Count -le 1) {
        return $result
    }

    Add-Type -AssemblyName System.Net.Http -ErrorAction Stop
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $client = [System.Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds([Math]::Max(1, $TimeoutSec))
    $entries = [System.Collections.ArrayList]::new()
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        for ($index = 0; $index -lt $Count; $index += 1) {
            $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Post, $Url)
            foreach ($headerName in $Headers.Keys) {
                if ($headerName -ieq "Content-Type") { continue }
                [void]$request.Headers.TryAddWithoutValidation($headerName, [string]$Headers[$headerName])
            }
            $payload = @{
                model = $Model
                stream = $false
                messages = @(@{ role = "user"; content = "CONCURRENCY_PROBE_7319 request $index" })
                temperature = 0
                max_tokens = 32
            } | ConvertTo-Json -Depth 8 -Compress
            $request.Content = [System.Net.Http.StringContent]::new($payload, [System.Text.Encoding]::UTF8, "application/json")
            [void]$entries.Add([PSCustomObject]@{
                request = $request
                task = $client.SendAsync($request)
            })
        }
        $statusCodes = [System.Collections.ArrayList]::new()
        foreach ($entry in $entries) {
            try {
                $response = $entry.task.GetAwaiter().GetResult()
                try {
                    $statusCode = [int]$response.StatusCode
                    [void]$statusCodes.Add($statusCode)
                    $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
                    $json = ConvertTo-JsonObjectOrNull $body
                    $choices = Get-JsonPropertyValue $json "choices"
                    $firstChoice = if (@($choices).Count -gt 0) { @($choices)[0] } else { $null }
                    $message = Get-JsonPropertyValue $firstChoice "message"
                    $content = Get-JsonPropertyValue $message "content"
                    $toolCalls = Get-JsonPropertyValue $message "tool_calls"
                    $validCompletion = (
                        $null -ne $message -and
                        ((-not [string]::IsNullOrWhiteSpace([string]$content)) -or @($toolCalls).Count -gt 0)
                    )
                    if ($statusCode -eq 200 -and $validCompletion) {
                        $result.succeeded += 1
                    } else {
                        $result.failed += 1
                        if ($statusCode -in @(429, 503)) { $result.throttled += 1 }
                    }
                } finally {
                    $response.Dispose()
                }
            } catch {
                $result.failed += 1
                $result.error = $_.Exception.Message
            }
        }
        $result.status_codes = @($statusCodes)
        $result.status = if ($result.succeeded -eq $Count) { "passed" } elseif ($result.succeeded -gt 0) { "inconclusive" } else { "failed" }
    } catch {
        $result.status = "failed"
        $result.error = $_.Exception.Message
    } finally {
        $stopwatch.Stop()
        $result.elapsed_ms = [long]$stopwatch.ElapsedMilliseconds
        foreach ($entry in $entries) { $entry.request.Dispose() }
        $client.Dispose()
        $handler.Dispose()
    }
    return $result
}

function ConvertFrom-McpResponseBody {
    param([string]$Body)

    $direct = ConvertTo-JsonObjectOrNull $Body
    if ($null -ne $direct) { return $direct }
    foreach ($line in ($Body -split "`r?`n")) {
        if ($line.Trim().StartsWith("data:")) {
            $parsed = ConvertTo-JsonObjectOrNull $line.Trim().Substring(5).Trim()
            if ($null -ne $parsed) { return $parsed }
        }
    }
    return $null
}

function Invoke-McpStreamableHttpProbe {
    param(
        [string]$Url,
        [int]$TimeoutSec,
        [hashtable]$AdditionalHeaders = @{}
    )

    $result = [PSCustomObject]@{
        status = if ([string]::IsNullOrWhiteSpace($Url)) { "not_configured" } else { "inconclusive" }
        attempted = -not [string]::IsNullOrWhiteSpace($Url)
        url = Get-SanitizedUrl $Url
        protocol_version = $null
        session_id = $null
        server_name = $null
        server_version = $null
        ping_ok = $false
        tool_count = 0
        resource_count = 0
        prompt_count = 0
        elapsed_ms = $null
        error = $null
    }
    if ([string]::IsNullOrWhiteSpace($Url)) { return $result }

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $headers = @{
            Accept = "application/json, text/event-stream"
            "Content-Type" = "application/json"
        }
        foreach ($headerName in $AdditionalHeaders.Keys) {
            $headers[$headerName] = $AdditionalHeaders[$headerName]
        }
        $initializePayload = [ordered]@{
            jsonrpc = "2.0"
            id = 1
            method = "initialize"
            params = [ordered]@{
                protocolVersion = "2025-06-18"
                capabilities = [ordered]@{}
                clientInfo = [ordered]@{ name = "fanban-ai-connectivity"; version = "0.3" }
            }
        } | ConvertTo-Json -Depth 12 -Compress
        $initializeResponse = Invoke-CurlJson -Url $Url -Method "POST" -Headers $headers -Body $initializePayload -TimeoutSec $TimeoutSec
        if ($initializeResponse.status_code -ne 200) {
            $result.status = if ($initializeResponse.status_code -in @(400, 404, 405, 415, 422)) { "unsupported" } else { "failed" }
            $result.error = "MCP initialize returned HTTP $($initializeResponse.status_code)"
            return $result
        }
        $initializeJson = ConvertFrom-McpResponseBody $initializeResponse.body
        $initializeResult = Get-JsonPropertyValue $initializeJson "result"
        if ($null -eq $initializeResult) {
            $result.status = "inconclusive"
            $result.error = "MCP initialize response did not contain a result."
            return $result
        }
        $result.protocol_version = [string](Get-JsonPropertyValue $initializeResult "protocolVersion")
        $serverInfo = Get-JsonPropertyValue $initializeResult "serverInfo"
        $result.server_name = [string](Get-JsonPropertyValue $serverInfo "name")
        $result.server_version = [string](Get-JsonPropertyValue $serverInfo "version")
        $sessionHeader = $initializeResponse.response_headers.PSObject.Properties | Where-Object { $_.Name -ieq "Mcp-Session-Id" } | Select-Object -First 1
        if ($null -ne $sessionHeader) {
            $result.session_id = [string]$sessionHeader.Value
            $headers["Mcp-Session-Id"] = $result.session_id
        }

        $requestId = 2
        $calls = @(
            @{ name = "initialized"; method = "notifications/initialized"; params = @{} },
            @{ name = "ping"; method = "ping"; params = @{} },
            @{ name = "tools"; method = "tools/list"; params = @{} },
            @{ name = "resources"; method = "resources/list"; params = @{} },
            @{ name = "prompts"; method = "prompts/list"; params = @{} }
        )
        foreach ($call in $calls) {
            $payloadObject = [ordered]@{
                jsonrpc = "2.0"
                method = $call.method
                params = $call.params
            }
            $isNotification = $call.method -eq "notifications/initialized"
            if (-not $isNotification) {
                $payloadObject.id = $requestId
                $requestId += 1
            }
            $payload = $payloadObject | ConvertTo-Json -Depth 10 -Compress
            $response = Invoke-CurlJson -Url $Url -Method "POST" -Headers $headers -Body $payload -TimeoutSec $TimeoutSec
            if ($response.status_code -notin @(200, 202, 204)) {
                throw "MCP $($call.method) returned HTTP $($response.status_code)"
            }
            if ($isNotification) { continue }
            $json = ConvertFrom-McpResponseBody $response.body
            $callResult = Get-JsonPropertyValue $json "result"
            if ($call.name -eq "ping") { $result.ping_ok = $null -ne $callResult }
            if ($call.name -eq "tools") { $result.tool_count = @(Get-JsonPropertyValue $callResult "tools").Count }
            if ($call.name -eq "resources") { $result.resource_count = @(Get-JsonPropertyValue $callResult "resources").Count }
            if ($call.name -eq "prompts") { $result.prompt_count = @(Get-JsonPropertyValue $callResult "prompts").Count }
        }
        $result.status = if ($result.ping_ok) { "passed" } else { "inconclusive" }
    } catch {
        $result.status = "failed"
        $result.error = $_.Exception.Message
    } finally {
        $stopwatch.Stop()
        $result.elapsed_ms = [long]$stopwatch.ElapsedMilliseconds
    }
    return $result
}

$startedAt = Get-UtcIsoTimestamp
$root = Resolve-RepoOrPackageRoot
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Resolve-DefaultConfigPath
} else {
    $ConfigPath = Resolve-FullPathOrRaw $ConfigPath
}

$config = Read-ModelAccessConfig $ConfigPath
$selectedProfile = $Profile
if ([string]::IsNullOrWhiteSpace($selectedProfile)) {
    $selectedProfile = [string]$config.root["active_profile"]
}
if ([string]::IsNullOrWhiteSpace($selectedProfile)) {
    throw "No active_profile found in $ConfigPath and -Profile was not provided."
}
if (-not $config.profiles.ContainsKey($selectedProfile)) {
    throw "Profile '$selectedProfile' not found in $ConfigPath."
}

$profileConfig = $config.profiles[$selectedProfile]
if (-not [string]::IsNullOrWhiteSpace($BaseUrl)) {
    $profileConfig["base_url"] = $BaseUrl
}
if (-not [string]::IsNullOrWhiteSpace($ChatModel)) {
    $profileConfig["chat_model"] = $ChatModel
}
if (-not [string]::IsNullOrWhiteSpace($ApiKeyEnvVar)) {
    $profileConfig["api_key_env_var"] = $ApiKeyEnvVar
}
if ($SslNoRevoke) {
    $profileConfig["ssl_no_revoke"] = $true
}

$baseUrl = [string]$profileConfig["base_url"]
$modelsPath = [string]$profileConfig["models_path"]
$chatPath = [string]$profileConfig["chat_completions_path"]
$responsesPath = [string]$profileConfig["responses_path"]
$chatModel = [string]$profileConfig["chat_model"]
$apiKeyEnvVar = [string]$profileConfig["api_key_env_var"]
$apiKeyRequired = [bool]$profileConfig["api_key_required"]
$streamEnabled = [bool]$profileConfig["stream_enabled"]
$modelListRequired = [bool]$profileConfig["model_list_required"]
$networkMode = [string]$profileConfig["network_mode"]
$allowedHosts = @(ConvertTo-StringArray $profileConfig["allowed_hosts"])
$mcpAllowedHosts = @(ConvertTo-StringArray $profileConfig["mcp_allowed_hosts"])
if ($mcpAllowedHosts.Count -eq 0) {
    $mcpAllowedHosts = @($allowedHosts)
}
$timeoutSec = [int]$profileConfig["timeout_sec"]
$sslNoRevokeConfig = [bool]$profileConfig["ssl_no_revoke"]
$testPrompt = [string]$profileConfig["test_prompt"]
$expectedResponseContains = [string]$profileConfig["expected_response_contains"]
$agentProbeEnabled = if ($null -eq $profileConfig["agent_probe_enabled"]) { $false } else { [bool]$profileConfig["agent_probe_enabled"] }
$multimodalProbeEnabled = if ($null -eq $profileConfig["multimodal_probe_enabled"]) { $false } else { [bool]$profileConfig["multimodal_probe_enabled"] }
$configuredConcurrency = if ($null -eq $profileConfig["concurrency_probe_count"]) { 0 } else { [int]$profileConfig["concurrency_probe_count"] }
if ($Concurrency -ge 0) {
    $configuredConcurrency = $Concurrency
}
$mcpStreamableHttpUrl = if (-not [string]::IsNullOrWhiteSpace($McpUrl)) { $McpUrl } else { [string]$profileConfig["mcp_streamable_http_url"] }
$mcpLegacySseUrl = if (-not [string]::IsNullOrWhiteSpace($McpSseUrl)) { $McpSseUrl } else { [string]$profileConfig["mcp_sse_url"] }
$mcpCommand = if (-not [string]::IsNullOrWhiteSpace($McpStdioCommand)) { $McpStdioCommand } else { [string]$profileConfig["mcp_stdio_command"] }
$mcpApiKeyEnvVar = [string]$profileConfig["mcp_api_key_env_var"]

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $stamp = (Get-Date).ToString("yyyyMMdd-HHmmss")
    $OutputPath = Join-Path $root ("storage\ai\diagnostics\ai-connectivity-{0}.json" -f $stamp)
} else {
    $OutputPath = Resolve-FullPathOrRaw $OutputPath
}

$errors = [System.Collections.ArrayList]::new()
$warnings = [System.Collections.ArrayList]::new()
$apiKey = ""
if (-not [string]::IsNullOrWhiteSpace($apiKeyEnvVar)) {
    $apiKey = [Environment]::GetEnvironmentVariable($apiKeyEnvVar)
}
if ($apiKeyRequired -and [string]::IsNullOrWhiteSpace($apiKey)) {
    Add-DiagnosticError $errors "auth" ("Required API key env var is missing or empty: {0}" -f $apiKeyEnvVar)
}

$headers = @{
    "Accept" = "application/json"
}
if (-not [string]::IsNullOrWhiteSpace($apiKey)) {
    $headers["Authorization"] = "Bearer $apiKey"
}

$endpoint = Get-UrlHostAndPort $baseUrl
$normalizedAllowedHosts = @(
    $allowedHosts |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        ForEach-Object { $_.Trim().ToLowerInvariant() }
)
$normalizedMcpAllowedHosts = @(
    $mcpAllowedHosts |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        ForEach-Object { $_.Trim().ToLowerInvariant() }
)
$networkPolicyBlocked = $false
if ($networkMode -eq "intranet_only") {
    if ($normalizedAllowedHosts.Count -eq 0) {
        Add-DiagnosticError $errors "config" "Intranet-only profile requires a non-empty allowed_hosts list."
        $networkPolicyBlocked = $true
    } elseif (-not ($normalizedAllowedHosts -contains $endpoint.host.ToLowerInvariant())) {
        Add-DiagnosticError $errors "config" (
            "Base URL host '{0}' is not allowed by intranet profile '{1}'." -f
            $endpoint.host,
            $selectedProfile
        )
        $networkPolicyBlocked = $true
    }
}
$dnsResult = [PSCustomObject]@{
    attempted = -not $networkPolicyBlocked
    ok = $false
    host = $endpoint.host
    addresses = @()
    error = $null
}
if (-not $networkPolicyBlocked) {
    try {
        $addresses = [System.Net.Dns]::GetHostAddresses($endpoint.host) | ForEach-Object { $_.IPAddressToString }
        $dnsResult.addresses = @($addresses)
        $dnsResult.ok = $dnsResult.addresses.Count -gt 0
    } catch {
        $dnsResult.error = $_.Exception.Message
        Add-DiagnosticError $errors "dns" $_.Exception.Message
    }
}

$tcpResult = [PSCustomObject]@{
    attempted = -not $networkPolicyBlocked
    ok = $false
    host = $endpoint.host
    port = $endpoint.port
    error = $null
}
if (-not $networkPolicyBlocked) {
    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        try {
            $async = $client.BeginConnect($endpoint.host, $endpoint.port, $null, $null)
            $connected = $async.AsyncWaitHandle.WaitOne([TimeSpan]::FromSeconds([int]$profileConfig["connect_timeout_sec"]))
            if ($connected) {
                $client.EndConnect($async)
                $tcpResult.ok = $true
            } else {
                $tcpResult.error = "TCP connect timed out"
                Add-DiagnosticError $errors "tcp" $tcpResult.error
            }
        } finally {
            $client.Close()
        }
    } catch {
        $tcpResult.error = $_.Exception.Message
        Add-DiagnosticError $errors "tcp" $_.Exception.Message
    }
}

$modelsResult = [PSCustomObject]@{
    attempted = (-not $SkipModels) -and (-not $networkPolicyBlocked)
    ok = $false
    required = $modelListRequired
    url = Join-EndpointUrl $baseUrl $modelsPath
    status_code = $null
    model_count = 0
    models = @()
    body_preview = ""
    content_type = ""
    content_length = $null
    final_url = ""
    elapsed_ms = $null
    error = $null
}
if ((-not $SkipModels) -and (-not $networkPolicyBlocked)) {
    try {
        $modelResponse = Invoke-CurlJson -Url $modelsResult.url -Headers $headers -TimeoutSec $timeoutSec -UseSslNoRevoke:$sslNoRevokeConfig
        $modelsResult.status_code = $modelResponse.status_code
        $modelsResult.body_preview = $modelResponse.body_preview
        $modelsResult.content_type = $modelResponse.content_type
        $modelsResult.content_length = $modelResponse.content_length
        $modelsResult.final_url = $modelResponse.final_url
        $modelsResult.elapsed_ms = $modelResponse.elapsed_ms
        if ($modelResponse.status_code -eq 200) {
            $modelJson = ConvertTo-JsonObjectOrNull $modelResponse.body
            $items = @()
            if ($null -ne $modelJson -and $null -ne $modelJson.data) {
                $items = @($modelJson.data)
            }
            $modelIds = @()
            foreach ($item in $items) {
                if ($null -ne $item.id) {
                    $modelIds += [string]$item.id
                } elseif ($null -ne $item.model) {
                    $modelIds += [string]$item.model
                } elseif ($null -ne $item.name) {
                    $modelIds += [string]$item.name
                }
            }
            $modelsResult.models = @($modelIds)
            $modelsResult.model_count = $modelsResult.models.Count
            $modelsResult.ok = $true
        } elseif ($modelListRequired) {
            Add-DiagnosticError $errors "models" ("Model list request failed with HTTP {0}" -f $modelResponse.status_code)
        } else {
            [void]$warnings.Add("Model list request failed but model_list_required is false.")
        }
    } catch {
        $modelsResult.error = $_.Exception.Message
        if ($modelListRequired) {
            Add-DiagnosticError $errors "models" $_.Exception.Message
        } else {
            [void]$warnings.Add("Model list request failed but model_list_required is false: " + $_.Exception.Message)
        }
    }
}

$chatResult = [PSCustomObject]@{
    attempted = (-not $SkipChat) -and (-not $networkPolicyBlocked)
    ok = $false
    url = Join-EndpointUrl $baseUrl $chatPath
    status_code = $null
    model = $chatModel
    finish_reason = $null
    response_contains_expected = $false
    content_preview = ""
    body_preview = ""
    content_type = ""
    content_length = $null
    final_url = ""
    elapsed_ms = $null
    error = $null
}
if ((-not $SkipChat) -and (-not $networkPolicyBlocked)) {
    try {
        $chatHeaders = $headers.Clone()
        $chatHeaders["Content-Type"] = "application/json"
        $payload = @{
            model = $chatModel
            stream = $false
            messages = @(
                @{ role = "system"; content = "You are a connectivity test assistant. Return a short final answer." },
                @{ role = "user"; content = $testPrompt }
            )
            temperature = 0.1
            max_tokens = 128
        } | ConvertTo-Json -Depth 8
        $chatResponse = Invoke-CurlJson -Url $chatResult.url -Method "POST" -Headers $chatHeaders -Body $payload -TimeoutSec $timeoutSec -UseSslNoRevoke:$sslNoRevokeConfig
        $chatResult.status_code = $chatResponse.status_code
        $chatResult.body_preview = $chatResponse.body_preview
        $chatResult.content_type = $chatResponse.content_type
        $chatResult.content_length = $chatResponse.content_length
        $chatResult.final_url = $chatResponse.final_url
        $chatResult.elapsed_ms = $chatResponse.elapsed_ms
        if ($chatResponse.status_code -eq 200) {
            $chatJson = ConvertTo-JsonObjectOrNull $chatResponse.body
            if ($null -ne $chatJson -and $null -ne $chatJson.choices -and @($chatJson.choices).Count -gt 0) {
                $choice = @($chatJson.choices)[0]
                $content = ""
                if ($null -ne $choice.message -and $null -ne $choice.message.content) {
                    $content = [string]$choice.message.content
                }
                $chatResult.finish_reason = $choice.finish_reason
                $chatResult.content_preview = if ($content.Length -gt 600) { $content.Substring(0, 600) } else { $content }
                $chatResult.response_contains_expected = $chatResult.content_preview.Contains($expectedResponseContains)
                $chatResult.ok = $chatResult.response_contains_expected
                if (-not $chatResult.ok) {
                    Add-DiagnosticError $errors "chat" "Chat response did not contain expected marker."
                }
            } else {
                Add-DiagnosticError $errors "chat" "Chat response JSON did not contain choices."
            }
        } else {
            Add-DiagnosticError $errors "chat" ("Chat request failed with HTTP {0}" -f $chatResponse.status_code)
        }
    } catch {
        $chatResult.error = $_.Exception.Message
        Add-DiagnosticError $errors "chat" $_.Exception.Message
    }
}

$streamResult = [PSCustomObject]@{
    attempted = (-not $SkipStream) -and $streamEnabled -and (-not $networkPolicyBlocked)
    ok = $false
    url = Join-EndpointUrl $baseUrl $chatPath
    status_code = $null
    model = $chatModel
    data_line_count = 0
    parsed_event_count = 0
    invalid_data_line_count = 0
    done_received = $false
    response_contains_expected = $false
    content_preview = ""
    body_preview = ""
    content_type = ""
    content_length = $null
    final_url = ""
    elapsed_ms = $null
    error = $null
}
if ((-not $SkipStream) -and $streamEnabled -and (-not $networkPolicyBlocked)) {
    try {
        $streamHeaders = $headers.Clone()
        $streamHeaders["Content-Type"] = "application/json"
        $streamHeaders["Accept"] = "text/event-stream"
        $payload = @{
            model = $chatModel
            stream = $true
            messages = @(
                @{ role = "system"; content = "You are a streaming connectivity test assistant." },
                @{ role = "user"; content = $testPrompt }
            )
            temperature = 0.1
            max_tokens = 128
        } | ConvertTo-Json -Depth 8
        $streamResponse = Invoke-CurlStream -Url $streamResult.url -Headers $streamHeaders -Body $payload -TimeoutSec $timeoutSec -UseSslNoRevoke:$sslNoRevokeConfig
        $streamResult.status_code = $streamResponse.status_code
        $streamResult.body_preview = $streamResponse.body_preview
        $streamResult.content_type = $streamResponse.content_type
        $streamResult.content_length = $streamResponse.content_length
        $streamResult.final_url = $streamResponse.final_url
        $streamResult.elapsed_ms = $streamResponse.elapsed_ms
        $streamResult.data_line_count = $streamResponse.data_line_count
        $streamDiagnostics = ConvertFrom-StreamResponse $streamResponse.body
        $streamContent = [string]$streamDiagnostics.content
        $streamResult.parsed_event_count = $streamDiagnostics.parsed_event_count
        $streamResult.invalid_data_line_count = $streamDiagnostics.invalid_data_line_count
        $streamResult.done_received = $streamDiagnostics.done_received
        $streamResult.content_preview = if ($streamContent.Length -gt 600) { $streamContent.Substring(0, 600) } else { $streamContent }
        $streamResult.response_contains_expected = $streamContent.Contains($expectedResponseContains) -or $streamResponse.body.Contains($expectedResponseContains)
        $streamResult.ok = ($streamResponse.status_code -eq 200) -and ($streamResult.data_line_count -gt 0) -and $streamResult.response_contains_expected
        if (-not $streamResult.ok) {
            Add-DiagnosticError $errors "stream" "Stream response failed or did not contain expected marker."
        }
    } catch {
        $streamResult.error = $_.Exception.Message
        Add-DiagnosticError $errors "stream" $_.Exception.Message
    }
}

$agentProbeNames = @(
    "responses_api",
    "system_instruction",
    "multi_turn_memory",
    "json_object",
    "json_schema",
    "named_tool_choice",
    "tool_round_trip",
    "parallel_tool_calls",
    "streamed_tool_calls"
)
$agentProbeResults = @{}
foreach ($probeName in $agentProbeNames) {
    $agentProbeResults[$probeName] = New-CapabilityResult -Name $probeName
}
$routingGeneralResult = New-CapabilityResult -Name "general_conversation"
$routingBusinessResult = New-CapabilityResult -Name "explicit_business_handoff"
$routingBusinessResult | Add-Member -NotePropertyName selected_agent -NotePropertyValue $null

if ($agentProbeEnabled -and (-not $SkipAdvanced) -and (-not $networkPolicyBlocked)) {
    $chatUrl = Join-EndpointUrl $baseUrl $chatPath
    $responsesUrl = if ([string]::IsNullOrWhiteSpace($responsesPath)) { "" } else { Join-EndpointUrl $baseUrl $responsesPath }
    $probeTools = @(
        @{
            type = "function"
            function = @{
                name = "probe_sum"
                description = "Add two integers for a harmless protocol probe."
                parameters = @{
                    type = "object"
                    properties = @{
                        a = @{ type = "integer" }
                        b = @{ type = "integer" }
                    }
                    required = @("a", "b")
                    additionalProperties = $false
                }
            }
        },
        @{
            type = "function"
            function = @{
                name = "probe_echo"
                description = "Echo text for a harmless protocol probe."
                parameters = @{
                    type = "object"
                    properties = @{ text = @{ type = "string" } }
                    required = @("text")
                    additionalProperties = $false
                }
            }
        }
    )
    $handoffTools = @(
        @{
            type = "function"
            function = @{
                name = "transfer_to_drawing_agent"
                description = "Use only when the user explicitly asks to process or understand engineering drawings."
                parameters = @{
                    type = "object"
                    properties = @{ reason = @{ type = "string" } }
                    required = @("reason")
                    additionalProperties = $false
                }
            }
        },
        @{
            type = "function"
            function = @{
                name = "transfer_to_template_agent"
                description = "Use only when the user explicitly asks to process a drawing template or template rules."
                parameters = @{
                    type = "object"
                    properties = @{ reason = @{ type = "string" } }
                    required = @("reason")
                    additionalProperties = $false
                }
            }
        }
    )

    $agentProbeResults["responses_api"] = Invoke-ResponsesCapabilityProbe `
        -Url $responsesUrl -Model $chatModel -Headers $headers -TimeoutSec $timeoutSec `
        -UseSslNoRevoke:$sslNoRevokeConfig

    $agentProbeResults["system_instruction"] = Invoke-ChatCapabilityProbe `
        -Name "system_instruction" -Url $chatUrl -Model $chatModel -Headers $headers -TimeoutSec $timeoutSec `
        -Messages @(
            @{ role = "system"; content = "SYSTEM_RULE_7319: reply with SYSTEM_INSTRUCTION_OK." },
            @{ role = "user"; content = "SYSTEM_PROBE_7319" }
        ) -ExpectedContains "SYSTEM_INSTRUCTION_OK" -UseSslNoRevoke:$sslNoRevokeConfig

    $agentProbeResults["multi_turn_memory"] = Invoke-ChatCapabilityProbe `
        -Name "multi_turn_memory" -Url $chatUrl -Model $chatModel -Headers $headers -TimeoutSec $timeoutSec `
        -Messages @(
            @{ role = "system"; content = "Return the requested memory marker exactly." },
            @{ role = "user"; content = "Remember MEMORY_VALUE_4826." },
            @{ role = "assistant"; content = "I will remember MEMORY_VALUE_4826." },
            @{ role = "user"; content = "MEMORY_RECALL_7319: return MEMORY_HISTORY_OK if the value is present." }
        ) -ExpectedContains "MEMORY_HISTORY_OK" -UseSslNoRevoke:$sslNoRevokeConfig

    $agentProbeResults["json_object"] = Invoke-ChatCapabilityProbe `
        -Name "json_object" -Url $chatUrl -Model $chatModel -Headers $headers -TimeoutSec $timeoutSec `
        -Messages @(
            @{ role = "system"; content = "Return valid JSON." },
            @{ role = "user"; content = "Return a JSON object with marker JSON_OBJECT_OK." }
        ) -ExtraPayload @{ response_format = @{ type = "json_object" } } `
        -ExpectedContains "JSON_OBJECT_OK" -UseSslNoRevoke:$sslNoRevokeConfig

    $agentProbeResults["json_schema"] = Invoke-ChatCapabilityProbe `
        -Name "json_schema" -Url $chatUrl -Model $chatModel -Headers $headers -TimeoutSec $timeoutSec `
        -Messages @(@{ role = "user"; content = "Return the requested structured probe object." }) `
        -ExtraPayload @{
            response_format = @{
                type = "json_schema"
                json_schema = @{
                    name = "agent_probe_result"
                    strict = $true
                    schema = @{
                        type = "object"
                        properties = @{
                            marker = @{ type = "string"; enum = @("JSON_SCHEMA_OK") }
                            value = @{ type = "integer"; enum = @(7319) }
                        }
                        required = @("marker", "value")
                        additionalProperties = $false
                    }
                }
            }
        } -ExpectedContains "JSON_SCHEMA_OK" -UseSslNoRevoke:$sslNoRevokeConfig

    $agentProbeResults["named_tool_choice"] = Invoke-ChatCapabilityProbe `
        -Name "named_tool_choice" -Url $chatUrl -Model $chatModel -Headers $headers -TimeoutSec $timeoutSec `
        -Messages @(@{ role = "user"; content = "Call probe_sum with a=7 and b=12." }) `
        -ExtraPayload @{
            tools = $probeTools
            tool_choice = @{ type = "function"; function = @{ name = "probe_sum" } }
        } -ExpectedToolName "probe_sum" -UseSslNoRevoke:$sslNoRevokeConfig

    $namedCall = @($agentProbeResults["named_tool_choice"].tool_calls | Where-Object { $_.name -eq "probe_sum" }) | Select-Object -First 1
    if ($null -ne $namedCall) {
        $assistantToolCall = @{
            role = "assistant"
            content = $null
            tool_calls = @(
                @{
                    id = $namedCall.id
                    type = "function"
                    function = @{ name = $namedCall.name; arguments = $namedCall.arguments_raw }
                }
            )
        }
        $agentProbeResults["tool_round_trip"] = Invoke-ChatCapabilityProbe `
            -Name "tool_round_trip" -Url $chatUrl -Model $chatModel -Headers $headers -TimeoutSec $timeoutSec `
            -Messages @(
                @{ role = "user"; content = "Call probe_sum, then report the tool result marker." },
                $assistantToolCall,
                @{ role = "tool"; tool_call_id = $namedCall.id; content = '{"result":19,"marker":"TOOL_ROUNDTRIP_OK"}' }
            ) -ExtraPayload @{ tools = $probeTools } -ExpectedContains "TOOL_ROUNDTRIP_OK" -UseSslNoRevoke:$sslNoRevokeConfig
    } else {
        $agentProbeResults["tool_round_trip"].status = "skipped"
        $agentProbeResults["tool_round_trip"].error = "Named tool call was not available for the round trip."
    }

    $agentProbeResults["parallel_tool_calls"] = Invoke-ChatCapabilityProbe `
        -Name "parallel_tool_calls" -Url $chatUrl -Model $chatModel -Headers $headers -TimeoutSec $timeoutSec `
        -Messages @(@{ role = "user"; content = "PARALLEL_TOOL_PROBE_7319" }) `
        -ExtraPayload @{ tools = $probeTools; tool_choice = "auto"; parallel_tool_calls = $true } `
        -UseSslNoRevoke:$sslNoRevokeConfig
    if (@($agentProbeResults["parallel_tool_calls"].tool_calls | Where-Object { $_.arguments_valid }).Count -ge 2) {
        $agentProbeResults["parallel_tool_calls"].status = "passed"
    } else {
        $agentProbeResults["parallel_tool_calls"].status = "inconclusive"
    }

    $agentProbeResults["streamed_tool_calls"] = Invoke-ChatCapabilityProbe `
        -Name "streamed_tool_calls" -Url $chatUrl -Model $chatModel -Headers $headers -TimeoutSec $timeoutSec `
        -Messages @(@{ role = "user"; content = "STREAM_TOOL_PROBE_7319" }) `
        -ExtraPayload @{ tools = $probeTools; tool_choice = @{ type = "function"; function = @{ name = "probe_sum" } } } `
        -ExpectedToolName "probe_sum" -Stream $true -UseSslNoRevoke:$sslNoRevokeConfig

    $routingGeneralResult = Invoke-ChatCapabilityProbe `
        -Name "general_conversation" -Url $chatUrl -Model $chatModel -Headers $headers -TimeoutSec $timeoutSec `
        -Messages @(
            @{ role = "system"; content = "Answer general requests directly. Use a transfer tool only for explicit engineering business work." },
            @{ role = "user"; content = "ROUTING_GENERAL_7319: say hello without transferring." }
        ) -ExtraPayload @{ tools = $handoffTools; tool_choice = "auto" } `
        -UseSslNoRevoke:$sslNoRevokeConfig
    if (
        $routingGeneralResult.status_code -ne 200 -or
        [string]::IsNullOrWhiteSpace([string]$routingGeneralResult.content_preview) -or
        @($routingGeneralResult.tool_calls).Count -gt 0
    ) {
        $routingGeneralResult.status = "inconclusive"
    }

    $routingBusinessResult = Invoke-ChatCapabilityProbe `
        -Name "explicit_business_handoff" -Url $chatUrl -Model $chatModel -Headers $headers -TimeoutSec $timeoutSec `
        -Messages @(
            @{ role = "system"; content = "Answer general requests directly. Transfer explicit drawing work to the drawing agent." },
            @{ role = "user"; content = "ROUTING_BUSINESS_7319: I explicitly want to process and understand an engineering drawing." }
        ) -ExtraPayload @{ tools = $handoffTools; tool_choice = "auto" } `
        -ExpectedToolName "transfer_to_drawing_agent" -UseSslNoRevoke:$sslNoRevokeConfig
    $selectedHandoff = @($routingBusinessResult.tool_calls | Where-Object { $_.name -like "transfer_to_*_agent" }) | Select-Object -First 1
    $routingBusinessResult | Add-Member -NotePropertyName selected_agent -NotePropertyValue $(
        if ($null -eq $selectedHandoff) {
            $null
        } elseif ($selectedHandoff.name -eq "transfer_to_drawing_agent") {
            "drawing_understanding"
        } elseif ($selectedHandoff.name -eq "transfer_to_template_agent") {
            "template_rule_assistant"
        } else {
            $selectedHandoff.name -replace '^transfer_to_', '' -replace '_agent$', ''
        }
    ) -Force
}

$imageInputResult = New-CapabilityResult -Name "image_input"
$fileInputResult = New-CapabilityResult -Name "file_input"
if ($multimodalProbeEnabled -and (-not $SkipMultimodal) -and (-not $networkPolicyBlocked)) {
    $chatUrl = Join-EndpointUrl $baseUrl $chatPath
    try {
        $imageDataUrl = New-ProbeImageDataUrl
        $imageInputResult = Invoke-ChatCapabilityProbe `
            -Name "image_input" -Url $chatUrl -Model $chatModel -Headers $headers -TimeoutSec $timeoutSec `
            -Messages @(
                @{
                    role = "user"
                    content = @(
                        @{ type = "text"; text = "Read the exact marker shown in this generated probe image. Do not infer it from prior context." },
                        @{ type = "image_url"; image_url = @{ url = $imageDataUrl; detail = "high" } }
                    )
                }
            ) -ExpectedContains "VISION_MARKER_7319" -UseSslNoRevoke:$sslNoRevokeConfig
    } catch {
        $imageInputResult.status = "inconclusive"
        $imageInputResult.error = "Could not generate or submit the local vision fixture: $($_.Exception.Message)"
    }

    $fileBytes = [System.Text.Encoding]::UTF8.GetBytes("The exact file marker is FILE_CONTENT_OK_7319.")
    $fileData = "data:text/plain;base64," + [Convert]::ToBase64String($fileBytes)
    $fileInputResult = Invoke-ChatCapabilityProbe `
        -Name "file_input" -Url $chatUrl -Model $chatModel -Headers $headers -TimeoutSec $timeoutSec `
        -Messages @(
            @{
                role = "user"
                content = @(
                    @{ type = "text"; text = "Read and return the exact marker stored in the attached text file." },
                    @{ type = "file"; file = @{ filename = "fanban-agent-probe.txt"; file_data = $fileData } }
                )
            }
        ) -ExpectedContains "FILE_CONTENT_OK_7319" -UseSslNoRevoke:$sslNoRevokeConfig
}

$runtimeResult = Get-PythonRuntimeInventory -Root $root
$concurrencyResult = if ($networkPolicyBlocked) {
    [PSCustomObject]@{
        status = "skipped"; attempted = $false; requested = $configuredConcurrency
        succeeded = 0; failed = 0; throttled = 0; status_codes = @(); elapsed_ms = $null
        error = "Network policy blocked model requests."
    }
} else {
    Invoke-LowLoadConcurrencyProbe `
        -Url (Join-EndpointUrl $baseUrl $chatPath) -Model $chatModel -Headers $headers `
        -TimeoutSec $timeoutSec -Count $configuredConcurrency
}

$mcpHeaders = @{}
if (-not [string]::IsNullOrWhiteSpace($mcpApiKeyEnvVar)) {
    $mcpApiKey = [Environment]::GetEnvironmentVariable($mcpApiKeyEnvVar)
    if (-not [string]::IsNullOrWhiteSpace($mcpApiKey)) {
        $mcpHeaders["Authorization"] = "Bearer $mcpApiKey"
    }
}
$mcpPolicyBlocked = $false
if (-not [string]::IsNullOrWhiteSpace($mcpStreamableHttpUrl) -and $networkMode -eq "intranet_only") {
    try {
        $mcpEndpoint = Get-UrlHostAndPort $mcpStreamableHttpUrl
        if ($normalizedMcpAllowedHosts.Count -eq 0 -or -not ($normalizedMcpAllowedHosts -contains $mcpEndpoint.host.ToLowerInvariant())) {
            $mcpPolicyBlocked = $true
            [void]$warnings.Add("MCP Streamable HTTP host is outside the intranet allowlist; MCP probe was blocked.")
        }
    } catch {
        $mcpPolicyBlocked = $true
        [void]$warnings.Add("MCP Streamable HTTP URL is invalid; MCP probe was blocked.")
    }
}
$mcpStreamableResult = if ($mcpPolicyBlocked) {
    [PSCustomObject]@{
        status = "failed"; attempted = $false; url = (Get-SanitizedUrl $mcpStreamableHttpUrl); protocol_version = $null
        session_id = $null; server_name = $null; server_version = $null; ping_ok = $false
        tool_count = 0; resource_count = 0; prompt_count = 0; elapsed_ms = $null
        error = "MCP URL was blocked by the intranet host policy."
    }
} else {
    Invoke-McpStreamableHttpProbe -Url $mcpStreamableHttpUrl -TimeoutSec $timeoutSec -AdditionalHeaders $mcpHeaders
}
$mcpSseResult = [PSCustomObject]@{
    status = if ([string]::IsNullOrWhiteSpace($mcpLegacySseUrl)) { "not_configured" } else { "inconclusive" }
    attempted = $false
    url = Get-SanitizedUrl $mcpLegacySseUrl
    error = if ([string]::IsNullOrWhiteSpace($mcpLegacySseUrl)) { $null } else { "Legacy MCP SSE requires an installed MCP client runtime for a persistent duplex session." }
}
$mcpStdioResult = [PSCustomObject]@{
    status = if ([string]::IsNullOrWhiteSpace($mcpCommand)) { "not_configured" } elseif (Test-Path -LiteralPath $mcpCommand -PathType Leaf) { "inconclusive" } else { "not_installed" }
    attempted = $false
    command = $mcpCommand
    arguments = @($McpStdioArguments)
    error = if ([string]::IsNullOrWhiteSpace($mcpCommand)) { $null } elseif (-not (Test-Path -LiteralPath $mcpCommand -PathType Leaf)) { "Configured MCP stdio command was not found." } else { "MCP stdio command exists; use the packaged MCP SDK runtime to complete a duplex protocol probe." }
}

$finishedAt = Get-UtcIsoTimestamp
$summaryOk = ($errors.Count -eq 0)
$result = [PSCustomObject]@{
    schema_version = "0.3"
    status = if ($summaryOk) { "passed" } else { "failed" }
    started_at_utc = $startedAt
    finished_at_utc = $finishedAt
    script = [PSCustomObject]@{
        path = $PSCommandPath
        version = "fanban-ai-connectivity@0.3"
        sha256 = Get-FileSha256 $PSCommandPath
        powershell = $PSVersionTable.PSVersion.ToString()
    }
    environment = [PSCustomObject]@{
        computer_name = $env:COMPUTERNAME
        user_name = $env:USERNAME
        root = $root
        config_path = $ConfigPath
        config_sha256 = Get-FileSha256 $ConfigPath
        profile = $selectedProfile
        output_path = $OutputPath
    }
    invocation = [PSCustomObject]@{
        skip_models = [bool]$SkipModels
        skip_chat = [bool]$SkipChat
        skip_stream = [bool]$SkipStream
        skip_advanced = [bool]$SkipAdvanced
        skip_multimodal = [bool]$SkipMultimodal
        concurrency = $configuredConcurrency
        mcp_streamable_http_configured = -not [string]::IsNullOrWhiteSpace($mcpStreamableHttpUrl)
        mcp_sse_configured = -not [string]::IsNullOrWhiteSpace($mcpLegacySseUrl)
        mcp_stdio_configured = -not [string]::IsNullOrWhiteSpace($mcpCommand)
        base_url_overridden = -not [string]::IsNullOrWhiteSpace($BaseUrl)
        chat_model_overridden = -not [string]::IsNullOrWhiteSpace($ChatModel)
        api_key_env_var_overridden = -not [string]::IsNullOrWhiteSpace($ApiKeyEnvVar)
        ssl_no_revoke = $sslNoRevokeConfig
    }
    profile = [PSCustomObject]@{
        provider = [string]$profileConfig["provider"]
        protocol = [string]$profileConfig["protocol"]
        network_mode = $networkMode
        allowed_hosts = @($allowedHosts)
        mcp_allowed_hosts = @($mcpAllowedHosts)
        architecture = [string]$profileConfig["architecture"]
        base_url = $baseUrl
        models_url = $modelsResult.url
        chat_completions_url = $chatResult.url
        responses_url = if ([string]::IsNullOrWhiteSpace($responsesPath)) { $null } else { Join-EndpointUrl $baseUrl $responsesPath }
        chat_model = $chatModel
        structured_model = [string]$profileConfig["structured_model"]
        stream_enabled = $streamEnabled
        model_list_required = $modelListRequired
    }
    auth = [PSCustomObject]@{
        api_key_env_var = $apiKeyEnvVar
        api_key_required = $apiKeyRequired
        api_key_present = -not [string]::IsNullOrWhiteSpace($apiKey)
        api_key_length = if ([string]::IsNullOrWhiteSpace($apiKey)) { 0 } else { $apiKey.Length }
        api_key_sha256_prefix = Get-SecretFingerprint $apiKey
        authorization_scheme = [string]$profileConfig["authorization_scheme"]
    }
    network = [PSCustomObject]@{
        dns = $dnsResult
        tcp = $tcpResult
    }
    checks = [PSCustomObject]@{
        models = $modelsResult
        chat = $chatResult
        stream = $streamResult
        agent_protocol = [PSCustomObject]$agentProbeResults
        routing = [PSCustomObject]@{
            general_conversation = $routingGeneralResult
            explicit_business_handoff = $routingBusinessResult
        }
        multimodal = [PSCustomObject]@{
            image_input = $imageInputResult
            file_input = $fileInputResult
        }
        concurrency = $concurrencyResult
        runtime = $runtimeResult
        mcp = [PSCustomObject]@{
            streamable_http = $mcpStreamableResult
            sse = $mcpSseResult
            stdio = $mcpStdioResult
        }
    }
    readiness = [PSCustomObject]@{
        core_connectivity = New-ReadinessResult `
            -Status $(if ($summaryOk) { "passed" } else { "failed" }) `
            -Summary $(if ($summaryOk) { "Core model connectivity passed." } else { "One or more required core checks failed." }) `
            -Checks @("dns", "tcp", "chat", "stream")
        agent_protocol = New-ReadinessResult `
            -Status $(Get-ReadinessStatus @($agentProbeResults.Values) + @($routingGeneralResult, $routingBusinessResult)) `
            -Summary $(if ($agentProbeEnabled -and (-not $SkipAdvanced)) { "Agent protocol probes completed; inspect individual capability evidence." } else { "Agent protocol probes were not enabled for this run." }) `
            -Checks @($agentProbeNames + @("general_conversation", "explicit_business_handoff"))
        multimodal = New-ReadinessResult `
            -Status $(Get-ReadinessStatus @($imageInputResult, $fileInputResult)) `
            -Summary $(if ($multimodalProbeEnabled -and (-not $SkipMultimodal)) { "Multimodal discovery probes completed; inspect each input type." } else { "Multimodal probes were not enabled for this run." }) `
            -Checks @("image_input", "file_input")
        agents_sdk_runtime = New-ReadinessResult `
            -Status $(if ($runtimeResult.packages.agents.installed) { "passed" } else { "not_installed" }) `
            -Summary $(if ($runtimeResult.packages.agents.installed) { "The OpenAI Agents SDK is installed in the selected Python runtime." } else { "The selected Python runtime does not contain the OpenAI Agents SDK." }) `
            -Checks @("python", "openai", "agents", "mcp")
        mcp = New-ReadinessResult `
            -Status $(
                if ($mcpStreamableResult.status -eq "passed") { "passed" }
                elseif ([string]::IsNullOrWhiteSpace($mcpStreamableHttpUrl) -and [string]::IsNullOrWhiteSpace($mcpLegacySseUrl) -and [string]::IsNullOrWhiteSpace($mcpCommand)) { "not_configured" }
                elseif ($mcpStreamableResult.status -eq "failed") { "failed" }
                else { "inconclusive" }
            ) `
            -Summary "MCP readiness reflects only explicitly configured transports; no listed tool was executed." `
            -Checks @("streamable_http", "sse", "stdio")
    }
    recommendations = @(
        "Use the capability readiness sections, not core connectivity alone, when selecting the Agent architecture."
    )
    warnings = @($warnings)
    errors = @($errors)
}

$outDir = Split-Path -Parent $OutputPath
if (-not [string]::IsNullOrWhiteSpace($outDir)) {
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
}
$json = $result | ConvertTo-Json -Depth 12
Set-Content -LiteralPath $OutputPath -Value $json -Encoding UTF8

Write-Host ("AI connectivity status: {0}" -f $result.status)
Write-Host ("Profile: {0}" -f $selectedProfile)
Write-Host ("BaseUrl: {0}" -f $baseUrl)
Write-Host ("OutputJson: {0}" -f $OutputPath)

if (-not $summaryOk) {
    foreach ($errorItem in $errors) {
        Write-Host ("ERROR[{0}]: {1}" -f $errorItem.stage, $errorItem.message)
    }
    exit 1
}
