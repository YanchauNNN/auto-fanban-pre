from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SPEC_NAME = "\u53c2\u6570\u89c4\u8303.yaml"
RUNTIME_SPEC_NAME = "\u53c2\u6570\u89c4\u8303_\u8fd0\u884c\u671f.yaml"
DEPLOY_README = "README_\u90e8\u7f72\u8bf4\u660e.md"
MISSING_INSTALLER_README = "README_\u7f3a\u5931\u79bb\u7ebf\u5b89\u88c5\u5668.md"
PYTHON_PACKAGES_DEST = Path("python-packages") / "Lib" / "site-packages"
STALE_RUNTIME_PTH_FILES = ("_auto_fanban.pth", "a1_coverage.pth")
PACKAGE_MANIFEST = "package-manifest.json"
DELTA_DIR_NAME = "_delta"
DELTA_MANIFEST = "delta-manifest.json"
DELTA_OVERWRITE_LIST = "覆盖清单.txt"
DELTA_DELETE_LIST = "删除清单.txt"
DELTA_USAGE = "使用说明.txt"


@dataclass(frozen=True)
class CopyPlanEntry:
    source: Path
    destination: Path


@dataclass(frozen=True)
class DeployArtifacts:
    full_root: Path
    delta_root: Path


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
            repo_root / "backend" / ".venv" / "Lib" / "site-packages",
            PYTHON_PACKAGES_DEST,
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
        ignore = None
        if entry.destination != PYTHON_PACKAGES_DEST:
            ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
        shutil.copytree(
            entry.source,
            target,
            ignore=ignore,
        )
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry.source, target)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoding = "utf-8-sig" if path.suffix.lower() == ".ps1" else "utf-8"
    path.write_text(content, encoding=encoding, newline="\n")


def _sanitize_python_packages(output_root: Path) -> None:
    site_packages_root = output_root / PYTHON_PACKAGES_DEST
    if not site_packages_root.exists():
        return
    for filename in STALE_RUNTIME_PTH_FILES:
        target = site_packages_root / filename
        if target.exists():
            target.unlink()


def _timestamp_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_package_files(package_root: Path) -> list[Path]:
    if not package_root.exists():
        return []
    return sorted(path for path in package_root.rglob("*") if path.is_file())


def _collect_package_files(package_root: Path | None) -> dict[str, dict[str, object]]:
    if package_root is None or not package_root.exists():
        return {}

    files: dict[str, dict[str, object]] = {}
    for path in _iter_package_files(package_root):
        rel_path = path.relative_to(package_root).as_posix()
        files[rel_path] = {
            "path": rel_path,
            "size": path.stat().st_size,
            "sha256": _hash_file(path),
        }
    return files


def _write_json(path: Path, payload: object) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def write_package_manifest(package_root: Path, *, package_kind: str) -> dict[str, object]:
    file_map = _collect_package_files(package_root)
    file_map.pop(PACKAGE_MANIFEST, None)
    manifest = {
        "generated_at_utc": _timestamp_utc(),
        "package_kind": package_kind,
        "file_count": len(file_map),
        "files": [file_map[key] for key in sorted(file_map)],
    }
    _write_json(package_root / PACKAGE_MANIFEST, manifest)
    return manifest


