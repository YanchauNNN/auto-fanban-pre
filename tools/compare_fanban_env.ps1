[CmdletBinding()]
param(
    [string]$DeployRoot = "D:\FanBanServer",
    [string]$PackageRoot = "",
    [string]$OutputDir = "",
    [string]$BaselineJson = "",
    [string]$CurrentJson = "",
    [string]$ApiBaseUrl = "http://127.0.0.1",
    [int]$ApiPort = 8000,
    [switch]$RunProjectProbes,
    [int]$ProbeTimeoutSec = 420,
    [int]$LogTailLines = 120,
    [int]$HashSizeLimitMB = 256,
    [switch]$HashLargeFiles
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$script:SchemaVersion = "fanban-env-compare@1"
$script:InterestingPorts = @(80, 443, 8000, 5173)
$script:ImportantPackagePaths = @(
    "package-manifest.json",
    "README_部署说明.md",
    "scripts\start_backend.ps1",
    "scripts\check_health.ps1",
    "scripts\probe_target_env.ps1",
    "scripts\cad_env_fingerprint.ps1",
    "scripts\runtime.env.ps1",
    "install\check_iis_proxy_prereqs.ps1",
    "install\configure_iis_site.ps1",
    "install\install_runtime_prereqs.ps1",
    "install\register_backend_task.ps1",
    "backend-runtime\API\app\main.py",
    "backend-runtime\API\app\worker.py",
    "backend-runtime\backend\src\pipeline\sqlite_queue.py",
    "backend-runtime\backend\src\cad\dotnet\Module5CadBridge\bin\Release\net48\Module5CadBridge.dll",
    "documents\参数规范.yaml",
    "documents\参数规范_运行期.yaml",
    "documents\参数规范-3.yaml",
    "documents\Resources\fanban_monochrome.ctb",
    "documents\Resources\打印PDF2.pc3",
    "documents_bin\目录模板文件.xlsx",
    "documents_bin\封面模板文件.docx"
)

function Get-Timestamp {
    return (Get-Date).ToString("yyyyMMdd-HHmmss")
}

function Resolve-FullPathOrRaw {
    param([string]$PathText)
    if ([string]::IsNullOrWhiteSpace($PathText)) {
        return ""
    }
    try {
        return [System.IO.Path]::GetFullPath($PathText)
    } catch {
        return $PathText
    }
}

function New-StatusObject {
    param(
        [bool]$Ok,
        [object]$Value = $null,
        [string]$ErrorMessage = ""
    )
    return [ordered]@{
        ok = [bool]$Ok
        error = [string]$ErrorMessage
        value = $Value
    }
}

function Invoke-Capture {
    param(
        [scriptblock]$ScriptBlock,
        [object]$DefaultValue = $null
    )
    try {
        return New-StatusObject -Ok $true -Value (& $ScriptBlock)
    } catch {
        return New-StatusObject -Ok $false -Value $DefaultValue -ErrorMessage $_.Exception.Message
    }
}

function Get-IsAdministrator {
    try {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($identity)
        return [bool]$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch {
        return $false
    }
}

function Get-Sha256Hex {
    param([string]$PathText)
    if ([string]::IsNullOrWhiteSpace($PathText) -or -not (Test-Path -LiteralPath $PathText -PathType Leaf)) {
        return ""
    }
    $item = Get-Item -LiteralPath $PathText -ErrorAction Stop
    $limitBytes = [int64]$HashSizeLimitMB * 1024 * 1024
    if (-not $HashLargeFiles -and $item.Length -gt $limitBytes) {
        return ("<skipped:larger-than-{0}MB>" -f $HashSizeLimitMB)
    }
    return [string](Get-FileHash -LiteralPath $PathText -Algorithm SHA256 -ErrorAction Stop).Hash
}

function Get-FileFact {
    param([string]$PathText)
    $resolved = Resolve-FullPathOrRaw -PathText $PathText
    $exists = $false
    $item = $null
    $errorMessage = ""
    $sha = ""
    if (-not [string]::IsNullOrWhiteSpace($resolved)) {
        try {
            $exists = Test-Path -LiteralPath $resolved -PathType Leaf -ErrorAction Stop
        } catch {
            $errorMessage = $_.Exception.Message
        }
    }
    if ($exists) {
        try {
            $item = Get-Item -LiteralPath $resolved -ErrorAction Stop
            $sha = Get-Sha256Hex -PathText $resolved
        } catch {
            $errorMessage = $_.Exception.Message
        }
    }
    return [ordered]@{
        path = $resolved
        exists = [bool]$exists
        size_bytes = if ($item) { [int64]$item.Length } else { 0 }
        last_write_utc = if ($item) { $item.LastWriteTimeUtc.ToString("o") } else { "" }
        sha256 = $sha
        error = $errorMessage
    }
}

function Get-DirectoryFact {
    param(
        [string]$PathText,
        [switch]$RecursiveCount
    )
    $resolved = Resolve-FullPathOrRaw -PathText $PathText
    $exists = $false
    $fileCount = $null
    $dirCount = $null
    $lastWriteUtc = ""
    $errorMessage = ""
    if (-not [string]::IsNullOrWhiteSpace($resolved)) {
        try {
            $exists = Test-Path -LiteralPath $resolved -PathType Container -ErrorAction Stop
        } catch {
            $errorMessage = $_.Exception.Message
        }
    }
    if ($exists) {
        try {
            $item = Get-Item -LiteralPath $resolved -ErrorAction Stop
            $lastWriteUtc = $item.LastWriteTimeUtc.ToString("o")
            if ($RecursiveCount) {
                try {
                    $children = @(Get-ChildItem -LiteralPath $resolved -Recurse -Force -ErrorAction SilentlyContinue)
                    $fileCount = @($children | Where-Object { -not $_.PSIsContainer }).Count
                    $dirCount = @($children | Where-Object { $_.PSIsContainer }).Count
                } catch {
                    $fileCount = $null
                    $dirCount = $null
                    $errorMessage = $_.Exception.Message
                }
            }
        } catch {
            $errorMessage = $_.Exception.Message
        }
    }
    return [ordered]@{
        path = $resolved
        exists = [bool]$exists
        last_write_utc = $lastWriteUtc
        recursive_file_count = $fileCount
        recursive_dir_count = $dirCount
        error = $errorMessage
    }
}

function Read-JsonFile {
    param([string]$PathText)
    return (Get-Content -LiteralPath $PathText -Raw -Encoding UTF8 | ConvertFrom-Json)
}

function ConvertTo-PlainLines {
    param([object[]]$Lines)
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($line in $Lines) {
        $out.Add([string]$line)
    }
    return @($out.ToArray())
}

function ConvertTo-ProcessArgumentText {
    param([string[]]$Arguments)
    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($arg in $Arguments) {
        if ($null -eq $arg) {
            continue
        }
        $text = [string]$arg
        if ($text -match '[\s"]') {
            $text = '"' + ($text -replace '"', '\"') + '"'
        }
        $parts.Add($text)
    }
    return ($parts.ToArray() -join " ")
}

function Get-CommandResult {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList = @(),
        [int]$TimeoutSec = 30,
        [string]$WorkingDirectory = ""
    )
    $tempBase = Join-Path ([System.IO.Path]::GetTempPath()) ("fanban-env-cmd-" + [guid]::NewGuid().ToString("N"))
    $stdout = $tempBase + ".stdout.txt"
    $stderr = $tempBase + ".stderr.txt"
    $result = [ordered]@{
        file_path = $FilePath
        arguments = @($ArgumentList)
        timeout_sec = $TimeoutSec
        exit_code = $null
        timed_out = $false
        stdout = ""
        stderr = ""
        error = ""
    }
    try {
        $startArgs = @{
            FilePath = $FilePath
            ArgumentList = (ConvertTo-ProcessArgumentText -Arguments $ArgumentList)
            PassThru = $true
            RedirectStandardOutput = $stdout
            RedirectStandardError = $stderr
            WindowStyle = "Hidden"
        }
        if (-not [string]::IsNullOrWhiteSpace($WorkingDirectory)) {
            $startArgs.WorkingDirectory = $WorkingDirectory
        }
        $process = Start-Process @startArgs
        if (-not $process.WaitForExit($TimeoutSec * 1000)) {
            $result.timed_out = $true
            try { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue } catch {}
        } else {
            $result.exit_code = [int]$process.ExitCode
        }
    } catch {
        $result.error = $_.Exception.Message
    } finally {
        if (Test-Path -LiteralPath $stdout -PathType Leaf) {
            $result.stdout = [string](Get-Content -LiteralPath $stdout -Raw -Encoding UTF8)
            Remove-Item -LiteralPath $stdout -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $stderr -PathType Leaf) {
            $result.stderr = [string](Get-Content -LiteralPath $stderr -Raw -Encoding UTF8)
            Remove-Item -LiteralPath $stderr -Force -ErrorAction SilentlyContinue
        }
    }
    return $result
}

function Get-HostFacts {
    $os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
    $cs = Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue
    $bios = Get-CimInstance Win32_BIOS -ErrorAction SilentlyContinue
    $cpu = Get-CimInstance Win32_Processor -ErrorAction SilentlyContinue | Select-Object -First 1
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return [ordered]@{
        computer_name = $env:COMPUTERNAME
        user = $identity.Name
        is_admin = Get-IsAdministrator
        os_caption = if ($os) { [string]$os.Caption } else { "" }
        os_version = if ($os) { [string]$os.Version } else { "" }
        os_build = if ($os) { [string]$os.BuildNumber } else { "" }
        install_date = if ($os) { [string]$os.InstallDate } else { "" }
        last_boot = if ($os) { [string]$os.LastBootUpTime } else { "" }
        architecture = if ($os) { [string]$os.OSArchitecture } else { "" }
        manufacturer = if ($cs) { [string]$cs.Manufacturer } else { "" }
        model = if ($cs) { [string]$cs.Model } else { "" }
        domain = if ($cs) { [string]$cs.Domain } else { "" }
        total_memory_gb = if ($cs) { [math]::Round([double]$cs.TotalPhysicalMemory / 1GB, 2) } else { $null }
        cpu_name = if ($cpu) { [string]$cpu.Name } else { "" }
        logical_processors = if ($cpu) { [int]$cpu.NumberOfLogicalProcessors } else { 0 }
        bios_serial_hash = if ($bios -and $bios.SerialNumber) {
            $bytes = [Text.Encoding]::UTF8.GetBytes([string]$bios.SerialNumber)
            ([System.BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($bytes))).Replace("-", "")
        } else { "" }
        powershell_version = $PSVersionTable.PSVersion.ToString()
        culture = (Get-Culture).Name
        ui_culture = (Get-UICulture).Name
        system_locale = (Get-WinSystemLocale).Name
        time_zone = (Get-TimeZone).Id
        execution_policy = Get-ExecutionPolicy -List | ForEach-Object {
            [ordered]@{ scope = [string]$_.Scope; policy = [string]$_.ExecutionPolicy }
        }
    }
}

function Get-EnvironmentFacts {
    $names = @(
        "FANBAN_SPEC_PATH",
        "FANBAN_RUNTIME_SPEC_PATH",
        "FANBAN_MECHANISM_SPEC_PATH",
        "FANBAN_STORAGE_ROOT",
        "FANBAN_MODULE5_EXPORT__CAD_RUNNER__SCRIPT_DIR",
        "FANBAN_MODULE5_EXPORT__DOTNET_BRIDGE__DLL_PATH",
        "FANBAN_MODULE5_EXPORT__PLOT__CTB_NAME",
        "PYTHONHOME",
        "PYTHONPATH",
        "PATH",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "ProgramFiles",
        "ProgramFiles(x86)",
        "PROCESSOR_ARCHITECTURE"
    )
    $values = [ordered]@{}
    foreach ($name in $names) {
        $values[$name] = [string][Environment]::GetEnvironmentVariable($name, "Process")
    }
    $machineFanban = [ordered]@{}
    $userFanban = [ordered]@{}
    foreach ($target in @("Machine", "User")) {
        foreach ($name in @("FANBAN_SPEC_PATH", "FANBAN_RUNTIME_SPEC_PATH", "FANBAN_MECHANISM_SPEC_PATH", "FANBAN_STORAGE_ROOT")) {
            $v = [Environment]::GetEnvironmentVariable($name, $target)
            if ($target -eq "Machine") { $machineFanban[$name] = [string]$v } else { $userFanban[$name] = [string]$v }
        }
    }
    $pathEntries = @()
    if ($values["PATH"]) {
        $pathEntries = $values["PATH"].Split(";") | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    }
    return [ordered]@{
        selected_process_vars = $values
        fanban_machine_vars = $machineFanban
        fanban_user_vars = $userFanban
        path_entries = @($pathEntries)
    }
}

function Get-DriveFacts {
    return @(Get-CimInstance Win32_LogicalDisk -ErrorAction SilentlyContinue | ForEach-Object {
        [ordered]@{
            device_id = [string]$_.DeviceID
            drive_type = [int]$_.DriveType
            file_system = [string]$_.FileSystem
            size_gb = if ($_.Size) { [math]::Round([double]$_.Size / 1GB, 2) } else { $null }
            free_gb = if ($_.FreeSpace) { [math]::Round([double]$_.FreeSpace / 1GB, 2) } else { $null }
            volume_name = [string]$_.VolumeName
        }
    })
}

function Get-RegistryValue {
    param(
        [string]$PathText,
        [string]$Name
    )
    try {
        $item = Get-ItemProperty -LiteralPath $PathText -ErrorAction Stop
        return [string]$item.$Name
    } catch {
        return ""
    }
}

function Get-DotNetFacts {
    $release = Get-RegistryValue -PathText "HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full" -Name "Release"
    $version = Get-RegistryValue -PathText "HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full" -Name "Version"
    return [ordered]@{
        netfx_v4_release = $release
        netfx_v4_version = $version
    }
}

function Get-ProgramInventory {
    $keys = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    $patterns = @("AutoCAD", "Autodesk", "Office", "Microsoft 365", "Visual C++", "URL Rewrite", "Application Request Routing", "ODA", "Open Design")
    $rows = New-Object System.Collections.Generic.List[object]
    foreach ($key in $keys) {
        try {
            Get-ItemProperty -Path $key -ErrorAction SilentlyContinue | ForEach-Object {
                $name = [string]$_.DisplayName
                if (-not [string]::IsNullOrWhiteSpace($name)) {
                    $match = $false
                    foreach ($pattern in $patterns) {
                        if ($name -like ("*" + $pattern + "*")) {
                            $match = $true
                            break
                        }
                    }
                    if ($match) {
                        $rows.Add([ordered]@{
                            name = $name
                            version = [string]$_.DisplayVersion
                            publisher = [string]$_.Publisher
                            install_location = [string]$_.InstallLocation
                            install_date = [string]$_.InstallDate
                            registry_key = [string]$_.PSPath
                        })
                    }
                }
            }
        } catch {}
    }
    return @($rows.ToArray() | Sort-Object name, version)
}

function Get-ComRegistrationFacts {
    $progIds = @("Word.Application", "Excel.Application", "AutoCAD.Application")
    $rows = New-Object System.Collections.Generic.List[object]
    foreach ($progId in $progIds) {
        $clsid = Get-RegistryValue -PathText ("Registry::HKEY_CLASSES_ROOT\" + $progId + "\CLSID") -Name "(default)"
        if ([string]::IsNullOrWhiteSpace($clsid)) {
            try {
                $key = Get-Item -LiteralPath ("Registry::HKEY_CLASSES_ROOT\" + $progId + "\CLSID") -ErrorAction Stop
                $clsid = [string]$key.GetValue("")
            } catch {}
        }
        $localServer = ""
        if (-not [string]::IsNullOrWhiteSpace($clsid)) {
            try {
                $key = Get-Item -LiteralPath ("Registry::HKEY_CLASSES_ROOT\CLSID\" + $clsid + "\LocalServer32") -ErrorAction Stop
                $localServer = [string]$key.GetValue("")
            } catch {}
        }
        $rows.Add([ordered]@{
            prog_id = $progId
            clsid = $clsid
            local_server32 = $localServer
        })
    }
    return @($rows.ToArray())
}

function Get-IisFacts {
    $services = @()
    foreach ($name in @("W3SVC", "WAS", "IISADMIN")) {
        $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
        $services += [ordered]@{
            name = $name
            exists = [bool]$svc
            status = if ($svc) { [string]$svc.Status } else { "" }
            start_type = if ($svc) { [string]$svc.StartType } else { "" }
        }
    }

    $urlRewriteReg = Invoke-Capture -DefaultValue $null -ScriptBlock {
        Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\IIS Extensions\URL Rewrite" -ErrorAction Stop |
            Select-Object Version, Install
    }
    $arrReg = Invoke-Capture -DefaultValue $null -ScriptBlock {
        Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\IIS Extensions\Application Request Routing" -ErrorAction Stop |
            Select-Object Version, Install
    }

    $webAdmin = [ordered]@{
        import_ok = $false
        import_error = ""
        global_modules = @()
        sites = @()
        proxy = $null
    }
    try {
        Import-Module WebAdministration -ErrorAction Stop
        $webAdmin.import_ok = $true
        $webAdmin.global_modules = @(Get-WebGlobalModule -ErrorAction SilentlyContinue | ForEach-Object {
            [ordered]@{ name = [string]$_.Name; image = [string]$_.Image }
        })
        $webAdmin.sites = @(Get-Website -ErrorAction SilentlyContinue | ForEach-Object {
            [ordered]@{
                name = [string]$_.Name
                id = [string]$_.Id
                state = [string]$_.State
                physical_path = [string]$_.PhysicalPath
                bindings = @($_.Bindings.Collection | ForEach-Object { [string]$_.bindingInformation })
            }
        })
        $proxy = Get-WebConfigurationProperty -PSPath "MACHINE/WEBROOT/APPHOST" -Filter "system.webServer/proxy" -Name "." -ErrorAction SilentlyContinue
        $timeout = Get-WebConfigurationProperty -PSPath "MACHINE/WEBROOT/APPHOST" -Filter "system.webServer/proxy" -Name "timeout" -ErrorAction SilentlyContinue
        $webAdmin.proxy = [ordered]@{
            exists = [bool]$proxy
            enabled = if ($proxy -and $null -ne $proxy.enabled) { [string]$proxy.enabled } else { "" }
            preserve_host_header = if ($proxy -and $null -ne $proxy.preserveHostHeader) { [string]$proxy.preserveHostHeader } else { "" }
            timeout = if ($timeout) { [string]$timeout } else { "" }
        }
    } catch {
        $webAdmin.import_error = $_.Exception.Message
    }

    $appHost = Join-Path $env:WINDIR "System32\inetsrv\config\applicationHost.config"
    return [ordered]@{
        services = $services
        url_rewrite_registry = $urlRewriteReg
        arr_registry = $arrReg
        web_administration = $webAdmin
        application_host_config = Get-FileFact -PathText $appHost
    }
}

function Get-WindowsFeatureFacts {
    $featureNames = @(
        "IIS-WebServerRole",
        "IIS-WebServer",
        "IIS-CommonHttpFeatures",
        "IIS-StaticContent",
        "IIS-DefaultDocument",
        "IIS-HttpErrors",
        "IIS-HttpLogging",
        "IIS-RequestFiltering",
        "IIS-ManagementConsole",
        "NetFx4Extended-ASPNET45",
        "WCF-HTTP-Activation45"
    )
    $rows = New-Object System.Collections.Generic.List[object]
    foreach ($name in $featureNames) {
        try {
            $f = Get-WindowsOptionalFeature -Online -FeatureName $name -ErrorAction Stop
            $rows.Add([ordered]@{ name = $name; state = [string]$f.State })
        } catch {
            $rows.Add([ordered]@{ name = $name; state = "unknown"; error = $_.Exception.Message })
        }
    }
    return @($rows.ToArray())
}

function Get-NetworkFacts {
    $adapters = @(Get-NetIPConfiguration -ErrorAction SilentlyContinue | ForEach-Object {
        [ordered]@{
            interface_alias = [string]$_.InterfaceAlias
            interface_index = [int]$_.InterfaceIndex
            ipv4 = @($_.IPv4Address | ForEach-Object { [string]$_.IPAddress })
            ipv6 = @($_.IPv6Address | ForEach-Object { [string]$_.IPAddress })
            dns = @($_.DNSServer.ServerAddresses | ForEach-Object { [string]$_ })
            gateway = @($_.IPv4DefaultGateway | ForEach-Object { [string]$_.NextHop })
        }
    })
    $listeners = New-Object System.Collections.Generic.List[object]
    foreach ($port in $script:InterestingPorts) {
        try {
            Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
                $proc = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f [int]$_.OwningProcess) -ErrorAction SilentlyContinue
                $listeners.Add([ordered]@{
                    local_address = [string]$_.LocalAddress
                    local_port = [int]$_.LocalPort
                    owning_process = [int]$_.OwningProcess
                    process_name = if ($proc) { [string]$proc.Name } else { "" }
                    command_line = if ($proc) { [string]$proc.CommandLine } else { "" }
                })
            }
        } catch {}
    }
    return [ordered]@{
        adapters = $adapters
        proxy = Invoke-Capture -DefaultValue $null -ScriptBlock { netsh winhttp show proxy }
        listeners = @($listeners.ToArray())
    }
}

function Invoke-HttpCheck {
    param([string]$Url)
    $result = [ordered]@{
        url = $Url
        ok = $false
        status_code = $null
        server = ""
        elapsed_ms = $null
        content_sample = ""
        json = $null
        error = ""
    }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10
        $sw.Stop()
        $result.ok = $true
        $result.status_code = [int]$response.StatusCode
        $result.server = [string]$response.Headers["Server"]
        $result.elapsed_ms = [int]$sw.ElapsedMilliseconds
        $content = [string]$response.Content
        $result.content_sample = if ($content.Length -gt 500) { $content.Substring(0, 500) } else { $content }
        try {
            $result.json = $content | ConvertFrom-Json
        } catch {}
    } catch {
        $sw.Stop()
        $result.elapsed_ms = [int]$sw.ElapsedMilliseconds
        $result.error = $_.Exception.Message
    }
    return $result
}

function Get-HttpFacts {
    $base = $ApiBaseUrl.TrimEnd("/")
    $directBase = ("http://127.0.0.1:{0}" -f $ApiPort)
    return [ordered]@{
        via_iis_root = Invoke-HttpCheck -Url ($base + "/")
        via_iis_ping = Invoke-HttpCheck -Url ($base + "/api/system/ping")
        via_iis_health = Invoke-HttpCheck -Url ($base + "/api/system/health")
        direct_ping = Invoke-HttpCheck -Url ($directBase + "/api/system/ping")
        direct_health = Invoke-HttpCheck -Url ($directBase + "/api/system/health")
    }
}

function Get-TaskFacts {
    $taskName = "FanBanBackend"
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if (-not $task) {
        return [ordered]@{ exists = $false; name = $taskName }
    }
    $info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue
    $events = @()
    try {
        $events = @(Get-WinEvent -LogName "Microsoft-Windows-TaskScheduler/Operational" -MaxEvents 80 -ErrorAction SilentlyContinue |
            Where-Object { $_.Message -like ("*" + $taskName + "*") } |
            Select-Object -First 20 |
            ForEach-Object {
                [ordered]@{
                    time_created = $_.TimeCreated.ToString("o")
                    id = [int]$_.Id
                    level = [string]$_.LevelDisplayName
                    message = [string]$_.Message
                }
            })
    } catch {}
    return [ordered]@{
        exists = $true
        name = $taskName
        state = [string]$task.State
        actions = @($task.Actions | ForEach-Object { [ordered]@{ execute = [string]$_.Execute; arguments = [string]$_.Arguments } })
        triggers = @($task.Triggers | ForEach-Object { [ordered]@{ type = [string]$_.CimClass.CimClassName; enabled = [bool]$_.Enabled } })
        principal = [ordered]@{
            user_id = [string]$task.Principal.UserId
            logon_type = [string]$task.Principal.LogonType
            run_level = [string]$task.Principal.RunLevel
        }
        settings = [ordered]@{
            execution_time_limit = [string]$task.Settings.ExecutionTimeLimit
            restart_count = [string]$task.Settings.RestartCount
            restart_interval = [string]$task.Settings.RestartInterval
            multiple_instances = [string]$task.Settings.MultipleInstances
            stop_if_going_on_batteries = [string]$task.Settings.StopIfGoingOnBatteries
        }
        info = if ($info) {
            [ordered]@{
                last_run_time = [string]$info.LastRunTime
                last_task_result = [int]$info.LastTaskResult
                next_run_time = [string]$info.NextRunTime
                number_of_missed_runs = [int]$info.NumberOfMissedRuns
            }
        } else { $null }
        recent_events = $events
    }
}

function Get-ProcessFacts {
    $deployEscaped = [regex]::Escape((Resolve-FullPathOrRaw -PathText $DeployRoot))
    $patterns = @("uvicorn", "API.app.worker", "start_backend", "FanBanServer", $deployEscaped)
    $rows = New-Object System.Collections.Generic.List[object]
    try {
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
            $cmd = [string]$_.CommandLine
            $name = [string]$_.Name
            $keep = $false
            foreach ($pattern in $patterns) {
                if ($name -match "python|powershell|w3wp|acad|accoreconsole|excel|winword" -or ($cmd -and $cmd -match $pattern)) {
                    $keep = $true
                    break
                }
            }
            if ($keep) {
                $rows.Add([ordered]@{
                    process_id = [int]$_.ProcessId
                    parent_process_id = [int]$_.ParentProcessId
                    name = $name
                    command_line = $cmd
                    creation_date = [string]$_.CreationDate
                    executable_path = [string]$_.ExecutablePath
                })
            }
        }
    } catch {}
    return @($rows.ToArray() | Sort-Object name, process_id)
}

