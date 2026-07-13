param(
    [string]$DeployRoot = "D:\FanBanServer",
    [string]$SiteName = "FanBanTerminal",
    [string]$AppPoolName = "FanBanTerminalAppPool",
    [int]$FrontendPort = 8888,
    [int]$BackendPort = 8000,
    [int]$TimeoutSec = 10,
    [int]$StepTimeoutSec = 20,
    [string]$ServerIp = "",
    [int]$RecentHours = 4,
    [int]$LogTailLines = 300,
    [int]$CommandTimeoutSec = 15,
    [switch]$SkipZip
)

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

$startedAt = Get-Date
$timestamp = $startedAt.ToString("yyyyMMdd-HHmmss")
$logsDir = Join-Path $DeployRoot "logs"
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null

$jsonPath = Join-Path $logsDir ("frontend-503-diagnosis-{0}.json" -f $timestamp)
$textPath = Join-Path $logsDir ("frontend-503-diagnosis-{0}.txt" -f $timestamp)
$tracePath = Join-Path $logsDir ("frontend-503-diagnosis-{0}.trace.log" -f $timestamp)
$artifactDir = Join-Path $logsDir ("frontend-503-diagnosis-{0}" -f $timestamp)
$zipPath = Join-Path $logsDir ("frontend-503-diagnosis-{0}.zip" -f $timestamp)
New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null
$script:ArtifactRecords = @()

function Write-Step {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date).ToString("HH:mm:ss"), $Message
    Write-Host $line
    Add-Content -LiteralPath $tracePath -Encoding UTF8 -Value $line
}

Write-Step "start diagnosis"
Write-Step ("trace log: " + $tracePath)

function ConvertTo-LineArray {
    param([object]$Value)
    $lines = @()
    if ($null -eq $Value) {
        return @()
    }
    if ($Value -is [System.Collections.IEnumerable] -and -not ($Value -is [string])) {
        foreach ($item in $Value) {
            $lines += [string]$item
        }
    } else {
        $lines += [string]$Value
    }
    return @($lines)
}

function Write-ArtifactText {
    param(
        [string]$FileName,
        [object]$Lines
    )
    $path = Join-Path $artifactDir $FileName
    $lineArray = ConvertTo-LineArray $Lines
    try {
        if ($lineArray.Count -eq 0) {
            "" | Set-Content -LiteralPath $path -Encoding UTF8
        } else {
            $lineArray | Set-Content -LiteralPath $path -Encoding UTF8
        }
        $record = [ordered]@{
            file_name = $FileName
            path = $path
            ok = $true
            line_count = [int]$lineArray.Count
            error = ""
        }
        $script:ArtifactRecords += $record
        return $record
    } catch {
        $record = [ordered]@{
            file_name = $FileName
            path = $path
            ok = $false
            line_count = [int]$lineArray.Count
            error = $_.Exception.Message
        }
        $script:ArtifactRecords += $record
        return $record
    }
}

function ConvertTo-PlainValue {
    param([object]$Value)
    if ($null -eq $Value) {
        return $null
    }
    try {
        return [string]$Value
    } catch {
        return $null
    }
}

function ConvertTo-PlainDateTime {
    param([object]$Value)
    if ($null -eq $Value) {
        return ""
    }
    try {
        if ($Value -is [datetime]) {
            return $Value.ToString("o")
        }
        return ([datetime]$Value).ToString("o")
    } catch {
        return [string]$Value
    }
}

function ConvertTo-PlainEventRow {
    param([object]$Event)
    if ($null -eq $Event) {
        return $null
    }
    return [ordered]@{
        time_created = ConvertTo-PlainDateTime $Event.TimeCreated
        provider_name = [string]$Event.ProviderName
        id = if ($null -ne $Event.Id) { [int]$Event.Id } else { $null }
        level = [string]$Event.LevelDisplayName
        message = [string]$Event.Message
    }
}

function ConvertTo-PlainProcessRow {
    param([object]$Process)
    if ($null -eq $Process) {
        return $null
    }
    return [ordered]@{
        process_id = if ($null -ne $Process.ProcessId) { [int]$Process.ProcessId } else { $null }
        name = [string]$Process.Name
        creation_date = ConvertTo-PlainDateTime $Process.CreationDate
        executable_path = [string]$Process.ExecutablePath
        command_line = [string]$Process.CommandLine
    }
}

function ConvertTo-PlainBindingRow {
    param([object]$Binding)
    if ($null -eq $Binding) {
        return $null
    }
    return [ordered]@{
        protocol = [string]$Binding.protocol
        binding_information = [string]$Binding.bindingInformation
        item_xpath = [string]$Binding.ItemXPath
    }
}

function ConvertTo-JsonSafeValue {
    param(
        [object]$Value,
        [int]$MaxDepth = 8,
        [int]$CurrentDepth = 0
    )

    if ($null -eq $Value) {
        return $null
    }
    if ($CurrentDepth -ge $MaxDepth) {
        return [string]$Value
    }
    if ($Value -is [string] -or $Value -is [bool] -or $Value -is [int] -or $Value -is [long] -or $Value -is [double] -or $Value -is [decimal]) {
        return $Value
    }
    if ($Value -is [datetime]) {
        return $Value.ToString("o")
    }
    if ($Value -is [TimeSpan]) {
        return $Value.ToString()
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $mapped = [ordered]@{}
        foreach ($key in $Value.Keys) {
            $mapped[[string]$key] = ConvertTo-JsonSafeValue -Value $Value[$key] -MaxDepth $MaxDepth -CurrentDepth ($CurrentDepth + 1)
        }
        return $mapped
    }
    if ($Value -is [System.Collections.IEnumerable] -and -not ($Value -is [string])) {
        $items = @()
        foreach ($item in $Value) {
            $items += ConvertTo-JsonSafeValue -Value $item -MaxDepth $MaxDepth -CurrentDepth ($CurrentDepth + 1)
        }
        return @($items)
    }

    $properties = @($Value.PSObject.Properties | Where-Object { $_.MemberType -in @("NoteProperty", "Property") })
    if ($properties.Count -eq 0) {
        return [string]$Value
    }

    $objectMap = [ordered]@{}
    foreach ($property in $properties) {
        try {
            $objectMap[[string]$property.Name] = ConvertTo-JsonSafeValue -Value $property.Value -MaxDepth $MaxDepth -CurrentDepth ($CurrentDepth + 1)
        } catch {
            $objectMap[[string]$property.Name] = ("<unreadable: {0}>" -f $_.Exception.Message)
        }
    }
    return $objectMap
}