def _copy_relative_file(source_root: Path, destination_root: Path, rel_path: str) -> None:
    source = source_root / Path(rel_path)
    target = destination_root / Path(rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _write_delta_text_list(path: Path, header: str, items: list[str], empty_message: str) -> None:
    lines = [header, ""]
    if items:
        lines.extend(items)
    else:
        lines.append(empty_message)
    _write_text(path, "\n".join(lines) + "\n")


def _is_delta_relevant_path(rel_path: str) -> bool:
    path = Path(rel_path)
    if "__pycache__" in path.parts:
        return False
    if path.suffix.lower() in {".pyc", ".pyo"}:
        return False
    return True


def build_terminal_deploy_delta_package(
    *,
    baseline_root: Path | None,
    target_root: Path,
    delta_root: Path,
    baseline_label: str,
    target_label: str,
) -> Path:
    baseline_exists = baseline_root is not None and baseline_root.exists()
    baseline_files = _collect_package_files(baseline_root) if baseline_exists else {}
    target_files = _collect_package_files(target_root)

    baseline_files.pop(PACKAGE_MANIFEST, None)
    target_files.pop(PACKAGE_MANIFEST, None)
    baseline_files = {path: meta for path, meta in baseline_files.items() if _is_delta_relevant_path(path)}
    target_files = {path: meta for path, meta in target_files.items() if _is_delta_relevant_path(path)}

    if delta_root.exists():
        shutil.rmtree(delta_root)
    delta_root.mkdir(parents=True, exist_ok=True)

    added_files: list[str] = []
    modified_files: list[str] = []
    deleted_files: list[str] = []

    if baseline_exists:
        added_files = sorted(path for path in target_files if path not in baseline_files)
        modified_files = sorted(
            path
            for path in target_files
            if path in baseline_files and target_files[path]["sha256"] != baseline_files[path]["sha256"]
        )
        deleted_files = sorted(path for path in baseline_files if path not in target_files)
        for rel_path in added_files + modified_files:
            _copy_relative_file(target_root, delta_root, rel_path)

    unchanged_files = 0
    if baseline_exists:
        unchanged_files = sum(
            1
            for path in target_files
            if path in baseline_files and target_files[path]["sha256"] == baseline_files[path]["sha256"]
        )

    delta_meta_dir = delta_root / DELTA_DIR_NAME
    delta_meta_dir.mkdir(parents=True, exist_ok=True)

    delta_manifest = {
        "generated_at_utc": _timestamp_utc(),
        "baseline_exists": baseline_exists,
        "baseline_package_root": baseline_label,
        "target_package_root": target_label,
        "added_files": added_files,
        "modified_files": modified_files,
        "deleted_files": deleted_files,
        "copied_file_count": len(added_files) + len(modified_files),
        "unchanged_file_count": unchanged_files,
        "message": (
            "未检测到上一版 full 包基线；首次部署或基线不确定时请使用 full 包。"
            if not baseline_exists
            else "delta 包只适用于当前离线机已匹配上一版 full 包基线的场景。"
        ),
    }
    _write_json(delta_meta_dir / DELTA_MANIFEST, delta_manifest)

    _write_delta_text_list(
        delta_meta_dir / DELTA_OVERWRITE_LIST,
        "# 覆盖清单",
        added_files + modified_files,
        "无需要覆盖的文件。",
    )
    _write_delta_text_list(
        delta_meta_dir / DELTA_DELETE_LIST,
        "# 删除清单",
        deleted_files,
        "无需要删除的文件。",
    )

    usage_lines = [
        "# 使用说明",
        "",
        "1. 当前 full 包输出目录为: " + target_label,
        "2. 当前 delta 包只包含需要覆盖到离线部署机的新增/修改文件。",
        "3. 覆盖完成后，再按 `_delta/删除清单.txt` 删除旧文件。",
        "4. 只有当离线机当前内容匹配上一版 full 包基线时，才可直接使用 delta 包。",
    ]
    if not baseline_exists:
        usage_lines.extend(
            [
                "5. 当前未检测到上一版 full 包基线。",
                "6. 本次请优先使用 full 包，不要只拷 delta 包。",
            ]
        )
    _write_text(delta_meta_dir / DELTA_USAGE, "\n".join(usage_lines) + "\n")
    write_package_manifest(delta_root, package_kind="delta")
    return delta_root


def _write_support_files(
    output_root: Path,
    *,
    dotnet_installer: Path | None,
    vc_redist_installer: Path | None,
    python_installer: Path | None,
    url_rewrite_installer: Path | None,
    arr_installer: Path | None,
) -> None:
    storage_root = output_root / "storage"
    for rel in [Path("jobs"), Path("groups"), Path("runtime")]:
        (storage_root / rel).mkdir(parents=True, exist_ok=True)

    start_backend = r'''param(
    [string]$ListenHost = "127.0.0.1",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "python-runtime\python.exe"
$runtimeEnv = Join-Path $PSScriptRoot "runtime.env.ps1"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python 运行环境不存在: $python"
}

if (Test-Path -LiteralPath $runtimeEnv -PathType Leaf) {
    . $runtimeEnv
}

Push-Location (Join-Path $root "backend-runtime")
try {
    & $python -X utf8 -m uvicorn API.app.main:create_app --factory --host $ListenHost --port $Port
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

Write-Host "[1/4] 校验并补齐运行时依赖..."
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
    [int]$Port = 8000,
    [switch]$ForceFullProbe
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$probeJson = Join-Path $root "logs\probe_target_env.deep.json"
$quickProbeJson = Join-Path $root "logs\probe_target_env.json"
$probeArgs = @{
    OutJson = $probeJson
    RepoRoot = $root
    Port = $Port
    StorageRoot = $StorageRoot
    OfficeProbeMode = "deep"
}

if ($ForceFullProbe) {
    Write-Host "开始执行深度环境检查（完整重跑模式）..."
} elseif (Test-Path -LiteralPath $quickProbeJson -PathType Leaf) {
    Write-Host ("开始执行深度环境检查（复用 quick 探针结果）: " + $quickProbeJson)
    $probeArgs.ReuseQuickProbeJson = $quickProbeJson
} else {
    Write-Host "未找到 quick 探针结果，将执行完整 deep 探针..."
}

& (Join-Path $PSScriptRoot "probe_target_env.ps1") @probeArgs
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
$packageRoot = Split-Path -Parent $PSScriptRoot
$pythonRuntimeDir = Join-Path $packageRoot "python-runtime"
$pythonExe = Join-Path $pythonRuntimeDir "python.exe"
$pythonPackagesSeed = Join-Path $packageRoot "python-packages\Lib\site-packages"

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

function Test-PackagePythonInstalled {
    param([string]$PythonPath)

    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        return $false
    }
    try {
        & $PythonPath --version | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Expand-PackagePythonRuntime {
    param(
        [string]$ArchivePath,
        [string]$TargetDir
    )

    if (-not (Test-Path -LiteralPath $ArchivePath -PathType Leaf)) {
        Write-Warning "Python 3.13 离线运行时包不存在，请手工补充。"
        return
    }

    if (Test-Path -LiteralPath $TargetDir -PathType Container) {
        Remove-Item -LiteralPath $TargetDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
    Write-Host ("解压离线 Python 运行时: " + $ArchivePath)
    Expand-Archive -LiteralPath $ArchivePath -DestinationPath $TargetDir -Force
}

function Enable-EmbeddedPythonSitePackages {
    param([string]$PythonRuntimeRoot)

    $pthFile = Get-ChildItem -LiteralPath $PythonRuntimeRoot -Filter "python*._pth" -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $pthFile) {
        throw "未找到嵌入式 Python 的 ._pth 文件。"
    }

    $existing = @()
    if (Test-Path -LiteralPath $pthFile.FullName -PathType Leaf) {
        $existing = @(Get-Content -LiteralPath $pthFile.FullName -ErrorAction SilentlyContinue)
    }

    $filtered = @()
    foreach ($line in $existing) {
        $trimmed = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed)) {
            continue
        }
        if ($trimmed -eq "#import site" -or $trimmed -eq "import site") {
            continue
        }
        if ($trimmed -eq "Lib" -or $trimmed -eq "Lib\\site-packages") {
            continue
        }
        $filtered += $line
    }

    $updated = @($filtered + "Lib" + "Lib\\site-packages" + "import site")
    Set-Content -LiteralPath $pthFile.FullName -Value $updated -Encoding ascii
}

function Sync-PythonSitePackages {
    param(
        [string]$SeedRoot,
        [string]$PythonRuntimeRoot
    )

    if (-not (Test-Path -LiteralPath $SeedRoot -PathType Container)) {
        throw "部署包缺少 python-packages 目录: $SeedRoot"
    }

    $targetRoot = Join-Path $PythonRuntimeRoot "Lib\site-packages"
    New-Item -ItemType Directory -Path $targetRoot -Force | Out-Null

    foreach ($item in Get-ChildItem -LiteralPath $SeedRoot -Force) {
        Copy-Item -LiteralPath $item.FullName -Destination $targetRoot -Recurse -Force
    }

    foreach ($stalePth in @("_auto_fanban.pth", "a1_coverage.pth")) {
        Remove-Item -LiteralPath (Join-Path $targetRoot $stalePth) -Force -ErrorAction SilentlyContinue
    }

    $backendRoot = Join-Path $packageRoot "backend-runtime\backend"
    Set-Content -LiteralPath (Join-Path $targetRoot "fanban_backend_runtime.pth") -Value $backendRoot -Encoding utf8
}

$dotnet = Get-ChildItem -Path (Join-Path $root "dotnet") -Filter *.exe -File -ErrorAction SilentlyContinue | Select-Object -First 1
$vc = Get-ChildItem -Path (Join-Path $root "vc_redist") -Filter *.exe -File -ErrorAction SilentlyContinue | Select-Object -First 1
$pythonInstaller = Get-ChildItem -Path (Join-Path $root "python") -Filter *.zip -File -ErrorAction SilentlyContinue | Select-Object -First 1

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

if (Test-PackagePythonInstalled -PythonPath $pythonExe) {
    Write-Host ("离线 Python 运行时已就绪: " + $pythonExe)
} else {
    Expand-PackagePythonRuntime -ArchivePath $(if ($pythonInstaller) { $pythonInstaller.FullName } else { "" }) -TargetDir $pythonRuntimeDir
    Enable-EmbeddedPythonSitePackages -PythonRuntimeRoot $pythonRuntimeDir
}

if (-not (Test-PackagePythonInstalled -PythonPath $pythonExe)) {
    throw "离线 Python 运行时准备失败，请检查 install/python 下的压缩包内容与目标机权限。"
}

Enable-EmbeddedPythonSitePackages -PythonRuntimeRoot $pythonRuntimeDir
Sync-PythonSitePackages -SeedRoot $pythonPackagesSeed -PythonRuntimeRoot $pythonRuntimeDir
Write-Host ("已同步部署包 Python 依赖到: " + (Join-Path $pythonRuntimeDir "Lib\site-packages"))
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

function Get-ConflictingHttpBindingSiteName {
    param(
        [string]$CurrentSiteName,
        [string]$BindingInformation
    )

    $sites = Get-Website -ErrorAction SilentlyContinue
    foreach ($site in $sites) {
        if ($site.Name -eq $CurrentSiteName) {
            continue
        }

        $bindings = Get-WebBinding -Name $site.Name -Protocol http -ErrorAction SilentlyContinue
        foreach ($binding in $bindings) {
            if ($binding.bindingInformation -eq $BindingInformation) {
                return $site.Name
            }
        }
    }

    return $null
}

if (-not (Test-Path "IIS:\AppPools\$AppPoolName")) {
    New-WebAppPool -Name $AppPoolName | Out-Null
}
Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name managedRuntimeVersion -Value ""
Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name processModel.identityType -Value "ApplicationPoolIdentity"

$bindingInformation = "{0}:{1}:{2}" -f $BindAddress, $Port, $HostName
$conflictingSiteName = Get-ConflictingHttpBindingSiteName -CurrentSiteName $SiteName -BindingInformation $bindingInformation
if (-not [string]::IsNullOrWhiteSpace($conflictingSiteName)) {
    $conflictHint = if ([string]::IsNullOrWhiteSpace($HostName)) {
        "当前是空 Host 绑定，通常会与 Default Web Site 或其他占用该端口的站点冲突。请先停止或调整冲突站点，或者改用其他端口；如果你本来就是按主机名访问，请继续使用非空 HostName。"
    } else {
        "请调整冲突站点的绑定，或者改用其他端口/主机名。"
    }
    throw ("IIS 绑定冲突: 站点 '{0}' 已占用 http 绑定 {1}。{2}" -f $conflictingSiteName, $bindingInformation, $conflictHint)
}

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
if (-not [string]::IsNullOrWhiteSpace($HostName)) {
    Write-Warning "HostName 只负责 IIS 主机头绑定，不会自动创建 DNS 或 hosts 解析。若要直接访问该主机名，请先让部署机和客户端都能解析到正确 IP。"
}
if ($proxyWarning) {
    Write-Warning $proxyWarning
}
'''
    _write_text(output_root / "install" / "configure_iis_site.ps1", configure_iis_site)

    register_backend_task = r'''param(
    [string]$TaskName = "FanBanBackend",
    [Parameter(Mandatory = $true)]
    [string]$UserName,
    [string]$ListenHost = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$StartImmediately = $true
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$startScript = Join-Path $root "scripts\start_backend.ps1"
if (-not (Test-Path -LiteralPath $startScript -PathType Leaf)) {
    throw "启动脚本不存在: $startScript"
}

function Remove-LegacyWindowsService {
    param([string]$LegacyName)

    $legacyService = Get-Service -Name $LegacyName -ErrorAction SilentlyContinue
    if ($null -eq $legacyService) {
        return
    }

    if ($legacyService.Status -ne "Stopped") {
        Stop-Service -Name $LegacyName -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }

    & sc.exe delete $LegacyName | Out-Null
    Write-Warning ("检测到旧版 Windows 服务，已尝试删除: " + $LegacyName)
}

function Build-TaskActionArguments {
    return "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$startScript`" -ListenHost `"$ListenHost`" -Port $Port"
}

Remove-LegacyWindowsService -LegacyName $TaskName

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument (Build-TaskActionArguments)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserName
$principal = New-ScheduledTaskPrincipal -UserId $UserName -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -StartWhenAvailable -Hidden

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Write-Host ("已注册登录触发任务: " + $TaskName)
Write-Host ("运行账号: " + $UserName)
Write-Host "该任务依赖交互式登录会话；执行 Office COM 任务时，请保持该账号已登录。"

if ($StartImmediately) {
    try {
        Start-ScheduledTask -TaskName $TaskName
        Write-Host ("已尝试立即启动任务: " + $TaskName)
    } catch {
        Write-Warning "任务已注册，但当前未能立即启动。通常是因为目标账号尚未处于登录状态；请先登录该账号，再重新执行本脚本或手工启动任务。"
    }
}
'''
    _write_text(output_root / "install" / "register_backend_task.ps1", register_backend_task)

    unregister_backend_task = r'''param(
    [string]$TaskName = "FanBanBackend"
)

$ErrorActionPreference = "Stop"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    try {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    } catch {
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$legacyService = Get-Service -Name $TaskName -ErrorAction SilentlyContinue
if ($null -ne $legacyService) {
    if ($legacyService.Status -ne "Stopped") {
        Stop-Service -Name $TaskName -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
    & sc.exe delete $TaskName | Out-Null
}

Write-Host ("已移除登录任务/旧版服务: " + $TaskName)
'''
    _write_text(output_root / "install" / "unregister_backend_task.ps1", unregister_backend_task)

    readme = r'''# 部署说明

## 目录用途
- `frontend-dist/`: IIS 前端站点目录
- `backend-runtime/`: 后端运行目录
- `python-runtime/`: 目标机离线 Python 运行时
- `python-packages/`: 随包分发的 Python site-packages
- `bin/ODAFileConverter 25.12.0/`: ODA 运行目录
- `documents/Resources/`: 受管打印和校准资源
- `documents_bin/`: 模板与词库资源
- `scripts/`: 启动、探测、健康检查脚本
- `install/`: 离线运行时安装脚本和安装器目录

## 建议顺序

1. 先执行 `install\install_runtime_prereqs.ps1`
2. 再执行 `scripts\prepare_terminal.ps1`
3. 再执行 `scripts\deep_check_terminal.ps1`
4. 配置 IIS：`install\configure_iis_site.ps1`
5. 注册登录触发任务：`install\register_backend_task.ps1 -UserName "<本机登录账号>"`
6. 执行 `scripts\check_health.ps1`
7. 如果只想临时本机调试，可手工执行 `scripts\start_backend.ps1`

## 为什么默认不用 Windows 服务

- 当前后端任务链包含 Office COM 自动化。
- Office COM 在交互式登录会话里稳定性显著高于 `LocalSystem` 等服务态会话。
- 因此正式部署默认改为“登录时触发”的隐藏计划任务，而不是 `NSSM` / Windows 服务。

## 前端地址怎么定

- 推荐使用 IIS 同源模式，前端访问地址就是 IIS 站点绑定的地址。
- 你可以自己设置：
  - `http://部署机IP/`
  - `http://部署机IP:8080/`
  - `http://自定义主机名/`
- `configure_iis_site.ps1` 里通过 `HostName` 和 `Port` 控制最终地址，不固定写死 IP。
- 如果按部署机 IP 访问，直接省略 `HostName` 参数即可，不要显式传 `-HostName ""`。
- `HostName` 只负责 IIS 主机头绑定，不会自动创建 DNS 或 hosts 解析；如果你要直接访问 `http://fanban-server/` 这类地址，必须先让部署机和客户端都能解析这个名字。
- `prepare_terminal.ps1` 会再次调用 `install_runtime_prereqs.ps1` 做补齐后验收，这是有意保留的幂等校验，不是重复安装。
- `scripts\start_backend.ps1` 会自动加载 `scripts\runtime.env.ps1`，所以正常部署不需要手工再执行一次环境文件；只有你想在当前 PowerShell 会话里直接复用这些环境变量时，才需要手工点源它。
'''
    _write_text(output_root / DEPLOY_README, readme)

    missing_lines = ["# 缺失的离线安装器", ""]
    if dotnet_installer is None:
        missing_lines.append("- 未找到 `.NET Framework 4.8` 离线安装器，请手工放入 `install/dotnet/`。")
    if vc_redist_installer is None:
        missing_lines.append("- 未找到 `VC++ 2015-2022 x64` 离线安装器，请手工放入 `install/vc_redist/`。")
    if python_installer is None:
        missing_lines.append("- 未找到 `Python 3.13 x64` 离线安装器，请手工放入 `install/python/`。")
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

    if python_installer is not None:
        target = output_root / "install" / "python" / python_installer.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(python_installer, target)
    else:
        (output_root / "install" / "python").mkdir(parents=True, exist_ok=True)

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
    python_installer: Path | None = None,
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

    _sanitize_python_packages(output_root)

    _write_support_files(
        output_root,
        dotnet_installer=dotnet_installer,
        vc_redist_installer=vc_redist_installer,
        python_installer=python_installer,
        url_rewrite_installer=url_rewrite_installer,
        arr_installer=arr_installer,
    )
    write_package_manifest(output_root, package_kind="full")

    return output_root


def publish_terminal_deploy_artifacts(
    *,
    repo_root: Path,
    output_root: Path,
    delta_root: Path | None = None,
    dotnet_installer: Path | None = None,
    vc_redist_installer: Path | None = None,
    python_installer: Path | None = None,
    url_rewrite_installer: Path | None = None,
    arr_installer: Path | None = None,
) -> DeployArtifacts:
    baseline_root = output_root if output_root.exists() else None
    resolved_delta_root = delta_root or output_root.parent / f"{output_root.name}-delta"
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging_root = output_root.parent / "_stg"
    if staging_root.exists():
        shutil.rmtree(staging_root)

    try:
        build_terminal_deploy_package(
            repo_root=repo_root,
            output_root=staging_root,
            dotnet_installer=dotnet_installer,
            vc_redist_installer=vc_redist_installer,
            python_installer=python_installer,
            url_rewrite_installer=url_rewrite_installer,
            arr_installer=arr_installer,
        )
        build_terminal_deploy_delta_package(
            baseline_root=baseline_root,
            target_root=staging_root,
            delta_root=resolved_delta_root,
            baseline_label=str(output_root),
            target_label=str(output_root),
        )

        if output_root.exists():
            shutil.rmtree(output_root)
        shutil.move(str(staging_root), str(output_root))
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root)

    return DeployArtifacts(full_root=output_root, delta_root=resolved_delta_root)