function Get-PythonFacts {
    $candidates = @(
        (Join-Path $DeployRoot "python-runtime\python.exe"),
        (Join-Path $DeployRoot "python.exe"),
        "python",
        "py"
    )
    $rows = New-Object System.Collections.Generic.List[object]
    foreach ($candidate in $candidates) {
        $exists = $true
        if ($candidate -match "^[A-Za-z]:\\") {
            $exists = Test-Path -LiteralPath $candidate -PathType Leaf
        }
        if (-not $exists) {
            $rows.Add([ordered]@{ command = $candidate; exists = $false })
            continue
        }
        $code = "import json,sys,site,platform; print(json.dumps({'executable':sys.executable,'version':sys.version,'prefix':sys.prefix,'base_prefix':sys.base_prefix,'platform':platform.platform(),'path':sys.path,'sitepackages':getattr(site,'getsitepackages',lambda:[])()}, ensure_ascii=False))"
        $r = Get-CommandResult -FilePath $candidate -ArgumentList @("-X", "utf8", "-c", $code) -TimeoutSec 20
        $parsed = $null
        if ($r.stdout) {
            try { $parsed = $r.stdout | ConvertFrom-Json } catch {}
        }
        $rows.Add([ordered]@{
            command = $candidate
            exists = $true
            exit_code = $r.exit_code
            timed_out = $r.timed_out
            error = $r.error
            stderr = $r.stderr
            info = $parsed
        })
    }
    return @($rows.ToArray())
}

