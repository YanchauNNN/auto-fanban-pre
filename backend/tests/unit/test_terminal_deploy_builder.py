from __future__ import annotations

import json
import subprocess
from pathlib import Path

from src.deploy.prereq_installers import ensure_prereq_installers
from src.deploy.terminal_package import (
    DELTA_DIR_NAME,
    DELTA_DELETE_LIST,
    DELTA_MANIFEST,
    DELTA_OVERWRITE_LIST,
    DELTA_USAGE,
    PACKAGE_MANIFEST,
    build_terminal_deploy_package,
    gather_copy_plan,
    publish_terminal_deploy_artifacts,
)

SPEC_NAME = "\u53c2\u6570\u89c4\u8303.yaml"
RUNTIME_SPEC_NAME = "\u53c2\u6570\u89c4\u8303_\u8fd0\u884c\u671f.yaml"
PC3_NAME = "\u6253\u5370PDF2.pc3"
DEPLOY_README = "README_\u90e8\u7f72\u8bf4\u660e.md"
MISSING_INSTALLER_README = "README_\u7f3a\u5931\u79bb\u7ebf\u5b89\u88c5\u5668.md"


def _write_file(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _relative_files(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def _make_fake_repo(repo_root: Path) -> None:
    _write_file(repo_root / "frontend" / "dist" / "index.html", "<html></html>")
    _write_file(repo_root / "API" / "app" / "main.py", "app = None")
    _write_file(repo_root / "backend" / "pyproject.toml", "[project]\nname = 'demo'\n")
    _write_file(repo_root / "backend" / "src" / "config" / "runtime_config.py", "CONFIG = 1")
    _write_file(
        repo_root / "backend" / "src" / "deploy" / "__pycache__" / "terminal_package.cpython-313.pyc",
        "compiled",
    )
    _write_file(repo_root / "backend" / ".venv" / "Lib" / "site-packages" / "demo_pkg" / "__init__.py")
    _write_file(repo_root / "backend" / ".venv" / "Lib" / "site-packages" / "pywin32.pth", "import pywin32_bootstrap")
    _write_file(repo_root / "backend" / ".venv" / "Lib" / "site-packages" / "_auto_fanban.pth", str(repo_root / "backend"))
    _write_file(repo_root / "backend" / ".venv" / "Lib" / "site-packages" / "a1_coverage.pth", "import coverage")
    _write_file(
        repo_root
        / "backend"
        / "src"
        / "cad"
        / "dotnet"
        / "Module5CadBridge"
        / "bin"
        / "Release"
        / "net48"
        / "Module5CadBridge.dll",
    )
    _write_file(repo_root / "bin" / "ODAFileConverter 25.12.0" / "ODAFileConverter.exe")
    _write_file(repo_root / "documents" / "Resources" / PC3_NAME)
    _write_file(repo_root / "documents" / "Resources" / "fanban_monochrome.ctb")
    _write_file(repo_root / "documents" / SPEC_NAME, "schema_version: '1'")
    _write_file(repo_root / "documents" / RUNTIME_SPEC_NAME, "concurrency: {}")
    _write_file(repo_root / "documents_bin" / "responsible_unit.json", "{}")
    _write_file(repo_root / "tools" / "probe_target_env.ps1", "Write-Host probe")


def test_gather_copy_plan_includes_required_runtime_assets(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)

    plan = gather_copy_plan(repo_root)
    rel_pairs = {(item.source.relative_to(repo_root), item.destination) for item in plan}

    assert (Path("frontend/dist"), Path("frontend-dist")) in rel_pairs
    assert (Path("backend/.venv/Lib/site-packages"), Path("python-packages/Lib/site-packages")) in rel_pairs
    assert (Path("documents/Resources"), Path("documents/Resources")) in rel_pairs
    assert (Path("documents_bin"), Path("documents_bin")) in rel_pairs
    assert (Path("bin/ODAFileConverter 25.12.0"), Path("bin/ODAFileConverter 25.12.0")) in rel_pairs


def test_build_terminal_deploy_package_writes_layout_and_missing_installer_notes(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    output_root = tmp_path / "build" / "fanban-terminal-deploy"

    build_terminal_deploy_package(repo_root=repo_root, output_root=output_root)

    assert (output_root / "frontend-dist" / "index.html").exists()
    assert (output_root / "backend-runtime" / "API" / "app" / "main.py").exists()
    assert (output_root / "python-packages" / "Lib" / "site-packages" / "demo_pkg" / "__init__.py").exists()
    assert not (
        output_root
        / "backend-runtime"
        / "backend"
        / "src"
        / "deploy"
        / "__pycache__"
        / "terminal_package.cpython-313.pyc"
    ).exists()
    assert not (output_root / "python-packages" / "Lib" / "site-packages" / "_auto_fanban.pth").exists()
    assert not (output_root / "python-packages" / "Lib" / "site-packages" / "a1_coverage.pth").exists()
    assert (
        output_root
        / "backend-runtime"
        / "backend"
        / "src"
        / "cad"
        / "dotnet"
        / "Module5CadBridge"
        / "bin"
        / "Release"
        / "net48"
        / "Module5CadBridge.dll"
    ).exists()
    assert (output_root / "bin" / "ODAFileConverter 25.12.0" / "ODAFileConverter.exe").exists()
    assert (output_root / "documents" / "Resources" / PC3_NAME).exists()
    assert (output_root / "documents" / SPEC_NAME).exists()
    assert (output_root / "documents_bin" / "responsible_unit.json").exists()
    assert (output_root / "scripts" / "start_backend.ps1").exists()
    assert (output_root / "scripts" / "check_health.ps1").exists()
    assert (output_root / "scripts" / "deep_check_terminal.ps1").exists()
    assert (output_root / "scripts" / "probe_target_env.ps1").exists()
    assert (output_root / DEPLOY_README).exists()
    manifest = json.loads((output_root / PACKAGE_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["package_kind"] == "full"
    assert any(item["path"] == "scripts/start_backend.ps1" for item in manifest["files"])

    missing_readme = output_root / "install" / MISSING_INSTALLER_README
    assert missing_readme.exists()
    text = missing_readme.read_text(encoding="utf-8")
    assert ".NET Framework 4.8" in text
    assert "VC++ 2015-2022 x64" in text
    assert "NSSM" in text


def test_build_terminal_deploy_package_copies_offline_installers_and_writes_prepare_scripts(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    output_root = tmp_path / "build" / "fanban-terminal-deploy"
    dotnet = tmp_path / "installers" / "ndp48-x86-x64-allos-enu.exe"
    vc = tmp_path / "installers" / "VC_redist.x64.exe"
    python = tmp_path / "installers" / "python-3.13.12-embed-amd64.zip"
    nssm = tmp_path / "installers" / "nssm-2.24-101-g897c7ad.zip"
    _write_file(dotnet)
    _write_file(vc)
    _write_file(python)
    _write_file(nssm)

    build_terminal_deploy_package(
        repo_root=repo_root,
        output_root=output_root,
        dotnet_installer=dotnet,
        vc_redist_installer=vc,
        python_installer=python,
        nssm_archive=nssm,
    )

    assert (output_root / "install" / "dotnet" / dotnet.name).exists()
    assert (output_root / "install" / "vc_redist" / vc.name).exists()
    assert (output_root / "install" / "python" / python.name).exists()
    assert (output_root / "install" / "nssm" / nssm.name).exists()
    assert (output_root / "install" / "iis" / "url_rewrite").exists()
    assert (output_root / "install" / "iis" / "arr").exists()
    assert (output_root / "install" / "configure_iis_site.ps1").exists()
    assert (output_root / "install" / "check_iis_proxy_prereqs.ps1").exists()
    assert (output_root / "install" / "install_iis_proxy_prereqs.ps1").exists()
    assert (output_root / "install" / "register_backend_service.ps1").exists()
    assert (output_root / "install" / "unregister_backend_service.ps1").exists()

    start_backend = (output_root / "scripts" / "start_backend.ps1").read_text(encoding="utf-8")
    prepare_terminal = (output_root / "scripts" / "prepare_terminal.ps1").read_text(encoding="utf-8")
    check_health = (output_root / "scripts" / "check_health.ps1").read_text(encoding="utf-8")
    deep_check = (output_root / "scripts" / "deep_check_terminal.ps1").read_text(encoding="utf-8")
    install_runtime = (output_root / "install" / "install_runtime_prereqs.ps1").read_text(encoding="utf-8")
    configure_iis = (output_root / "install" / "configure_iis_site.ps1").read_text(encoding="utf-8")
    check_iis_proxy = (output_root / "install" / "check_iis_proxy_prereqs.ps1").read_text(encoding="utf-8")
    install_iis_proxy = (output_root / "install" / "install_iis_proxy_prereqs.ps1").read_text(encoding="utf-8")
    register_service = (output_root / "install" / "register_backend_service.ps1").read_text(encoding="utf-8")

    assert 'python-runtime\\python.exe' in start_backend
    assert 'Push-Location (Join-Path $root "backend-runtime")' in start_backend
    assert "runtime.env.ps1" in start_backend
    assert "probe_target_env.ps1" in prepare_terminal
    assert "runtime.env.ps1" in prepare_terminal
    assert "Set-Item -Path 'Env:{0}' -Value '{1}'" in prepare_terminal
    assert "$env:{0}" not in prepare_terminal
    assert "OfficeProbeMode" in prepare_terminal
    assert "quick" in prepare_terminal
    assert "Blocking issues detail" in prepare_terminal
    assert "$probe.blocking_issues" in prepare_terminal
    assert "[1/4]" in prepare_terminal
    assert "Invoke-RestMethod" in check_health
    assert "check_iis_proxy_prereqs.ps1" in check_health
    assert "probe_target_env.ps1" in check_health
    assert "-OfficeProbeMode quick" in check_health
    assert 'OfficeProbeMode = "deep"' in deep_check
    assert "ForceFullProbe" in deep_check
    assert "ReuseQuickProbeJson" in deep_check
    assert "probe_target_env.json" in deep_check
    assert "$probeArgs = @{" in deep_check
    assert "$probeArgs.ReuseQuickProbeJson = $quickProbeJson" in deep_check
    assert "Test-DotNet48OrAboveInstalled" in install_runtime
    assert "Get-VcRuntimeInfo" in install_runtime
    assert "Expand-PackagePythonRuntime" in install_runtime
    assert "Enable-EmbeddedPythonSitePackages" in install_runtime
    assert "-Encoding ascii" in install_runtime
    assert "Sync-PythonSitePackages" in install_runtime
    assert "Install-BundledNssm" in install_runtime
    install_nssm_section = install_runtime.split("function Install-BundledNssm", 1)[1].split(
        "function Enable-EmbeddedPythonSitePackages",
        1,
    )[0]
    assert "Remove-Item -LiteralPath $TargetDir -Recurse -Force" not in install_nssm_section
    assert "NSSM 已就绪" in install_runtime
    assert "python-runtime" in install_runtime
    assert "python-packages\\Lib\\site-packages" in install_runtime
    assert 'Join-Path $root "nssm"' in install_runtime
    assert "fanban_backend_runtime.pth" in install_runtime
    assert ".NET Framework 4.8" in install_runtime
    assert "New-Website" in configure_iis or "Set-ItemProperty" in configure_iis
    assert "HostName" in configure_iis
    assert "system.webServer/proxy" in configure_iis
    assert "ARR" in configure_iis
    assert "RewriteModule" in check_iis_proxy
    assert "Application Request Routing" in check_iis_proxy
    assert "msiexec.exe" in install_iis_proxy
    assert "url_rewrite" in install_iis_proxy
    assert "requestRouter_amd64.msi" in install_iis_proxy or "arr" in install_iis_proxy
    assert "Test-UrlRewriteInstalled" in install_iis_proxy
    assert "Test-ArrInstalled" in install_iis_proxy
    assert "nssm" in register_service
    assert '[string]$Mode = "nssm"' in register_service
    assert "& $nssmPath start $ServiceName" in register_service
    assert "Start-ScheduledTask -TaskName $ServiceName" in register_service
    assert 'throw "未找到 nssm.exe，请先执行 install_runtime_prereqs.ps1 准备部署包内的 NSSM。"' in register_service
    assert "Register-ScheduledTask" in register_service

    ps1_bytes = (output_root / "install" / "check_iis_proxy_prereqs.ps1").read_bytes()
    assert ps1_bytes.startswith(b"\xef\xbb\xbf")


def test_publish_terminal_deploy_artifacts_writes_delta_for_added_modified_and_deleted_files(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    output_root = tmp_path / "build" / "fanban-terminal-deploy"
    delta_root = tmp_path / "build" / "fanban-terminal-deploy-delta"

    build_terminal_deploy_package(repo_root=repo_root, output_root=output_root)

    _write_file(repo_root / "tools" / "probe_target_env.ps1", "Write-Host probe-v2")
    _write_file(repo_root / "documents_bin" / "delta_only.json", '{"delta": true}')
    (repo_root / "documents" / "Resources" / "fanban_monochrome.ctb").unlink()

    artifacts = publish_terminal_deploy_artifacts(
        repo_root=repo_root,
        output_root=output_root,
        delta_root=delta_root,
    )

    assert artifacts.full_root == output_root
    assert artifacts.delta_root == delta_root
    assert (output_root / "scripts" / "probe_target_env.ps1").read_text(encoding="utf-8-sig") == "Write-Host probe-v2"
    assert (output_root / "documents_bin" / "delta_only.json").exists()
    assert not (output_root / "documents" / "Resources" / "fanban_monochrome.ctb").exists()

    delta_files = _relative_files(delta_root)
    assert "scripts/probe_target_env.ps1" in delta_files
    assert "documents_bin/delta_only.json" in delta_files
    assert "documents/Resources/fanban_monochrome.ctb" not in delta_files
    assert not any("__pycache__" in path for path in delta_files)
    assert PACKAGE_MANIFEST in delta_files
    assert f"{DELTA_DIR_NAME}/{DELTA_MANIFEST}" in delta_files
    assert f"{DELTA_DIR_NAME}/{DELTA_OVERWRITE_LIST}" in delta_files
    assert f"{DELTA_DIR_NAME}/{DELTA_DELETE_LIST}" in delta_files
    assert f"{DELTA_DIR_NAME}/{DELTA_USAGE}" in delta_files

    delta_manifest = json.loads((delta_root / DELTA_DIR_NAME / DELTA_MANIFEST).read_text(encoding="utf-8"))
    assert delta_manifest["baseline_exists"] is True
    assert "scripts/probe_target_env.ps1" in delta_manifest["modified_files"]
    assert "documents_bin/delta_only.json" in delta_manifest["added_files"]
    assert "documents/Resources/fanban_monochrome.ctb" in delta_manifest["deleted_files"]

    delete_list = (delta_root / DELTA_DIR_NAME / DELTA_DELETE_LIST).read_text(encoding="utf-8")
    assert "documents/Resources/fanban_monochrome.ctb" in delete_list


def test_publish_terminal_deploy_artifacts_without_baseline_writes_metadata_only_delta(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    output_root = tmp_path / "build" / "fanban-terminal-deploy"
    delta_root = tmp_path / "build" / "fanban-terminal-deploy-delta"

    publish_terminal_deploy_artifacts(
        repo_root=repo_root,
        output_root=output_root,
        delta_root=delta_root,
    )

    assert (output_root / "frontend-dist" / "index.html").exists()
    delta_files = _relative_files(delta_root)
    assert PACKAGE_MANIFEST in delta_files
    assert f"{DELTA_DIR_NAME}/{DELTA_MANIFEST}" in delta_files
    assert "frontend-dist/index.html" not in delta_files

    delta_manifest = json.loads((delta_root / DELTA_DIR_NAME / DELTA_MANIFEST).read_text(encoding="utf-8"))
    assert delta_manifest["baseline_exists"] is False
    assert delta_manifest["added_files"] == []
    assert delta_manifest["modified_files"] == []
    assert delta_manifest["deleted_files"] == []

    usage = (delta_root / DELTA_DIR_NAME / DELTA_USAGE).read_text(encoding="utf-8")
    assert "请优先使用 full 包" in usage


def test_ensure_prereq_installers_downloads_missing_files(tmp_path: Path) -> None:
    downloads: list[tuple[str, Path]] = []

    def fake_downloader(url: str, destination: Path) -> Path:
        downloads.append((url, destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(url, encoding="utf-8")
        return destination

    installers = ensure_prereq_installers(download_root=tmp_path / "downloads", downloader=fake_downloader)

    assert installers.dotnet is not None
    assert installers.vc_redist is not None
    assert installers.python is not None
    assert installers.nssm is not None
    assert installers.url_rewrite is not None
    assert installers.arr is not None
    assert installers.dotnet.exists()
    assert installers.vc_redist.exists()
    assert installers.python.exists()
    assert installers.nssm.exists()
    assert installers.url_rewrite.exists()
    assert installers.arr.exists()
    assert len(downloads) == 6
    assert "2088631" in downloads[0][0]
    assert "vc_redist.x64.exe" in downloads[1][0]
    assert "python-3.13.12-embed-amd64.zip" in downloads[2][0]
    assert "nssm" in downloads[3][0].lower()
    assert "rewrite_amd64_zh-CN.msi" in downloads[4][0]
    assert "LinkID=615136" in downloads[5][0] or "requestRouter_amd64.msi" in downloads[5][0]


def test_generated_powershell_scripts_parse_cleanly(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    output_root = tmp_path / "build" / "fanban-terminal-deploy"

    build_terminal_deploy_package(repo_root=repo_root, output_root=output_root)

    ps1_files = sorted((output_root / "install").rglob("*.ps1")) + sorted(
        (output_root / "scripts").rglob("*.ps1")
    )
    assert ps1_files

    for path in ps1_files:
        script = f'\n$target = "{str(path).replace("\\", "\\\\")}"\n' + """
$ErrorActionPreference = "Stop"
$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile($target, [ref]$tokens, [ref]$errors) | Out-Null
if ($errors -and $errors.Count -gt 0) {
    $errors | ForEach-Object { Write-Output $_.Message }
    exit 1
}
"""
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert completed.returncode == 0, f"{path} parse failed: {completed.stdout}\n{completed.stderr}"


def test_generated_deep_check_terminal_invokes_probe_with_named_params_in_windows_powershell(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    output_root = tmp_path / "build" / "fanban-terminal-deploy"

    build_terminal_deploy_package(repo_root=repo_root, output_root=output_root)

    logs_dir = output_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    quick_probe = logs_dir / "probe_target_env.json"
    quick_probe.write_text("{}", encoding="utf-8")

    probe_stub = """param(
    [string]$OutJson = "",
    [string]$RepoRoot = "",
    [int]$Port = 8000,
    [string]$StorageRoot = "",
    [string]$OfficeProbeMode = "",
    [string]$ReuseQuickProbeJson = ""
)

$payload = [ordered]@{
    out_json = $OutJson
    repo_root = $RepoRoot
    port = $Port
    storage_root = $StorageRoot
    office_probe_mode = $OfficeProbeMode
    reuse_quick_probe_json = $ReuseQuickProbeJson
}
$payload | ConvertTo-Json -Depth 4 | Out-File -LiteralPath $OutJson -Encoding utf8
"""
    (output_root / "scripts" / "probe_target_env.ps1").write_text(probe_stub, encoding="utf-8")

    storage_root = str(output_root / "storage-test")
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(output_root / "scripts" / "deep_check_terminal.ps1"),
            "-Port",
            "8123",
            "-StorageRoot",
            storage_root,
        ],
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="ignore")

    deep_probe = json.loads((logs_dir / "probe_target_env.deep.json").read_text(encoding="utf-8-sig"))
    assert deep_probe["port"] == 8123
    assert deep_probe["repo_root"] == str(output_root)
    assert deep_probe["storage_root"] == storage_root
    assert deep_probe["office_probe_mode"] == "deep"
    assert deep_probe["reuse_quick_probe_json"] == str(quick_probe)



