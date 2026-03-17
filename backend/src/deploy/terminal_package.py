from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

SPEC_NAME = "\u53c2\u6570\u89c4\u8303.yaml"
RUNTIME_SPEC_NAME = "\u53c2\u6570\u89c4\u8303_\u8fd0\u884c\u671f.yaml"
DEPLOY_README = "README_\u90e8\u7f72\u8bf4\u660e.md"
MISSING_INSTALLER_README = "README_\u7f3a\u5931\u79bb\u7ebf\u5b89\u88c5\u5668.md"


@dataclass(frozen=True)
class CopyPlanEntry:
    source: Path
    destination: Path


def gather_copy_plan(repo_root: Path) -> list[CopyPlanEntry]:
    return [
        CopyPlanEntry(repo_root / "frontend" / "dist", Path("frontend-dist")),
        CopyPlanEntry(repo_root / "API", Path("backend-runtime") / "API"),
        CopyPlanEntry(repo_root / "backend" / "src", Path("backend-runtime") / "backend" / "src"),
        CopyPlanEntry(
            repo_root / "backend" / "pyproject.toml",
            Path("backend-runtime") / "backend" / "pyproject.toml",
        ),
        CopyPlanEntry(
            repo_root / "backend" / ".venv",
            Path("backend-runtime") / "backend" / ".venv",
        ),
        CopyPlanEntry(
            repo_root
            / "backend"
            / "src"
            / "cad"
            / "dotnet"
            / "Module5CadBridge"
            / "bin"
            / "Release"
            / "net48",
            Path("backend-runtime")
            / "backend"
            / "src"
            / "cad"
            / "dotnet"
            / "Module5CadBridge"
            / "bin"
            / "Release"
            / "net48",
        ),
        CopyPlanEntry(
            repo_root / "bin" / "ODAFileConverter 25.12.0",
            Path("bin") / "ODAFileConverter 25.12.0",
        ),
        CopyPlanEntry(repo_root / "documents" / "Resources", Path("documents") / "Resources"),
        CopyPlanEntry(repo_root / "documents" / SPEC_NAME, Path("documents") / SPEC_NAME),
        CopyPlanEntry(repo_root / "documents" / RUNTIME_SPEC_NAME, Path("documents") / RUNTIME_SPEC_NAME),
        CopyPlanEntry(repo_root / "documents_bin", Path("documents_bin")),
        CopyPlanEntry(repo_root / "tools" / "probe_target_env.ps1", Path("scripts") / "probe_target_env.ps1"),
    ]


def _ensure_exists(copy_plan: list[CopyPlanEntry]) -> None:
    missing = [str(entry.source) for entry in copy_plan if not entry.source.exists()]
    if missing:
        joined = "\n".join(missing)
        raise FileNotFoundError(f"离线部署包缺少必要源文件/目录:\n{joined}")


def _copy_entry(entry: CopyPlanEntry, output_root: Path) -> None:
    target = output_root / entry.destination
    if entry.source.is_dir():
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(entry.source, target)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry.source, target)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoding = "utf-8-sig" if path.suffix.lower() == ".ps1" else "utf-8"
    path.write_text(content, encoding=encoding, newline="\n")