function Get-PackageFacts {
    param([string]$Root)
    if ([string]::IsNullOrWhiteSpace($Root)) {
        return [ordered]@{ root = ""; exists = $false }
    }
    $rootResolved = Resolve-FullPathOrRaw -PathText $Root
    $exists = Test-Path -LiteralPath $rootResolved -PathType Container
    $manifestPath = Join-Path $rootResolved "package-manifest.json"
    $manifestInfo = [ordered]@{ exists = $false }
    if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
        $manifestJson = $null
        try { $manifestJson = Read-JsonFile -PathText $manifestPath } catch {}
        $manifestInfo = [ordered]@{
            exists = $true
            file = Get-FileFact -PathText $manifestPath
            generated_at_utc = if ($manifestJson) { [string]$manifestJson.generated_at_utc } else { "" }
            package_kind = if ($manifestJson) { [string]$manifestJson.package_kind } else { "" }
            file_count = if ($manifestJson) { [int]$manifestJson.file_count } else { 0 }
        }
    }

    $files = New-Object System.Collections.Generic.List[object]
    foreach ($rel in $script:ImportantPackagePaths) {
        $full = Join-Path $rootResolved $rel
        $files.Add([ordered]@{ relative_path = $rel; fact = Get-FileFact -PathText $full })
    }

    $dirs = @("frontend-dist", "backend-runtime", "install", "scripts", "documents", "documents_bin", "python-packages", "python-runtime", "storage", "storage\runtime", "storage\jobs") | ForEach-Object {
        [ordered]@{ relative_path = $_; fact = Get-DirectoryFact -PathText (Join-Path $rootResolved $_) }
    }

    return [ordered]@{
        root = $rootResolved
        exists = [bool]$exists
        manifest = $manifestInfo
        important_files = @($files.ToArray())
        important_dirs = @($dirs)
    }
}

