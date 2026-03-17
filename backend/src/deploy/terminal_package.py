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
    path.write_text(content, encoding="utf-8", newline="\n")


def _write_support_files(
    output_root: Path,
    *,
    dotnet_installer: Path | None,
    vc_redist_installer: Path | None,
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
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$probeJson = Join-Path $root "logs\probe_target_env.json"
$runtimeEnv = Join-Path $PSScriptRoot "runtime.env.ps1"

New-Item -ItemType Directory -Path (Join-Path $root "logs") -Force | Out-Null

& (Join-Path $root "install\install_runtime_prereqs.ps1")
& (Join-Path $PSScriptRoot "init_storage.ps1")
& (Join-Path $PSScriptRoot "probe_target_env.ps1") -OutJson $probeJson -RepoRoot $root -Port $Port -StorageRoot $StorageRoot

$probe = Get-Content -LiteralPath $probeJson -Raw | ConvertFrom-Json -Depth 20
if ($probe.blocking_issues.Count -gt 0) {
    throw ("环境探测未通过，blocking issues = " + $probe.blocking_issues.Count)
}

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
    $escaped = $value.Replace("`", "``").Replace('"', '`"')
    $lines += ('$env:{0} = "{1}"' -f $name, $escaped)
}
$lines -join [Environment]::NewLine | Out-File -LiteralPath $runtimeEnv -Encoding utf8
Write-Host ("已生成运行环境文件: " + $runtimeEnv)
'''
    _write_text(output_root / "scripts" / "prepare_terminal.ps1", prepare_terminal)

    check_health = r'''param(
    [string]$Url = "http://127.0.0.1:8000/api/system/health"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$probeJson = Join-Path $root "logs\probe_target_env.json"
$probeScript = Join-Path $PSScriptRoot "probe_target_env.ps1"

if (Test-Path -LiteralPath $probeScript -PathType Leaf) {
    & $probeScript -OutJson $probeJson -RepoRoot $root
    Write-Host "==== Local Probe ===="
    Get-Content -LiteralPath $probeJson
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
$root = Split-Path -Parent $PSScriptRoot

$dotnet = Get-ChildItem -Path (Join-Path $root "dotnet") -Filter *.exe -File -ErrorAction SilentlyContinue | Select-Object -First 1
$vc = Get-ChildItem -Path (Join-Path $root "vc_redist") -Filter *.exe -File -ErrorAction SilentlyContinue | Select-Object -First 1

if ($dotnet) {
    Write-Host "安装 .NET Framework 4.8: $($dotnet.FullName)"
    & $dotnet.FullName /q /norestart
} else {
    Write-Warning ".NET Framework 4.8 离线安装器不存在，请手工补充。"
}

if ($vc) {
    Write-Host "安装 VC++ 运行时: $($vc.FullName)"
    & $vc.FullName /install /quiet /norestart
} else {
    Write-Warning "VC++ 离线安装器不存在，请手工补充。"
}
'''
    _write_text(output_root / "install" / "install_runtime_prereqs.ps1", install_runtime)

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
3. 确认 AutoCAD 与 Office 探测通过
4. 执行 `scripts\start_backend.ps1`
5. 执行 `scripts\check_health.ps1`
'''
    _write_text(output_root / DEPLOY_README, readme)

    missing_lines = ["# 缺失的离线安装器", ""]
    if dotnet_installer is None:
        missing_lines.append("- 未找到 `.NET Framework 4.8` 离线安装器，请手工放入 `install/dotnet/`。")
    if vc_redist_installer is None:
        missing_lines.append("- 未找到 `VC++ 2015-2022 x64` 离线安装器，请手工放入 `install/vc_redist/`。")
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


def build_terminal_deploy_package(
    *,
    repo_root: Path,
    output_root: Path,
    dotnet_installer: Path | None = None,
    vc_redist_installer: Path | None = None,
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
    )

    return output_root