function ConvertTo-JsonWithTimeout {
    param(
        [object]$Value,
        [int]$Depth = 8,
        [int]$TimeoutSec = 30
    )

    $job = $null
    try {
        $job = Start-Job -ScriptBlock {
            param($ReportValue, $ReportDepth)
            $ReportValue | ConvertTo-Json -Depth $ReportDepth
        } -ArgumentList $Value, $Depth

        $finished = Wait-Job -Job $job -Timeout $TimeoutSec
        if ($null -eq $finished) {
            Stop-Job -Job $job -ErrorAction SilentlyContinue | Out-Null
            throw "ConvertTo-Json timed out after $TimeoutSec seconds"
        }

        $jsonText = Receive-Job -Job $job -ErrorAction Stop
        if ($jsonText -is [array]) {
            return ($jsonText -join [Environment]::NewLine)
        }
        return [string]$jsonText
    } finally {
        if ($null -ne $job) {
            Remove-Job -Job $job -Force -ErrorAction SilentlyContinue | Out-Null
        }
    }
}

function Invoke-Safely {
    param(
        [scriptblock]$ScriptBlock,
        [object]$DefaultValue = $null
    )
    try {
        return & $ScriptBlock
    } catch {
        return $DefaultValue
    }
}

function Invoke-ExternalCommandCapture {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$Arguments = @(),
        [int]$TimeoutSeconds = $CommandTimeoutSec
    )
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    if ([System.IO.Path]::IsPathRooted($FilePath) -and -not (Test-Path -LiteralPath $FilePath -PathType Leaf)) {
        return [ordered]@{
            name = $Name
            file_path = $FilePath
            arguments = @($Arguments)
            ok = $false
            timed_out = $false
            elapsed_ms = $sw.ElapsedMilliseconds
            exit_code = $null
            output = @()
            error = "command file not found"
        }
    }

    $job = $null
    try {
        $job = Start-Job -ScriptBlock {
            param($Command, $CommandArgs)
            try {
                $output = @(& $Command @CommandArgs 2>&1 | ForEach-Object { [string]$_ })
                $exitCode = 0
                if ($null -ne $LASTEXITCODE) {
                    $exitCode = [int]$LASTEXITCODE
                }
                [pscustomobject]@{
                    exit_code = $exitCode
                    output = @($output)
                    error = ""
                }
            } catch {
                [pscustomobject]@{
                    exit_code = $null
                    output = @()
                    error = $_.Exception.Message
                }
            }
        } -ArgumentList $FilePath, $Arguments
        $finished = Wait-Job -Job $job -Timeout $TimeoutSeconds
        if ($null -eq $finished) {
            Stop-Job -Job $job -ErrorAction SilentlyContinue | Out-Null
            return [ordered]@{
                name = $Name
                file_path = $FilePath
                arguments = @($Arguments)
                ok = $false
                timed_out = $true
                elapsed_ms = $sw.ElapsedMilliseconds
                exit_code = $null
                output = @()
                error = "command timed out after $TimeoutSeconds seconds"
            }
        }

        $received = Receive-Job -Job $job -ErrorAction SilentlyContinue
        if ($received -is [array]) {
            $received = $received | Select-Object -First 1
        }
        if ($null -eq $received) {
            return [ordered]@{
                name = $Name
                file_path = $FilePath
                arguments = @($Arguments)
                ok = $false
                timed_out = $false
                elapsed_ms = $sw.ElapsedMilliseconds
                exit_code = $null
                output = @()
                error = "command returned no result"
            }
        }

        $outputLines = ConvertTo-LineArray $received.output
        return [ordered]@{
            name = $Name
            file_path = $FilePath
            arguments = @($Arguments)
            ok = ([string]$received.error -eq "" -and ($received.exit_code -eq 0 -or $null -eq $received.exit_code))
            timed_out = $false
            elapsed_ms = $sw.ElapsedMilliseconds
            exit_code = $received.exit_code
            output = @($outputLines)
            error = [string]$received.error
        }
    } catch {
        return [ordered]@{
            name = $Name
            file_path = $FilePath
            arguments = @($Arguments)
            ok = $false
            timed_out = $false
            elapsed_ms = $sw.ElapsedMilliseconds
            exit_code = $null
            output = @()
            error = $_.Exception.Message
        }
    } finally {
        if ($null -ne $job) {
            Remove-Job -Job $job -Force -ErrorAction SilentlyContinue | Out-Null
        }
    }
}

function Read-TextSample {
    param(
        [string]$Path,
        [int]$MaxChars = 4000
    )
    try {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            return ""
        }
        $text = [System.IO.File]::ReadAllText($Path)
        if ($text.Length -le $MaxChars) {
            return $text
        }
        return $text.Substring(0, $MaxChars)
    } catch {
        return ("<read failed: {0}>" -f $_.Exception.Message)
    }
}

function Test-TcpPort {
    param(
        [string]$HostName,
        [int]$Port,
        [int]$TimeoutMs = 3000
    )
    $client = $null
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        $connected = $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
        if ($connected) {
            try {
                $client.EndConnect($async)
            } catch {
                return [ordered]@{
                    ok = $false
                    host = $HostName
                    port = $Port
                    elapsed_ms = $sw.ElapsedMilliseconds
                    error = $_.Exception.Message
                }
            }
        }
        return [ordered]@{
            ok = [bool]$connected
            host = $HostName
            port = $Port
            elapsed_ms = $sw.ElapsedMilliseconds
            error = if ($connected) { "" } else { "connect timeout" }
        }
    } catch {
        return [ordered]@{
            ok = $false
            host = $HostName
            port = $Port
            elapsed_ms = $sw.ElapsedMilliseconds
            error = $_.Exception.Message
        }
    } finally {
        if ($null -ne $client) {
            $client.Close()
        }
    }
}