function Find-FileInRoots {
    param(
        [string[]]$Roots,
        [string[]]$RelativeNames
    )
    foreach ($root in $Roots) {
        if ([string]::IsNullOrWhiteSpace($root)) { continue }
        foreach ($relative in $RelativeNames) {
            $candidate = Join-Path $root $relative
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                return $candidate
            }
        }
    }
    return ""
}

function Get-CadFacts {
    $installRows = New-Object System.Collections.Generic.List[object]
    foreach ($program in (Get-ProgramInventory | Where-Object { $_.name -match "AutoCAD|Autodesk|ODA|Open Design" })) {
        $installRows.Add($program)
    }

    $candidateDirs = New-Object System.Collections.Generic.List[string]
    foreach ($dir in @(
        "C:\Program Files\Autodesk",
        "C:\Program Files (x86)\Autodesk",
        "D:\Program Files\AUTOCAD",
        "D:\Program Files\Autodesk",
        (Join-Path $DeployRoot "bin")
    )) {
        if (Test-Path -LiteralPath $dir -PathType Container) {
            $candidateDirs.Add($dir)
        }
    }

    $executables = New-Object System.Collections.Generic.List[object]
    foreach ($base in @($candidateDirs.ToArray())) {
        foreach ($exeName in @("acad.exe", "accoreconsole.exe", "ODAFileConverter.exe")) {
            try {
                Get-ChildItem -LiteralPath $base -Recurse -File -Filter $exeName -ErrorAction SilentlyContinue |
                    Select-Object -First 20 |
                    ForEach-Object {
                        $executables.Add([ordered]@{
                            name = $_.Name
                            fact = Get-FileFact -PathText $_.FullName
                            version = (Get-Item -LiteralPath $_.FullName).VersionInfo.FileVersion
                        })
                    }
            } catch {}
        }
    }

    $fontRoots = New-Object System.Collections.Generic.List[string]
    foreach ($dir in @(
        "C:\Windows\Fonts",
        "D:\Program Files\AUTOCAD\AutoCAD 2022\Fonts",
        "$env:APPDATA\Autodesk\AutoCAD 2022\R24.1\chs\Fonts",
        "$env:APPDATA\Autodesk\AutoCAD 2022\R24.1\enu\Fonts",
        (Join-Path $DeployRoot "documents\Resources")
    )) {
        if (Test-Path -LiteralPath $dir -PathType Container) {
            $fontRoots.Add($dir)
        }
    }

    $requiredFiles = @("tssdeng.shx", "tssdchn.shx", "hztxt.shx", "tssdeng2.shx", "simsun.ttc", "simsun.ttf", "打印PDF2.pc3", "fanban_monochrome.ctb", "monochrome.ctb")
    $requiredFacts = New-Object System.Collections.Generic.List[object]
    foreach ($name in $requiredFiles) {
        $found = Find-FileInRoots -Roots @($fontRoots.ToArray() + @(
            "D:\Program Files\AUTOCAD\AutoCAD 2022\Plotters",
            "D:\Program Files\AUTOCAD\AutoCAD 2022\Plotters\Plot Styles",
            "$env:APPDATA\Autodesk\AutoCAD 2022\R24.1\chs\Plotters",
            "$env:APPDATA\Autodesk\AutoCAD 2022\R24.1\chs\Plotters\Plot Styles",
            "$env:APPDATA\Autodesk\AutoCAD 2022\R24.1\enu\Plotters",
            "$env:APPDATA\Autodesk\AutoCAD 2022\R24.1\enu\Plotters\Plot Styles",
            (Join-Path $DeployRoot "documents\Resources")
        )) -RelativeNames @($name)
        $requiredFacts.Add([ordered]@{ name = $name; fact = Get-FileFact -PathText $found })
    }

    return [ordered]@{
        installed_programs = @($installRows.ToArray())
        candidate_dirs = @($candidateDirs.ToArray())
        executables = @($executables.ToArray())
        font_roots = @($fontRoots.ToArray())
        required_assets = @($requiredFacts.ToArray())
    }
}

