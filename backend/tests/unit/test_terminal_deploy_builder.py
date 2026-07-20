from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

from src.deploy.prereq_installers import ensure_prereq_installers
from src.deploy.terminal_package import (
    DELTA_DELETE_LIST,
    DELTA_DIR_NAME,
    DELTA_MANIFEST,
    DELTA_OVERWRITE_LIST,
    DELTA_USAGE,
    MANAGED_MONOCHROME_CTB_NAME,
    PACKAGE_MANIFEST,
    build_terminal_deploy_package,
    gather_copy_plan,
    publish_terminal_deploy_artifacts,
)

SPEC_NAME = "\u53c2\u6570\u89c4\u8303.yaml"
RUNTIME_SPEC_NAME = "\u53c2\u6570\u89c4\u8303_\u8fd0\u884c\u671f.yaml"
MECHANISM_SPEC_NAME = "\u53c2\u6570\u89c4\u8303-3.yaml"
TERMINAL_INSTALL_PLAN_NAME = "\u7ec8\u7aef\u5b9e\u88c5\u5b89\u88c5\u8ba1\u5212.md"
AI_MODEL_GATEWAY_CONFIG_NAME = "ai_model_gateway.yaml"
AI_SPEC_NAME = "参数规范_AI.yaml"
AI_CONNECTIVITY_SCRIPT_NAME = "test_ai_model_connectivity.ps1"
ANSYS_MAPDL_INSTALL_SCRIPT_NAME = "install_ansys_mapdl_skill.ps1"
BUILDING_STANDARDS_INSTALL_SCRIPT_NAME = "install_building_standards_skill.ps1"
PC3_NAME = "\u6253\u5370PDF2.pc3"
PMP_NAME = "tszdef-02fc5f1cb3db4a5b8afc9cce5dca6cd1.pmp"
DEPLOY_README = "README_\u90e8\u7f72\u8bf4\u660e.md"
MISSING_INSTALLER_README = "README_\u7f3a\u5931\u79bb\u7ebf\u5b89\u88c5\u5668.md"
REGISTER_TASK_SCRIPT = "register_backend_task.ps1"
UNREGISTER_TASK_SCRIPT = "unregister_backend_task.ps1"


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _valid_pc3_text(label: str = "pc3") -> str:
    return f"PIAFILEVERSION_2.0,PC3VER1,compressed-test,{label}\n" * 8


def _valid_pmp_text(label: str = "pmp") -> str:
    return f"PIAFILEVERSION_2.0,PC3VER1,compressed-test,{label}\n" * 8


@pytest.fixture(autouse=True)
def _isolate_autocad_user_dirs(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))