function Invoke-HttpProbe {
    param(
        [string]$Name,
        [string]$Uri,
        [int]$TimeoutSeconds
    )
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $job = $null
    try {
        Write-Step ("http probe: " + $Name + " " + $Uri)
        $job = Start-Job -ScriptBlock {
            param($ProbeUri, $ProbeTimeoutSec)
            $ProgressPreference = "SilentlyContinue"
            try {
                $response = Invoke-WebRequest -Uri $ProbeUri -UseBasicParsing -TimeoutSec $ProbeTimeoutSec
                [ordered]@{
                    ok = $true
                    status_code = [int]$response.StatusCode
                    status_description = [string]$response.StatusDescription
                    content_length = if ($null -ne $response.RawContentLength) { [int64]$response.RawContentLength } else { $null }
                    content_sample = if ($null -ne $response.Content) { ([string]$response.Content).Substring(0, [Math]::Min(1000, ([string]$response.Content).Length)) } else { "" }
                    error_type = ""
                    error_message = ""
                }
            } catch {
                $statusCode = $null
                $statusDescription = ""
                $contentSample = ""
                $contentLength = $null
                if ($_.Exception.Response) {
                    try {
                        $statusCode = [int]$_.Exception.Response.StatusCode
                        $statusDescription = [string]$_.Exception.Response.StatusDescription
                    } catch {
                        $statusCode = $null
                        $statusDescription = ""
                    }
                    try {
                        $stream = $_.Exception.Response.GetResponseStream()
                        if ($null -ne $stream) {
                            $reader = New-Object System.IO.StreamReader($stream)
                            $body = $reader.ReadToEnd()
                            $contentLength = [int64]$body.Length
                            $contentSample = $body.Substring(0, [Math]::Min(1000, $body.Length))
                        }
                    } catch {
                        $contentSample = ""
                    }
                }
                [ordered]@{
                    ok = $false
                    status_code = $statusCode
                    status_description = $statusDescription
                    content_length = $contentLength
                    content_sample = $contentSample
                    error_type = $_.Exception.GetType().FullName
                    error_message = $_.Exception.Message
                }
            }
        } -ArgumentList $Uri, $TimeoutSeconds
        $finished = Wait-Job -Job $job -Timeout $StepTimeoutSec
        if ($null -eq $finished) {
            Stop-Job -Job $job -ErrorAction SilentlyContinue | Out-Null
            return [ordered]@{
                name = $Name
                uri = $Uri
                ok = $false
                elapsed_ms = $sw.ElapsedMilliseconds
                status_code = $null
                status_description = ""
                content_length = $null
                content_sample = ""
                error_type = "probe_step_timeout"
                error_message = "HTTP probe exceeded StepTimeoutSec=$StepTimeoutSec"
            }
        }
        $probeResult = Receive-Job -Job $job -ErrorAction SilentlyContinue
        if ($probeResult -is [array]) {
            $probeResult = $probeResult | Select-Object -First 1
        }
        if ($null -eq $probeResult) {
            return [ordered]@{
                name = $Name
                uri = $Uri
                ok = $false
                elapsed_ms = $sw.ElapsedMilliseconds
                status_code = $null
                status_description = ""
                content_length = $null
                content_sample = ""
                error_type = "probe_no_result"
                error_message = "HTTP probe job returned no result"
            }
        }
        return [ordered]@{
            name = $Name
            uri = $Uri
            ok = [bool]$probeResult.ok
            elapsed_ms = $sw.ElapsedMilliseconds
            status_code = $probeResult.status_code
            status_description = [string]$probeResult.status_description
            content_length = $probeResult.content_length
            content_sample = [string]$probeResult.content_sample
            error_type = [string]$probeResult.error_type
            error_message = [string]$probeResult.error_message
        }
    } catch {
        return [ordered]@{
            name = $Name
            uri = $Uri
            ok = $false
            elapsed_ms = $sw.ElapsedMilliseconds
            status_code = $null
            status_description = ""
            content_length = $null
            content_sample = ""
            error_type = $_.Exception.GetType().FullName
            error_message = $_.Exception.Message
        }
    } finally {
        if ($null -ne $job) {
            Remove-Job -Job $job -Force -ErrorAction SilentlyContinue | Out-Null
        }
    }
}

function Get-ServerIpGuess {
    if (-not [string]::IsNullOrWhiteSpace($ServerIp)) {
        return $ServerIp
    }
    $ip = Invoke-Safely -ScriptBlock {
        Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object {
                $_.IPAddress -notlike "127.*" -and
                $_.IPAddress -notlike "169.254.*" -and
                $_.AddressState -eq "Preferred"
            } |
            Sort-Object InterfaceMetric |
            Select-Object -First 1 -ExpandProperty IPAddress
    } -DefaultValue ""
    if (-not [string]::IsNullOrWhiteSpace($ip)) {
        return [string]$ip
    }
    $fallback = Invoke-Safely -ScriptBlock {
        [System.Net.Dns]::GetHostAddresses($env:COMPUTERNAME) |
            Where-Object { $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork } |
            Select-Object -First 1
    } -DefaultValue $null
    if ($null -ne $fallback) {
        return [string]$fallback.IPAddressToString
    }
    return ""
}

function Get-RecentEventRows {
    param(
        [string]$LogName,
        [datetime]$StartTime,
        [string]$ProviderPattern,
        [int]$MaxRows = 100
    )
    try {
        return @(
            Get-WinEvent -FilterHashtable @{ LogName = $LogName; StartTime = $StartTime } -ErrorAction Stop |
                Where-Object { $_.ProviderName -match $ProviderPattern } |
                Select-Object -First $MaxRows |
                ForEach-Object { ConvertTo-PlainEventRow $_ }
        )
    } catch {
        return @()
    }
}

function Get-ProcessByPid {
    param([int]$PidValue)
    if ($PidValue -le 0) {
        return $null
    }
    $process = Invoke-Safely -ScriptBlock {
        Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $PidValue) -ErrorAction Stop |
            Select-Object -First 1
    } -DefaultValue $null
    return ConvertTo-PlainProcessRow $process
}

function Get-ListeningPorts {
    param([int[]]$Ports)
    $items = @()
    foreach ($port in $Ports) {
        $connections = @(
            Invoke-Safely -ScriptBlock {
                Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop
            } -DefaultValue @()
        )
        foreach ($conn in $connections) {
            $proc = Get-ProcessByPid -PidValue ([int]$conn.OwningProcess)
            $items += [ordered]@{
                local_address = [string]$conn.LocalAddress
                local_port = [int]$conn.LocalPort
                state = [string]$conn.State
                owning_process = [int]$conn.OwningProcess
                process_name = if ($null -ne $proc) { [string]$proc.Name } else { "" }
                executable_path = if ($null -ne $proc) { [string]$proc.ExecutablePath } else { "" }
                command_line = if ($null -ne $proc) { [string]$proc.CommandLine } else { "" }
            }
        }
    }
    return @($items)
}

function Get-ServiceSnapshot {
    $serviceNames = @("W3SVC", "WAS", "AppHostSvc", "HTTP")
    $items = @()
    foreach ($name in $serviceNames) {
        $svc = Invoke-Safely -ScriptBlock { Get-Service -Name $name -ErrorAction Stop } -DefaultValue $null
        $items += [ordered]@{
            name = $name
            found = $null -ne $svc
            status = if ($null -ne $svc) { [string]$svc.Status } else { "" }
            start_type = if ($null -ne $svc) { ConvertTo-PlainValue $svc.StartType } else { "" }
            display_name = if ($null -ne $svc) { [string]$svc.DisplayName } else { "" }
        }
    }
    return @($items)
}