function Get-LogFacts {
    $logsDir = Join-Path $DeployRoot "logs"
    $files = @(
        "probe_target_env.json",
        "probe_target_env.deep.json",
        "check_health.summary.json",
        "check_health.full.json",
        "backend-latest-stderr.log",
        "backend-latest-stdout.log"
    )
    $facts = New-Object System.Collections.Generic.List[object]
    foreach ($file in $files) {
        $path = Join-Path $logsDir $file
        $tail = @()
        $parsed = $null
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $tail = ConvertTo-PlainLines -Lines (Get-Content -LiteralPath $path -Tail $LogTailLines -Encoding UTF8 -ErrorAction SilentlyContinue)
            if ($file -like "*.json") {
                try { $parsed = Read-JsonFile -PathText $path } catch {}
            }
        }
        $facts.Add([ordered]@{
            name = $file
            fact = Get-FileFact -PathText $path
            parsed = $parsed
            tail = $tail
        })
    }

    $recent = @()
    if (Test-Path -LiteralPath $logsDir -PathType Container) {
        $recent = @(Get-ChildItem -LiteralPath $logsDir -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 30 |
            ForEach-Object {
                [ordered]@{
                    name = $_.Name
                    size_bytes = [int64]$_.Length
                    last_write_utc = $_.LastWriteTimeUtc.ToString("o")
                }
            })
    }
    return [ordered]@{
        logs_dir = Get-DirectoryFact -PathText $logsDir
        key_files = @($facts.ToArray())
        recent_files = $recent
    }
}

