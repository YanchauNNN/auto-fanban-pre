from __future__ import annotations

import subprocess
from pathlib import Path

from src.deploy.prereq_installers import ensure_prereq_installers
from src.deploy.terminal_package import build_terminal_deploy_package, gather_copy_plan

SPEC_NAME = "\u53c2\u6570\u89c4\u8303.yaml"
RUNTIME_SPEC_NAME = "\u53c2\u6570\u89c4\u8303_\u8fd0\u884c\u671f.yaml"
PC3_NAME = "\u6253\u5370PDF2.pc3"
DEPLOY_README = "README_\u90e8\u7f72\u8bf4\u660e.md"
MISSING_INSTALLER_README = "README_\u7f3a\u5931\u79bb\u7ebf\u5b89\u88c5\u5668.md"


def _write_file(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_fake_repo(repo_root: Path) -> None:
    _write_file(repo_root / "frontend" / "dist" / "index.html", "<html></html>")
    _write_file(repo_root / "API" / "app" / "main.py", "app = None")
    _write_file(repo_root / "backend" / "pyproject.toml", "[project]\nname = 'demo'\n")
    _write_file(repo_root / "backend" / "src" / "config" / "runtime_config.py", "CONFIG = 1")
    _write_file(repo_root / "backend" / ".venv" / "Scripts" / "python.exe")
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
    assert (Path("backend/.venv"), Path("backend-runtime/backend/.venv")) in rel_pairs
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
    assert (output_root / "backend-runtime" / "backend" / ".venv" / "Scripts" / "python.exe").exists()
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

    missing_readme = output_root / "install" / MISSING_INSTALLER_README
    assert missing_readme.exists()
    text = missing_readme.read_text(encoding="utf-8")
    assert ".NET Framework 4.8" in text
    assert "VC++ 2015-2022 x64" in text


def test_build_terminal_deploy_package_copies_offline_installers_and_writes_prepare_scripts(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    output_root = tmp_path / "build" / "fanban-terminal-deploy"
    dotnet = tmp_path / "installers" / "ndp48-x86-x64-allos-enu.exe"
    vc = tmp_path / "installers" / "VC_redist.x64.exe"
    _write_file(dotnet)
    _write_file(vc)

    build_terminal_deploy_package(
        repo_root=repo_root,
        output_root=output_root,
        dotnet_installer=dotnet,
        vc_redist_installer=vc,
    )

    assert (output_root / "install" / "dotnet" / dotnet.name).exists()
    assert (output_root / "install" / "vc_redist" / vc.name).exists()
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
    assert "-OfficeProbeMode deep" in deep_check
    assert "OfficeProbeMode deep" in deep_check
    assert "Test-DotNet48OrAboveInstalled" in install_runtime
    assert "Get-VcRuntimeInfo" in install_runtime
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
    assert "Register-ScheduledTask" in register_service

    ps1_bytes = (output_root / "install" / "check_iis_proxy_prereqs.ps1").read_bytes()
    assert ps1_bytes.startswith(b"\xef\xbb\xbf")


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
    assert installers.url_rewrite is not None
    assert installers.arr is not None
    assert installers.dotnet.exists()
    assert installers.vc_redist.exists()
    assert installers.url_rewrite.exists()
    assert installers.arr.exists()
    assert len(downloads) == 4
    assert "2088631" in downloads[0][0]
    assert "vc_redist.x64.exe" in downloads[1][0]
    assert "rewrite_amd64_zh-CN.msi" in downloads[2][0]
    assert "LinkID=615136" in downloads[3][0] or "requestRouter_amd64.msi" in downloads[3][0]


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