function Get-EnvironmentSnapshot {
    $os = Invoke-Safely -ScriptBlock { Get-CimInstance Win32_OperatingSystem -ErrorAction Stop } -DefaultValue $null
    $isAdmin = Invoke-Safely -ScriptBlock {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($identity)
        $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } -DefaultValue $false
    $driveRoot = ""
    try {
        $driveRoot = [System.IO.Path]::GetPathRoot($DeployRoot)
    } catch {
        $driveRoot = ""
    }
    $drive = if (-not [string]::IsNullOrWhiteSpace($driveRoot)) {
        Invoke-Safely -ScriptBlock { Get-PSDrive -Name $driveRoot.Substring(0, 1) -ErrorAction Stop } -DefaultValue $null
    } else {
        $null
    }

    return [ordered]@{
        user = [string]([Security.Principal.WindowsIdentity]::GetCurrent().Name)
        is_admin = [bool]$isAdmin
        powershell_version = [string]$PSVersionTable.PSVersion
        os_caption = if ($null -ne $os) { [string]$os.Caption } else { "" }
        os_version = if ($null -ne $os) { [string]$os.Version } else { "" }
        os_last_boot = if ($null -ne $os) { ConvertTo-PlainDateTime $os.LastBootUpTime } else { "" }
        deploy_root_drive = [ordered]@{
            root = $driveRoot
            free_bytes = if ($null -ne $drive) { [int64]$drive.Free } else { $null }
            used_bytes = if ($null -ne $drive) { [int64]$drive.Used } else { $null }
        }
        ip_addresses = @(
            Invoke-Safely -ScriptBlock {
                Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
                    Where-Object { $_.IPAddress -notlike "127.*" } |
                    ForEach-Object {
                        [ordered]@{
                            ip_address = [string]$_.IPAddress
                            interface_alias = [string]$_.InterfaceAlias
                            address_state = [string]$_.AddressState
                            prefix_length = [int]$_.PrefixLength
                        }
                    }
            } -DefaultValue @()
        )
    }
}

