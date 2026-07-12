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
        return [PSCustomObject]@{
            status_code = $status
            body = $content
            body_preview = if ($content.Length -gt 1000) { $content.Substring(0, 1000) } else { $content }
            content_type = [string]$response.ContentType
            content_length = [long]$response.ContentLength
            final_url = [string]$response.ResponseUri.AbsoluteUri
            elapsed_ms = [long]$stopwatch.ElapsedMilliseconds
        }
    } catch [System.Net.WebException] {
        $errorResponse = $_.Exception.Response
        if ($null -ne $errorResponse) {
            $status = [int]([System.Net.HttpWebResponse]$errorResponse).StatusCode
            $reader = [System.IO.StreamReader]::new($errorResponse.GetResponseStream(), [System.Text.Encoding]::UTF8)
            $content = $reader.ReadToEnd()
            $reader.Dispose()
            $stopwatch.Stop()
            return [PSCustomObject]@{
                status_code = $status
                body = $content
                body_preview = if ($content.Length -gt 1000) { $content.Substring(0, 1000) } else { $content }
                content_type = [string]$errorResponse.ContentType
                content_length = [long]$errorResponse.ContentLength
                final_url = [string]$errorResponse.ResponseUri.AbsoluteUri
                elapsed_ms = [long]$stopwatch.ElapsedMilliseconds
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
        }
    }

    return [PSCustomObject]@{
        content = ($parts -join "")
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
$chatModel = [string]$profileConfig["chat_model"]
$apiKeyEnvVar = [string]$profileConfig["api_key_env_var"]
$apiKeyRequired = [bool]$profileConfig["api_key_required"]
$streamEnabled = [bool]$profileConfig["stream_enabled"]
$modelListRequired = [bool]$profileConfig["model_list_required"]
$networkMode = [string]$profileConfig["network_mode"]
$allowedHosts = @(ConvertTo-StringArray $profileConfig["allowed_hosts"])
$timeoutSec = [int]$profileConfig["timeout_sec"]
$sslNoRevokeConfig = [bool]$profileConfig["ssl_no_revoke"]
$testPrompt = [string]$profileConfig["test_prompt"]
$expectedResponseContains = [string]$profileConfig["expected_response_contains"]

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

$finishedAt = Get-UtcIsoTimestamp
$summaryOk = ($errors.Count -eq 0)
$result = [PSCustomObject]@{
    schema_version = "0.2"
    status = if ($summaryOk) { "passed" } else { "failed" }
    started_at_utc = $startedAt
    finished_at_utc = $finishedAt
    script = [PSCustomObject]@{
        path = $PSCommandPath
        version = "fanban-ai-connectivity@0.2"
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
        architecture = [string]$profileConfig["architecture"]
        base_url = $baseUrl
        models_url = $modelsResult.url
        chat_completions_url = $chatResult.url
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
    }
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