function Invoke-ProjectProbes {
    param([string]$OutDir)
    $probeScript = Join-Path $DeployRoot "scripts\probe_target_env.ps1"
    $checkHealthScript = Join-Path $DeployRoot "scripts\check_health.ps1"
    $cadFingerprintScript = Join-Path $DeployRoot "scripts\cad_env_fingerprint.ps1"
    if (-not (Test-Path -LiteralPath $probeScript -PathType Leaf)) {
        $probeScript = Join-Path $PSScriptRoot "probe_target_env.ps1"
    }
    if (-not (Test-Path -LiteralPath $cadFingerprintScript -PathType Leaf)) {
        $cadFingerprintScript = Join-Path $PSScriptRoot "cad_env_fingerprint.ps1"
    }

    $results = [ordered]@{
        quick_probe = $null
        deep_probe = $null
        check_health = $null
        cad_fingerprint = $null
    }

    if (Test-Path -LiteralPath $probeScript -PathType Leaf) {
        $quickJson = Join-Path $OutDir "probe_target_env.quick.json"
        $deepJson = Join-Path $OutDir "probe_target_env.deep.json"
        $quick = Get-CommandResult -FilePath "powershell.exe" -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $probeScript,
            "-OutJson", $quickJson, "-RepoRoot", $DeployRoot, "-Port", [string]$ApiPort,
            "-StorageRoot", (Join-Path $DeployRoot "storage"), "-OfficeProbeMode", "quick"
        ) -TimeoutSec $ProbeTimeoutSec
        $deep = Get-CommandResult -FilePath "powershell.exe" -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $probeScript,
            "-OutJson", $deepJson, "-RepoRoot", $DeployRoot, "-Port", [string]$ApiPort,
            "-StorageRoot", (Join-Path $DeployRoot "storage"), "-OfficeProbeMode", "deep",
            "-ReuseQuickProbeJson", $quickJson
        ) -TimeoutSec $ProbeTimeoutSec
        $results.quick_probe = [ordered]@{
            command = $quick
            json_path = $quickJson
            parsed = if (Test-Path -LiteralPath $quickJson -PathType Leaf) { Read-JsonFile -PathText $quickJson } else { $null }
        }
        $results.deep_probe = [ordered]@{
            command = $deep
            json_path = $deepJson
            parsed = if (Test-Path -LiteralPath $deepJson -PathType Leaf) { Read-JsonFile -PathText $deepJson } else { $null }
        }
    }

    if (Test-Path -LiteralPath $checkHealthScript -PathType Leaf) {
        $check = Get-CommandResult -FilePath "powershell.exe" -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $checkHealthScript,
            "-Url", ("http://127.0.0.1:{0}/api/system/health" -f $ApiPort),
            "-PingUrl", ("http://127.0.0.1:{0}/api/system/ping" -f $ApiPort),
            "-ApiPort", [string]$ApiPort,
            "-Mode", "full"
        ) -TimeoutSec $ProbeTimeoutSec
        $summaryPath = Join-Path $DeployRoot "logs\check_health.summary.json"
        $fullPath = Join-Path $DeployRoot "logs\check_health.full.json"
        $results.check_health = [ordered]@{
            command = $check
            summary_path = $summaryPath
            full_path = $fullPath
            summary = if (Test-Path -LiteralPath $summaryPath -PathType Leaf) { Read-JsonFile -PathText $summaryPath } else { $null }
            full = if (Test-Path -LiteralPath $fullPath -PathType Leaf) { Read-JsonFile -PathText $fullPath } else { $null }
        }
    }

    if (Test-Path -LiteralPath $cadFingerprintScript -PathType Leaf) {
        $cadJson = Join-Path $OutDir "cad_env_fingerprint.json"
        $cad = Get-CommandResult -FilePath "powershell.exe" -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $cadFingerprintScript,
            "-OutputJson", $cadJson, "-RepoRoot", $DeployRoot
        ) -TimeoutSec $ProbeTimeoutSec
        $results.cad_fingerprint = [ordered]@{
            command = $cad
            json_path = $cadJson
            parsed = if (Test-Path -LiteralPath $cadJson -PathType Leaf) { Read-JsonFile -PathText $cadJson } else { $null }
        }
    }

    return $results
}