def _write_file(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _find_unused_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _relative_files(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def _make_fake_repo(repo_root: Path) -> None:
    _write_file(repo_root / "frontend" / "dist" / "index.html", "<html></html>")
    _write_file(repo_root / "frontend" / "dist" / "assets" / "pdf.worker.min-test.mjs", "worker")
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
    _write_file(
        repo_root / "backend" / ".venv" / "Lib" / "site-packages" / "_editable_impl_auto_fanban.pth",
        str(repo_root / "backend"),
    )
    _write_file(repo_root / "backend" / ".venv" / "Lib" / "site-packages" / "a1_coverage.pth", "import coverage")
    _write_file(
        repo_root / "backend" / ".venv" / "Lib" / "site-packages" / "auto_fanban-0.1.0.dist-info" / "direct_url.json",
        '{"url":"file:///E:/project/auto-fanban-pre/backend","dir_info":{"editable":true}}',
    )
    _write_file(
        repo_root / "backend" / ".venv" / "Lib" / "site-packages" / "auto_fanban-0.1.0.dist-info" / "RECORD",
        "_editable_impl_auto_fanban.pth,sha256=stale,34\n"
        "auto_fanban-0.1.0.dist-info/direct_url.json,sha256=stale,81\n"
        "auto_fanban-0.1.0.dist-info/METADATA,,\n",
    )
    _write_file(
        repo_root
        / "backend"
        / "src"
        / "cad"
        / "dotnet"
        / "Module5CadBridge"
        / "obj"
        / "Release"
        / "net48"
        / "Module5CadBridge.csproj.FileListAbsolute.txt",
        "E:\\project\\auto-fanban-pre\\backend\\src\\cad\\dotnet\\Module5CadBridge\\bin\\Release\\net48\\Module5CadBridge.dll",
    )
    _write_file(
        repo_root
        / "backend"
        / "src"
        / "cad"
        / "dotnet"
        / "Module5CadBridge"
        / "Module5CadBridge.csproj.lscache",
        "SolutionPath=<PATH>../../../../../auto-fanban-pre.sln",
    )
    _write_file(
        repo_root
        / "backend"
        / "src"
        / "cad"
        / "dotnet"
        / ".build_packages"
        / "microsoft.netframework.referenceassemblies.net48.1.0.3.nupkg",
        "build cache",
    )
    _write_file(
        repo_root
        / "backend"
        / "src"
        / "cad"
        / "dotnet"
        / "Module5CadBridge"
        / "bin"
        / "x64"
        / "Debug"
        / "net48"
        / "debug-only.txt",
    )
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
        / "Module5CadBridge.pdb",
        "E:\\project\\auto-fanban-pre\\backend\\src\\cad\\dotnet\\Module5CadBridge\\Commands.cs",
    )
    _write_file(repo_root / "bin" / "ODAFileConverter 25.12.0" / "ODAFileConverter.exe")
    _write_file(repo_root / "documents" / "Resources" / PC3_NAME, _valid_pc3_text("repo-pc3"))
    _write_file(repo_root / "documents" / "Resources" / PMP_NAME, _valid_pmp_text("repo-pmp"))
    _write_file(repo_root / "documents" / "Resources" / "fanban_monochrome.ctb")
    _write_file(repo_root / "documents" / SPEC_NAME, "schema_version: '1'")
    _write_file(repo_root / "documents" / RUNTIME_SPEC_NAME, "concurrency: {}")
    _write_file(repo_root / "documents" / MECHANISM_SPEC_NAME, "schema_version: '1'\nbackend_mechanism: {}")
    _write_file(repo_root / "documents" / TERMINAL_INSTALL_PLAN_NAME, "terminal install plan")
    _write_file(repo_root / "documents" / "AI" / AI_SPEC_NAME, "schema_version: '1'\nai_layer: {}")
    _write_file(repo_root / "documents" / "AI" / AI_MODEL_GATEWAY_CONFIG_NAME, "schema_version: '1'")
    _write_file(repo_root / "documents_bin" / "responsible_unit.json", "{}")
    _write_file(repo_root / "documents_bin" / "~$规范库.xlsx", "office lock")
    _write_file(repo_root / "tools" / "probe_target_env.ps1", "Write-Host probe")
    _write_file(repo_root / "tools" / "cad_env_fingerprint.ps1", "Write-Host cad-env-fingerprint")
    _write_file(repo_root / "tools" / "cad_env_sync.ps1", "Write-Host cad-env-sync")
    _write_file(repo_root / "tools" / "diagnose_iis_frontend_503.ps1", "Write-Host diagnose-503")
    _write_file(repo_root / "tools" / "ai" / AI_CONNECTIVITY_SCRIPT_NAME, "Write-Host ai-connectivity")
    _write_file(
        repo_root / "tools" / "ai" / ANSYS_MAPDL_INSTALL_SCRIPT_NAME,
        "Write-Host install-ansys-mapdl",
    )
    _write_file(
        repo_root / "tools" / "ai" / BUILDING_STANDARDS_INSTALL_SCRIPT_NAME,
        "Write-Host install-building-standards",
    )


def test_gather_copy_plan_includes_required_runtime_assets(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)

    plan = gather_copy_plan(repo_root)
    rel_pairs = {(item.source.relative_to(repo_root), item.destination) for item in plan}

    assert (Path("frontend/dist"), Path("frontend-dist")) in rel_pairs
    assert (Path("backend/.venv/Lib/site-packages"), Path("python-packages/Lib/site-packages")) in rel_pairs
    assert (Path("documents/Resources"), Path("documents/Resources")) in rel_pairs
    assert (Path("documents") / MECHANISM_SPEC_NAME, Path("documents") / MECHANISM_SPEC_NAME) in rel_pairs
    assert (Path("documents") / TERMINAL_INSTALL_PLAN_NAME, Path("documents") / TERMINAL_INSTALL_PLAN_NAME) in rel_pairs
    assert (Path("documents/AI"), Path("documents/AI")) in rel_pairs
    assert (
        Path("documents/AI") / AI_SPEC_NAME,
        Path("documents/AI") / AI_SPEC_NAME,
    ) in rel_pairs
    assert (
        Path("documents/AI") / AI_MODEL_GATEWAY_CONFIG_NAME,
        Path("documents/AI") / AI_MODEL_GATEWAY_CONFIG_NAME,
    ) in rel_pairs
    assert (Path("documents_bin"), Path("documents_bin")) in rel_pairs
    assert (Path("bin/ODAFileConverter 25.12.0"), Path("bin/ODAFileConverter 25.12.0")) in rel_pairs
    assert (Path("tools/diagnose_iis_frontend_503.ps1"), Path("tools/diagnose_iis_frontend_503.ps1")) in rel_pairs
    assert (
        Path("tools") / "ai" / AI_CONNECTIVITY_SCRIPT_NAME,
        Path("scripts") / AI_CONNECTIVITY_SCRIPT_NAME,
    ) in rel_pairs
    assert (
        Path("tools") / "ai" / ANSYS_MAPDL_INSTALL_SCRIPT_NAME,
        Path("scripts") / ANSYS_MAPDL_INSTALL_SCRIPT_NAME,
    ) in rel_pairs
    assert (
        Path("tools") / "ai" / BUILDING_STANDARDS_INSTALL_SCRIPT_NAME,
        Path("scripts") / BUILDING_STANDARDS_INSTALL_SCRIPT_NAME,
    ) in rel_pairs


def test_build_terminal_deploy_package_writes_layout_and_missing_installer_notes(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    output_root = tmp_path / "build" / "fanban-terminal-deploy"

    build_terminal_deploy_package(repo_root=repo_root, output_root=output_root)

    assert (output_root / "frontend-dist" / "index.html").exists()
    frontend_web_config = (output_root / "frontend-dist" / "web.config").read_text(encoding="utf-8")
    assert '<mimeMap fileExtension=".mjs" mimeType="text/javascript" />' in frontend_web_config
    assert '<mimeMap fileExtension=".wasm" mimeType="application/wasm" />' in frontend_web_config
    assert 'url="http://127.0.0.1:8000/api/{R:1}"' in frontend_web_config
    assert 'url="/index.html"' in frontend_web_config
    assert (output_root / "backend-runtime" / "API" / "app" / "main.py").exists()
    assert (output_root / "documents" / TERMINAL_INSTALL_PLAN_NAME).read_text(encoding="utf-8-sig") == "terminal install plan"
    assert (output_root / "tools" / "diagnose_iis_frontend_503.ps1").read_text(
        encoding="utf-8-sig"
    ) == "Write-Host diagnose-503"
    assert not (output_root / "documents_bin" / "~$规范库.xlsx").exists()
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


def test_terminal_package_materializes_ansys_skill_without_copying_private_archive(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    (repo_root / "documents" / "AI" / AI_SPEC_NAME).write_text(
        """
schema_version: "0.1"
ai_layer:
  chat:
    skills:
      - skill_id: "ansys_mapdl_18_2"
        name: "ANSYS MAPDL 18.2"
        handler: "ansys_mapdl_18_2"
        enabled: true
        root: "storage/ai/skills/ansys-mapdl-18-2"
""".strip(),
        encoding="utf-8",
    )
    archive = (
        repo_root
        / "documents"
        / "AI"
        / "ansys-mapdl-18-2-private-offline-2026-07-16.zip"
    )
    with ZipFile(archive, "w") as bundle:
        prefix = "private/ansys-mapdl-18-2"
        bundle.writestr(f"{prefix}/SKILL.md", "skill")
        bundle.writestr(f"{prefix}/scripts/mapdl_query.py", "print('{}')")
        bundle.writestr(f"{prefix}/assets/data/mapdl_help.sqlite", "sqlite")
        bundle.writestr(f"{prefix}/assets/data/mapdl_commands.jsonl", "{}\n")
        bundle.writestr(f"{prefix}/assets/data/manifest.json", "{}\n")

    output_root = tmp_path / "build" / "fanban-terminal-deploy"
    build_terminal_deploy_package(repo_root=repo_root, output_root=output_root)

    installed = output_root / "storage" / "ai" / "skills" / "ansys-mapdl-18-2"
    assert (installed / "SKILL.md").exists()
    assert (installed / "scripts" / "mapdl_query.py").exists()
    assert not (
        output_root
        / "documents"
        / "AI"
        / "ansys-mapdl-18-2-private-offline-2026-07-16.zip"
    ).exists()
    assert not (output_root / "python-packages" / "Lib" / "site-packages" / "_auto_fanban.pth").exists()
    assert not (
        output_root / "python-packages" / "Lib" / "site-packages" / "_editable_impl_auto_fanban.pth"
    ).exists()
    assert not (output_root / "python-packages" / "Lib" / "site-packages" / "a1_coverage.pth").exists()
    assert not (
        output_root
        / "python-packages"
        / "Lib"
        / "site-packages"
        / "auto_fanban-0.1.0.dist-info"
        / "direct_url.json"
    ).exists()
    record = (
        output_root
        / "python-packages"
        / "Lib"
        / "site-packages"
        / "auto_fanban-0.1.0.dist-info"
        / "RECORD"
    ).read_text(encoding="utf-8")
    assert "_editable_impl_auto_fanban.pth" not in record
    assert "direct_url.json" not in record
    assert "METADATA" in record


def test_terminal_package_materializes_building_standards_skill(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    (repo_root / "documents" / "AI" / AI_SPEC_NAME).write_text(
        """
schema_version: "0.1"
ai_layer:
  chat:
    skills:
      - skill_id: "building_structure_standards"
        name: "建筑结构总图规范"
        handler: "building_structure_standards"
        enabled: true
        root: "storage/ai/skills/building-structure-standards"
""".strip(),
        encoding="utf-8",
    )
    source = repo_root / "tools" / "ai" / "building-structure-standards"
    _write_file(source / "SKILL.md", "skill")
    _write_file(source / "scripts" / "standards_query.py", "print('{}')")
    _write_file(source / "assets" / "data" / "standards.sqlite", "sqlite")
    _write_file(source / "assets" / "data" / "audit_catalog.json", "[]")
    _write_file(source / "assets" / "data" / "manifest.json", "{}")
    _write_file(source / "assets" / "data" / "validation_report.json", "{}")

    output_root = tmp_path / "build" / "fanban-terminal-deploy"
    build_terminal_deploy_package(repo_root=repo_root, output_root=output_root)

    installed = (
        output_root
        / "storage"
        / "ai"
        / "skills"
        / "building-structure-standards"
    )
    assert (installed / "SKILL.md").is_file()
    assert (installed / "scripts" / "standards_query.py").is_file()
    assert (installed / "assets" / "data" / "standards.sqlite").is_file()
    assert not (
        output_root
        / "backend-runtime"
        / "backend"
        / "src"
        / "cad"
        / "dotnet"
        / "Module5CadBridge"
        / "obj"
    ).exists()
    assert not (
        output_root
        / "backend-runtime"
        / "backend"
        / "src"
        / "cad"
        / "dotnet"
        / "Module5CadBridge"
        / "Module5CadBridge.csproj.lscache"
    ).exists()
    assert not (
        output_root
        / "backend-runtime"
        / "backend"
        / "src"
        / "cad"
        / "dotnet"
        / ".build_packages"
    ).exists()
    assert not (
        output_root
        / "backend-runtime"
        / "backend"
        / "src"
        / "cad"
        / "dotnet"
        / "Module5CadBridge"
        / "bin"
        / "x64"
    ).exists()
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
    assert not (
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
        / "Module5CadBridge.pdb"
    ).exists()
    assert (output_root / "bin" / "ODAFileConverter 25.12.0" / "ODAFileConverter.exe").exists()
    assert (output_root / "documents" / "Resources" / PC3_NAME).exists()
    assert (output_root / "documents" / SPEC_NAME).exists()
    assert (output_root / "documents" / MECHANISM_SPEC_NAME).exists()
    assert (output_root / "documents" / "AI" / AI_SPEC_NAME).exists()
    assert (output_root / "documents" / "AI" / AI_MODEL_GATEWAY_CONFIG_NAME).exists()
    assert (output_root / "documents_bin" / "responsible_unit.json").exists()
    assert (output_root / "scripts" / "start_backend.ps1").exists()
    assert (output_root / "scripts" / "check_health.ps1").exists()
    assert (output_root / "scripts" / "deep_check_terminal.ps1").exists()
    assert (output_root / "scripts" / "probe_target_env.ps1").exists()
    assert (output_root / "scripts" / "cad_env_fingerprint.ps1").exists()
    assert (output_root / "scripts" / "cad_env_sync.ps1").exists()
    assert (output_root / "scripts" / AI_CONNECTIVITY_SCRIPT_NAME).exists()
    assert (output_root / "scripts" / AI_CONNECTIVITY_SCRIPT_NAME).read_bytes() == (
        repo_root / "tools" / "ai" / AI_CONNECTIVITY_SCRIPT_NAME
    ).read_bytes()
    assert (output_root / DEPLOY_README).exists()
    deploy_readme = (output_root / DEPLOY_README).read_text(encoding="utf-8")
    assert "install\\check_iis_proxy_prereqs.ps1" in deploy_readme
    assert "一致性边界" in deploy_readme
    assert "API 与 worker 分离" in deploy_readme
    assert "不需要单独启动 worker" in deploy_readme
    assert "Stop-ScheduledTask -TaskName FanBanBackend" in deploy_readme
    assert "api/system/ping" in deploy_readme
    assert "不要再额外执行 `Start-ScheduledTask -TaskName FanBanBackend`" in deploy_readme
    assert "ARR proxy timeout 低于 600 秒" in deploy_readme
    assert "scripts\\test_ai_model_connectivity.ps1" in deploy_readme
    assert "script.sha256" in deploy_readme
    assert "package-manifest.json" in deploy_readme
    assert "done_received=false" in deploy_readme
    assert "不能单独判定为失败" in deploy_readme
    assert "*.lscache" in deploy_readme
    manifest = json.loads((output_root / PACKAGE_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["package_kind"] == "full"
    assert any(item["path"] == "scripts/start_backend.ps1" for item in manifest["files"])

    missing_readme = output_root / "install" / MISSING_INSTALLER_README
    assert missing_readme.exists()
    text = missing_readme.read_text(encoding="utf-8")
    assert ".NET Framework 4.8" in text
    assert "VC++ 2015-2022 x64" in text
    assert "NSSM" not in text


def test_build_terminal_deploy_package_requires_pdf_preview_worker_asset(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    output_root = tmp_path / "build" / "fanban-terminal-deploy"
    (repo_root / "frontend" / "dist" / "assets" / "pdf.worker.min-test.mjs").unlink()

    with pytest.raises(FileNotFoundError, match="PDF 预览 worker"):
        build_terminal_deploy_package(repo_root=repo_root, output_root=output_root)


def test_build_terminal_deploy_package_prefers_valid_local_autocad_pdf2_pc3_pair_when_available(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    output_root = tmp_path / "build" / "fanban-terminal-deploy"

    managed_pc3 = repo_root / "documents" / "Resources" / PC3_NAME
    managed_pc3.write_text(_valid_pc3_text("repo-pc3"), encoding="utf-8")
    managed_pmp = repo_root / "documents" / "Resources" / PMP_NAME
    managed_pmp.write_text(_valid_pmp_text("repo-pmp"), encoding="utf-8")

    appdata = tmp_path / "AppData" / "Roaming"
    local_plotters = appdata / "Autodesk" / "AutoCAD 2022" / "R24.1" / "chs" / "Plotters"
    local_plotters.mkdir(parents=True, exist_ok=True)
    (local_plotters / PC3_NAME).write_text(_valid_pc3_text("local-pc3"), encoding="utf-8")
    (local_plotters / PMP_NAME).write_text(_valid_pmp_text("local-pmp"), encoding="utf-8")
    (local_plotters / "PMP Files" / PMP_NAME).parent.mkdir(parents=True, exist_ok=True)
    (local_plotters / "PMP Files" / PMP_NAME).write_text(_valid_pmp_text("local-pmp"), encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))

    build_terminal_deploy_package(repo_root=repo_root, output_root=output_root)

    assert (output_root / "documents" / "Resources" / PC3_NAME).read_text(
        encoding="utf-8"
    ) == _valid_pc3_text("local-pc3")
    assert (output_root / "documents" / "Resources" / PMP_NAME).read_text(
        encoding="utf-8"
    ) == _valid_pmp_text("local-pmp")


def test_build_terminal_deploy_package_ignores_invalid_local_autocad_pdf2_pc3(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    output_root = tmp_path / "build" / "fanban-terminal-deploy"

    managed_pc3 = repo_root / "documents" / "Resources" / PC3_NAME
    managed_pc3.write_text(_valid_pc3_text("repo-pc3"), encoding="utf-8")

    appdata = tmp_path / "AppData" / "Roaming"
    local_plotters = appdata / "Autodesk" / "AutoCAD 2022" / "R24.1" / "chs" / "Plotters"
    local_plotters.mkdir(parents=True, exist_ok=True)
    (local_plotters / PC3_NAME).write_text("pc3", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))

    build_terminal_deploy_package(repo_root=repo_root, output_root=output_root)

    assert (output_root / "documents" / "Resources" / PC3_NAME).read_text(
        encoding="utf-8"
    ) == _valid_pc3_text("repo-pc3")


def test_build_terminal_deploy_package_copies_offline_installers_and_writes_prepare_scripts(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    output_root = tmp_path / "build" / "fanban-terminal-deploy"
    dotnet = tmp_path / "installers" / "ndp48-x86-x64-allos-enu.exe"
    vc = tmp_path / "installers" / "VC_redist.x64.exe"
    python = tmp_path / "installers" / "python-3.13.12-embed-amd64.zip"
    _write_file(dotnet)
    _write_file(vc)
    _write_file(python)

    build_terminal_deploy_package(
        repo_root=repo_root,
        output_root=output_root,
        dotnet_installer=dotnet,
        vc_redist_installer=vc,
        python_installer=python,
    )

    assert (output_root / "install" / "dotnet" / dotnet.name).exists()
    assert (output_root / "install" / "vc_redist" / vc.name).exists()
    assert (output_root / "install" / "python" / python.name).exists()
    assert not (output_root / "install" / "nssm").exists()
    assert (output_root / "install" / "iis" / "url_rewrite").exists()
    assert (output_root / "install" / "iis" / "arr").exists()
    assert (output_root / "install" / "configure_iis_site.ps1").exists()
    assert (output_root / "install" / "check_iis_proxy_prereqs.ps1").exists()
    assert (output_root / "install" / "install_iis_proxy_prereqs.ps1").exists()
    assert (output_root / "install" / REGISTER_TASK_SCRIPT).exists()
    assert (output_root / "install" / UNREGISTER_TASK_SCRIPT).exists()

    start_backend = (output_root / "scripts" / "start_backend.ps1").read_text(encoding="utf-8")
    prepare_terminal = (output_root / "scripts" / "prepare_terminal.ps1").read_text(encoding="utf-8")
    check_health = (output_root / "scripts" / "check_health.ps1").read_text(encoding="utf-8")
    deep_check = (output_root / "scripts" / "deep_check_terminal.ps1").read_text(encoding="utf-8")
    install_runtime = (output_root / "install" / "install_runtime_prereqs.ps1").read_text(encoding="utf-8")
    configure_iis = (output_root / "install" / "configure_iis_site.ps1").read_text(encoding="utf-8")
    check_iis_proxy = (output_root / "install" / "check_iis_proxy_prereqs.ps1").read_text(encoding="utf-8")
    install_iis_proxy = (output_root / "install" / "install_iis_proxy_prereqs.ps1").read_text(encoding="utf-8")
    register_task = (output_root / "install" / REGISTER_TASK_SCRIPT).read_text(encoding="utf-8")

    assert 'python-runtime\\python.exe' in start_backend
    assert 'Push-Location (Join-Path $root "backend-runtime")' in start_backend
    assert "runtime.env.ps1" in start_backend
    assert 'Join-Path $root "documents\\参数规范.yaml"' in start_backend
    assert 'Join-Path $root "documents\\参数规范_运行期.yaml"' in start_backend
    assert 'Join-Path $root "documents\\参数规范-3.yaml"' in start_backend
    assert 'Join-Path $root "backend-runtime\\backend\\src\\cad\\scripts"' in start_backend
    assert (
        'Join-Path $root "backend-runtime\\backend\\src\\cad\\dotnet\\Module5CadBridge\\bin\\Release\\net48\\Module5CadBridge.dll"'
        in start_backend
    )
    assert "Set-BackendRuntimeEnvironment" in start_backend
    assert "Test-BackendImportPreflight" in start_backend
    assert "后端启动环境变量无效" in start_backend
    assert "后端导入预检失败" in start_backend
    assert "backend-start-script: path=$scriptPath sha256=$scriptHash" in start_backend
    assert "Get-FileHash -LiteralPath $scriptPath -Algorithm SHA256" in start_backend
    assert "backend-import-preflight-ok" in start_backend
    assert "sys.path.insert(0, backend_runtime_root)" in start_backend
    assert "backend-import-preflight-warning:" not in start_backend
    assert "backend-start-cwd:" in start_backend
    assert "backend-command:" in start_backend
    assert "backend-env: {0}={1}" in start_backend
    assert "FANBAN_MODULE5_EXPORT__CAD_RUNNER__SCRIPT_DIR" in start_backend
    assert "FANBAN_MODULE5_EXPORT__DOTNET_BRIDGE__DLL_PATH" in start_backend
    assert '$pathType = if ($name -eq "FANBAN_MODULE5_EXPORT__CAD_RUNNER__SCRIPT_DIR")' in start_backend
    assert "fanban_backend_import_preflight_" in start_backend
    assert 'Join-Path $BackendRuntimeRoot ($preflightPrefix + ".py")' in start_backend
    assert "Set-Content -LiteralPath $preflightScript" in start_backend
    assert 'Start-Process `\n            -FilePath $PythonPath' in start_backend
    assert "-WindowStyle Hidden" in start_backend
    assert "-NoNewWindow" not in start_backend
    assert "-RedirectStandardOutput $preflightStdout" in start_backend
    assert "-RedirectStandardError $preflightStderr" in start_backend
    assert "-c $preflightCode" not in start_backend
    assert 'Set-Item -Path "Env:FANBAN_SPEC_PATH"' in start_backend
    assert 'Set-Item -Path "Env:FANBAN_RUNTIME_SPEC_PATH"' in start_backend
    assert 'Set-Item -Path "Env:FANBAN_MECHANISM_SPEC_PATH"' in start_backend
    assert 'Set-Item -Path "Env:FANBAN_AI_GATEWAY_CONFIG_PATH"' in start_backend
    assert 'Set-Item -Path "Env:FANBAN_AI_GATEWAY_PROFILE"' in start_backend
    assert 'Set-Item -Path "Env:FANBAN_AI_SPEC_PATH"' in start_backend
    assert "terminal_cnpe_intranet_qwen_fast" in start_backend
    assert "ai-config-preflight-ok" in start_backend
    assert 'if ([string]::IsNullOrWhiteSpace($env:FANBAN_AI_GATEWAY_PROFILE))' not in start_backend
    assert 'profile_name != "terminal_cnpe_intranet_qwen_fast"' in start_backend
    assert 'validate_gateway_network_policy(required_network_mode="intranet_only")' in start_backend
    assert '"--proxy-headers"' in start_backend
    assert '"--forwarded-allow-ips"' in start_backend
    assert '"127.0.0.1"' in start_backend
    assert '"--workers",\n            "1"' in start_backend
    assert f'$managedCtbName = "{MANAGED_MONOCHROME_CTB_NAME}"' in start_backend
    assert '$env:FANBAN_MODULE5_EXPORT__PLOT__CTB_NAME -eq "monochrome.ctb"' in start_backend
    assert '[Environment]::SetEnvironmentVariable("PYTHONNOUSERSITE", "1", "Process")' in start_backend
    assert '[Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "1", "Process")' in start_backend
    assert '[Environment]::SetEnvironmentVariable("PYTHONPATH", $null, "Process")' in start_backend
    assert '[Environment]::SetEnvironmentVariable("PYTHONHOME", $null, "Process")' in start_backend
    assert '$logsDir = Join-Path $root "logs"' in start_backend
    assert 'backend-stdout-' in start_backend
    assert 'backend-stderr-' in start_backend
    assert 'api-stdout-' in start_backend
    assert 'api-stderr-' in start_backend
    assert 'worker-stdout-' in start_backend
    assert 'worker-stderr-' in start_backend
    assert 'Append-UvicornProcessLogs' in start_backend
    assert 'backend-api-logs:' in start_backend
    assert 'backend-worker-logs:' in start_backend
    assert 'backend-latest-stderr.log' in start_backend
    assert "Start-Process" in start_backend
    assert '-FilePath $python' in start_backend
    assert '-ArgumentList $ArgumentList' in start_backend
    assert '-RedirectStandardOutput $childStdoutLog' in start_backend
    assert '-RedirectStandardError $childStderrLog' in start_backend
    assert 'Start-Process -FilePath "cmd.exe"' not in start_backend
    assert "Test-BackendPing" in start_backend
    assert "Get-BackendListenerSnapshot" in start_backend
    assert "Stop-BackendProcessTree" in start_backend
    assert "SupervisorFailureThreshold" in start_backend
    assert "ListenerAliveFailureThreshold" in start_backend
    assert "PingTimeoutSeconds" in start_backend
    assert "backend-supervisor" in start_backend
    assert "[int]$RestartDelaySeconds = 10" in start_backend
    assert '$script:stopSupervisor = $false' in start_backend
    assert 'while (-not $script:stopSupervisor)' in start_backend
    assert "backend-supervisor: launching api attempt=" in start_backend
    assert "backend-supervisor: launching worker attempt=" in start_backend
    assert '$apiRestartReason = "api_process_exited"' in start_backend
    assert '$workerRestartReason = "worker_process_exited"' in start_backend
    assert '$apiRestartReason = "api_ping_failed_no_listener"' in start_backend
    assert '$apiRestartReason = "api_ping_failed_listener_alive"' in start_backend
    assert "backend-supervisor: restarting api reason={0}" in start_backend
    assert "backend-supervisor: restarting worker reason={0}" in start_backend
    assert "Start-Sleep -Seconds $RestartDelaySeconds" in start_backend
    assert "Test-BackendPing -PingUrl $pingUrl -TimeoutSeconds $PingTimeoutSeconds" in start_backend
    assert "elapsed_ms" in start_backend
    assert "error = $_.Exception.Message" in start_backend
    assert "api_ping_failed_listener_alive" in start_backend
    assert "api_ping_failed_listener_alive count={0}/{1}" in start_backend
    assert "ping_elapsed_ms={4}" in start_backend
    assert "ping_error={5}" in start_backend
    assert "$listenerAliveThreshold = [Math]::Max" in start_backend
    assert "ping_failed_but_listener_alive" not in start_backend
    assert "api_ping_failed_no_listener" in start_backend
    assert '$listenerSnapshot.status -eq "pass"' in start_backend
    assert "$apiChild.process.WaitForExit(5000)" in start_backend
    assert "$apiChild.process.Refresh()" in start_backend
    assert "backend-supervisor unhealthy: ping_url=" not in start_backend
    assert '& cmd.exe /d /c $cmdLine' not in start_backend
    assert '& $python -X utf8 -m uvicorn' not in start_backend
    assert "probe_target_env.ps1" in prepare_terminal
    assert "runtime.env.ps1" in prepare_terminal
    assert "Set-Item -Path 'Env:{0}' -Value '{1}'" in prepare_terminal
    assert "documents\\AI\\ai_model_gateway.yaml" in prepare_terminal
    assert "documents\\AI\\参数规范_AI.yaml" in prepare_terminal
    assert "FANBAN_AI_SPEC_PATH" in prepare_terminal
    assert "FANBAN_AI_GATEWAY_CONFIG_PATH" in prepare_terminal
    assert "FANBAN_AI_GATEWAY_PROFILE" in prepare_terminal
    assert "terminal_cnpe_intranet_qwen_fast" in prepare_terminal
    assert "$env:{0}" not in prepare_terminal
    assert "OfficeProbeMode" in prepare_terminal
    assert "quick" in prepare_terminal
    assert "Blocking issues detail" in prepare_terminal
    assert "$probe.blocking_issues" in prepare_terminal
    assert "[1/4]" in prepare_terminal
    assert "Invoke-RestMethod" in check_health
    assert "/api/system/ping" in check_health
    assert "api_ping_status" in check_health
    assert "api_health_status" in check_health
    assert "check_iis_proxy_prereqs.ps1" in check_health
    assert "probe_target_env.ps1" in check_health
    assert '-OfficeProbeMode quick' not in check_health
    assert '-OfficeProbeMode deep' in check_health
    assert '-ReuseQuickProbeJson' not in check_health
    assert "[int]$taskInfo.LastTaskResult" not in check_health
    assert "[int64]$taskInfo.LastTaskResult" in check_health
    assert "last_task_result_hex" in check_health
    assert "task_settings_status" in check_health
    assert "execution_time_limit" in check_health
    assert "restart_count" in check_health
    assert "restart_interval" in check_health
    assert "backend_listener_status" in check_health
    assert "backend_failure_classification" in check_health
    assert "task_running_but_no_backend_listener" in check_health
    assert "Get-NetTCPConnection" in check_health
    assert "Win32_Process" in check_health
    assert "recent_task_events" in check_health
    assert "Get-WinEvent" in check_health
    assert "Microsoft-Windows-TaskScheduler/Operational" in check_health
    assert 'ValidateSet("full", "deep")' in check_health
    assert 'if ($Mode -eq "deep" -and (Test-Path -LiteralPath $probeScript -PathType Leaf))' in check_health
    assert '$probeRequiredForOverall = ($Mode -eq "deep")' in check_health
    assert '$null -eq $selectedProbe -or' not in check_health
    assert 'selected_probe_json = $selectedProbeJson' in check_health
    assert "check_health.summary.json" in check_health
    assert "check_health.full.json" in check_health
    assert "proxy_timeout_status" in check_health
    assert "proxy_timeout_seconds" in check_health
    assert "IIS proxy timeout" in check_health
    assert "==== FanBan Health Summary ====" in check_health
    assert 'Get-Content -LiteralPath $probeJson' not in check_health
    assert 'OfficeProbeMode = "deep"' in deep_check
    assert "ForceFullProbe" not in deep_check
    assert "ReuseQuickProbeJson" not in deep_check
    assert "probe_target_env.json" not in deep_check
    assert "$probeArgs = @{" in deep_check
    assert "Test-DotNet48OrAboveInstalled" in install_runtime
    assert "Get-VcRuntimeInfo" in install_runtime
    assert "Expand-PackagePythonRuntime" in install_runtime
    assert "Enable-EmbeddedPythonSitePackages" in install_runtime
    assert "-Encoding ascii" in install_runtime
    assert "Sync-PythonSitePackages" in install_runtime
    assert "python-runtime" in install_runtime
    assert "python-packages\\Lib\\site-packages" in install_runtime
    assert "NSSM" not in install_runtime
    assert "fanban_backend_runtime.pth" in install_runtime
    assert '$backendRuntimeRoot = Join-Path $packageRoot "backend-runtime"' in install_runtime
    assert '$backendRoot = Join-Path $backendRuntimeRoot "backend"' in install_runtime
    assert "Value @($backendRuntimeRoot, $backendRoot)" in install_runtime
    assert "_editable_impl_auto_fanban.pth" in install_runtime
    assert ".NET Framework 4.8" in install_runtime
    assert "New-Website" in configure_iis or "Set-ItemProperty" in configure_iis
    assert "HostName" in configure_iis
    assert "system.webServer/proxy" in configure_iis
    assert '/timeout:"00:10:00"' in configure_iis
    assert "ARR" in configure_iis
    assert '<remove fileExtension=".mjs" />' in configure_iis
    assert '<mimeMap fileExtension=".mjs" mimeType="text/javascript" />' in configure_iis
    assert '<remove fileExtension=".wasm" />' in configure_iis
    assert '<mimeMap fileExtension=".wasm" mimeType="application/wasm" />' in configure_iis
    assert "Get-ConflictingHttpBindingSiteName" in configure_iis
    assert "IIS 绑定冲突" in configure_iis
    assert "Default Web Site" in configure_iis
    assert "HostName 只负责 IIS 主机头绑定" in configure_iis
    assert "不会自动创建 DNS 或 hosts 解析" in configure_iis
    assert "RewriteModule" in check_iis_proxy
    assert "Application Request Routing" in check_iis_proxy
    assert "$minimumProxyTimeoutSeconds = 600" in check_iis_proxy
    assert "timeout_status" in check_iis_proxy
    assert "timeout_seconds" in check_iis_proxy
    assert "function Resolve-ArrTimeoutValue" in check_iis_proxy
    assert '$Value.PSObject.Properties["Value"]' in check_iis_proxy
    assert '$Value.PSObject.Properties["Attributes"]' in check_iis_proxy
    assert '$attributesProperty.Value["timeout"]' in check_iis_proxy
    assert "Convert-ArrTimeoutToSeconds -Value $proxyTimeoutResolved" in check_iis_proxy
    assert "msiexec.exe" in install_iis_proxy
    assert "url_rewrite" in install_iis_proxy
    assert "requestRouter_amd64.msi" in install_iis_proxy or "arr" in install_iis_proxy
    assert "Test-UrlRewriteInstalled" in install_iis_proxy
    assert "Test-ArrInstalled" in install_iis_proxy
    assert "Register-ScheduledTask" in register_task
    assert "New-ScheduledTaskTrigger -AtLogOn" in register_task
    assert "New-ScheduledTaskPrincipal" in register_task
    assert "Interactive" in register_task
    assert "InteractiveToken" not in register_task
    assert "WindowStyle Hidden" in register_task
    assert "-ExecutionTimeLimit (New-TimeSpan -Seconds 0)" in register_task
    assert "-RestartCount 999" in register_task
    assert "-RestartInterval (New-TimeSpan -Minutes 1)" in register_task
    assert "-MultipleInstances IgnoreNew" in register_task
    assert "-DontStopIfGoingOnBatteries" in register_task
    assert "Start-ScheduledTask -TaskName $TaskName" in register_task
    assert "nssm" not in register_task.lower()
    assert "$UserName" in register_task

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
    assert delta_manifest["baseline_package_root"] == "../build/fanban-terminal-deploy"
    assert delta_manifest["target_package_root"] == "../build/fanban-terminal-deploy"
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
    assert (output_root / "frontend-dist" / "web.config").exists()
    delta_files = _relative_files(delta_root)
    assert PACKAGE_MANIFEST in delta_files
    assert f"{DELTA_DIR_NAME}/{DELTA_MANIFEST}" in delta_files
    assert "frontend-dist/index.html" not in delta_files
    assert "frontend-dist/web.config" not in delta_files

    delta_manifest = json.loads((delta_root / DELTA_DIR_NAME / DELTA_MANIFEST).read_text(encoding="utf-8"))
    assert delta_manifest["baseline_exists"] is False
    assert delta_manifest["added_files"] == []
    assert delta_manifest["modified_files"] == []
    assert delta_manifest["deleted_files"] == []

    usage = (delta_root / DELTA_DIR_NAME / DELTA_USAGE).read_text(encoding="utf-8")
    assert "请优先使用 full 包" in usage


def test_publish_terminal_deploy_artifacts_adds_web_config_for_legacy_baseline(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    output_root = tmp_path / "build" / "fanban-terminal-deploy"
    delta_root = tmp_path / "build" / "fanban-terminal-deploy-delta"

    build_terminal_deploy_package(repo_root=repo_root, output_root=output_root)
    (output_root / "frontend-dist" / "web.config").unlink()

    publish_terminal_deploy_artifacts(
        repo_root=repo_root,
        output_root=output_root,
        delta_root=delta_root,
    )

    assert (output_root / "frontend-dist" / "web.config").exists()
    assert (delta_root / "frontend-dist" / "web.config").exists()

    delta_manifest = json.loads((delta_root / DELTA_DIR_NAME / DELTA_MANIFEST).read_text(encoding="utf-8"))
    assert "frontend-dist/web.config" in delta_manifest["added_files"]


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
    assert installers.url_rewrite is not None
    assert installers.arr is not None
    assert installers.dotnet.exists()
    assert installers.vc_redist.exists()
    assert installers.python.exists()
    assert installers.url_rewrite.exists()
    assert installers.arr.exists()
    assert len(downloads) == 5
    assert "2088631" in downloads[0][0]
    assert "vc_redist.x64.exe" in downloads[1][0]
    assert "python-3.13.12-embed-amd64.zip" in downloads[2][0]
    assert "rewrite_amd64_zh-CN.msi" in downloads[3][0]
    assert "LinkID=615136" in downloads[4][0] or "requestRouter_amd64.msi" in downloads[4][0]


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


def test_generated_configure_iis_site_keeps_frontend_app_pool_resident(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    output_root = tmp_path / "build" / "fanban-terminal-deploy"

    build_terminal_deploy_package(repo_root=repo_root, output_root=output_root)

    configure_iis = (output_root / "install" / "configure_iis_site.ps1").read_text(encoding="utf-8")

    assert 'Set-ItemProperty "IIS:\\AppPools\\$AppPoolName" -Name autoStart -Value $true' in configure_iis
    assert 'Set-ItemProperty "IIS:\\AppPools\\$AppPoolName" -Name startMode -Value "AlwaysRunning"' in configure_iis
    assert 'Set-ItemProperty "IIS:\\AppPools\\$AppPoolName" -Name processModel.idleTimeout -Value "00:00:00"' in configure_iis
    assert 'Set-ItemProperty "IIS:\\AppPools\\$AppPoolName" -Name recycling.periodicRestart.time -Value "00:00:00"' in configure_iis
    assert "frontend-app-pool: AlwaysRunning" in configure_iis


def test_generated_check_health_reports_frontend_iis_residency_and_http(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    output_root = tmp_path / "build" / "fanban-terminal-deploy"

    build_terminal_deploy_package(repo_root=repo_root, output_root=output_root)

    check_health = (output_root / "scripts" / "check_health.ps1").read_text(encoding="utf-8")

    assert '[string]$FrontendUrl = ""' in check_health
    assert '[string]$FrontendApiPingUrl = ""' in check_health
    assert '[string]$IisSiteName = "FanBanTerminal"' in check_health
    assert '[string]$IisAppPoolName = "FanBanTerminalAppPool"' in check_health
    assert "Get-FrontendProbeUrlFromBinding" in check_health
    assert "Invoke-FrontendHttpProbe" in check_health
    assert "Get-WebAppPoolState -Name $AppPoolName" in check_health
    assert "processModel.idleTimeout" in check_health
    assert "recycling.periodicRestart.time" in check_health
    assert "frontend_app_pool_status" in check_health
    assert "frontend_http_status" in check_health
    assert "frontend_api_proxy_status" in check_health
    assert "Frontend HTTP:" in check_health
    assert "Frontend AppPool:" in check_health


def test_build_terminal_deploy_package_init_storage_does_not_hardcode_slot_count(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    output_root = tmp_path / "build" / "fanban-terminal-deploy"

    build_terminal_deploy_package(repo_root=repo_root, output_root=output_root)

    init_storage = (output_root / "scripts" / "init_storage.ps1").read_text(encoding="utf-8")

    assert 'runtime\\cad-slots"' in init_storage
    assert "slot-01" not in init_storage
    assert "slot-04" not in init_storage


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
    assert deep_probe["reuse_quick_probe_json"] == ""


def test_generated_start_backend_does_not_use_powershell_reserved_host_variable(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    output_root = tmp_path / "build" / "fanban-terminal-deploy"

    build_terminal_deploy_package(repo_root=repo_root, output_root=output_root)
    unused_port = _find_unused_tcp_port()

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(output_root / "scripts" / "start_backend.ps1"),
            "-Port",
            str(unused_port),
        ],
        capture_output=True,
    )

    stderr = completed.stderr.decode("utf-8", errors="ignore")
    stdout = completed.stdout.decode("utf-8", errors="ignore")
    merged = stdout + "\n" + stderr

    assert "VariableNotWritable" not in merged
    assert "Python 运行环境不存在" in merged


def test_generated_start_backend_ties_uvicorn_to_task_lifetime(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    output_root = tmp_path / "build" / "fanban-terminal-deploy"

    build_terminal_deploy_package(repo_root=repo_root, output_root=output_root)

    start_backend = (output_root / "scripts" / "start_backend.ps1").read_text(encoding="utf-8")

    assert "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE" in start_backend
    assert "CreateJobObject" in start_backend
    assert "AssignProcessToJobObject" in start_backend
    assert "$basicLimitInformation.LimitFlags = [FanBanBackendJobObject]::JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE" in start_backend
    assert "$info.BasicLimitInformation = $basicLimitInformation" in start_backend
    assert "$info.BasicLimitInformation.LimitFlags =" not in start_backend
    assert "Register-BackendChildProcessForTaskStop -BackendProcess $apiProcess" in start_backend
    assert "Register-BackendChildProcessForTaskStop -BackendProcess $workerProcess" in start_backend
    assert "backend-job-object-fatal:" in start_backend
    assert 'throw ("backend-job-object assign failed pid={0} win32_error={1}"' in start_backend
    assert "Stop-Process -Id $BackendProcess.Id -Force -ErrorAction SilentlyContinue" in start_backend
    assert "backend-job-object-warning" not in start_backend
    assert "Close-BackendChildProcessJob" in start_backend

    register_task = (output_root / "install" / REGISTER_TASK_SCRIPT).read_text(encoding="utf-8")
    assert "$settings.AllowHardTerminate = $true" in register_task
    assert "-DisallowHardTerminate" not in register_task


def test_generated_start_backend_appends_child_logs_to_supervisor_stderr(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    output_root = tmp_path / "build" / "fanban-terminal-deploy"

    build_terminal_deploy_package(repo_root=repo_root, output_root=output_root)

    start_backend = (output_root / "scripts" / "start_backend.ps1").read_text(encoding="utf-8")

    assert "[string]$SupervisorStderrLog" in start_backend
    assert "-ChildStderrLog $apiChild.stderr" in start_backend
    assert "-ChildStderrLog $workerChild.stderr" in start_backend
    assert "-SupervisorStderrLog $stderrLog" in start_backend
    assert "[string]$StderrLog" not in start_backend
    assert "Out-File -LiteralPath $SupervisorStderrLog -Encoding utf8 -Append" in start_backend
    assert "Get-Content -LiteralPath $path -Encoding utf8 -Tail $MaxTailLines" in start_backend


def test_generated_start_backend_runs_api_and_worker_as_separate_children(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    output_root = tmp_path / "build" / "fanban-terminal-deploy"

    build_terminal_deploy_package(repo_root=repo_root, output_root=output_root)

    start_backend = (output_root / "scripts" / "start_backend.ps1").read_text(encoding="utf-8")

    assert '"API.app.main:create_app"' in start_backend
    assert '"API.app.worker"' in start_backend
    assert "api-stdout-" in start_backend
    assert "api-stderr-" in start_backend
    assert "worker-stdout-" in start_backend
    assert "worker-stderr-" in start_backend
    assert "backend-supervisor: launching api attempt=" in start_backend
    assert "backend-supervisor: launching worker attempt=" in start_backend
    assert "backend-supervisor: restarting api reason={0}" in start_backend
    assert "backend-supervisor: restarting worker reason={0}" in start_backend
    assert '$apiRestartReason = "api_ping_failed_listener_alive"' in start_backend
    assert '$workerRestartReason = "worker_process_exited"' in start_backend
    assert "Register-BackendChildProcessForTaskStop -BackendProcess $apiProcess" in start_backend
    assert "Register-BackendChildProcessForTaskStop -BackendProcess $workerProcess" in start_backend


def test_generated_start_backend_prevents_duplicate_supervisors_and_workers(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _make_fake_repo(repo_root)
    output_root = tmp_path / "build" / "fanban-terminal-deploy"

    build_terminal_deploy_package(repo_root=repo_root, output_root=output_root)

    start_backend = (output_root / "scripts" / "start_backend.ps1").read_text(encoding="utf-8")

    assert "New-BackendSupervisorMutex" in start_backend
    assert "Test-ExistingBackendBeforeLaunch" in start_backend
    assert "existing_backend_detected action=exit_without_launching_children" in start_backend
    assert "backend_port_already_listening action=fail_without_launching_children" in start_backend
    assert "api_port_bind_failed action=fail_without_retry" in start_backend
    assert '$apiReadyForWorker = $false' in start_backend
    assert '$apiReadyForWorker = $true' in start_backend
    assert 'if ($apiReadyForWorker -and $null -eq $workerChild)' in start_backend
    assert 'Start-BackendManagedProcess -Label "worker"' in start_backend