def _write_support_files(
    output_root: Path,
    *,
    dotnet_installer: Path | None,
    vc_redist_installer: Path | None,
    url_rewrite_installer: Path | None,
    arr_installer: Path | None,
) -> None:
    storage_root = output_root / "storage"
    for rel in [Path("jobs"), Path("groups"), Path("runtime")]:
        (storage_root / rel).mkdir(parents=True, exist_ok=True)

    start_backend = r'''param(
    [string]$Host = "127.0.0.1",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "backend-runtime\backend\.venv\Scripts\python.exe"
$runtimeEnv = Join-Path $PSScriptRoot "runtime.env.ps1"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python 运行环境不存在: $python"
}

if (Test-Path -LiteralPath $runtimeEnv -PathType Leaf) {
    . $runtimeEnv
}

Push-Location $root
try {
    & $python -m uvicorn API.app.main:create_app --factory --host $Host --port $Port
} finally {
    Pop-Location
}
'''
    _write_text(output_root / "scripts" / "start_backend.ps1", start_backend)

    init_storage = r'''$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$storage = Join-Path $root "storage"

$dirs = @(
    "jobs",
    "groups",
    "runtime",
    "runtime\cad-slots\slot-01",
    "runtime\cad-slots\slot-02",
    "runtime\cad-slots\slot-03",
    "runtime\cad-slots\slot-04"
)

foreach ($dir in $dirs) {
    New-Item -ItemType Directory -Path (Join-Path $storage $dir) -Force | Out-Null
}

Write-Host "storage 初始化完成"
'''
    _write_text(output_root / "scripts" / "init_storage.ps1", init_storage)

    prepare_terminal = r'''param(
    [string]$StorageRoot = "",
    [int]$Port = 8000,
    [ValidateSet("quick", "deep")]
    [string]$OfficeProbeMode = "quick"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$probeJson = Join-Path $root "logs\probe_target_env.json"
$runtimeEnv = Join-Path $PSScriptRoot "runtime.env.ps1"

New-Item -ItemType Directory -Path (Join-Path $root "logs") -Force | Out-Null

Write-Host "[1/4] 检查并安装运行时依赖..."
& (Join-Path $root "install\install_runtime_prereqs.ps1")

Write-Host "[2/4] 初始化 storage 目录..."
& (Join-Path $PSScriptRoot "init_storage.ps1")

Write-Host ("[3/4] 执行环境探针（Office 模式: " + $OfficeProbeMode + "）...")
& (Join-Path $PSScriptRoot "probe_target_env.ps1") -OutJson $probeJson -RepoRoot $root -Port $Port -StorageRoot $StorageRoot -OfficeProbeMode $OfficeProbeMode

$probe = Get-Content -LiteralPath $probeJson -Raw | ConvertFrom-Json
if ($probe.blocking_issues.Count -gt 0) {
    Write-Host "Blocking issues detail:"
    foreach ($issue in $probe.blocking_issues) {
        $section = if ($null -ne $issue.section) { [string]$issue.section } else { "unknown" }
        $code = if ($null -ne $issue.code) { [string]$issue.code } else { "-" }
        $message = if ($null -ne $issue.message) { [string]$issue.message } else { "" }
        Write-Host ("- [{0}/{1}] {2}" -f $section, $code, $message)
    }
    Write-Host ("探针结果文件: " + $probeJson)
    throw ("环境探测未通过，blocking issues = " + $probe.blocking_issues.Count)
}

Write-Host "[4/4] 生成运行环境文件..."
$envMap = $probe.recommended_runtime.recommended_env
$lines = @(
    '$ErrorActionPreference = "Stop"',
    ''
)
foreach ($prop in $envMap.PSObject.Properties) {
    $name = [string]$prop.Name
    $value = [string]$prop.Value
    if ([string]::IsNullOrWhiteSpace($value)) {
        continue
    }
    $escaped = $value.Replace("'", "''")
    $lines += ("Set-Item -Path 'Env:{0}' -Value '{1}'" -f $name, $escaped)
}
$lines -join [Environment]::NewLine | Out-File -LiteralPath $runtimeEnv -Encoding utf8
Write-Host ("已生成运行环境文件: " + $runtimeEnv)
'''
    _write_text(output_root / "scripts" / "prepare_terminal.ps1", prepare_terminal)

    deep_check_terminal = r'''param(
    [string]$StorageRoot = "",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$probeJson = Join-Path $root "logs\probe_target_env.deep.json"

Write-Host "开始执行深度环境检查..."
& (Join-Path $PSScriptRoot "probe_target_env.ps1") -OutJson $probeJson -RepoRoot $root -Port $Port -StorageRoot $StorageRoot -OfficeProbeMode deep
Write-Host ("深度环境检查完成，输出文件: " + $probeJson)
'''
    _write_text(output_root / "scripts" / "deep_check_terminal.ps1", deep_check_terminal)

    check_health = r'''param(
    [string]$Url = "http://127.0.0.1:8000/api/system/health"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$probeJson = Join-Path $root "logs\probe_target_env.json"
$probeScript = Join-Path $PSScriptRoot "probe_target_env.ps1"
$iisProxyScript = Join-Path $root "install\check_iis_proxy_prereqs.ps1"

if (Test-Path -LiteralPath $probeScript -PathType Leaf) {
    & $probeScript -OutJson $probeJson -RepoRoot $root -OfficeProbeMode quick
    Write-Host "==== Local Probe ===="
    Get-Content -LiteralPath $probeJson
}

if (Test-Path -LiteralPath $iisProxyScript -PathType Leaf) {
    Write-Host "==== IIS Proxy Prereqs ===="
    & $iisProxyScript
}

try {
    $resp = Invoke-RestMethod -Uri $Url -Method Get
    Write-Host "==== API Health ===="
    $resp | ConvertTo-Json -Depth 8
} catch {
    Write-Warning ("API health unavailable: " + $_.Exception.Message)
}
'''
    _write_text(output_root / "scripts" / "check_health.ps1", check_health)

    install_runtime = r'''$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Get-DotNetRelease {
    $keys = @(
        "HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\NET Framework Setup\NDP\v4\Full"
    )
    foreach ($key in $keys) {
        try {
            $item = Get-ItemProperty -Path $key -ErrorAction Stop
            if ($null -ne $item.Release) {
                return [int]$item.Release
            }
        } catch {
        }
    }
    return 0
}

function Test-DotNet48OrAboveInstalled {
    return ((Get-DotNetRelease) -ge 528040)
}

function Get-VcRuntimeInfo {
    $keys = @(
        "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"
    )
    foreach ($key in $keys) {
        try {
            $item = Get-ItemProperty -Path $key -ErrorAction Stop
            if ([int]$item.Installed -eq 1) {
                return [ordered]@{
                    installed = $true
                    version = [string]$item.Version
                }
            }
        } catch {
        }
    }
    return [ordered]@{
        installed = $false
        version = ""
    }
}

$dotnet = Get-ChildItem -Path (Join-Path $root "dotnet") -Filter *.exe -File -ErrorAction SilentlyContinue | Select-Object -First 1
$vc = Get-ChildItem -Path (Join-Path $root "vc_redist") -Filter *.exe -File -ErrorAction SilentlyContinue | Select-Object -First 1

if (Test-DotNet48OrAboveInstalled) {
    Write-Host ".NET Framework 4.8 或更高版本已安装，跳过。"
} elseif ($dotnet) {
    Write-Host "安装 .NET Framework 4.8: $($dotnet.FullName)"
    & $dotnet.FullName /q /norestart
} else {
    Write-Warning ".NET Framework 4.8 未安装，且离线安装器不存在，请手工补充。"
}

$vcInfo = Get-VcRuntimeInfo
if ($vcInfo.installed) {
    $versionText = if ([string]::IsNullOrWhiteSpace($vcInfo.version)) { "未知版本" } else { $vcInfo.version }
    Write-Host ("VC++ 2015-2022 x64 运行时已安装，版本: " + $versionText + "，跳过。")
} elseif ($vc) {
    Write-Host "安装 VC++ 运行时: $($vc.FullName)"
    & $vc.FullName /install /quiet /norestart
} else {
    Write-Warning "VC++ 2015-2022 x64 运行时未安装，且离线安装器不存在，请手工补充。"
}
'''
    _write_text(output_root / "install" / "install_runtime_prereqs.ps1", install_runtime)

    install_iis_proxy = r'''$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Test-IisInstalled {
    try {
        Import-Module WebAdministration -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

function Test-UrlRewriteInstalled {
    if (-not (Test-IisInstalled)) {
        return $false
    }
    $rewriteModule = Get-WebGlobalModule -Name "RewriteModule" -ErrorAction SilentlyContinue
    return ($null -ne $rewriteModule)
}

function Test-ArrInstalled {
    if (-not (Test-IisInstalled)) {
        return $false
    }
    $proxySection = Get-WebConfigurationProperty -PSPath "MACHINE/WEBROOT/APPHOST" -Filter "system.webServer/proxy" -Name "." -ErrorAction SilentlyContinue
    if ($null -ne $proxySection) {
        return $true
    }
    $arrModule = Get-WebGlobalModule | Where-Object {
        $_.Name -like "*ARR*" -or $_.Image -like "*requestRouter*"
    }
    return ($null -ne $arrModule)
}

$rewrite = Get-ChildItem -Path (Join-Path $root "iis\url_rewrite") -Filter *.msi -File -ErrorAction SilentlyContinue | Select-Object -First 1
$arr = Get-ChildItem -Path (Join-Path $root "iis\arr") -Filter *.msi -File -ErrorAction SilentlyContinue | Select-Object -First 1

if (Test-UrlRewriteInstalled) {
    Write-Host "URL Rewrite 已安装，跳过。"
} elseif ($rewrite) {
    Write-Host "安装 URL Rewrite: $($rewrite.FullName)"
    Start-Process -FilePath "msiexec.exe" -ArgumentList @("/i", $rewrite.FullName, "/qn", "/norestart") -Wait
} else {
    Write-Warning "URL Rewrite 未安装，且离线安装器不存在，请手工补充。"
}

if (Test-ArrInstalled) {
    Write-Host "ARR 已安装，跳过。"
} elseif ($arr) {
    Write-Host "安装 ARR: $($arr.FullName)"
    Start-Process -FilePath "msiexec.exe" -ArgumentList @("/i", $arr.FullName, "/qn", "/norestart") -Wait
} else {
    Write-Warning "ARR 未安装，且离线安装器不存在，请手工补充。"
}
'''
    _write_text(output_root / "install" / "install_iis_proxy_prereqs.ps1", install_iis_proxy)

    check_iis_proxy = r'''$ErrorActionPreference = "Stop"

$iisInstalled = $false
try {
    Import-Module WebAdministration -ErrorAction Stop
    $iisInstalled = $true
} catch {
    $iisInstalled = $false
}

$rewriteInstalled = $false
$arrInstalled = $false

if ($iisInstalled) {
    $rewriteModule = Get-WebGlobalModule -Name "RewriteModule" -ErrorAction SilentlyContinue
    if ($null -ne $rewriteModule) {
        $rewriteInstalled = $true
    }

    $proxySection = Get-WebConfigurationProperty -PSPath "MACHINE/WEBROOT/APPHOST" -Filter "system.webServer/proxy" -Name "." -ErrorAction SilentlyContinue
    if ($null -ne $proxySection) {
        $arrInstalled = $true
    }

    if (-not $arrInstalled) {
        $arrModule = Get-WebGlobalModule | Where-Object {
            $_.Name -like "*ARR*" -or $_.Image -like "*requestRouter*"
        }
        if ($null -ne $arrModule) {
            $arrInstalled = $true
        }
    }
}

$result = [ordered]@{
    iis = [ordered]@{
        installed = $iisInstalled
        status = if ($iisInstalled) { "pass" } else { "missing" }
    }
    url_rewrite = [ordered]@{
        installed = $rewriteInstalled
        status = if ($rewriteInstalled) { "pass" } else { "missing" }
        module_name = "RewriteModule"
    }
    arr = [ordered]@{
        installed = $arrInstalled
        status = if ($arrInstalled) { "pass" } else { "missing" }
        product_name = "Application Request Routing"
    }
}

$result | ConvertTo-Json -Depth 6

if (-not $iisInstalled) {
    Write-Warning "未检测到 IIS。"
}
if (-not $rewriteInstalled) {
    Write-Warning "未检测到 URL Rewrite 模块。"
}
if (-not $arrInstalled) {
    Write-Warning "未检测到 ARR（Application Request Routing）。"
}
'''
    _write_text(output_root / "install" / "check_iis_proxy_prereqs.ps1", check_iis_proxy)

    configure_iis_site = r'''param(
    [string]$SiteName = "FanBanTerminal",
    [string]$AppPoolName = "FanBanTerminalAppPool",
    [int]$Port = 80,
    [string]$HostName = "",
    [string]$BindAddress = "*",
    [int]$ApiPort = 8000,
    [switch]$EnableReverseProxy = $true,
    [string]$PhysicalPath = ""
)

$ErrorActionPreference = "Stop"
Import-Module WebAdministration

$root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($PhysicalPath)) {
    $PhysicalPath = Join-Path $root "frontend-dist"
}

if (-not (Test-Path -LiteralPath $PhysicalPath -PathType Container)) {
    throw "前端静态目录不存在: $PhysicalPath"
}

if (-not (Test-Path "IIS:\AppPools\$AppPoolName")) {
    New-WebAppPool -Name $AppPoolName | Out-Null
}
Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name managedRuntimeVersion -Value ""
Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name processModel.identityType -Value "ApplicationPoolIdentity"

$bindingInformation = "{0}:{1}:{2}" -f $BindAddress, $Port, $HostName

if (-not (Test-Path "IIS:\Sites\$SiteName")) {
    New-Website -Name $SiteName -PhysicalPath $PhysicalPath -Port $Port -IPAddress $BindAddress -HostHeader $HostName | Out-Null
} else {
    Stop-Website -Name $SiteName -ErrorAction SilentlyContinue | Out-Null
    Set-ItemProperty "IIS:\Sites\$SiteName" -Name physicalPath -Value $PhysicalPath
    Get-WebBinding -Name $SiteName -ErrorAction SilentlyContinue | Remove-WebBinding -ErrorAction SilentlyContinue
    New-WebBinding -Name $SiteName -Protocol http -IPAddress $BindAddress -Port $Port -HostHeader $HostName | Out-Null
}

Set-ItemProperty "IIS:\Sites\$SiteName" -Name applicationPool -Value $AppPoolName

$webConfig = Join-Path $PhysicalPath "web.config"
$proxyWarning = $null
if ($EnableReverseProxy) {
    $rewriteModule = Get-WebGlobalModule -Name "RewriteModule" -ErrorAction SilentlyContinue
    $proxySection = Get-WebConfigurationProperty -PSPath "MACHINE/WEBROOT/APPHOST" -Filter "system.webServer/proxy" -Name "." -ErrorAction SilentlyContinue
    $arrInstalled = $null -ne $proxySection
    if ($null -eq $rewriteModule -or -not $arrInstalled) {
        $missingParts = @()
        if ($null -eq $rewriteModule) {
            $missingParts += "URL Rewrite"
        }
        if (-not $arrInstalled) {
            $missingParts += "ARR"
        }
        $proxyWarning = "未检测到 " + ($missingParts -join " + ") + "，已仅写入 SPA 静态站点配置。若需要同源 /api 反代，请离线安装缺失组件。"
        $webConfigContent = @"
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="SPA Fallback" stopProcessing="true">
          <match url=".*" />
          <conditions logicalGrouping="MatchAll">
            <add input="{REQUEST_FILENAME}" matchType="IsFile" negate="true" />
            <add input="{REQUEST_FILENAME}" matchType="IsDirectory" negate="true" />
          </conditions>
          <action type="Rewrite" url="/index.html" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
"@
    } else {
        $appcmd = Join-Path $env:WinDir "System32\inetsrv\appcmd.exe"
        if (Test-Path -LiteralPath $appcmd -PathType Leaf) {
            & $appcmd set config -section:system.webServer/proxy /enabled:"True" /commit:apphost | Out-Null
        }
        $webConfigContent = @"
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="API Proxy" stopProcessing="true">
          <match url="^api/(.*)" />
          <action type="Rewrite" url="http://127.0.0.1:$ApiPort/api/{R:1}" />
        </rule>
        <rule name="SPA Fallback" stopProcessing="true">
          <match url=".*" />
          <conditions logicalGrouping="MatchAll">
            <add input="{REQUEST_FILENAME}" matchType="IsFile" negate="true" />
            <add input="{REQUEST_FILENAME}" matchType="IsDirectory" negate="true" />
            <add input="{REQUEST_URI}" pattern="^/api/" negate="true" />
          </conditions>
          <action type="Rewrite" url="/index.html" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
"@
    }
} else {
    $webConfigContent = @"
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="SPA Fallback" stopProcessing="true">
          <match url=".*" />
          <conditions logicalGrouping="MatchAll">
            <add input="{REQUEST_FILENAME}" matchType="IsFile" negate="true" />
            <add input="{REQUEST_FILENAME}" matchType="IsDirectory" negate="true" />
          </conditions>
          <action type="Rewrite" url="/index.html" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
"@
}

$webConfigContent | Out-File -LiteralPath $webConfig -Encoding utf8
Start-Website -Name $SiteName | Out-Null

$displayHost = if ([string]::IsNullOrWhiteSpace($HostName)) { "<部署机IP或主机名>" } else { $HostName }
$displayPort = if ($Port -eq 80) { "" } else { ":" + $Port }
Write-Host ("IIS 站点已配置完成。前端访问地址: http://{0}{1}/" -f $displayHost, $displayPort)
if ($proxyWarning) {
    Write-Warning $proxyWarning
}
'''
    _write_text(output_root / "install" / "configure_iis_site.ps1", configure_iis_site)

    register_backend_service = r'''param(
    [string]$ServiceName = "FanBanBackend",
    [string]$DisplayName = "FanBan Backend",
    [ValidateSet("auto", "nssm", "scheduled-task")]
    [string]$Mode = "auto"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$startScript = Join-Path $root "scripts\start_backend.ps1"
if (-not (Test-Path -LiteralPath $startScript -PathType Leaf)) {
    throw "启动脚本不存在: $startScript"
}

function Get-NssmPath {
    $candidate = Join-Path $PSScriptRoot "nssm\nssm.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        return $candidate
    }
    $cmd = Get-Command nssm.exe -ErrorAction SilentlyContinue
    if ($null -eq $cmd) {
        $cmd = Get-Command nssm -ErrorAction SilentlyContinue
    }
    return if ($null -ne $cmd) { [string]$cmd.Source } else { "" }
}

function Register-WithNssm([string]$nssmPath) {
    & $nssmPath remove $ServiceName confirm 2>$null | Out-Null
    & $nssmPath install $ServiceName "powershell.exe" "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`""
    & $nssmPath set $ServiceName AppDirectory $root
    & $nssmPath set $ServiceName DisplayName $DisplayName
    & $nssmPath set $ServiceName Start SERVICE_AUTO_START
    Write-Host ("已使用 NSSM 注册 Windows 服务: " + $ServiceName)
}

function Register-WithScheduledTask {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`""
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $ServiceName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Write-Warning ("未检测到 NSSM，已回退为开机自启动计划任务: " + $ServiceName)
}

$nssmPath = Get-NssmPath
if ($Mode -eq "nssm" -and [string]::IsNullOrWhiteSpace($nssmPath)) {
    throw "指定使用 NSSM，但未找到 nssm.exe"
}

if ($Mode -eq "nssm" -or ($Mode -eq "auto" -and -not [string]::IsNullOrWhiteSpace($nssmPath))) {
    Register-WithNssm -nssmPath $nssmPath
} else {
    Register-WithScheduledTask
}
'''
    _write_text(output_root / "install" / "register_backend_service.ps1", register_backend_service)

    unregister_backend_service = r'''param(
    [string]$ServiceName = "FanBanBackend"
)

$ErrorActionPreference = "Stop"

$nssmCommand = Get-Command nssm.exe -ErrorAction SilentlyContinue
if ($null -eq $nssmCommand) {
    $nssmCommand = Get-Command nssm -ErrorAction SilentlyContinue
}

if ($null -ne $nssmCommand) {
    & $nssmCommand.Source remove $ServiceName confirm 2>$null | Out-Null
}

if (Get-ScheduledTask -TaskName $ServiceName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $ServiceName -Confirm:$false
}

Write-Host ("已移除服务/计划任务: " + $ServiceName)
'''
    _write_text(output_root / "install" / "unregister_backend_service.ps1", unregister_backend_service)

    readme = r'''# 部署说明

## 目录用途
- `frontend-dist/`: IIS 前端站点目录
- `backend-runtime/`: 后端运行目录
- `bin/ODAFileConverter 25.12.0/`: ODA 运行目录
- `documents/Resources/`: 受管打印和校准资源
- `documents_bin/`: 模板与词库资源
- `scripts/`: 启动、探测、健康检查脚本
- `install/`: 离线运行时安装脚本和安装器目录

## 建议顺序

1. 先执行 `install\install_runtime_prereqs.ps1`
2. 再执行 `scripts\prepare_terminal.ps1`
3. 配置 IIS：`install\configure_iis_site.ps1`
4. 注册后端常驻：`install\register_backend_service.ps1`
5. 确认 AutoCAD 与 Office 探测通过
6. 手工启动时执行 `scripts\start_backend.ps1`
7. 执行 `scripts\check_health.ps1`

## 前端地址怎么定

- 推荐使用 IIS 同源模式，前端访问地址就是 IIS 站点绑定的地址。
- 你可以自己设置：
  - `http://部署机IP/`
  - `http://部署机IP:8080/`
  - `http://自定义主机名/`
- `configure_iis_site.ps1` 里通过 `HostName` 和 `Port` 控制最终地址，不固定写死 IP。
'''
    _write_text(output_root / DEPLOY_README, readme)

    missing_lines = ["# 缺失的离线安装器", ""]
    if dotnet_installer is None:
        missing_lines.append("- 未找到 `.NET Framework 4.8` 离线安装器，请手工放入 `install/dotnet/`。")
    if vc_redist_installer is None:
        missing_lines.append("- 未找到 `VC++ 2015-2022 x64` 离线安装器，请手工放入 `install/vc_redist/`。")
    if url_rewrite_installer is None:
        missing_lines.append("- 未找到 `URL Rewrite` 离线安装器，请手工放入 `install/iis/url_rewrite/`。")
    if arr_installer is None:
        missing_lines.append("- 未找到 `ARR` 离线安装器，请手工放入 `install/iis/arr/`。")
    if len(missing_lines) == 2:
        missing_lines.append("- 当前离线安装器已齐备。")
    _write_text(output_root / "install" / MISSING_INSTALLER_README, "\n".join(missing_lines) + "\n")

    if dotnet_installer is not None:
        target = output_root / "install" / "dotnet" / dotnet_installer.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dotnet_installer, target)
    else:
        (output_root / "install" / "dotnet").mkdir(parents=True, exist_ok=True)

    if vc_redist_installer is not None:
        target = output_root / "install" / "vc_redist" / vc_redist_installer.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(vc_redist_installer, target)
    else:
        (output_root / "install" / "vc_redist").mkdir(parents=True, exist_ok=True)

    if url_rewrite_installer is not None:
        target = output_root / "install" / "iis" / "url_rewrite" / url_rewrite_installer.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(url_rewrite_installer, target)
    else:
        (output_root / "install" / "iis" / "url_rewrite").mkdir(parents=True, exist_ok=True)

    if arr_installer is not None:
        target = output_root / "install" / "iis" / "arr" / arr_installer.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(arr_installer, target)
    else:
        (output_root / "install" / "iis" / "arr").mkdir(parents=True, exist_ok=True)


def build_terminal_deploy_package(
    *,
    repo_root: Path,
    output_root: Path,
    dotnet_installer: Path | None = None,
    vc_redist_installer: Path | None = None,
    url_rewrite_installer: Path | None = None,
    arr_installer: Path | None = None,
) -> Path:
    copy_plan = gather_copy_plan(repo_root)
    _ensure_exists(copy_plan)

    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    for entry in copy_plan:
        _copy_entry(entry, output_root)

    _write_support_files(
        output_root,
        dotnet_installer=dotnet_installer,
        vc_redist_installer=vc_redist_installer,
        url_rewrite_installer=url_rewrite_installer,
        arr_installer=arr_installer,
    )

    return output_root