function Get-Report {
    param([string]$OutDir)
    $deployResolved = Resolve-FullPathOrRaw -PathText $DeployRoot
    $packageResolved = $PackageRoot
    if ([string]::IsNullOrWhiteSpace($packageResolved)) {
        $candidate = Join-Path (Split-Path -Parent $PSScriptRoot) "build\fanban-terminal-deploy"
        if (Test-Path -LiteralPath $candidate -PathType Container) {
            $packageResolved = $candidate
        }
    }

    $report = [ordered]@{
        schema_version = $script:SchemaVersion
        collected_at = (Get-Date).ToString("o")
        script = [ordered]@{
            path = $PSCommandPath
            version = $script:SchemaVersion
            run_project_probes = [bool]$RunProjectProbes
        }
        inputs = [ordered]@{
            deploy_root = $deployResolved
            package_root = Resolve-FullPathOrRaw -PathText $packageResolved
            output_dir = Resolve-FullPathOrRaw -PathText $OutDir
            api_base_url = $ApiBaseUrl
            api_port = $ApiPort
        }
        host = Invoke-Capture -ScriptBlock { Get-HostFacts }
        environment = Invoke-Capture -ScriptBlock { Get-EnvironmentFacts }
        drives = Invoke-Capture -ScriptBlock { Get-DriveFacts }
        dotnet = Invoke-Capture -ScriptBlock { Get-DotNetFacts }
        installed_programs = Invoke-Capture -ScriptBlock { Get-ProgramInventory }
        com_registration = Invoke-Capture -ScriptBlock { Get-ComRegistrationFacts }
        windows_features = Invoke-Capture -ScriptBlock { Get-WindowsFeatureFacts }
        iis = Invoke-Capture -ScriptBlock { Get-IisFacts }
        network = Invoke-Capture -ScriptBlock { Get-NetworkFacts }
        scheduled_task = Invoke-Capture -ScriptBlock { Get-TaskFacts }
        processes = Invoke-Capture -ScriptBlock { Get-ProcessFacts }
        python = Invoke-Capture -ScriptBlock { Get-PythonFacts }
        deploy_package = Invoke-Capture -ScriptBlock { Get-PackageFacts -Root $deployResolved }
        source_package = Invoke-Capture -ScriptBlock { Get-PackageFacts -Root $packageResolved }
        cad = Invoke-Capture -ScriptBlock { Get-CadFacts }
        http = Invoke-Capture -ScriptBlock { Get-HttpFacts }
        logs = Invoke-Capture -ScriptBlock { Get-LogFacts }
        project_probes = $null
    }

    if ($RunProjectProbes) {
        $report.project_probes = Invoke-Capture -ScriptBlock { Invoke-ProjectProbes -OutDir $OutDir }
    }

    return $report
}

function Should-IgnoreDiffPath {
    param([string]$PathText)
    $patterns = @(
        "\.collected_at$",
        "\.script\.path$",
        "\.inputs\.output_dir$",
        "\.last_write_utc$",
        "\.last_run_time$",
        "\.next_run_time$",
        "\.time_created$",
        "\.creation_date$",
        "\.server_time$",
        "\.worker_last_seen_at$",
        "\.elapsed_ms$",
        "\.process_id$",
        "\.parent_process_id$",
        "\.owning_process$",
        "\.content_sample$",
        "\.tail(\.|$)",
        "\.recent_events(\.|$)",
        "\.recent_files(\.|$)",
        "\.stdout$",
        "\.stderr$",
        "\.command\.stdout$",
        "\.command\.stderr$"
    )
    foreach ($pattern in $patterns) {
        if ($PathText -match $pattern) {
            return $true
        }
    }
    return $false
}

function ConvertTo-ComparableString {
    param([object]$Value)
    if ($null -eq $Value) {
        return "<null>"
    }
    if ($Value -is [bool]) {
        return $Value.ToString().ToLowerInvariant()
    }
    if ($Value -is [string]) {
        return $Value
    }
    if ($Value -is [ValueType]) {
        return [string]$Value
    }
    return ($Value | ConvertTo-Json -Compress -Depth 20)
}

