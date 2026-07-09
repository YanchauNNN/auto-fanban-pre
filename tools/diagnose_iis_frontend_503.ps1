param(
    [string]$DeployRoot = "D:\FanBanServer",
    [string]$SiteName = "FanBanTerminal",
    [string]$AppPoolName = "FanBanTerminalAppPool",
    [int]$FrontendPort = 8888,
    [int]$BackendPort = 8000,
    [int]$TimeoutSec = 10,
    [int]$StepTimeoutSec = 20,
    [string]$ServerIp = "",
    [int]$RecentHours = 4
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

function Write-Step {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date).ToString("HH:mm:ss"), $Message
    Write-Host $line
    Add-Content -LiteralPath $tracePath -Encoding UTF8 -Value $line
}

Write-Step "start diagnosis"
Write-Step ("trace log: " + $tracePath)

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
                    content_sample = if ($null -ne $response.Content) { ([string]$response.Content).Substring(0, [Math]::Min(300, ([string]$response.Content).Length)) } else { "" }
                    error_type = ""
                    error_message = ""
                }
            } catch {
                $statusCode = $null
                $statusDescription = ""
                if ($_.Exception.Response) {
                    try {
                        $statusCode = [int]$_.Exception.Response.StatusCode
                        $statusDescription = [string]$_.Exception.Response.StatusDescription
                    } catch {
                        $statusCode = $null
                        $statusDescription = ""
                    }
                }
                [ordered]@{
                    ok = $false
                    status_code = $statusCode
                    status_description = $statusDescription
                    content_length = $null
                    content_sample = ""
                    error_type = $_.Exception.GetType().FullName
                    error_message = $_.Exception.Message
                }
            }
        } -ArgumentList $Uri, $TimeoutSeconds
        $finished = Wait-Job -Job $job -Timeout $StepTimeoutSec
        if ($null -eq $finished) {
            Stop-Job -Job $job -ErrorAction SilentlyContinue
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
            Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
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
        [int]$MaxRows = 50
    )
    try {
        return @(
            Get-WinEvent -FilterHashtable @{ LogName = $LogName; StartTime = $StartTime } -ErrorAction Stop |
                Where-Object { $_.ProviderName -match $ProviderPattern } |
                Select-Object -First $MaxRows TimeCreated, ProviderName, Id, LevelDisplayName, Message
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
    return Invoke-Safely -ScriptBlock {
        Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $PidValue) -ErrorAction Stop |
            Select-Object -First 1 ProcessId, Name, ExecutablePath, CommandLine
    } -DefaultValue $null
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

function Get-IisLogSnapshot {
    param(
        [string]$SiteId,
        [datetime]$ProbeStartedAt
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
        $latestTail = @(Get-Content -LiteralPath $latestSiteLog.FullName -Tail 80 -ErrorAction SilentlyContinue)
    }
    return [ordered]@{
        all_log_dirs = @($allLogDirs | ForEach-Object { [ordered]@{ name = $_.Name; full_name = $_.FullName; last_write_time = $_.LastWriteTime.ToString("o") } })
        site_log_dir = $siteLogDir
        site_log_exists = if (-not [string]::IsNullOrWhiteSpace($siteLogDir)) { Test-Path -LiteralPath $siteLogDir -PathType Container } else { $false }
        latest_site_log = if ($null -ne $latestSiteLog) { [ordered]@{ full_name = $latestSiteLog.FullName; last_write_time = $latestSiteLog.LastWriteTime.ToString("o"); length = [int64]$latestSiteLog.Length } } else { $null }
        latest_site_log_updated_after_probe_start = if ($null -ne $latestSiteLog) { [bool]($latestSiteLog.LastWriteTime -ge $ProbeStartedAt.AddSeconds(-2)) } else { $false }
        latest_site_log_tail = @($latestTail)
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
    }
    tcp = [ordered]@{}
    http = [ordered]@{}
    iis = [ordered]@{}
    files = [ordered]@{}
    processes = [ordered]@{}
    events = [ordered]@{}
    issues = @()
}

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
                Select-Object protocol, bindingInformation, ItemXPath
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
    $result.iis.arr_proxy = [ordered]@{
        exists = $null -ne $proxySection
        enabled = if ($null -ne $proxySection) { ConvertTo-PlainValue $proxySection.enabled } else { "" }
        timeout = ConvertTo-PlainValue $proxyTimeout
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
    $result.files[[System.IO.Path]::GetFileName($filePath)] = [ordered]@{
        path = $filePath
        exists = $null -ne $item
        length = if ($null -ne $item) { [int64]$item.Length } else { $null }
        last_write_time = if ($null -ne $item) { $item.LastWriteTime.ToString("o") } else { "" }
        sha256 = $hash
    }
}

Write-Step "collect processes"
$result.processes.listening_ports = Get-ListeningPorts -Ports @($FrontendPort, $BackendPort)
$result.processes.w3wp = @(
    Invoke-Safely -ScriptBlock {
        Get-CimInstance Win32_Process -Filter "name='w3wp.exe'" -ErrorAction Stop |
            Select-Object ProcessId, Name, CreationDate, ExecutablePath, CommandLine
    } -DefaultValue @()
)
$result.processes.python = @(
    Invoke-Safely -ScriptBlock {
        Get-CimInstance Win32_Process -Filter "name='python.exe'" -ErrorAction Stop |
            Where-Object { $_.CommandLine -match "uvicorn|API\.app" -or $_.CommandLine -match [regex]::Escape($DeployRoot) } |
            Select-Object ProcessId, Name, CreationDate, ExecutablePath, CommandLine
    } -DefaultValue @()
)

Write-Step "collect IIS logs"
$result.iis.logs = Get-IisLogSnapshot -SiteId $siteId -ProbeStartedAt $startedAt
Write-Step "collect Windows events"
$result.events.system = Get-RecentEventRows -LogName "System" -StartTime $eventStart -ProviderPattern "WAS|W3SVC|IIS|HttpEvent|HTTP"
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
if ($result.http.frontend_local_root.error_message -match "timed out|超时") {
    $result.issues += "frontend_local_root_http_timeout"
}

$result.generated_at = (Get-Date).ToString("o")
Write-Step "write report files"
$json = $result | ConvertTo-Json -Depth 12
$json | Set-Content -LiteralPath $jsonPath -Encoding UTF8

$summaryLines = @()
$summaryLines += "FanBan frontend 503 diagnosis"
$summaryLines += "Generated: $($result.generated_at)"
$summaryLines += "DeployRoot: $DeployRoot"
$summaryLines += "SiteName: $SiteName"
$summaryLines += "AppPoolName: $AppPoolName"
$summaryLines += "FrontendPort: $FrontendPort"
$summaryLines += "BackendPort: $BackendPort"
$summaryLines += "ServerIp: $serverIpGuess"
$summaryLines += ""
$summaryLines += "HTTP results:"
foreach ($key in $result.http.Keys) {
    $probe = $result.http[$key]
    $summaryLines += ("- {0}: ok={1}, status={2}, elapsed_ms={3}, error={4}" -f $key, $probe.ok, $probe.status_code, $probe.elapsed_ms, $probe.error_message)
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
if ($null -ne $result.iis.logs.latest_site_log) {
    $summaryLines += ("- latest_site_log: {0}, last_write={1}, updated_after_probe={2}" -f $result.iis.logs.latest_site_log.full_name, $result.iis.logs.latest_site_log.last_write_time, $result.iis.logs.latest_site_log_updated_after_probe_start)
}
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
$summaryLines | Set-Content -LiteralPath $textPath -Encoding UTF8

Write-Host 'Diagnosis completed.'
Write-Host ('Summary: ' + $textPath)
Write-Host ('Full JSON: ' + $jsonPath)
if ($result.issues.Count -gt 0) {
    $issueText = $result.issues -join ', '
    Write-Warning ('Detected issues: ' + $issueText)
}