function Get-IisLogSnapshot {
    param(
        [string]$SiteId,
        [datetime]$ProbeStartedAt,
        [int]$TailLines = 300
    )
    $allLogDirs = @(
        Get-ChildItem "C:\inetpub\logs\LogFiles" -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name
    )
    $siteLogDir = if (-not [string]::IsNullOrWhiteSpace($SiteId)) {
        Join-Path "C:\inetpub\logs\LogFiles" ("W3SVC{0}" -f $SiteId)
    } else {
        ""
    }
    $siteLogs = @()
    if (-not [string]::IsNullOrWhiteSpace($siteLogDir) -and (Test-Path -LiteralPath $siteLogDir -PathType Container)) {
        $siteLogs = @(Get-ChildItem $siteLogDir -Filter "u_ex*.log" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
    }
    $latestSiteLog = $siteLogs | Select-Object -First 1
    $latestTail = @()
    if ($null -ne $latestSiteLog) {
        $latestTail = @(Get-Content -LiteralPath $latestSiteLog.FullName -Tail $TailLines -ErrorAction SilentlyContinue | ForEach-Object { [string]$_ })
        Write-ArtifactText -FileName "iis-site-latest-tail.log" -Lines $latestTail | Out-Null
    }
    $filteredTail = @($latestTail | Where-Object { $_ -match " 5[0-9]{2} | 502 | 503 | 504 |Bad Gateway|Service Unavailable|$FrontendPort|$BackendPort" })
    if ($filteredTail.Count -gt 0) {
        Write-ArtifactText -FileName "iis-site-filtered-tail.log" -Lines $filteredTail | Out-Null
    }
    return [ordered]@{
        all_log_dirs = @($allLogDirs | ForEach-Object { [ordered]@{ name = $_.Name; full_name = $_.FullName; last_write_time = $_.LastWriteTime.ToString("o") } })
        site_log_dir = $siteLogDir
        site_log_exists = if (-not [string]::IsNullOrWhiteSpace($siteLogDir)) { Test-Path -LiteralPath $siteLogDir -PathType Container } else { $false }
        latest_site_log = if ($null -ne $latestSiteLog) { [ordered]@{ full_name = $latestSiteLog.FullName; last_write_time = $latestSiteLog.LastWriteTime.ToString("o"); length = [int64]$latestSiteLog.Length } } else { $null }
        latest_site_log_updated_after_probe_start = if ($null -ne $latestSiteLog) { [bool]($latestSiteLog.LastWriteTime -ge $ProbeStartedAt.AddSeconds(-2)) } else { $false }
        latest_site_log_tail = @($latestTail)
        latest_site_log_filtered_tail = @($filteredTail)
    }
}

function Get-HttpErrSnapshot {
    param(
        [datetime]$ProbeStartedAt,
        [int]$TailLines = 300
    )
    $dir = Join-Path $env:windir "System32\LogFiles\HTTPERR"
    $logs = @()
    if (Test-Path -LiteralPath $dir -PathType Container) {
        $logs = @(Get-ChildItem $dir -Filter "httperr*.log" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
    }
    $latestLog = $logs | Select-Object -First 1
    $latestTail = @()
    if ($null -ne $latestLog) {
        $latestTail = @(Get-Content -LiteralPath $latestLog.FullName -Tail $TailLines -ErrorAction SilentlyContinue | ForEach-Object { [string]$_ })
        Write-ArtifactText -FileName "httperr-latest-tail.log" -Lines $latestTail | Out-Null
    }
    $filteredTail = @($latestTail | Where-Object {
            $_ -match " 503 |503$|ServiceUnavailable|QueueFull|Disabled|AppOffline|AppPool|Timer_|Connection_|$FrontendPort|$BackendPort|$SiteName|$AppPoolName"
        })
    if ($filteredTail.Count -gt 0) {
        Write-ArtifactText -FileName "httperr-filtered-tail.log" -Lines $filteredTail | Out-Null
    }

    return [ordered]@{
        log_dir = $dir
        log_dir_exists = Test-Path -LiteralPath $dir -PathType Container
        logs = @($logs | Select-Object -First 10 | ForEach-Object {
                [ordered]@{
                    full_name = [string]$_.FullName
                    last_write_time = $_.LastWriteTime.ToString("o")
                    length = [int64]$_.Length
                }
            })
        latest_log = if ($null -ne $latestLog) { [ordered]@{ full_name = $latestLog.FullName; last_write_time = $latestLog.LastWriteTime.ToString("o"); length = [int64]$latestLog.Length } } else { $null }
        latest_log_updated_after_probe_start = if ($null -ne $latestLog) { [bool]($latestLog.LastWriteTime -ge $ProbeStartedAt.AddSeconds(-2)) } else { $false }
        latest_log_tail = @($latestTail)
        filtered_tail = @($filteredTail)
    }
}

function Get-AppCmdSnapshot {
    $appcmd = Join-Path $env:windir "System32\inetsrv\appcmd.exe"
    $commands = @(
        [ordered]@{ key = "list_site"; args = @("list", "site", $SiteName, "/text:*") },
        [ordered]@{ key = "list_app"; args = @("list", "app", "/site.name:$SiteName", "/text:*") },
        [ordered]@{ key = "list_vdir"; args = @("list", "vdir", "/app.name:$SiteName/", "/text:*") },
        [ordered]@{ key = "list_apppool"; args = @("list", "apppool", $AppPoolName, "/text:*") },
        [ordered]@{ key = "list_wp"; args = @("list", "wp") },
        [ordered]@{ key = "list_request"; args = @("list", "request") },
        [ordered]@{ key = "config_proxy"; args = @("list", "config", $SiteName, "-section:system.webServer/proxy") },
        [ordered]@{ key = "config_rewrite_rules"; args = @("list", "config", $SiteName, "-section:system.webServer/rewrite/rules") },
        [ordered]@{ key = "config_http_errors"; args = @("list", "config", $SiteName, "-section:system.webServer/httpErrors") },
        [ordered]@{ key = "config_static_content"; args = @("list", "config", $SiteName, "-section:system.webServer/staticContent") },
        [ordered]@{ key = "config_handlers"; args = @("list", "config", $SiteName, "-section:system.webServer/handlers") },
        [ordered]@{ key = "config_application_pools"; args = @("list", "config", "-section:system.applicationHost/applicationPools") }
    )
    $items = [ordered]@{}
    foreach ($cmd in $commands) {
        $capture = Invoke-ExternalCommandCapture -Name ("appcmd_" + $cmd.key) -FilePath $appcmd -Arguments ([string[]]$cmd.args) -TimeoutSeconds $CommandTimeoutSec
        $artifact = Write-ArtifactText -FileName ("appcmd-{0}.txt" -f $cmd.key) -Lines $capture.output
        $items[$cmd.key] = [ordered]@{
            ok = [bool]$capture.ok
            timed_out = [bool]$capture.timed_out
            elapsed_ms = [int64]$capture.elapsed_ms
            exit_code = $capture.exit_code
            arguments = @($capture.arguments)
            error = [string]$capture.error
            artifact = $artifact.path
            output_line_count = [int](ConvertTo-LineArray $capture.output).Count
            output_preview = @((ConvertTo-LineArray $capture.output) | Select-Object -First 80)
        }
    }
    return [ordered]@{
        appcmd_path = $appcmd
        appcmd_exists = Test-Path -LiteralPath $appcmd -PathType Leaf
        commands = $items
    }
}

function Get-NetshHttpSnapshot {
    $netsh = Join-Path $env:windir "System32\netsh.exe"
    $commands = @(
        [ordered]@{ key = "show_servicestate"; args = @("http", "show", "servicestate") },
        [ordered]@{ key = "show_urlacl"; args = @("http", "show", "urlacl") },
        [ordered]@{ key = "show_iplisten"; args = @("http", "show", "iplisten") },
        [ordered]@{ key = "show_timeout"; args = @("http", "show", "timeout") }
    )
    $items = [ordered]@{}
    foreach ($cmd in $commands) {
        $capture = Invoke-ExternalCommandCapture -Name ("netsh_" + $cmd.key) -FilePath $netsh -Arguments ([string[]]$cmd.args) -TimeoutSeconds $CommandTimeoutSec
        $artifact = Write-ArtifactText -FileName ("netsh-http-{0}.txt" -f $cmd.key) -Lines $capture.output
        $items[$cmd.key] = [ordered]@{
            ok = [bool]$capture.ok
            timed_out = [bool]$capture.timed_out
            elapsed_ms = [int64]$capture.elapsed_ms
            exit_code = $capture.exit_code
            arguments = @($capture.arguments)
            error = [string]$capture.error
            artifact = $artifact.path
            output_line_count = [int](ConvertTo-LineArray $capture.output).Count
            output_preview = @((ConvertTo-LineArray $capture.output) | Select-Object -First 120)
        }
    }
    return [ordered]@{
        netsh_path = $netsh
        netsh_exists = Test-Path -LiteralPath $netsh -PathType Leaf
        commands = $items
    }
}

function Get-FanBanScheduledTaskSnapshot {
    $task = Invoke-Safely -ScriptBlock { Get-ScheduledTask -TaskName "FanBanBackend" -ErrorAction Stop } -DefaultValue $null
    if ($null -eq $task) {
        return [ordered]@{
            found = $false
            state = ""
            task_path = ""
            last_run_time = ""
            last_task_result = ""
            next_run_time = ""
        }
    }
    $info = Invoke-Safely -ScriptBlock { Get-ScheduledTaskInfo -TaskName "FanBanBackend" -ErrorAction Stop } -DefaultValue $null
    return [ordered]@{
        found = $true
        state = [string]$task.State
        task_path = [string]$task.TaskPath
        actions = @($task.Actions | ForEach-Object { [string]$_ })
        triggers = @($task.Triggers | ForEach-Object { [string]$_ })
        last_run_time = if ($null -ne $info) { ConvertTo-PlainDateTime $info.LastRunTime } else { "" }
        last_task_result = if ($null -ne $info) { ConvertTo-PlainValue $info.LastTaskResult } else { "" }
        next_run_time = if ($null -ne $info) { ConvertTo-PlainDateTime $info.NextRunTime } else { "" }
    }
}

$serverIpGuess = Get-ServerIpGuess
$eventStart = $startedAt.AddHours(-1 * [Math]::Abs($RecentHours))

$result = [ordered]@{
    generated_at = (Get-Date).ToString("o")
    probe_started_at = $startedAt.ToString("o")
    computer_name = $env:COMPUTERNAME
    parameters = [ordered]@{
        deploy_root = $DeployRoot
        site_name = $SiteName
        app_pool_name = $AppPoolName
        frontend_port = $FrontendPort
        backend_port = $BackendPort
        timeout_sec = $TimeoutSec
        step_timeout_sec = $StepTimeoutSec
        server_ip = $serverIpGuess
        recent_hours = $RecentHours
        log_tail_lines = $LogTailLines
        command_timeout_sec = $CommandTimeoutSec
        skip_zip = [bool]$SkipZip
    }
    artifacts = [ordered]@{
        directory = $artifactDir
        zip_path = $zipPath
        zip_requested = -not [bool]$SkipZip
        zip_created = $false
        zip_error = ""
        files = @()
    }
    environment = [ordered]@{}
    scheduled_task = [ordered]@{}
    tcp = [ordered]@{}
    http = [ordered]@{}
    services = @()
    iis = [ordered]@{}
    httperr = [ordered]@{}
    appcmd = [ordered]@{}
    netsh_http = [ordered]@{}
    files = [ordered]@{}
    processes = [ordered]@{}
    events = [ordered]@{}
    issues = @()
}

Write-Step "collect environment"
$result.environment = Get-EnvironmentSnapshot
$result.scheduled_task.fanban_backend = Get-FanBanScheduledTaskSnapshot

Write-Step "tcp probes"
$result.tcp.backend_local = Test-TcpPort -HostName "127.0.0.1" -Port $BackendPort
$result.tcp.frontend_local = Test-TcpPort -HostName "127.0.0.1" -Port $FrontendPort
if (-not [string]::IsNullOrWhiteSpace($serverIpGuess)) {
    $result.tcp.frontend_server_ip = Test-TcpPort -HostName $serverIpGuess -Port $FrontendPort
}

Write-Step "http probes"
$result.http.backend_local_ping = Invoke-HttpProbe -Name "backend_local_ping" -Uri ("http://127.0.0.1:{0}/api/system/ping" -f $BackendPort) -TimeoutSeconds $TimeoutSec
$result.http.frontend_local_root = Invoke-HttpProbe -Name "frontend_local_root" -Uri ("http://127.0.0.1:{0}/" -f $FrontendPort) -TimeoutSeconds $TimeoutSec
$result.http.frontend_local_api_ping = Invoke-HttpProbe -Name "frontend_local_api_ping" -Uri ("http://127.0.0.1:{0}/api/system/ping" -f $FrontendPort) -TimeoutSeconds $TimeoutSec
if (-not [string]::IsNullOrWhiteSpace($serverIpGuess)) {
    $result.http.frontend_server_ip_root = Invoke-HttpProbe -Name "frontend_server_ip_root" -Uri ("http://{0}:{1}/" -f $serverIpGuess, $FrontendPort) -TimeoutSeconds $TimeoutSec
    $result.http.frontend_server_ip_api_ping = Invoke-HttpProbe -Name "frontend_server_ip_api_ping" -Uri ("http://{0}:{1}/api/system/ping" -f $serverIpGuess, $FrontendPort) -TimeoutSeconds $TimeoutSec
}

Write-Step "collect services"
$result.services = Get-ServiceSnapshot

Write-Step "load WebAdministration"
$webAdminLoaded = $false
try {
    Import-Module WebAdministration -ErrorAction Stop
    $webAdminLoaded = $true
} catch {
    $result.iis.web_administration_error = $_.Exception.Message
}
$result.iis.web_administration_loaded = $webAdminLoaded

$siteId = ""
if ($webAdminLoaded) {
    Write-Step "collect IIS site/app pool"
    $site = Invoke-Safely -ScriptBlock { Get-Website -Name $SiteName -ErrorAction Stop } -DefaultValue $null
    if ($null -ne $site) {
        $siteId = [string]$site.Id
        $result.iis.site = [ordered]@{
            name = [string]$site.Name
            id = [string]$site.Id
            state = [string]$site.State
            physical_path = [string]$site.PhysicalPath
            application_pool = [string]$site.ApplicationPool
            bindings = [string]$site.Bindings.Collection
        }
    } else {
        $result.iis.site = $null
    }

    $bindings = @(
        Invoke-Safely -ScriptBlock {
            Get-WebBinding -Name $SiteName -ErrorAction Stop |
                ForEach-Object { ConvertTo-PlainBindingRow $_ }
        } -DefaultValue @()
    )
    $result.iis.bindings = @($bindings)

    $poolState = Invoke-Safely -ScriptBlock { Get-WebAppPoolState -Name $AppPoolName -ErrorAction Stop } -DefaultValue $null
    $appPool = Invoke-Safely -ScriptBlock { Get-Item ("IIS:\AppPools\{0}" -f $AppPoolName) -ErrorAction Stop } -DefaultValue $null
    $result.iis.app_pool = [ordered]@{
        state = if ($null -ne $poolState) { [string]$poolState.Value } else { "" }
        managed_runtime_version = if ($null -ne $appPool) { ConvertTo-PlainValue $appPool.managedRuntimeVersion } else { "" }
        start_mode = if ($null -ne $appPool) { ConvertTo-PlainValue $appPool.startMode } else { "" }
        auto_start = if ($null -ne $appPool) { ConvertTo-PlainValue $appPool.autoStart } else { "" }
        identity_type = if ($null -ne $appPool) { ConvertTo-PlainValue $appPool.processModel.identityType } else { "" }
        idle_timeout = if ($null -ne $appPool) { ConvertTo-PlainValue $appPool.processModel.idleTimeout } else { "" }
        rapid_fail_protection = if ($null -ne $appPool) { ConvertTo-PlainValue $appPool.failure.rapidFailProtection } else { "" }
        rapid_fail_protection_max_crashes = if ($null -ne $appPool) { ConvertTo-PlainValue $appPool.failure.rapidFailProtectionMaxCrashes } else { "" }
        rapid_fail_protection_interval = if ($null -ne $appPool) { ConvertTo-PlainValue $appPool.failure.rapidFailProtectionInterval } else { "" }
    }

    $proxySection = Invoke-Safely -ScriptBlock { Get-WebConfigurationProperty -PSPath "MACHINE/WEBROOT/APPHOST" -Filter "system.webServer/proxy" -Name "." -ErrorAction Stop } -DefaultValue $null
    $proxyTimeout = Invoke-Safely -ScriptBlock { Get-WebConfigurationProperty -PSPath "MACHINE/WEBROOT/APPHOST" -Filter "system.webServer/proxy" -Name "timeout" -ErrorAction Stop } -DefaultValue $null
    $proxyTimeoutValue = ConvertTo-PlainValue $proxyTimeout
    if ($proxyTimeoutValue -match "^@\{Value=(.*)\}$") {
        $proxyTimeoutValue = $Matches[1]
    }
    if (($null -eq $proxyTimeoutValue -or $proxyTimeoutValue -eq "") -and $null -ne $proxySection) {
        $proxyTimeoutValue = ConvertTo-PlainValue $proxySection.timeout
    }
    $result.iis.arr_proxy = [ordered]@{
        exists = $null -ne $proxySection
        enabled = if ($null -ne $proxySection) { ConvertTo-PlainValue $proxySection.enabled } else { "" }
        timeout = $proxyTimeoutValue
        raw_timeout = ConvertTo-PlainValue $proxyTimeout
        preserve_host_header = if ($null -ne $proxySection) { ConvertTo-PlainValue $proxySection.preserveHostHeader } else { "" }
    }
}

Write-Step "collect frontend files"
$frontendDist = Join-Path $DeployRoot "frontend-dist"
$indexHtml = Join-Path $frontendDist "index.html"
$webConfig = Join-Path $frontendDist "web.config"
$result.files.frontend_dist = [ordered]@{
    path = $frontendDist
    exists = Test-Path -LiteralPath $frontendDist -PathType Container
}
foreach ($filePath in @($indexHtml, $webConfig)) {
    $item = Get-Item -LiteralPath $filePath -ErrorAction SilentlyContinue
    $hash = Invoke-Safely -ScriptBlock {
        if ($null -ne $item) {
            (Get-FileHash -LiteralPath $filePath -Algorithm SHA256 -ErrorAction Stop).Hash
        } else {
            ""
        }
    } -DefaultValue ""
    $name = [System.IO.Path]::GetFileName($filePath)
    $result.files[$name] = [ordered]@{
        path = $filePath
        exists = $null -ne $item
        length = if ($null -ne $item) { [int64]$item.Length } else { $null }
        last_write_time = if ($null -ne $item) { $item.LastWriteTime.ToString("o") } else { "" }
        sha256 = $hash
        content_sample = if ($name -eq "web.config") { Read-TextSample -Path $filePath -MaxChars 4000 } else { "" }
    }
    if ($name -eq "web.config" -and $null -ne $item) {
        Write-ArtifactText -FileName "frontend-web.config.txt" -Lines (Get-Content -LiteralPath $filePath -ErrorAction SilentlyContinue | ForEach-Object { [string]$_ }) | Out-Null
    }
}

Write-Step "collect processes"
$result.processes.listening_ports = Get-ListeningPorts -Ports @($FrontendPort, $BackendPort)
$result.processes.w3wp = @(
    Invoke-Safely -ScriptBlock {
        Get-CimInstance Win32_Process -Filter "name='w3wp.exe'" -ErrorAction Stop |
            ForEach-Object { ConvertTo-PlainProcessRow $_ }
    } -DefaultValue @()
)
$result.processes.python = @(
    Invoke-Safely -ScriptBlock {
        Get-CimInstance Win32_Process -Filter "name='python.exe'" -ErrorAction Stop |
            Where-Object { $_.CommandLine -match "uvicorn|API\.app" -or $_.CommandLine -match [regex]::Escape($DeployRoot) } |
            ForEach-Object { ConvertTo-PlainProcessRow $_ }
    } -DefaultValue @()
)

Write-Step "collect HTTPERR logs"
$result.httperr = Get-HttpErrSnapshot -ProbeStartedAt $startedAt -TailLines $LogTailLines

Write-Step "collect appcmd state"
$result.appcmd = Get-AppCmdSnapshot

Write-Step "collect netsh http state"
$result.netsh_http = Get-NetshHttpSnapshot

Write-Step "collect IIS logs"
$result.iis.logs = Get-IisLogSnapshot -SiteId $siteId -ProbeStartedAt $startedAt -TailLines $LogTailLines

Write-Step "collect Windows events"
$result.events.system = Get-RecentEventRows -LogName "System" -StartTime $eventStart -ProviderPattern "WAS|W3SVC|IIS|HttpEvent|HTTP|Service Control Manager"
$result.events.application = Get-RecentEventRows -LogName "Application" -StartTime $eventStart -ProviderPattern "IIS|WAS|W3SVC|Application Error|Windows Error Reporting|\.NET Runtime"

if ($result.http.backend_local_ping.ok -and -not $result.http.frontend_local_root.ok) {
    $result.issues += "backend_8000_ok_but_frontend_8888_root_failed"
}
if ($result.tcp.frontend_local.ok -and -not $result.http.frontend_local_root.ok) {
    $result.issues += "frontend_8888_accepts_tcp_but_http_failed_or_timed_out"
}
if (-not $result.tcp.frontend_local.ok) {
    $result.issues += "frontend_8888_not_listening_or_not_connectable"
}
if ($result.http.frontend_local_root.status_code -eq 503) {
    $result.issues += "frontend_local_root_http_503"
}
if ($result.http.frontend_local_api_ping.status_code -eq 503) {
    $result.issues += "frontend_local_api_ping_http_503"
}
if ($webAdminLoaded -and $null -eq $result.iis.site) {
    $result.issues += "iis_site_not_found"
}
if ($webAdminLoaded -and $result.iis.app_pool.state -ne "Started") {
    $result.issues += "iis_app_pool_not_started"
}
if ($null -ne $result.iis.logs.latest_site_log -and -not $result.iis.logs.latest_site_log_updated_after_probe_start) {
    $result.issues += "iis_site_log_not_updated_after_probe"
}
if ($null -eq $result.iis.logs.latest_site_log) {
    $result.issues += "iis_site_log_missing"
}
if ($result.http.frontend_local_root.error_message -match "timed out|timeout|operation has timed out") {
    $result.issues += "frontend_local_root_http_timeout"
}
<#
if ($result.http.frontend_local_root.error_message -match "timed out|超时|瓒呮椂") {
    $result.issues += "frontend_local_root_http_timeout"
}
#>
$httpErrText = (@($result.httperr.filtered_tail) -join "`n")
if ($httpErrText -match "503|ServiceUnavailable|QueueFull|Disabled|AppOffline|AppPool") {
    $result.issues += "httperr_recent_relevant_entries_present"
}
if ($httpErrText -match "Disabled") {
    $result.issues += "httperr_disabled_app_pool_or_disabled_queue"
}
if ($httpErrText -match "QueueFull") {
    $result.issues += "httperr_queue_full"
}
if ($httpErrText -match "AppOffline") {
    $result.issues += "httperr_app_offline"
}
if ($result.http.frontend_local_root.status_code -eq 503 -and $webAdminLoaded -and $result.iis.app_pool.state -eq "Started" -and @($result.processes.w3wp).Count -gt 0) {
    $result.issues += "iis_503_with_started_app_pool_and_w3wp"
}

$result.generated_at = (Get-Date).ToString("o")
$result.artifacts.files = @($script:ArtifactRecords)
Write-Step "write report files"

Write-Step "build text report start"
$summaryLines = @()
$summaryLines += "FanBan frontend 503 diagnosis"
$summaryLines += "Generated: $($result.generated_at)"
$summaryLines += "DeployRoot: $DeployRoot"
$summaryLines += "SiteName: $SiteName"
$summaryLines += "AppPoolName: $AppPoolName"
$summaryLines += "FrontendPort: $FrontendPort"
$summaryLines += "BackendPort: $BackendPort"
$summaryLines += "ServerIp: $serverIpGuess"
$summaryLines += "ArtifactDir: $artifactDir"
$summaryLines += "ZipPath: $zipPath"
$summaryLines += ""
$summaryLines += "HTTP results:"
foreach ($key in $result.http.Keys) {
    $probe = $result.http[$key]
    $summaryLines += ("- {0}: ok={1}, status={2}, elapsed_ms={3}, error={4}" -f $key, $probe.ok, $probe.status_code, $probe.elapsed_ms, $probe.error_message)
    if (-not [string]::IsNullOrWhiteSpace($probe.content_sample)) {
        $sample = ($probe.content_sample -replace "\s+", " ")
        $summaryLines += ("  sample: {0}" -f $sample.Substring(0, [Math]::Min(300, $sample.Length)))
    }
}
$summaryLines += ""
$summaryLines += "TCP results:"
foreach ($key in $result.tcp.Keys) {
    $probe = $result.tcp[$key]
    $summaryLines += ("- {0}: ok={1}, host={2}, port={3}, elapsed_ms={4}, error={5}" -f $key, $probe.ok, $probe.host, $probe.port, $probe.elapsed_ms, $probe.error)
}
$summaryLines += ""
$summaryLines += "IIS:"
$summaryLines += ("- web_administration_loaded={0}" -f $result.iis.web_administration_loaded)
if ($null -ne $result.iis.site) {
    $summaryLines += ("- site: id={0}, state={1}, physical_path={2}, app_pool={3}" -f $result.iis.site.id, $result.iis.site.state, $result.iis.site.physical_path, $result.iis.site.application_pool)
}
if ($null -ne $result.iis.app_pool) {
    $summaryLines += ("- app_pool: state={0}, start_mode={1}, auto_start={2}, idle_timeout={3}, rapid_fail={4}" -f $result.iis.app_pool.state, $result.iis.app_pool.start_mode, $result.iis.app_pool.auto_start, $result.iis.app_pool.idle_timeout, $result.iis.app_pool.rapid_fail_protection)
}
if ($null -ne $result.iis.arr_proxy) {
    $summaryLines += ("- arr_proxy: exists={0}, enabled={1}, timeout={2}, preserve_host_header={3}" -f $result.iis.arr_proxy.exists, $result.iis.arr_proxy.enabled, $result.iis.arr_proxy.timeout, $result.iis.arr_proxy.preserve_host_header)
}
if ($null -ne $result.iis.logs.latest_site_log) {
    $summaryLines += ("- latest_site_log: {0}, last_write={1}, updated_after_probe={2}" -f $result.iis.logs.latest_site_log.full_name, $result.iis.logs.latest_site_log.last_write_time, $result.iis.logs.latest_site_log_updated_after_probe_start)
}
$summaryLines += ""
$summaryLines += "HTTPERR:"
if ($null -ne $result.httperr.latest_log) {
    $summaryLines += ("- latest_log: {0}, last_write={1}, updated_after_probe={2}" -f $result.httperr.latest_log.full_name, $result.httperr.latest_log.last_write_time, $result.httperr.latest_log_updated_after_probe_start)
}
if (@($result.httperr.filtered_tail).Count -gt 0) {
    $summaryLines += "- filtered_tail:"
    foreach ($line in (@($result.httperr.filtered_tail) | Select-Object -Last 30)) {
        $summaryLines += ("  " + $line)
    }
} else {
    $summaryLines += "- filtered_tail: none"
}
$summaryLines += ""
$summaryLines += "Processes:"
$summaryLines += ("- listening_ports={0}, w3wp={1}, fanban_python={2}" -f @($result.processes.listening_ports).Count, @($result.processes.w3wp).Count, @($result.processes.python).Count)
$summaryLines += ""
$summaryLines += "Issues:"
if ($result.issues.Count -eq 0) {
    $summaryLines += "- none_detected_by_probe"
} else {
    foreach ($issue in $result.issues) {
        $summaryLines += "- $issue"
    }
}
$summaryLines += ""
$summaryLines += "Full JSON: $jsonPath"
$summaryLines += "Trace: $tracePath"
$summaryLines += "ArtifactDir: $artifactDir"
$summaryLines += "Zip: $zipPath"
Write-Step "write text report start"
$summaryLines | Set-Content -LiteralPath $textPath -Encoding UTF8
Write-Step "write text report done"

Write-Step "build json report start"
$safeResult = ConvertTo-JsonSafeValue -Value $result -MaxDepth 9
Write-Step "convert json start"
try {
    $json = ConvertTo-JsonWithTimeout -Value $safeResult -Depth 9 -TimeoutSec 45
    Write-Step "convert json done"
    Write-Step "write json report start"
    $json | Set-Content -LiteralPath $jsonPath -Encoding UTF8
    Write-Step "write json report done"
} catch {
    $jsonError = $_.Exception.Message
    Write-Step ("write json report failed: " + $jsonError)
    $fallbackJson = [ordered]@{
        generated_at = (Get-Date).ToString("o")
        status = "json_report_failed"
        error = $jsonError
        summary = $textPath
        trace = $tracePath
        artifacts = $artifactDir
        zip = $zipPath
        issues = @($result.issues)
    } | ConvertTo-Json -Depth 4
    $fallbackJson | Set-Content -LiteralPath $jsonPath -Encoding UTF8
}

Write-Step "copy report files into artifact directory"
foreach ($reportFile in @($textPath, $jsonPath, $tracePath)) {
    if (Test-Path -LiteralPath $reportFile -PathType Leaf) {
        try {
            Copy-Item -LiteralPath $reportFile -Destination (Join-Path $artifactDir ([System.IO.Path]::GetFileName($reportFile))) -Force
        } catch {
            Write-Step ("copy report file failed: " + $_.Exception.Message)
        }
    }
}

if (-not $SkipZip) {
    Write-Step "write diagnosis bundle zip start"
    try {
        if (Test-Path -LiteralPath $zipPath -PathType Leaf) {
            Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
        }
        $artifactItems = @(Get-ChildItem -LiteralPath $artifactDir -Force -ErrorAction Stop)
        if ($artifactItems.Count -eq 0) {
            throw "artifact directory is empty"
        }
        Compress-Archive -LiteralPath @($artifactItems.FullName) -DestinationPath $zipPath -Force -ErrorAction Stop
        $zipItem = Get-Item -LiteralPath $zipPath -ErrorAction Stop
        if ($zipItem.Length -le 0) {
            throw "zip file was created with zero length"
        }
        $result.artifacts.zip_created = $true
        Write-Step "write diagnosis bundle zip done"
    } catch {
        $result.artifacts.zip_error = $_.Exception.Message
        Write-Step ("write diagnosis bundle zip failed: " + $_.Exception.Message)
    }
} else {
    Write-Step "write diagnosis bundle zip skipped"
}

Write-Host 'Diagnosis completed.'
Write-Host ('Summary: ' + $textPath)
Write-Host ('Full JSON: ' + $jsonPath)
Write-Host ('ArtifactDir: ' + $artifactDir)
if (-not $SkipZip) {
    Write-Host ('Zip: ' + $zipPath)
}
if ($result.issues.Count -gt 0) {
    $issueText = $result.issues -join ', '
    Write-Warning ('Detected issues: ' + $issueText)
}