function Add-FlattenedJson {
    param(
        [object]$Value,
        [string]$PathText,
        [hashtable]$Map
    )
    if (Should-IgnoreDiffPath -PathText $PathText) {
        return
    }
    if ($null -eq $Value) {
        $Map[$PathText] = "<null>"
        return
    }
    if ($Value -is [string] -or $Value -is [ValueType]) {
        $Map[$PathText] = ConvertTo-ComparableString -Value $Value
        return
    }
    if ($Value -is [System.Collections.IDictionary]) {
        foreach ($key in $Value.Keys) {
            Add-FlattenedJson -Value $Value[$key] -PathText ($PathText + "." + [string]$key) -Map $Map
        }
        return
    }
    if ($Value -is [System.Collections.IEnumerable] -and -not ($Value -is [string])) {
        $i = 0
        foreach ($item in $Value) {
            Add-FlattenedJson -Value $item -PathText ("{0}[{1}]" -f $PathText, $i) -Map $Map
            $i++
        }
        if ($i -eq 0) {
            $Map[$PathText] = "<empty-array>"
        }
        return
    }
    $props = @($Value.PSObject.Properties)
    if ($props.Count -eq 0) {
        $Map[$PathText] = ConvertTo-ComparableString -Value $Value
        return
    }
    foreach ($prop in $props) {
        Add-FlattenedJson -Value $prop.Value -PathText ($PathText + "." + $prop.Name) -Map $Map
    }
}

function Compare-EnvReports {
    param(
        [object]$Baseline,
        [object]$Current,
        [int]$MaxDiffs = 3000
    )
    $left = @{}
    $right = @{}
    Add-FlattenedJson -Value $Baseline -PathText "report" -Map $left
    Add-FlattenedJson -Value $Current -PathText "report" -Map $right

    $allKeys = New-Object System.Collections.Generic.HashSet[string]
    foreach ($key in $left.Keys) { [void]$allKeys.Add($key) }
    foreach ($key in $right.Keys) { [void]$allKeys.Add($key) }

    $diffs = New-Object System.Collections.Generic.List[object]
    foreach ($key in ($allKeys | Sort-Object)) {
        $lv = if ($left.ContainsKey($key)) { $left[$key] } else { "<missing>" }
        $rv = if ($right.ContainsKey($key)) { $right[$key] } else { "<missing>" }
        if ($lv -ne $rv) {
            $top = $key
            if ($top -match "^report\.([^.[]+)") { $top = $Matches[1] }
            $diffs.Add([ordered]@{
                path = $key
                section = $top
                baseline = $lv
                current = $rv
            })
            if ($diffs.Count -ge $MaxDiffs) {
                break
            }
        }
    }

    $sectionCounts = @{}
    foreach ($diff in $diffs) {
        if (-not $sectionCounts.ContainsKey($diff.section)) {
            $sectionCounts[$diff.section] = 0
        }
        $sectionCounts[$diff.section]++
    }

    return [ordered]@{
        schema_version = "fanban-env-diff@1"
        compared_at = (Get-Date).ToString("o")
        baseline_computer = [string]$Baseline.host.value.computer_name
        current_computer = [string]$Current.host.value.computer_name
        diff_count = $diffs.Count
        truncated = ($diffs.Count -ge $MaxDiffs)
        section_counts = $sectionCounts
        diffs = @($diffs.ToArray())
    }
}

function Write-DiffMarkdown {
    param(
        [object]$Diff,
        [string]$PathText
    )
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("# FanBan environment diff")
    $lines.Add("")
    $lines.Add(("- Compared at: {0}" -f $Diff.compared_at))
    $lines.Add(("- Baseline: {0}" -f $Diff.baseline_computer))
    $lines.Add(("- Current: {0}" -f $Diff.current_computer))
    $lines.Add(("- Diff count: {0}" -f $Diff.diff_count))
    $lines.Add("")
    $lines.Add("## Section counts")
    if ($Diff.section_counts -is [System.Collections.IDictionary]) {
        foreach ($key in ($Diff.section_counts.Keys | Sort-Object)) {
            $lines.Add(("- {0}: {1}" -f $key, $Diff.section_counts[$key]))
        }
    } else {
        foreach ($prop in ($Diff.section_counts.PSObject.Properties | Sort-Object Name)) {
            $lines.Add(("- {0}: {1}" -f $prop.Name, $prop.Value))
        }
    }
    $lines.Add("")
    $lines.Add("## First diffs")
    $i = 0
    foreach ($diff in $Diff.diffs) {
        $i++
        if ($i -gt 200) { break }
        $baseline = [string]$diff.baseline
        $current = [string]$diff.current
        if ($baseline.Length -gt 240) { $baseline = $baseline.Substring(0, 240) + "..." }
        if ($current.Length -gt 240) { $current = $current.Substring(0, 240) + "..." }
        $baseline = $baseline.Replace([string][char]96, "'")
        $current = $current.Replace([string][char]96, "'")
        $lines.Add(("{0}. {1}" -f $i, $diff.path))
        $lines.Add(("   - baseline: {0}" -f $baseline))
        $lines.Add(("   - current: {0}" -f $current))
    }
    Set-Content -LiteralPath $PathText -Value $lines -Encoding UTF8
}

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path (Get-Location) ("fanban-env-report-{0}-{1}" -f $env:COMPUTERNAME, (Get-Timestamp))
}
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$OutputDir = Resolve-FullPathOrRaw -PathText $OutputDir

$currentReport = $null
if (-not [string]::IsNullOrWhiteSpace($CurrentJson)) {
    $currentReport = Read-JsonFile -PathText $CurrentJson
} else {
    $currentReport = Get-Report -OutDir $OutputDir
    $currentPath = Join-Path $OutputDir ("fanban-env-{0}.json" -f $env:COMPUTERNAME)
    $currentReport | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $currentPath -Encoding UTF8
    Write-Host ("Wrote current environment report: {0}" -f $currentPath)
}

if (-not [string]::IsNullOrWhiteSpace($BaselineJson)) {
    $baseline = Read-JsonFile -PathText $BaselineJson
    $diff = Compare-EnvReports -Baseline $baseline -Current $currentReport
    $diffPath = Join-Path $OutputDir "fanban-env-diff.json"
    $diffMdPath = Join-Path $OutputDir "fanban-env-diff-summary.md"
    $diff | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $diffPath -Encoding UTF8
    Write-DiffMarkdown -Diff $diff -PathText $diffMdPath
    Write-Host ("Wrote diff report: {0}" -f $diffPath)
    Write-Host ("Wrote diff summary: {0}" -f $diffMdPath)
}

Write-Host ("Output directory: {0}" -f $OutputDir)
