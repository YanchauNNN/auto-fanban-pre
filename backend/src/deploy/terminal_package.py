from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..ai.ansys_mapdl_skill import (
    ANSYS_MAPDL_SKILL_ID,
)
from ..ai.ansys_mapdl_skill import (
    install_skill_archive as install_ansys_mapdl_skill_archive,
)
from ..ai.building_standards_skill import (
    BUILDING_STANDARDS_SKILL_DIR,
    BUILDING_STANDARDS_SKILL_ID,
)
from ..ai.building_standards_skill import (
    install_skill_archive as install_building_standards_skill_archive,
)
from ..ai.reinforcement_table_skill import (
    REINFORCEMENT_TABLE_SKILL_DIR,
    REINFORCEMENT_TABLE_SKILL_ID,
)
from ..cad.plot_asset_validation import is_valid_pc3_file, is_valid_pmp_file
from ..cad.plot_resource_manager import PDF2_PMP_NAME
from ..config.ai.ai_spec import AiSpecLoader
from ..config.mechanism_spec import (
    DeploymentMechanismConfig,
    MechanismSpecLoader,
    load_mechanism_spec,
)

_DEFAULT_DEPLOYMENT_MECHANISM = DeploymentMechanismConfig()
SPEC_NAME = _DEFAULT_DEPLOYMENT_MECHANISM.spec_name
RUNTIME_SPEC_NAME = _DEFAULT_DEPLOYMENT_MECHANISM.runtime_spec_name
MECHANISM_SPEC_NAME = _DEFAULT_DEPLOYMENT_MECHANISM.mechanism_spec_name
TERMINAL_INSTALL_PLAN_NAME = "\u7ec8\u7aef\u5b9e\u88c5\u5b89\u88c5\u8ba1\u5212.md"
AI_SPEC_NAME = "参数规范_AI.yaml"
AI_GATEWAY_CONFIG_NAME = "ai_model_gateway.yaml"
ANSYS_MAPDL_PRIVATE_ARCHIVE_GLOB = "ansys-mapdl-18-2-private-offline-*.zip"
ANSYS_MAPDL_INSTALL_SCRIPT_NAME = "install_ansys_mapdl_skill.ps1"
BUILDING_STANDARDS_PRIVATE_ARCHIVE_GLOB = (
    "building-structure-standards-private-offline-*.zip"
)
BUILDING_STANDARDS_INSTALL_SCRIPT_NAME = "install_building_standards_skill.ps1"
DEPLOY_README = "README_\u90e8\u7f72\u8bf4\u660e.md"
MISSING_INSTALLER_README = "README_\u7f3a\u5931\u79bb\u7ebf\u5b89\u88c5\u5668.md"
PYTHON_PACKAGES_DEST = Path("python-packages") / "Lib" / "site-packages"
STALE_RUNTIME_PTH_FILES = (
    "_auto_fanban.pth",
    "_editable_impl_auto_fanban.pth",
    "a1_coverage.pth",
)
DEPLOY_IGNORE_PATTERNS = (
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "*.lscache",
    ".build_packages",
    "~$*",
    ANSYS_MAPDL_PRIVATE_ARCHIVE_GLOB,
    BUILDING_STANDARDS_PRIVATE_ARCHIVE_GLOB,
)
PACKAGE_MANIFEST = "package-manifest.json"
DELTA_DIR_NAME = "_delta"
DELTA_MANIFEST = "delta-manifest.json"
DELTA_OVERWRITE_LIST = "覆盖清单.txt"
DELTA_DELETE_LIST = "删除清单.txt"
DELTA_USAGE = "使用说明.txt"
MANAGED_PDF2_PC3_NAME = _DEFAULT_DEPLOYMENT_MECHANISM.managed_pdf2_pc3_name
MANAGED_MONOCHROME_CTB_NAME = _DEFAULT_DEPLOYMENT_MECHANISM.managed_monochrome_ctb_name
DEFAULT_FRONTEND_API_PORT = _DEFAULT_DEPLOYMENT_MECHANISM.default_frontend_api_port


@dataclass(frozen=True)
class CopyPlanEntry:
    source: Path
    destination: Path


@dataclass(frozen=True)
class DeployArtifacts:
    full_root: Path
    delta_root: Path


def _deployment_mechanism(root: Path | None = None) -> DeploymentMechanismConfig:
    if root is not None:
        local_spec = root / "documents" / _DEFAULT_DEPLOYMENT_MECHANISM.mechanism_spec_name
        if local_spec.exists():
            return MechanismSpecLoader.load(local_spec).deployment_mechanism
    try:
        return load_mechanism_spec().deployment_mechanism
    except FileNotFoundError:
        return DeploymentMechanismConfig()


def gather_copy_plan(repo_root: Path) -> list[CopyPlanEntry]:
    deployment = _deployment_mechanism(repo_root)
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
        CopyPlanEntry(repo_root / "documents" / deployment.spec_name, Path("documents") / deployment.spec_name),
        CopyPlanEntry(
            repo_root / "documents" / deployment.runtime_spec_name,
            Path("documents") / deployment.runtime_spec_name,
        ),
        CopyPlanEntry(
            repo_root / "documents" / deployment.mechanism_spec_name,
            Path("documents") / deployment.mechanism_spec_name,
        ),
        CopyPlanEntry(
            repo_root / "documents" / TERMINAL_INSTALL_PLAN_NAME,
            Path("documents") / TERMINAL_INSTALL_PLAN_NAME,
        ),
        CopyPlanEntry(repo_root / "documents" / "AI", Path("documents") / "AI"),
        CopyPlanEntry(
            repo_root / "documents" / "AI" / AI_SPEC_NAME,
            Path("documents") / "AI" / AI_SPEC_NAME,
        ),
        CopyPlanEntry(
            repo_root / "documents" / "AI" / AI_GATEWAY_CONFIG_NAME,
            Path("documents") / "AI" / AI_GATEWAY_CONFIG_NAME,
        ),
        CopyPlanEntry(repo_root / "documents_bin", Path("documents_bin")),
        CopyPlanEntry(repo_root / "tools" / "probe_target_env.ps1", Path("scripts") / "probe_target_env.ps1"),
        CopyPlanEntry(repo_root / "tools" / "cad_env_fingerprint.ps1", Path("scripts") / "cad_env_fingerprint.ps1"),
        CopyPlanEntry(repo_root / "tools" / "cad_env_sync.ps1", Path("scripts") / "cad_env_sync.ps1"),
        CopyPlanEntry(
            repo_root / "tools" / "diagnose_iis_frontend_503.ps1",
            Path("tools") / "diagnose_iis_frontend_503.ps1",
        ),
        CopyPlanEntry(
            repo_root / "tools" / "ai" / "test_ai_model_connectivity.ps1",
            Path("scripts") / "test_ai_model_connectivity.ps1",
        ),
        CopyPlanEntry(
            repo_root / "tools" / "ai" / ANSYS_MAPDL_INSTALL_SCRIPT_NAME,
            Path("scripts") / ANSYS_MAPDL_INSTALL_SCRIPT_NAME,
        ),
        CopyPlanEntry(
            repo_root / "tools" / "ai" / BUILDING_STANDARDS_INSTALL_SCRIPT_NAME,
            Path("scripts") / BUILDING_STANDARDS_INSTALL_SCRIPT_NAME,
        ),
    ]


def _ensure_exists(copy_plan: list[CopyPlanEntry]) -> None:
    missing = [str(entry.source) for entry in copy_plan if not entry.source.exists()]
    if missing:
        joined = "\n".join(missing)
        raise FileNotFoundError(f"离线部署包缺少必要源文件/目录:\n{joined}")


def _validate_frontend_preview_assets(repo_root: Path) -> None:
    assets_dir = repo_root / "frontend" / "dist" / "assets"
    if not assets_dir.exists():
        raise FileNotFoundError("frontend/dist/assets 不存在，请先执行 frontend 构建。")
    if not any(assets_dir.glob("pdf.worker*.mjs")):
        raise FileNotFoundError(
            "frontend/dist 缺少 PDF 预览 worker（pdf.worker*.mjs），"
            "请先执行 `npm run build`，不要使用旧的 dist 打包。"
        )


def _build_frontend_web_config(
    api_port: int | None = None,
    *,
    deployment: DeploymentMechanismConfig | None = None,
) -> str:
    if api_port is None:
        api_port = int((deployment or _deployment_mechanism()).default_frontend_api_port)
    return f'''<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <system.webServer>
    <staticContent>
      <remove fileExtension=".mjs" />
      <mimeMap fileExtension=".mjs" mimeType="text/javascript" />
      <remove fileExtension=".wasm" />
      <mimeMap fileExtension=".wasm" mimeType="application/wasm" />
    </staticContent>
    <rewrite>
      <rules>
        <rule name="API Proxy" stopProcessing="true">
          <match url="^api/(.*)" />
          <action type="Rewrite" url="http://127.0.0.1:{api_port}/api/{{R:1}}" />
        </rule>
        <rule name="SPA Fallback" stopProcessing="true">
          <match url=".*" />
          <conditions logicalGrouping="MatchAll">
            <add input="{{REQUEST_FILENAME}}" matchType="IsFile" negate="true" />
            <add input="{{REQUEST_FILENAME}}" matchType="IsDirectory" negate="true" />
            <add input="{{REQUEST_URI}}" pattern="^/api/" negate="true" />
          </conditions>
          <action type="Rewrite" url="/index.html" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
'''


def _write_frontend_web_config(output_root: Path) -> None:
    frontend_root = output_root / "frontend-dist"
    if not frontend_root.exists():
        raise FileNotFoundError(f"前端静态目录不存在: {frontend_root}")
    _write_text(
        frontend_root / "web.config",
        _build_frontend_web_config(deployment=_deployment_mechanism(output_root)),
    )


def _copy_entry(entry: CopyPlanEntry, output_root: Path) -> None:
    target = output_root / entry.destination
    if entry.source.is_dir():
        if target.exists():
            shutil.rmtree(target)
        ignore = None
        if entry.destination != PYTHON_PACKAGES_DEST:
            ignore = shutil.ignore_patterns(*DEPLOY_IGNORE_PATTERNS)
        shutil.copytree(
            entry.source,
            target,
            ignore=ignore,
        )
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry.source, target)


def _materialize_ansys_mapdl_skill(repo_root: Path, output_root: Path) -> None:
    spec = AiSpecLoader.load(repo_root / "documents" / "AI" / AI_SPEC_NAME)
    configured = next(
        (
            skill
            for skill in spec.ai_layer.chat.skills
            if skill.enabled and skill.handler == ANSYS_MAPDL_SKILL_ID
        ),
        None,
    )
    if configured is None:
        return

    relative_root = Path(configured.root)
    if not configured.root or relative_root.is_absolute() or ".." in relative_root.parts:
        raise ValueError("ANSYS MAPDL Skill root must be a package-relative path")
    target = output_root / relative_root
    source = repo_root / relative_root
    if source.is_dir():
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target, ignore=shutil.ignore_patterns(*DEPLOY_IGNORE_PATTERNS))
        return

    archives = sorted((repo_root / "documents" / "AI").glob(ANSYS_MAPDL_PRIVATE_ARCHIVE_GLOB))
    if not archives:
        raise FileNotFoundError(
            "ANSYS MAPDL 18.2 Skill 已启用，但未找到 storage 语料或私人离线包。"
            "请先运行 tools/ai/install_ansys_mapdl_skill.ps1。"
        )
    install_ansys_mapdl_skill_archive(archives[-1], target)


def _materialize_building_standards_skill(
    repo_root: Path,
    output_root: Path,
) -> None:
    spec = AiSpecLoader.load(repo_root / "documents" / "AI" / AI_SPEC_NAME)
    configured = next(
        (
            skill
            for skill in spec.ai_layer.chat.skills
            if skill.enabled and skill.handler == BUILDING_STANDARDS_SKILL_ID
        ),
        None,
    )
    if configured is None:
        return

    relative_root = Path(configured.root)
    if not configured.root or relative_root.is_absolute() or ".." in relative_root.parts:
        raise ValueError(
            "Building standards Skill root must be a package-relative path"
        )
    target = output_root / relative_root
    candidates = (
        repo_root / relative_root,
        repo_root / "tools" / "ai" / BUILDING_STANDARDS_SKILL_DIR,
    )
    source = next((candidate for candidate in candidates if candidate.is_dir()), None)
    if source is not None:
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(
            source,
            target,
            ignore=shutil.ignore_patterns(*DEPLOY_IGNORE_PATTERNS),
        )
        return

    archives = sorted(
        [
            *repo_root.glob(
                f"build/{BUILDING_STANDARDS_PRIVATE_ARCHIVE_GLOB}"
            ),
            *(repo_root / "documents" / "AI").glob(
                BUILDING_STANDARDS_PRIVATE_ARCHIVE_GLOB
            ),
        ]
    )
    if not archives:
        raise FileNotFoundError(
            "建筑结构总图规范 Skill 已启用，但未找到 storage 语料、"
            "tools/ai 源目录或私人离线包。"
            "请先运行 tools/ai/package_building_standards_skill.py。"
        )
    install_building_standards_skill_archive(archives[-1], target)


def _materialize_reinforcement_table_skill(
    repo_root: Path,
    output_root: Path,
) -> None:
    spec = AiSpecLoader.load(repo_root / "documents" / "AI" / AI_SPEC_NAME)
    configured = next(
        (
            skill
            for skill in spec.ai_layer.chat.skills
            if skill.enabled and skill.handler == REINFORCEMENT_TABLE_SKILL_ID
        ),
        None,
    )
    if configured is None:
        return

    relative_root = Path(configured.root)
    if not configured.root or relative_root.is_absolute() or ".." in relative_root.parts:
        raise ValueError(
            "Reinforcement table Skill root must be a package-relative path"
        )
    target = output_root / relative_root
    candidates = (
        repo_root / relative_root,
        repo_root / "tools" / "ai" / REINFORCEMENT_TABLE_SKILL_DIR,
    )
    source = next((candidate for candidate in candidates if candidate.is_dir()), None)
    required_files = (
        Path("SKILL.md"),
        Path("references") / "normalization-rules.md",
    )
    if source is None or not all(
        (source / relative).is_file() for relative in required_files
    ):
        raise FileNotFoundError(
            "墙体配筋表规范化 Skill 已启用，但本地规则包不完整。"
            "请检查 tools/ai/reinforcement-table-normalizer。"
        )
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns(*DEPLOY_IGNORE_PATTERNS),
    )


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
    for dist_info in site_packages_root.glob("auto_fanban-*.dist-info"):
        direct_url = dist_info / "direct_url.json"
        if direct_url.exists():
            direct_url.unlink()
        record = dist_info / "RECORD"
        if record.exists():
            stale_fragments = (*STALE_RUNTIME_PTH_FILES, "direct_url.json")
            lines = [
                line
                for line in record.read_text(encoding="utf-8").splitlines()
                if not any(fragment in line for fragment in stale_fragments)
            ]
            record.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _prune_development_artifacts(output_root: Path) -> None:
    backend_src_root = output_root / "backend-runtime" / "backend" / "src"
    removable_dirs = (
        backend_src_root / "cad" / "dotnet" / "Module5CadBridge" / "obj",
        backend_src_root / "cad" / "dotnet" / "Module5CadBridge" / "bin" / "x64",
    )
    for target in removable_dirs:
        if target.exists():
            shutil.rmtree(target)
    bridge_release_dir = (
        backend_src_root
        / "cad"
        / "dotnet"
        / "Module5CadBridge"
        / "bin"
        / "Release"
        / "net48"
    )
    if bridge_release_dir.exists():
        for pdb_file in bridge_release_dir.glob("*.pdb"):
            pdb_file.unlink()


def _find_local_managed_pdf2_pc3(pc3_name: str) -> Path | None:
    preferred_candidates: list[Path] = []
    for base in filter(None, (os.getenv("APPDATA"), os.getenv("LOCALAPPDATA"))):
        preferred_candidates.append(
            Path(base) / "Autodesk" / "AutoCAD 2022" / "R24.1" / "chs" / "Plotters" / pc3_name
        )

    for candidate in preferred_candidates:
        if candidate.exists() and candidate.is_file() and is_valid_pc3_file(candidate):
            return candidate

    for base in filter(None, (os.getenv("APPDATA"), os.getenv("LOCALAPPDATA"))):
        autodesk_root = Path(base) / "Autodesk"
        if not autodesk_root.exists() or not autodesk_root.is_dir():
            continue
        for candidate in sorted(autodesk_root.rglob(pc3_name), reverse=True):
            if candidate.is_file() and "Plotters" in candidate.parts and is_valid_pc3_file(candidate):
                return candidate
    return None


def _find_local_managed_pdf2_pmp(plotters_dir: Path, pmp_name: str) -> Path | None:
    for candidate in (plotters_dir / "PMP Files" / pmp_name, plotters_dir / pmp_name):
        if candidate.exists() and candidate.is_file() and is_valid_pmp_file(candidate):
            return candidate
    return None


def _overlay_local_managed_plotter_assets(output_root: Path) -> None:
    deployment = _deployment_mechanism(output_root)
    pc3_name = deployment.managed_pdf2_pc3_name
    local_pc3 = _find_local_managed_pdf2_pc3(pc3_name)
    if local_pc3 is None:
        return
    local_pmp = _find_local_managed_pdf2_pmp(local_pc3.parent, PDF2_PMP_NAME)
    if local_pmp is None:
        return
    resources_dir = output_root / "documents" / "Resources"
    resources_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(local_pc3, resources_dir / pc3_name)
    shutil.copy2(local_pmp, resources_dir / PDF2_PMP_NAME)


def _timestamp_utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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
    return path.suffix.lower() not in {".pyc", ".pyo"}


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
    deployment = _deployment_mechanism(output_root)
    storage_root = output_root / "storage"
    for rel in [Path("jobs"), Path("groups"), Path("runtime"), Path("ai") / "skills"]:
        (storage_root / rel).mkdir(parents=True, exist_ok=True)

    start_backend = r'''param(
    [string]$ListenHost = "127.0.0.1",
    [int]$Port = __DEFAULT_FRONTEND_API_PORT__,
    [int]$StartupGraceSeconds = 60,
    [int]$SupervisorIntervalSeconds = 15,
    [int]$SupervisorFailureThreshold = 3,
    [int]$ListenerAliveFailureThreshold = 6,
    [int]$RestartDelaySeconds = 10,
    [int]$PingTimeoutSeconds = 5
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "python-runtime\python.exe"
$runtimeEnv = Join-Path $PSScriptRoot "runtime.env.ps1"
$logsDir = Join-Path $root "logs"
$runStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$stdoutLog = Join-Path $logsDir ("backend-stdout-{0}.log" -f $runStamp)
$stderrLog = Join-Path $logsDir ("backend-stderr-{0}.log" -f $runStamp)
$latestStdoutLog = Join-Path $logsDir "backend-latest-stdout.log"
$latestStderrLog = Join-Path $logsDir "backend-latest-stderr.log"
$script:backendExitCode = 0
$script:stopSupervisor = $false
$script:supervisorMutex = $null
$script:supervisorMutexAcquired = $false

New-Item -ItemType Directory -Path $logsDir -Force | Out-Null

function Update-LatestBackendLogs {
    if (Test-Path -LiteralPath $stdoutLog -PathType Leaf) {
        Copy-Item -LiteralPath $stdoutLog -Destination $latestStdoutLog -Force
    }
    if (Test-Path -LiteralPath $stderrLog -PathType Leaf) {
        Copy-Item -LiteralPath $stderrLog -Destination $latestStderrLog -Force
    }
}

function Write-BackendLogHeader {
    $scriptPath = if ($PSCommandPath) { $PSCommandPath } else { $MyInvocation.MyCommand.Path }
    $scriptHash = ""
    if ($scriptPath -and (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
        try {
            $scriptHash = (Get-FileHash -LiteralPath $scriptPath -Algorithm SHA256).Hash
        } catch {
            $scriptHash = "<hash-error: $($_.Exception.Message)>"
        }
    }
    $header = @(
        "FanBanBackend start: " + (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"),
        "Root: $root",
        "Listen: $ListenHost`:$Port",
        "Python: $python",
        "backend-start-script: path=$scriptPath sha256=$scriptHash",
        ""
    ) -join [Environment]::NewLine
    $header | Out-File -LiteralPath $stdoutLog -Encoding utf8 -Append
    $header | Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
}

function Get-BackendSupervisorMutexName {
    $identity = "{0}|{1}|{2}" -f ([System.IO.Path]::GetFullPath($root).ToLowerInvariant()), $ListenHost, $Port
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($identity)
        $hashBytes = $sha256.ComputeHash($bytes)
        $hash = -join ($hashBytes | ForEach-Object { $_.ToString("x2") })
        return "Local\FanBanBackendSupervisor-{0}" -f $hash.Substring(0, 32)
    } finally {
        $sha256.Dispose()
    }
}

function New-BackendSupervisorMutex {
    $mutexName = Get-BackendSupervisorMutexName
    $createdNew = $false
    $mutex = New-Object System.Threading.Mutex($true, $mutexName, [ref]$createdNew)
    $script:supervisorMutex = $mutex
    $script:supervisorMutexAcquired = [bool]$createdNew
    if ($createdNew) {
        ("backend-supervisor: mutex_acquired name={0}" -f $mutexName) |
            Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
    } else {
        ("backend-supervisor: duplicate_supervisor_detected mutex={0} action=exit_without_launching_children" -f $mutexName) |
            Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
    }
    return [ordered]@{
        acquired = [bool]$createdNew
        name = $mutexName
    }
}

function Close-BackendSupervisorMutex {
    if ($null -ne $script:supervisorMutex) {
        if ($script:supervisorMutexAcquired) {
            try {
                $script:supervisorMutex.ReleaseMutex() | Out-Null
            } catch {
            }
        }
        try {
            $script:supervisorMutex.Dispose()
        } catch {
        }
    }
    $script:supervisorMutex = $null
    $script:supervisorMutexAcquired = $false
}

function Set-BackendRuntimeEnvironment {
    param(
        [string]$SpecPath,
        [string]$RuntimeSpecPath,
        [string]$MechanismSpecPath,
        [string]$AiSpecPath,
        [string]$AiGatewayConfigPath,
        [string]$CadScriptDir,
        [string]$DotNetBridgeDllPath,
        [string]$CtbName
    )

    if ((-not $env:FANBAN_SPEC_PATH) -or (-not (Test-Path -LiteralPath $env:FANBAN_SPEC_PATH -PathType Leaf))) {
        if (Test-Path -LiteralPath $SpecPath -PathType Leaf) {
            Set-Item -Path "Env:FANBAN_SPEC_PATH" -Value $SpecPath
        }
    }

    if ((-not $env:FANBAN_RUNTIME_SPEC_PATH) -or (-not (Test-Path -LiteralPath $env:FANBAN_RUNTIME_SPEC_PATH -PathType Leaf))) {
        if (Test-Path -LiteralPath $RuntimeSpecPath -PathType Leaf) {
            Set-Item -Path "Env:FANBAN_RUNTIME_SPEC_PATH" -Value $RuntimeSpecPath
        }
    }

    if ((-not $env:FANBAN_MECHANISM_SPEC_PATH) -or (-not (Test-Path -LiteralPath $env:FANBAN_MECHANISM_SPEC_PATH -PathType Leaf))) {
        if (Test-Path -LiteralPath $MechanismSpecPath -PathType Leaf) {
            Set-Item -Path "Env:FANBAN_MECHANISM_SPEC_PATH" -Value $MechanismSpecPath
        }
    }

    if ((-not $env:FANBAN_AI_SPEC_PATH) -or (-not (Test-Path -LiteralPath $env:FANBAN_AI_SPEC_PATH -PathType Leaf))) {
        if (Test-Path -LiteralPath $AiSpecPath -PathType Leaf) {
            Set-Item -Path "Env:FANBAN_AI_SPEC_PATH" -Value $AiSpecPath
        }
    }

    if ((-not $env:FANBAN_AI_GATEWAY_CONFIG_PATH) -or (-not (Test-Path -LiteralPath $env:FANBAN_AI_GATEWAY_CONFIG_PATH -PathType Leaf))) {
        if (Test-Path -LiteralPath $AiGatewayConfigPath -PathType Leaf) {
            Set-Item -Path "Env:FANBAN_AI_GATEWAY_CONFIG_PATH" -Value $AiGatewayConfigPath
        }
    }

    Set-Item -Path "Env:FANBAN_AI_GATEWAY_PROFILE" -Value "terminal_cnpe_intranet_qwen_fast"

    if ((-not $env:FANBAN_MODULE5_EXPORT__PLOT__CTB_NAME) -or ($env:FANBAN_MODULE5_EXPORT__PLOT__CTB_NAME -eq "monochrome.ctb")) {
        Set-Item -Path "Env:FANBAN_MODULE5_EXPORT__PLOT__CTB_NAME" -Value $CtbName
    }

    if (Test-Path -LiteralPath $CadScriptDir -PathType Container) {
        Set-Item -Path "Env:FANBAN_MODULE5_EXPORT__CAD_RUNNER__SCRIPT_DIR" -Value $CadScriptDir
    }

    if (Test-Path -LiteralPath $DotNetBridgeDllPath -PathType Leaf) {
        Set-Item -Path "Env:FANBAN_MODULE5_EXPORT__DOTNET_BRIDGE__DLL_PATH" -Value $DotNetBridgeDllPath
    }

    $requiredEnv = @(
        @("FANBAN_SPEC_PATH", $env:FANBAN_SPEC_PATH),
        @("FANBAN_RUNTIME_SPEC_PATH", $env:FANBAN_RUNTIME_SPEC_PATH),
        @("FANBAN_MECHANISM_SPEC_PATH", $env:FANBAN_MECHANISM_SPEC_PATH),
        @("FANBAN_AI_SPEC_PATH", $env:FANBAN_AI_SPEC_PATH),
        @("FANBAN_AI_GATEWAY_CONFIG_PATH", $env:FANBAN_AI_GATEWAY_CONFIG_PATH),
        @("FANBAN_MODULE5_EXPORT__CAD_RUNNER__SCRIPT_DIR", $env:FANBAN_MODULE5_EXPORT__CAD_RUNNER__SCRIPT_DIR),
        @("FANBAN_MODULE5_EXPORT__DOTNET_BRIDGE__DLL_PATH", $env:FANBAN_MODULE5_EXPORT__DOTNET_BRIDGE__DLL_PATH)
    )
    foreach ($entry in $requiredEnv) {
        $name = [string]$entry[0]
        $value = [string]$entry[1]
        $pathType = if ($name -eq "FANBAN_MODULE5_EXPORT__CAD_RUNNER__SCRIPT_DIR") { "Container" } else { "Leaf" }
        if ([string]::IsNullOrWhiteSpace($value) -or -not (Test-Path -LiteralPath $value -PathType $pathType)) {
            throw ("后端启动环境变量无效: {0}={1}" -f $name, $value)
        }
        ("backend-env: {0}={1}" -f $name, $value) | Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
    }
    ("backend-env: FANBAN_MODULE5_EXPORT__PLOT__CTB_NAME={0}" -f $env:FANBAN_MODULE5_EXPORT__PLOT__CTB_NAME) |
        Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
    ("backend-env: FANBAN_AI_GATEWAY_CONFIG_PATH={0}" -f $env:FANBAN_AI_GATEWAY_CONFIG_PATH) |
        Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
    ("backend-env: FANBAN_AI_GATEWAY_PROFILE={0}" -f $env:FANBAN_AI_GATEWAY_PROFILE) |
        Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
}

function Test-BackendImportPreflight {
    param(
        [string]$PythonPath,
        [string]$BackendRuntimeRoot
    )

    $preflightCode = @'
import os
import sys
from pathlib import Path

backend_runtime_root = str(Path.cwd())
if backend_runtime_root not in sys.path:
    sys.path.insert(0, backend_runtime_root)

required = (
    "FANBAN_SPEC_PATH",
    "FANBAN_RUNTIME_SPEC_PATH",
    "FANBAN_MECHANISM_SPEC_PATH",
    "FANBAN_AI_SPEC_PATH",
    "FANBAN_AI_GATEWAY_CONFIG_PATH",
)
for name in required:
    value = os.environ.get(name, "")
    if not value or not Path(value).is_file():
        raise SystemExit(f"{name} invalid: {value}")

import API.app.main as main
from src.config import load_ai_spec

ai_spec = load_ai_spec(os.environ["FANBAN_AI_SPEC_PATH"])
gateway = ai_spec.resolve_gateway()
models = ai_spec.resolve_models()
profile_name = ai_spec.resolve_gateway_profile_name()
if profile_name != "terminal_cnpe_intranet_qwen_fast":
    raise SystemExit(f"terminal AI gateway profile invalid: {profile_name}")
ai_spec.validate_gateway_network_policy(required_network_mode="intranet_only")
print(
    "ai-config-preflight-ok",
    f"profile={profile_name}",
    f"model={models.chat.model}",
    f"auth_required={bool(gateway.api_key_env_var)}",
)
print("backend-import-preflight-ok", main.create_app)
'@

    $preflightPrefix = "fanban_backend_import_preflight_" + [guid]::NewGuid().ToString("N")
    $preflightScript = Join-Path $BackendRuntimeRoot ($preflightPrefix + ".py")
    $preflightStdout = Join-Path ([System.IO.Path]::GetTempPath()) ($preflightPrefix + ".stdout.log")
    $preflightStderr = Join-Path ([System.IO.Path]::GetTempPath()) ($preflightPrefix + ".stderr.log")

    try {
        Set-Content -LiteralPath $preflightScript -Value $preflightCode -Encoding utf8
        $preflightProcess = Start-Process `
            -FilePath $PythonPath `
            -ArgumentList @("-X", "utf8", $preflightScript) `
            -WorkingDirectory $BackendRuntimeRoot `
            -WindowStyle Hidden `
            -Wait `
            -PassThru `
            -RedirectStandardOutput $preflightStdout `
            -RedirectStandardError $preflightStderr

        foreach ($outputPath in @($preflightStdout, $preflightStderr)) {
            if (Test-Path -LiteralPath $outputPath -PathType Leaf) {
                Get-Content -LiteralPath $outputPath -Encoding utf8 |
                    Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
            }
        }
        if ($preflightProcess.ExitCode -ne 0) {
            throw ("后端导入预检失败: exit_code={0}; cwd={1}" -f $preflightProcess.ExitCode, $BackendRuntimeRoot)
        }
    } finally {
        foreach ($tempPath in @($preflightScript, $preflightStdout, $preflightStderr)) {
            if (Test-Path -LiteralPath $tempPath -PathType Leaf) {
                Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

function Get-BackendProbeHost {
    param([string]$HostValue)

    if ([string]::IsNullOrWhiteSpace($HostValue) -or $HostValue -eq "0.0.0.0" -or $HostValue -eq "::") {
        return "127.0.0.1"
    }
    return $HostValue
}

function Test-BackendPing {
    param(
        [string]$PingUrl,
        [int]$TimeoutSeconds = 5
    )

    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $response = Invoke-RestMethod -Uri $PingUrl -Method Get -TimeoutSec $TimeoutSeconds -ErrorAction Stop
        $timer.Stop()
        $ok = ($null -ne $response -and $response.ok -eq $true)
        $status = if ($ok) { "pass" } else { "fail" }
        $error = if ($ok) { "" } else { "unexpected ping response" }
        return [ordered]@{
            ok = $ok
            status = $status
            error = $error
            elapsed_ms = [int64]$timer.ElapsedMilliseconds
            response = $response
        }
    } catch {
        $timer.Stop()
        return [ordered]@{
            ok = $false
            status = "fail"
            error = $_.Exception.Message
            elapsed_ms = [int64]$timer.ElapsedMilliseconds
            response = $null
        }
    }
}

function Append-UvicornProcessLogs {
    param(
        [string]$UvicornStdoutLog,
        [string]$UvicornStderrLog
    )

    foreach ($entry in @(@("stdout", $UvicornStdoutLog), @("stderr", $UvicornStderrLog))) {
        $label = [string]$entry[0]
        $path = [string]$entry[1]
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            ("----- uvicorn-{0}: {1} -----" -f $label, $path) |
                Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
            Get-Content -LiteralPath $path -Encoding utf8 |
                Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
        } else {
            ("----- uvicorn-{0}: missing {1} -----" -f $label, $path) |
                Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
        }
    }
}

function Get-BackendListenerSnapshot {
    param([int]$BackendPort)

    try {
        $connections = @(Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction Stop)
    } catch {
        $message = $_.Exception.Message
        if ($message -match "找不到任何匹配|No matching|No MSFT_NetTCPConnection objects found") {
            return [ordered]@{
                status = "fail"
                error = ""
                count = 0
                listeners = @()
            }
        }
        return [ordered]@{
            status = "error"
            error = $message
            count = 0
            listeners = @()
        }
    }

    $listeners = @()
    foreach ($connection in $connections) {
        $processId = [int]$connection.OwningProcess
        $processName = ""
        $commandLine = ""
        try {
            $processInfo = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $processId) -ErrorAction Stop
            $processName = [string]$processInfo.Name
            $commandLine = [string]$processInfo.CommandLine
        } catch {
            $processName = ""
            $commandLine = ""
        }

        $listeners += [ordered]@{
            local_address = [string]$connection.LocalAddress
            local_port = [int]$connection.LocalPort
            process_id = $processId
            process_name = $processName
            command_line = $commandLine
        }
    }

    return [ordered]@{
        status = if ($listeners.Count -gt 0) { "pass" } else { "fail" }
        error = ""
        count = $listeners.Count
        listeners = $listeners
    }
}

function Test-ExistingBackendBeforeLaunch {
    param(
        [string]$PingUrl,
        [int]$BackendPort,
        [int]$TimeoutSeconds = 5
    )

    $pingResult = Test-BackendPing -PingUrl $PingUrl -TimeoutSeconds $TimeoutSeconds
    $listenerSnapshot = Get-BackendListenerSnapshot -BackendPort $BackendPort
    $pingElapsedMs = if ($null -ne $pingResult.elapsed_ms) { [int64]$pingResult.elapsed_ms } else { -1 }
    $pingError = if ($null -ne $pingResult.error) { [string]$pingResult.error } else { "" }

    if ([bool]$pingResult.ok) {
        ("backend-supervisor: existing_backend_detected action=exit_without_launching_children listener_status={0} listener_count={1} ping_elapsed_ms={2}" -f `
            $listenerSnapshot.status,
            $listenerSnapshot.count,
            $pingElapsedMs) |
            Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
        return [ordered]@{
            action = "exit"
            reason = "healthy_existing_backend"
            ping = $pingResult
            listener = $listenerSnapshot
        }
    }

    if ($listenerSnapshot.status -eq "pass" -and [int]$listenerSnapshot.count -gt 0) {
        ("backend-supervisor: backend_port_already_listening action=fail_without_launching_children listener_status={0} listener_count={1} ping_elapsed_ms={2} ping_error={3}" -f `
            $listenerSnapshot.status,
            $listenerSnapshot.count,
            $pingElapsedMs,
            $pingError) |
            Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
        ($listenerSnapshot | ConvertTo-Json -Depth 8 -Compress) |
            Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
        return [ordered]@{
            action = "exit"
            reason = "port_already_listening_unhealthy"
            ping = $pingResult
            listener = $listenerSnapshot
        }
    }

    return [ordered]@{
        action = "launch"
        reason = "no_existing_backend"
        ping = $pingResult
        listener = $listenerSnapshot
    }
}

function Test-ManagedProcessPortBindFailure {
    param([string]$ChildStderrLog)

    if (-not (Test-Path -LiteralPath $ChildStderrLog -PathType Leaf)) {
        return $false
    }

    $content = ""
    try {
        $content = (Get-Content -LiteralPath $ChildStderrLog -Encoding utf8 -Tail 120) -join [Environment]::NewLine
    } catch {
        return $false
    }

    return (
        $content -match "WinError 10048" -or
        $content -match "Errno 10048" -or
        $content -match "address already in use" -or
        $content -match "only one usage of each socket address" -or
        $content -match "通常每个套接字地址"
    )
}

function Stop-BackendProcessTree {
    param(
        [object]$BackendProcess,
        [object]$ListenerSnapshot
    )

    if ($null -ne $ListenerSnapshot -and $null -ne $ListenerSnapshot.listeners) {
        foreach ($listener in @($ListenerSnapshot.listeners)) {
            $processId = [int]$listener.process_id
            $commandLine = [string]$listener.command_line
            if ($processId -gt 0 -and ($commandLine -match "API\.app\.main:create_app" -or $commandLine -match "uvicorn")) {
                try {
                    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
                } catch {
                }
            }
        }
    }

    if ($null -ne $BackendProcess -and -not $BackendProcess.HasExited) {
        try {
            Stop-Process -Id $BackendProcess.Id -Force -ErrorAction SilentlyContinue
        } catch {
        }
    }
}

$script:backendProcessJobHandle = [IntPtr]::Zero
$script:backendProcessJobTypeLoaded = $false

function Ensure-BackendChildProcessJobType {
    if ($script:backendProcessJobTypeLoaded) {
        return
    }

    if ($null -ne ("FanBanBackendJobObject" -as [type])) {
        $script:backendProcessJobTypeLoaded = $true
        return
    }

    $source = @"
using System;
using System.Runtime.InteropServices;

public static class FanBanBackendJobObject {
    public const UInt32 JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;

    [StructLayout(LayoutKind.Sequential)]
    public struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
        public Int64 PerProcessUserTimeLimit;
        public Int64 PerJobUserTimeLimit;
        public UInt32 LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public UInt32 ActiveProcessLimit;
        public IntPtr Affinity;
        public UInt32 PriorityClass;
        public UInt32 SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct IO_COUNTERS {
        public UInt64 ReadOperationCount;
        public UInt64 WriteOperationCount;
        public UInt64 OtherOperationCount;
        public UInt64 ReadTransferCount;
        public UInt64 WriteTransferCount;
        public UInt64 OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr CreateJobObject(IntPtr lpJobAttributes, string lpName);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool SetInformationJobObject(
        IntPtr hJob,
        int JobObjectInfoClass,
        IntPtr lpJobObjectInfo,
        UInt32 cbJobObjectInfoLength
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool AssignProcessToJobObject(IntPtr hJob, IntPtr hProcess);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool CloseHandle(IntPtr hObject);
}
"@

    Add-Type -TypeDefinition $source -ErrorAction Stop
    $script:backendProcessJobTypeLoaded = $true
}

function New-BackendChildProcessJob {
    if ($script:backendProcessJobHandle -ne [IntPtr]::Zero) {
        return
    }

    Ensure-BackendChildProcessJobType
    $jobName = "FanBanBackend-{0}-{1}" -f $PID, $runStamp
    $handle = [FanBanBackendJobObject]::CreateJobObject([IntPtr]::Zero, $jobName)
    if ($handle -eq [IntPtr]::Zero) {
        $err = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        throw ("backend-job-object create failed: win32_error={0}" -f $err)
    }

    $basicLimitInformation = New-Object FanBanBackendJobObject+JOBOBJECT_BASIC_LIMIT_INFORMATION
    $basicLimitInformation.LimitFlags = [FanBanBackendJobObject]::JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    $info = New-Object FanBanBackendJobObject+JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    $info.BasicLimitInformation = $basicLimitInformation
    $size = [Runtime.InteropServices.Marshal]::SizeOf($info)
    $ptr = [Runtime.InteropServices.Marshal]::AllocHGlobal($size)
    try {
        [Runtime.InteropServices.Marshal]::StructureToPtr($info, $ptr, $false)
        $ok = [FanBanBackendJobObject]::SetInformationJobObject($handle, 9, $ptr, [UInt32]$size)
        if (-not $ok) {
            $err = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
            [FanBanBackendJobObject]::CloseHandle($handle) | Out-Null
            throw ("backend-job-object configure failed: win32_error={0}" -f $err)
        }
        $script:backendProcessJobHandle = $handle
    } finally {
        [Runtime.InteropServices.Marshal]::FreeHGlobal($ptr)
    }
}

function Register-BackendChildProcessForTaskStop {
    param([object]$BackendProcess)

    if ($null -eq $BackendProcess) {
        return
    }

    try {
        New-BackendChildProcessJob
        $ok = [FanBanBackendJobObject]::AssignProcessToJobObject(
            $script:backendProcessJobHandle,
            $BackendProcess.Handle
        )
        if ($ok) {
            ("backend-job-object: assigned_pid={0} kill_on_job_close=true" -f $BackendProcess.Id) |
                Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
        } else {
            $err = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
            throw ("backend-job-object assign failed pid={0} win32_error={1}" -f $BackendProcess.Id, $err)
        }
    } catch {
        ("backend-job-object-fatal: " + $_.Exception.Message) |
            Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
        try {
            if ($null -ne $BackendProcess -and -not $BackendProcess.HasExited) {
                Stop-Process -Id $BackendProcess.Id -Force -ErrorAction SilentlyContinue
            }
        } catch {
        }
        Close-BackendChildProcessJob
        throw
    }
}

function Close-BackendChildProcessJob {
    if ($script:backendProcessJobHandle -eq [IntPtr]::Zero) {
        return
    }

    [FanBanBackendJobObject]::CloseHandle($script:backendProcessJobHandle) | Out-Null
    $script:backendProcessJobHandle = [IntPtr]::Zero
}

Write-BackendLogHeader

try {
    $mutexResult = New-BackendSupervisorMutex
    if (-not [bool]$mutexResult.acquired) {
        Update-LatestBackendLogs
        return
    }

    $probeHost = Get-BackendProbeHost -HostValue $ListenHost
    $pingUrl = "http://{0}:{1}/api/system/ping" -f $probeHost, $Port
    $existingBackendDecision = Test-ExistingBackendBeforeLaunch `
        -PingUrl $pingUrl `
        -BackendPort $Port `
        -TimeoutSeconds $PingTimeoutSeconds
    if ([string]$existingBackendDecision.action -eq "exit") {
        Update-LatestBackendLogs
        return
    }

    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Python 运行环境不存在: $python"
    }

    if (Test-Path -LiteralPath $runtimeEnv -PathType Leaf) {
        . $runtimeEnv
    }

    $managedSpecPath = Join-Path $root "documents\__SPEC_NAME__"
    $managedRuntimeSpecPath = Join-Path $root "documents\__RUNTIME_SPEC_NAME__"
    $managedMechanismSpecPath = Join-Path $root "documents\__MECHANISM_SPEC_NAME__"
    $managedAiSpecPath = Join-Path $root "documents\AI\参数规范_AI.yaml"
    $managedAiGatewayConfigPath = Join-Path $root "documents\AI\ai_model_gateway.yaml"
    $managedCadScriptDir = Join-Path $root "backend-runtime\backend\src\cad\scripts"
    $managedDotNetBridgeDllPath = Join-Path $root "backend-runtime\backend\src\cad\dotnet\Module5CadBridge\bin\Release\net48\Module5CadBridge.dll"
    $managedCtbName = "__MANAGED_MONOCHROME_CTB_NAME__"

    Set-BackendRuntimeEnvironment `
        -SpecPath $managedSpecPath `
        -RuntimeSpecPath $managedRuntimeSpecPath `
        -MechanismSpecPath $managedMechanismSpecPath `
        -AiSpecPath $managedAiSpecPath `
        -AiGatewayConfigPath $managedAiGatewayConfigPath `
        -CadScriptDir $managedCadScriptDir `
        -DotNetBridgeDllPath $managedDotNetBridgeDllPath `
        -CtbName $managedCtbName

    $previousPythonNoUserSite = [Environment]::GetEnvironmentVariable("PYTHONNOUSERSITE", "Process")
    $previousPythonDontWriteBytecode = [Environment]::GetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "Process")
    $previousPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    $previousPythonHome = [Environment]::GetEnvironmentVariable("PYTHONHOME", "Process")

    Push-Location (Join-Path $root "backend-runtime")
    try {
        [Environment]::SetEnvironmentVariable("PYTHONNOUSERSITE", "1", "Process")
        [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "1", "Process")
        [Environment]::SetEnvironmentVariable("PYTHONPATH", $null, "Process")
        [Environment]::SetEnvironmentVariable("PYTHONHOME", $null, "Process")
        ("backend-start-cwd: " + (Get-Location).Path) | Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
        Test-BackendImportPreflight -PythonPath $python -BackendRuntimeRoot (Get-Location).Path
        "Starting backend supervisor..." | Out-File -LiteralPath $stdoutLog -Encoding utf8 -Append

        $apiArgs = @(
            "-X",
            "utf8",
            "-m",
            "uvicorn",
            "API.app.main:create_app",
            "--factory",
            "--host",
            $ListenHost,
            "--port",
            [string]$Port,
            "--workers",
            "1",
            "--proxy-headers",
            "--forwarded-allow-ips",
            "127.0.0.1"
        )
        $workerArgs = @(
            "-X",
            "utf8",
            "-m",
            "API.app.worker"
        )
        $apiCmdLine = ('"{0}" {1}' -f $python, ($apiArgs -join " "))
        $workerCmdLine = ('"{0}" {1}' -f $python, ($workerArgs -join " "))
        ("backend-command: " + $apiCmdLine) | Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
        ("backend-worker-command: " + $workerCmdLine) | Out-File -LiteralPath $stderrLog -Encoding utf8 -Append

        function Start-BackendManagedProcess {
            param(
                [string]$Label,
                [object[]]$ArgumentList,
                [int]$Attempt
            )

            $attemptStamp = "{0}-{1}-{2:D4}" -f $runStamp, $Label, $Attempt
            if ($Label -eq "api") {
                $childStdoutLog = Join-Path $logsDir ("api-stdout-{0}.log" -f $attemptStamp)
                $childStderrLog = Join-Path $logsDir ("api-stderr-{0}.log" -f $attemptStamp)
            } else {
                $childStdoutLog = Join-Path $logsDir ("worker-stdout-{0}.log" -f $attemptStamp)
                $childStderrLog = Join-Path $logsDir ("worker-stderr-{0}.log" -f $attemptStamp)
            }
            if ($Label -eq "api") {
                ("backend-supervisor: launching api attempt={0}" -f $Attempt) |
                    Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
            } else {
                ("backend-supervisor: launching worker attempt={0}" -f $Attempt) |
                    Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
            }
            if ($Label -eq "api") {
                ("backend-api-logs: stdout={0} stderr={1}" -f $childStdoutLog, $childStderrLog) |
                    Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
            } else {
                ("backend-worker-logs: stdout={0} stderr={1}" -f $childStdoutLog, $childStderrLog) |
                    Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
            }
            $childProcess = Start-Process `
                -FilePath $python `
                -ArgumentList $ArgumentList `
                -WorkingDirectory (Get-Location).Path `
                -WindowStyle Hidden `
                -PassThru `
                -RedirectStandardOutput $childStdoutLog `
                -RedirectStandardError $childStderrLog
            if ($Label -eq "api") {
                $apiProcess = $childProcess
                Register-BackendChildProcessForTaskStop -BackendProcess $apiProcess
            } else {
                $workerProcess = $childProcess
                Register-BackendChildProcessForTaskStop -BackendProcess $workerProcess
            }
            ("backend-supervisor: {0}_pid={1}" -f $Label, $childProcess.Id) |
                Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
            return [ordered]@{
                process = $childProcess
                stdout = $childStdoutLog
                stderr = $childStderrLog
            }
        }

        function Append-ManagedProcessLogs {
            param(
                [string]$Label,
                [string]$StdoutLog,
                [string]$ChildStderrLog,
                [string]$SupervisorStderrLog,
                [int]$MaxTailLines = 400
            )

            foreach ($entry in @(@("stdout", $StdoutLog), @("stderr", $ChildStderrLog))) {
                $streamLabel = [string]$entry[0]
                $path = [string]$entry[1]
                if (Test-Path -LiteralPath $path -PathType Leaf) {
                    $sourceFullPath = [System.IO.Path]::GetFullPath($path)
                    $targetFullPath = [System.IO.Path]::GetFullPath($SupervisorStderrLog)
                    if ($sourceFullPath -eq $targetFullPath) {
                        ("----- {0}-{1}: skipped self-reference {2} -----" -f $Label, $streamLabel, $path) |
                            Out-File -LiteralPath $SupervisorStderrLog -Encoding utf8 -Append
                        continue
                    }
                    ("----- {0}-{1}: {2} -----" -f $Label, $streamLabel, $path) |
                        Out-File -LiteralPath $SupervisorStderrLog -Encoding utf8 -Append
                    Get-Content -LiteralPath $path -Encoding utf8 -Tail $MaxTailLines |
                        Out-File -LiteralPath $SupervisorStderrLog -Encoding utf8 -Append
                } else {
                    ("----- {0}-{1}: missing {2} -----" -f $Label, $streamLabel, $path) |
                        Out-File -LiteralPath $SupervisorStderrLog -Encoding utf8 -Append
                }
            }
        }

        function Stop-ManagedProcess {
            param([object]$ManagedProcess)

            if ($null -ne $ManagedProcess -and $null -ne $ManagedProcess.process -and -not $ManagedProcess.process.HasExited) {
                try {
                    Stop-Process -Id $ManagedProcess.process.Id -Force -ErrorAction SilentlyContinue
                } catch {
                }
            }
        }

        $apiAttempt = 0
        $workerAttempt = 0
        $apiChild = $null
        $workerChild = $null
        $failureCount = 0
        $startupDeadline = Get-Date
        $apiReadyForWorker = $false
        while (-not $script:stopSupervisor) {
            if ($null -eq $apiChild) {
                $apiAttempt += 1
                $apiChild = Start-BackendManagedProcess -Label "api" -ArgumentList $apiArgs -Attempt $apiAttempt
                $startupDeadline = (Get-Date).AddSeconds($StartupGraceSeconds)
                $failureCount = 0
                $apiReadyForWorker = $false
            }

            if ($script:stopSupervisor) {
                $listenerSnapshot = Get-BackendListenerSnapshot -BackendPort $Port
                if ($null -ne $apiChild) {
                    Stop-BackendProcessTree -BackendProcess $apiChild.process -ListenerSnapshot $listenerSnapshot
                }
                if ($null -ne $workerChild) {
                    Stop-ManagedProcess -ManagedProcess $workerChild
                }
                break
            }

            Start-Sleep -Seconds $SupervisorIntervalSeconds

            if ($null -ne $workerChild -and $workerChild.process.HasExited) {
                $workerChild.process.Refresh()
                $workerExitCode = $workerChild.process.ExitCode
                $workerRestartReason = "worker_process_exited"
                Append-ManagedProcessLogs `
                    -Label "worker" `
                    -StdoutLog $workerChild.stdout `
                    -ChildStderrLog $workerChild.stderr `
                    -SupervisorStderrLog $stderrLog
                ("backend-supervisor: restarting worker reason={0} exit_code={1} delay_seconds={2}" -f `
                    $workerRestartReason,
                    $workerExitCode,
                    $RestartDelaySeconds) |
                    Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
                $workerChild = $null
                Start-Sleep -Seconds $RestartDelaySeconds
                continue
            }

            if ($null -ne $apiChild -and $apiChild.process.HasExited) {
                $apiChild.process.Refresh()
                $script:backendExitCode = $apiChild.process.ExitCode
                $apiRestartReason = "api_process_exited"
                $apiReadyForWorker = $false
                Append-ManagedProcessLogs `
                    -Label "api" `
                    -StdoutLog $apiChild.stdout `
                    -ChildStderrLog $apiChild.stderr `
                    -SupervisorStderrLog $stderrLog
                if (Test-ManagedProcessPortBindFailure -ChildStderrLog $apiChild.stderr) {
                    ("backend-supervisor: api_port_bind_failed action=fail_without_retry exit_code={0}" -f $script:backendExitCode) |
                        Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
                    Update-LatestBackendLogs
                    return
                }
                ("backend-supervisor: restarting api reason={0} exit_code={1} delay_seconds={2}" -f `
                    $apiRestartReason,
                    $script:backendExitCode,
                    $RestartDelaySeconds) |
                    Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
                $apiChild = $null
                Start-Sleep -Seconds $RestartDelaySeconds
                continue
            }

            $pingResult = Test-BackendPing -PingUrl $pingUrl -TimeoutSeconds $PingTimeoutSeconds
            if ([bool]$pingResult.ok) {
                if ($failureCount -gt 0) {
                    ("backend-supervisor: api_ping_recovered_after_failures count={0} ping_elapsed_ms={1}" -f `
                        $failureCount,
                        $pingResult.elapsed_ms) |
                        Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
                }
                $failureCount = 0
                $apiReadyForWorker = $true
                if ($apiReadyForWorker -and $null -eq $workerChild) {
                    $workerAttempt += 1
                    $workerChild = Start-BackendManagedProcess -Label "worker" -ArgumentList $workerArgs -Attempt $workerAttempt
                }
                continue
            }
            $apiReadyForWorker = $false
            if ((Get-Date) -lt $startupDeadline) {
                continue
            }

            $listenerSnapshot = Get-BackendListenerSnapshot -BackendPort $Port
            $failureCount += 1
            $pingElapsedMs = if ($null -ne $pingResult.elapsed_ms) { [int64]$pingResult.elapsed_ms } else { -1 }
            $pingError = if ($null -ne $pingResult.error) { [string]$pingResult.error } else { "" }
            $listenerAliveThreshold = [Math]::Max($SupervisorFailureThreshold, $ListenerAliveFailureThreshold)
            if ($listenerSnapshot.status -eq "pass" -and [int]$listenerSnapshot.count -gt 0) {
                ("backend-supervisor: api_ping_failed_listener_alive count={0}/{1} listener_status={2} listener_count={3} ping_elapsed_ms={4} ping_error={5}" -f `
                    $failureCount,
                    $listenerAliveThreshold,
                    $listenerSnapshot.status,
                    $listenerSnapshot.count,
                    $pingElapsedMs,
                    $pingError) |
                    Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
                if ($failureCount -lt $listenerAliveThreshold) {
                    continue
                }
                ($listenerSnapshot | ConvertTo-Json -Depth 8 -Compress) |
                    Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
                Stop-BackendProcessTree -BackendProcess $apiChild.process -ListenerSnapshot $listenerSnapshot
                try {
                    $apiChild.process.WaitForExit(5000) | Out-Null
                } catch {
                }
                $apiRestartReason = "api_ping_failed_listener_alive"
            } else {
                ("backend-supervisor: api_ping_failed_no_listener count={0}/{1} listener_status={2} listener_count={3} ping_elapsed_ms={4} ping_error={5}" -f `
                    $failureCount,
                    $SupervisorFailureThreshold,
                    $listenerSnapshot.status,
                    $listenerSnapshot.count,
                    $pingElapsedMs,
                    $pingError) |
                    Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
                if ($failureCount -lt $SupervisorFailureThreshold) {
                    continue
                }
                ($listenerSnapshot | ConvertTo-Json -Depth 8 -Compress) |
                    Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
                Stop-BackendProcessTree -BackendProcess $apiChild.process -ListenerSnapshot $listenerSnapshot
                try {
                    $apiChild.process.WaitForExit(5000) | Out-Null
                } catch {
                }
                $apiRestartReason = "api_ping_failed_no_listener"
            }

            $apiChild.process.Refresh()
            $script:backendExitCode = $apiChild.process.ExitCode
            Append-ManagedProcessLogs `
                -Label "api" `
                -StdoutLog $apiChild.stdout `
                -ChildStderrLog $apiChild.stderr `
                -SupervisorStderrLog $stderrLog
            ("backend-supervisor: restarting api reason={0} exit_code={1} delay_seconds={2}" -f `
                $apiRestartReason,
                $script:backendExitCode,
                $RestartDelaySeconds) |
                Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
            $apiChild = $null
            Start-Sleep -Seconds $RestartDelaySeconds
        }
    } finally {
        [Environment]::SetEnvironmentVariable("PYTHONNOUSERSITE", $previousPythonNoUserSite, "Process")
        [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", $previousPythonDontWriteBytecode, "Process")
        [Environment]::SetEnvironmentVariable("PYTHONPATH", $previousPythonPath, "Process")
        [Environment]::SetEnvironmentVariable("PYTHONHOME", $previousPythonHome, "Process")
        Close-BackendChildProcessJob
        Pop-Location
        Update-LatestBackendLogs
    }
} catch {
    ("FanBanBackend startup/runtime failure: " + $_.Exception.Message) | Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
    ($_ | Out-String) | Out-File -LiteralPath $stderrLog -Encoding utf8 -Append
    Update-LatestBackendLogs
    throw
} finally {
    Close-BackendSupervisorMutex
}
'''
    start_backend = (
        start_backend
        .replace("__DEFAULT_FRONTEND_API_PORT__", str(int(deployment.default_frontend_api_port)))
        .replace("__SPEC_NAME__", deployment.spec_name)
        .replace("__RUNTIME_SPEC_NAME__", deployment.runtime_spec_name)
        .replace("__MECHANISM_SPEC_NAME__", deployment.mechanism_spec_name)
        .replace("__MANAGED_MONOCHROME_CTB_NAME__", deployment.managed_monochrome_ctb_name)
    )
    _write_text(output_root / "scripts" / "start_backend.ps1", start_backend)

    init_storage = r'''$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$storage = Join-Path $root "storage"

$dirs = @(
    "jobs",
    "groups",
    "runtime",
    "runtime\cad-slots",
    "ai\skills"
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
$aiSpecPath = Join-Path $root "documents\AI\参数规范_AI.yaml"
if (Test-Path -LiteralPath $aiSpecPath -PathType Leaf) {
    $escapedAiSpecPath = $aiSpecPath.Replace("'", "''")
    $lines += ("Set-Item -Path 'Env:FANBAN_AI_SPEC_PATH' -Value '{0}'" -f $escapedAiSpecPath)
}
$aiGatewayConfigPath = Join-Path $root "documents\AI\ai_model_gateway.yaml"
if (Test-Path -LiteralPath $aiGatewayConfigPath -PathType Leaf) {
    $escapedAiGatewayConfigPath = $aiGatewayConfigPath.Replace("'", "''")
    $lines += ("Set-Item -Path 'Env:FANBAN_AI_GATEWAY_CONFIG_PATH' -Value '{0}'" -f $escapedAiGatewayConfigPath)
    $lines += "Set-Item -Path 'Env:FANBAN_AI_GATEWAY_PROFILE' -Value 'terminal_cnpe_intranet_qwen_fast'"
}
$ansysSkillRoot = Join-Path $root "storage\ai\skills\ansys-mapdl-18-2"
if (Test-Path -LiteralPath $ansysSkillRoot -PathType Container) {
    $escapedAnsysSkillRoot = $ansysSkillRoot.Replace("'", "''")
    $lines += ("Set-Item -Path 'Env:FANBAN_ANSYS_MAPDL_SKILL_ROOT' -Value '{0}'" -f $escapedAnsysSkillRoot)
}
$buildingStandardsSkillRoot = Join-Path $root "storage\ai\skills\building-structure-standards"
if (Test-Path -LiteralPath $buildingStandardsSkillRoot -PathType Container) {
    $escapedBuildingStandardsSkillRoot = $buildingStandardsSkillRoot.Replace("'", "''")
    $lines += ("Set-Item -Path 'Env:FANBAN_BUILDING_STANDARDS_SKILL_ROOT' -Value '{0}'" -f $escapedBuildingStandardsSkillRoot)
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
$probeArgs = @{
    OutJson = $probeJson
    RepoRoot = $root
    Port = $Port
    StorageRoot = $StorageRoot
    OfficeProbeMode = "deep"
}

Write-Host "开始执行深度环境检查..."
& (Join-Path $PSScriptRoot "probe_target_env.ps1") @probeArgs
Write-Host ("深度环境检查完成，输出文件: " + $probeJson)
'''
    _write_text(output_root / "scripts" / "deep_check_terminal.ps1", deep_check_terminal)

    check_health = r'''param(
    [string]$Url = "http://127.0.0.1:8000/api/system/health",
    [string]$PingUrl = "http://127.0.0.1:8000/api/system/ping",
    [int]$ApiPort = __DEFAULT_FRONTEND_API_PORT__,
    [string]$FrontendUrl = "",
    [string]$FrontendApiPingUrl = "",
    [string]$IisSiteName = "FanBanTerminal",
    [string]$IisAppPoolName = "FanBanTerminalAppPool",
    [int]$HttpTimeoutSec = 5,
    [ValidateSet("full", "deep")]
    [string]$Mode = "full"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$probeScript = Join-Path $PSScriptRoot "probe_target_env.ps1"
$iisProxyScript = Join-Path $root "install\check_iis_proxy_prereqs.ps1"
$logsDir = Join-Path $root "logs"
$deepProbeJson = Join-Path $logsDir "probe_target_env.deep.json"
$summaryJson = Join-Path $logsDir "check_health.summary.json"
$fullJson = Join-Path $logsDir "check_health.full.json"

New-Item -ItemType Directory -Path $logsDir -Force | Out-Null

function Get-BackendListenerSnapshot {
    param([int]$BackendPort)

    try {
        $connections = @(Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction Stop)
    } catch {
        return [ordered]@{
            status = "error"
            error = $_.Exception.Message
            count = 0
            listeners = @()
        }
    }

    $listeners = @()
    foreach ($connection in $connections) {
        $processId = [int]$connection.OwningProcess
        $processName = ""
        $commandLine = ""
        try {
            $processInfo = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $processId) -ErrorAction Stop
            $processName = [string]$processInfo.Name
            $commandLine = [string]$processInfo.CommandLine
        } catch {
            $processName = ""
            $commandLine = ""
        }

        $listeners += [ordered]@{
            local_address = [string]$connection.LocalAddress
            local_port = [int]$connection.LocalPort
            process_id = $processId
            process_name = $processName
            command_line = $commandLine
        }
    }

    return [ordered]@{
        status = if ($listeners.Count -gt 0) { "pass" } else { "fail" }
        error = ""
        count = $listeners.Count
        listeners = $listeners
    }
}

function Get-BackendFailureClassification {
    param(
        [string]$PingStatus,
        [string]$TaskState,
        [object]$ListenerSnapshot
    )

    if ($PingStatus -eq "pass") {
        return "ok"
    }

    $listenerCount = 0
    if ($null -ne $ListenerSnapshot -and $null -ne $ListenerSnapshot.count) {
        $listenerCount = [int]$ListenerSnapshot.count
    }

    if ($listenerCount -eq 0) {
        if ($TaskState -eq "Running") {
            return "task_running_but_no_backend_listener"
        }
        return "backend_not_listening"
    }

    return "listener_present_but_api_unreachable"
}

function Convert-IisTimeValueToSeconds {
    param([object]$Value)

    if ($null -eq $Value) {
        return $null
    }
    if ($Value -is [TimeSpan]) {
        return [int][Math]::Round($Value.TotalSeconds)
    }

    try {
        $valueProperty = $Value.PSObject.Properties["Value"]
        if ($null -ne $valueProperty -and $null -ne $valueProperty.Value) {
            return Convert-IisTimeValueToSeconds -Value $valueProperty.Value
        }
    } catch {
    }

    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text)) {
        return $null
    }

    $parsedTimeSpan = [TimeSpan]::Zero
    if ([TimeSpan]::TryParse($text, [ref]$parsedTimeSpan)) {
        return [int][Math]::Round($parsedTimeSpan.TotalSeconds)
    }

    $parsedSeconds = 0
    if ([int]::TryParse($text, [ref]$parsedSeconds)) {
        return $parsedSeconds
    }

    return $null
}

function Get-FrontendProbeUrlFromBinding {
    param([object[]]$Bindings)

    foreach ($binding in $Bindings) {
        $protocol = [string]$binding.protocol
        if ($protocol -ne "http") {
            continue
        }

        $bindingInformation = [string]$binding.bindingInformation
        $parts = $bindingInformation.Split(":")
        if ($parts.Count -lt 2) {
            continue
        }

        $portText = [string]$parts[1]
        if ([string]::IsNullOrWhiteSpace($portText)) {
            continue
        }

        $hostHeader = ""
        if ($parts.Count -ge 3) {
            $hostHeader = [string]$parts[2]
        }
        $hostForProbe = if ([string]::IsNullOrWhiteSpace($hostHeader)) { "127.0.0.1" } else { $hostHeader }
        $portSuffix = if ($portText -eq "80") { "" } else { ":" + $portText }
        return ("http://{0}{1}/" -f $hostForProbe, $portSuffix)
    }

    return ""
}

function Join-FrontendApiPingUrl {
    param([string]$RootUrl)

    if ([string]::IsNullOrWhiteSpace($RootUrl)) {
        return ""
    }

    return ($RootUrl.TrimEnd("/") + "/api/system/ping")
}

function Invoke-FrontendHttpProbe {
    param(
        [string]$Uri,
        [bool]$ExpectJsonOk = $false,
        [int]$TimeoutSec = 5
    )

    if ([string]::IsNullOrWhiteSpace($Uri)) {
        return [ordered]@{
            status = "fail"
            url = ""
            status_code = $null
            json_ok = $false
            error = "frontend probe url is empty"
        }
    }

    $effectiveTimeoutSec = [Math]::Max(1, $TimeoutSec)
    $job = Start-Job -ScriptBlock {
        param(
            [string]$TargetUri,
            [bool]$TargetExpectJsonOk,
            [int]$TargetTimeoutSec
        )

        try {
            if ($TargetExpectJsonOk) {
                $response = Invoke-RestMethod -Uri $TargetUri -Method Get -TimeoutSec $TargetTimeoutSec
                $jsonOk = $false
                if ($null -ne $response -and $null -ne $response.PSObject.Properties["ok"]) {
                    $jsonOk = [bool]$response.ok
                }
                return [ordered]@{
                    status = if ($jsonOk) { "pass" } else { "fail" }
                    url = $TargetUri
                    status_code = $null
                    json_ok = $jsonOk
                    error = if ($jsonOk) { "" } else { "response did not contain ok=true" }
                }
            }

            $response = Invoke-WebRequest -Uri $TargetUri -UseBasicParsing -Method Get -TimeoutSec $TargetTimeoutSec
            return [ordered]@{
                status = if ([int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 400) { "pass" } else { "fail" }
                url = $TargetUri
                status_code = [int]$response.StatusCode
                json_ok = $false
                error = ""
            }
        } catch {
            $statusCode = $null
            try {
                if ($null -ne $_.Exception.Response) {
                    $statusCode = [int]$_.Exception.Response.StatusCode
                }
            } catch {
                $statusCode = $null
            }
            return [ordered]@{
                status = "fail"
                url = $TargetUri
                status_code = $statusCode
                json_ok = $false
                error = $_.Exception.Message
            }
        }
    } -ArgumentList $Uri, $ExpectJsonOk, $effectiveTimeoutSec

    $jobTimeoutSec = [Math]::Max($effectiveTimeoutSec + 3, 8)
    if (-not (Wait-Job -Job $job -Timeout $jobTimeoutSec)) {
        Stop-Job -Job $job -ErrorAction SilentlyContinue | Out-Null
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue | Out-Null
        return [ordered]@{
            status = "fail"
            url = $Uri
            status_code = $null
            json_ok = $false
            error = ("probe timed out after {0} seconds" -f $jobTimeoutSec)
        }
    }

    $result = Receive-Job -Job $job
    Remove-Job -Job $job -Force -ErrorAction SilentlyContinue | Out-Null
    if ($null -eq $result) {
        return [ordered]@{
            status = "fail"
            url = $Uri
            status_code = $null
            json_ok = $false
            error = "probe returned no result"
        }
    }

    return $result
}

function Get-IisFrontendSnapshot {
    param(
        [string]$SiteName,
        [string]$AppPoolName
    )

    $result = [ordered]@{
        status = "fail"
        error = ""
        problems = @()
        site_name = $SiteName
        app_pool_name = $AppPoolName
        site_state = ""
        site_physical_path = ""
        site_physical_path_exists = $false
        site_server_auto_start = $null
        app_pool_state = ""
        app_pool_auto_start = $null
        app_pool_start_mode = ""
        app_pool_idle_timeout_seconds = $null
        app_pool_periodic_restart_seconds = $null
        bindings = @()
        derived_frontend_url = ""
    }

    try {
        Import-Module WebAdministration -ErrorAction Stop
        $site = Get-Website -Name $SiteName -ErrorAction Stop
        $bindings = @(Get-WebBinding -Name $SiteName -Protocol http -ErrorAction SilentlyContinue)
        $appPoolState = Get-WebAppPoolState -Name $AppPoolName -ErrorAction Stop
        $appPool = Get-Item ("IIS:\AppPools\{0}" -f $AppPoolName) -ErrorAction Stop

        $sitePhysicalPath = [Environment]::ExpandEnvironmentVariables([string]$site.PhysicalPath)
        $siteServerAutoStart = $null
        try {
            if ($null -ne $site.serverAutoStart) {
                $siteServerAutoStart = [bool]$site.serverAutoStart
            }
        } catch {
            $siteServerAutoStart = $null
        }

        $appPoolAutoStart = $null
        try {
            if ($null -ne $appPool.autoStart) {
                $appPoolAutoStart = [bool]$appPool.autoStart
            }
        } catch {
            $appPoolAutoStart = $null
        }
        $idleTimeoutSeconds = Convert-IisTimeValueToSeconds -Value $appPool.processModel.idleTimeout
        $periodicRestartSeconds = Convert-IisTimeValueToSeconds -Value $appPool.recycling.periodicRestart.time

        $bindingDetails = @()
        foreach ($binding in $bindings) {
            $bindingDetails += [ordered]@{
                protocol = [string]$binding.protocol
                binding_information = [string]$binding.bindingInformation
            }
        }

        $problems = @()
        if ([string]$site.State -ne "Started") {
            $problems += ("IIS site state is " + [string]$site.State + ", expected Started")
        }
        if ($siteServerAutoStart -eq $false) {
            $problems += "IIS site serverAutoStart is false"
        }
        if (-not (Test-Path -LiteralPath $sitePhysicalPath -PathType Container)) {
            $problems += ("IIS site physical path does not exist: " + $sitePhysicalPath)
        }
        if ([string]$appPoolState.Value -ne "Started") {
            $problems += ("AppPool state is " + [string]$appPoolState.Value + ", expected Started")
        }
        if ($appPoolAutoStart -ne $true) {
            $problems += "AppPool autoStart is not true"
        }
        if ([string]$appPool.startMode -ne "AlwaysRunning") {
            $problems += ("AppPool startMode is " + [string]$appPool.startMode + ", expected AlwaysRunning")
        }
        if ($null -ne $idleTimeoutSeconds -and [int]$idleTimeoutSeconds -ne 0) {
            $problems += ("AppPool idleTimeout is " + $idleTimeoutSeconds + " seconds, expected 0")
        }
        if ($null -eq $idleTimeoutSeconds) {
            $problems += "AppPool idleTimeout could not be parsed"
        }
        if ($null -ne $periodicRestartSeconds -and [int]$periodicRestartSeconds -ne 0) {
            $problems += ("AppPool periodic restart is " + $periodicRestartSeconds + " seconds, expected 0")
        }
        if ($null -eq $periodicRestartSeconds) {
            $problems += "AppPool periodic restart could not be parsed"
        }

        $result.status = if ($problems.Count -eq 0) { "pass" } else { "fail" }
        $result.problems = $problems
        $result.site_state = [string]$site.State
        $result.site_physical_path = $sitePhysicalPath
        $result.site_physical_path_exists = (Test-Path -LiteralPath $sitePhysicalPath -PathType Container)
        $result.site_server_auto_start = $siteServerAutoStart
        $result.app_pool_state = [string]$appPoolState.Value
        $result.app_pool_auto_start = $appPoolAutoStart
        $result.app_pool_start_mode = [string]$appPool.startMode
        $result.app_pool_idle_timeout_seconds = $idleTimeoutSeconds
        $result.app_pool_periodic_restart_seconds = $periodicRestartSeconds
        $result.bindings = $bindingDetails
        $result.derived_frontend_url = Get-FrontendProbeUrlFromBinding -Bindings $bindings
    } catch {
        $result.status = "fail"
        $result.error = $_.Exception.Message
        $result.problems = @($_.Exception.Message)
    }

    return $result
}

function Convert-FirstJsonObjectFromText {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return $null
    }

    $start = $Text.IndexOf("{")
    $end = $Text.LastIndexOf("}")
    if ($start -lt 0 -or $end -lt $start) {
        return $null
    }

    $jsonText = $Text.Substring($start, $end - $start + 1)
    try {
        return ($jsonText | ConvertFrom-Json)
    } catch {
        return $null
    }
}

$deepProbe = $null
$selectedProbe = $null
$selectedProbeJson = ""
$proxyOutput = ""
$proxyStatus = "skip"
$proxyError = ""
$proxyDetails = $null
$proxyTimeoutStatus = "skip"
$proxyTimeoutSeconds = $null
$proxyMinimumTimeoutSeconds = 600
$apiPingStatus = "fail"
$apiPingError = ""
$apiPingResponse = $null
$apiHealthStatus = "fail"
$apiHealthError = ""
$apiHealthResponse = $null
$taskStatus = "skip"
$taskSettingsStatus = "skip"
$taskEventStatus = "skip"
$taskEventError = ""
$taskDetails = [ordered]@{}
$recentTaskEvents = @()
$backendListener = [ordered]@{
    status = "skip"
    error = ""
    count = 0
    listeners = @()
}
$backendListenerStatus = "skip"
$backendFailureClassification = "unknown"
$iisFrontend = [ordered]@{
    status = "skip"
    error = ""
    problems = @()
    derived_frontend_url = ""
}
$frontendAppPoolStatus = "skip"
$frontendRootProbeUrl = ""
$frontendApiProbeUrl = ""
$frontendHttpProbe = [ordered]@{
    status = "skip"
    url = ""
    error = ""
}
$frontendApiProxyProbe = [ordered]@{
    status = "skip"
    url = ""
    error = ""
}
$frontendHttpStatus = "skip"
$frontendApiProxyStatus = "skip"

if ($Mode -eq "deep" -and (Test-Path -LiteralPath $probeScript -PathType Leaf)) {
    & $probeScript -OutJson $deepProbeJson -RepoRoot $root -OfficeProbeMode deep
    $deepProbe = Get-Content -LiteralPath $deepProbeJson -Raw | ConvertFrom-Json
    $selectedProbe = $deepProbe
    $selectedProbeJson = $deepProbeJson
}

if (Test-Path -LiteralPath $iisProxyScript -PathType Leaf) {
    try {
        $proxyOutput = (& $iisProxyScript 2>&1 | Out-String).Trim()
        $proxyDetails = Convert-FirstJsonObjectFromText -Text $proxyOutput
        if ($null -ne $proxyDetails -and $null -ne $proxyDetails.arr) {
            if ($null -ne $proxyDetails.arr.timeout_status) {
                $proxyTimeoutStatus = [string]$proxyDetails.arr.timeout_status
            }
            if ($null -ne $proxyDetails.arr.timeout_seconds) {
                $proxyTimeoutSeconds = [int]$proxyDetails.arr.timeout_seconds
            }
            if ($null -ne $proxyDetails.arr.minimum_timeout_seconds) {
                $proxyMinimumTimeoutSeconds = [int]$proxyDetails.arr.minimum_timeout_seconds
            }
        }

        $proxyMissing = ($proxyOutput -match '"missing"' -or $proxyOutput -match '未检测到')
        $proxyTimeoutUnsafe = ($proxyTimeoutStatus -eq "warn" -or $proxyTimeoutStatus -eq "unknown")
        if ($proxyMissing -or $proxyTimeoutUnsafe) {
            $proxyStatus = "warn"
        } else {
            $proxyStatus = "pass"
        }
    } catch {
        $proxyStatus = "fail"
        $proxyError = $_.Exception.Message
    }
}

try {
    $task = Get-ScheduledTask -TaskName "FanBanBackend" -ErrorAction Stop
    $taskInfo = Get-ScheduledTaskInfo -TaskName "FanBanBackend" -ErrorAction Stop
    $lastTaskResultInt64 = [int64]$taskInfo.LastTaskResult
    $lastTaskResultUnsigned = if ($lastTaskResultInt64 -lt 0) {
        [uint64]($lastTaskResultInt64 + 4294967296)
    } else {
        [uint64]$lastTaskResultInt64
    }
    $lastTaskResultHex = "0x{0:X8}" -f ($lastTaskResultUnsigned -band 0xffffffff)
    $executionTimeLimit = [string]$task.Settings.ExecutionTimeLimit
    $restartCount = [int]$task.Settings.RestartCount
    $restartInterval = if ($null -ne $task.Settings.RestartInterval) { [string]$task.Settings.RestartInterval } else { "" }
    $multipleInstances = [string]$task.Settings.MultipleInstances
    $stopIfGoingOnBatteries = [bool]$task.Settings.StopIfGoingOnBatteries
    $executionTimeLimitUnlimited = ($executionTimeLimit -eq "" -or $executionTimeLimit -eq "PT0S" -or $executionTimeLimit -eq "P0D")
    $taskSettingsProblems = @()
    if (-not $executionTimeLimitUnlimited) {
        $taskSettingsProblems += ("ExecutionTimeLimit is " + $executionTimeLimit + ", expected PT0S/unlimited")
    }
    if ($restartCount -lt 1) {
        $taskSettingsProblems += ("RestartCount is " + $restartCount + ", expected >= 1")
    }
    $taskSettingsStatus = if ($taskSettingsProblems.Count -eq 0) { "pass" } else { "fail" }
    $taskStatus = "pass"
    $taskDetails = [ordered]@{
        state = [string]$task.State
        last_run_time = if ($taskInfo.LastRunTime) { [string]$taskInfo.LastRunTime } else { "" }
        last_task_result = $lastTaskResultInt64
        last_task_result_hex = $lastTaskResultHex
        last_task_result_ok = ($lastTaskResultInt64 -eq 0)
        next_run_time = if ($taskInfo.NextRunTime) { [string]$taskInfo.NextRunTime } else { "" }
        settings = [ordered]@{
            status = $taskSettingsStatus
            problems = $taskSettingsProblems
            execution_time_limit = $executionTimeLimit
            execution_time_limit_unlimited = $executionTimeLimitUnlimited
            restart_count = $restartCount
            restart_interval = $restartInterval
            multiple_instances = $multipleInstances
            stop_if_going_on_batteries = $stopIfGoingOnBatteries
        }
    }
} catch {
    $taskStatus = "fail"
    $taskDetails = [ordered]@{
        error = $_.Exception.Message
    }
}

try {
    $recentTaskEvents = @(
        Get-WinEvent -LogName "Microsoft-Windows-TaskScheduler/Operational" -MaxEvents 200 -ErrorAction Stop |
            Where-Object { $_.Message -match "\\FanBanBackend|FanBanBackend" } |
            Select-Object -First 12 `
                @{Name = "time_created"; Expression = { if ($_.TimeCreated) { $_.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss") } else { "" } } },
                Id,
                LevelDisplayName,
                ProviderName,
                Message
    )
    $taskEventStatus = "pass"
} catch {
    $taskEventStatus = "warn"
    $taskEventError = $_.Exception.Message
}

try {
    $apiPingResponse = Invoke-RestMethod -Uri $PingUrl -Method Get -TimeoutSec $HttpTimeoutSec
    $apiPingStatus = "pass"
} catch {
    $apiPingStatus = "fail"
    $apiPingError = $_.Exception.Message
}

try {
    $apiHealthResponse = Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec $HttpTimeoutSec
    $apiHealthStatus = "pass"
} catch {
    $apiHealthStatus = "fail"
    $apiHealthError = $_.Exception.Message
}

$backendListener = Get-BackendListenerSnapshot -BackendPort $ApiPort
$backendListenerStatus = [string]$backendListener.status
$taskStateForDiagnosis = if ($taskDetails.Contains("state")) { [string]$taskDetails.state } else { "" }
$backendFailureClassification = Get-BackendFailureClassification `
    -PingStatus $apiPingStatus `
    -TaskState $taskStateForDiagnosis `
    -ListenerSnapshot $backendListener

$iisFrontend = Get-IisFrontendSnapshot -SiteName $IisSiteName -AppPoolName $IisAppPoolName
$frontendAppPoolStatus = [string]$iisFrontend.status
$frontendRootProbeUrl = if ([string]::IsNullOrWhiteSpace($FrontendUrl)) {
    [string]$iisFrontend.derived_frontend_url
} else {
    $FrontendUrl
}
$frontendApiProbeUrl = if ([string]::IsNullOrWhiteSpace($FrontendApiPingUrl)) {
    Join-FrontendApiPingUrl -RootUrl $frontendRootProbeUrl
} else {
    $FrontendApiPingUrl
}
$frontendHttpProbe = Invoke-FrontendHttpProbe -Uri $frontendRootProbeUrl -ExpectJsonOk:$false -TimeoutSec $HttpTimeoutSec
$frontendApiProxyProbe = Invoke-FrontendHttpProbe -Uri $frontendApiProbeUrl -ExpectJsonOk:$true -TimeoutSec $HttpTimeoutSec
$frontendHttpStatus = [string]$frontendHttpProbe.status
$frontendApiProxyStatus = [string]$frontendApiProxyProbe.status

$blockingIssues = @()
$warnings = @()
if ($null -ne $selectedProbe) {
    $blockingIssues = @($selectedProbe.blocking_issues)
    $warnings = @($selectedProbe.warnings)
}

$overallStatus = "pass"
$probeRequiredForOverall = ($Mode -eq "deep")
if (($probeRequiredForOverall -and $null -eq $selectedProbe) -or $blockingIssues.Count -gt 0 -or $apiPingStatus -ne "pass" -or $apiHealthStatus -ne "pass" -or $taskStatus -ne "pass" -or $taskSettingsStatus -eq "fail" -or $frontendAppPoolStatus -ne "pass" -or $frontendHttpStatus -ne "pass" -or $frontendApiProxyStatus -ne "pass") {
    $overallStatus = "fail"
} elseif ($proxyStatus -eq "warn") {
    $overallStatus = "warn"
}

$reportedDeepProbeJson = if ($Mode -eq "deep") { $deepProbeJson } else { "" }

$summary = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    mode = $Mode
    overall_status = $overallStatus
    selected_probe_json = $selectedProbeJson
    blocking_issue_count = $blockingIssues.Count
    warning_count = $warnings.Count
    api_status = $apiPingStatus
    api_url = $PingUrl
    api_ping_status = $apiPingStatus
    api_ping_url = $PingUrl
    api_health_status = $apiHealthStatus
    api_health_url = $Url
    task_status = $taskStatus
    task_settings_status = $taskSettingsStatus
    task_event_status = $taskEventStatus
    backend_listener_status = $backendListenerStatus
    backend_listener_count = $backendListener.count
    backend_failure_classification = $backendFailureClassification
    frontend_app_pool_status = $frontendAppPoolStatus
    frontend_http_status = $frontendHttpStatus
    frontend_api_proxy_status = $frontendApiProxyStatus
    frontend_url = $frontendRootProbeUrl
    frontend_api_ping_url = $frontendApiProbeUrl
    proxy_status = $proxyStatus
    proxy_timeout_status = $proxyTimeoutStatus
    proxy_timeout_seconds = $proxyTimeoutSeconds
    proxy_minimum_timeout_seconds = $proxyMinimumTimeoutSeconds
    summary_json = $summaryJson
    full_json = $fullJson
}

$fullReport = [ordered]@{
    summary = $summary
    probe = [ordered]@{
        quick_json = ""
        deep_json = $reportedDeepProbeJson
        selected = $selectedProbe
    }
    scheduled_task = $taskDetails
    scheduled_task_events = [ordered]@{
        status = $taskEventStatus
        error = $taskEventError
        recent_task_events = $recentTaskEvents
    }
    backend_runtime = [ordered]@{
        status = if ($apiPingStatus -eq "pass" -and $backendListenerStatus -eq "pass") { "pass" } else { "fail" }
        failure_classification = $backendFailureClassification
    }
    backend_listener = $backendListener
    frontend_iis = $iisFrontend
    frontend = [ordered]@{
        app_pool_status = $frontendAppPoolStatus
        http = $frontendHttpProbe
        api_proxy = $frontendApiProxyProbe
    }
    api = [ordered]@{
        status = $apiPingStatus
        url = $PingUrl
        error = $apiPingError
        response = $apiPingResponse
        ping = [ordered]@{
            status = $apiPingStatus
            url = $PingUrl
            error = $apiPingError
            response = $apiPingResponse
        }
        health = [ordered]@{
            status = $apiHealthStatus
            url = $Url
            error = $apiHealthError
            response = $apiHealthResponse
        }
    }
    iis_proxy = [ordered]@{
        status = $proxyStatus
        error = $proxyError
        output = $proxyOutput
        details = $proxyDetails
        timeout_status = $proxyTimeoutStatus
        timeout_seconds = $proxyTimeoutSeconds
        minimum_timeout_seconds = $proxyMinimumTimeoutSeconds
    }
}

$summary | ConvertTo-Json -Depth 8 | Out-File -LiteralPath $summaryJson -Encoding utf8
$fullReport | ConvertTo-Json -Depth 12 | Out-File -LiteralPath $fullJson -Encoding utf8

Write-Host "==== FanBan Health Summary ===="
Write-Host ("Mode: " + $Mode)
Write-Host ("Overall status: " + $overallStatus)
Write-Host ("Blocking issues: " + $blockingIssues.Count)
Write-Host ("Warnings: " + $warnings.Count)
Write-Host ("Scheduled task: " + $taskStatus)
Write-Host ("Scheduled task settings: " + $taskSettingsStatus)
Write-Host ("Scheduled task recent events: " + $taskEventStatus)
Write-Host ("Backend listener: " + $backendListenerStatus + " (" + $backendListener.count + ")")
Write-Host ("Backend failure classification: " + $backendFailureClassification)
Write-Host ("API ping: " + $apiPingStatus)
Write-Host ("API health: " + $apiHealthStatus)
Write-Host ("Frontend AppPool: " + $frontendAppPoolStatus)
Write-Host ("Frontend HTTP: " + $frontendHttpStatus + " (" + $frontendRootProbeUrl + ")")
Write-Host ("Frontend API proxy: " + $frontendApiProxyStatus + " (" + $frontendApiProbeUrl + ")")
Write-Host ("IIS proxy prereqs: " + $proxyStatus)
Write-Host ("IIS proxy timeout: " + $proxyTimeoutStatus + " (" + $proxyTimeoutSeconds + "s, minimum " + $proxyMinimumTimeoutSeconds + "s)")
if ($blockingIssues.Count -gt 0) {
    Write-Host "Top blocking issues:"
    foreach ($issue in $blockingIssues) {
        $section = if ($null -ne $issue.section) { [string]$issue.section } else { "unknown" }
        $code = if ($null -ne $issue.code) { [string]$issue.code } else { "-" }
        $message = if ($null -ne $issue.message) { [string]$issue.message } else { "" }
        Write-Host ("- [{0}/{1}] {2}" -f $section, $code, $message)
    }
}
if ($apiPingStatus -ne "pass" -and -not [string]::IsNullOrWhiteSpace($apiPingError)) {
    Write-Host ("API ping detail: " + $apiPingError)
}
if ($apiHealthStatus -ne "pass" -and -not [string]::IsNullOrWhiteSpace($apiHealthError)) {
    Write-Host ("API health detail: " + $apiHealthError)
}
if ($frontendAppPoolStatus -ne "pass") {
    Write-Host "Frontend AppPool detail:"
    foreach ($problem in @($iisFrontend.problems)) {
        Write-Host ("- " + [string]$problem)
    }
}
if ($frontendHttpStatus -ne "pass" -and -not [string]::IsNullOrWhiteSpace([string]$frontendHttpProbe.error)) {
    Write-Host ("Frontend HTTP detail: " + [string]$frontendHttpProbe.error)
}
if ($frontendApiProxyStatus -ne "pass" -and -not [string]::IsNullOrWhiteSpace([string]$frontendApiProxyProbe.error)) {
    Write-Host ("Frontend API proxy detail: " + [string]$frontendApiProxyProbe.error)
}
Write-Host ("Summary JSON: " + $summaryJson)
Write-Host ("Full JSON: " + $fullJson)
'''
    check_health = check_health.replace(
        "__DEFAULT_FRONTEND_API_PORT__", str(int(deployment.default_frontend_api_port))
    )
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

    foreach ($stalePth in @("_auto_fanban.pth", "_editable_impl_auto_fanban.pth", "a1_coverage.pth")) {
        Remove-Item -LiteralPath (Join-Path $targetRoot $stalePth) -Force -ErrorAction SilentlyContinue
    }

    $backendRuntimeRoot = Join-Path $packageRoot "backend-runtime"
    $backendRoot = Join-Path $backendRuntimeRoot "backend"
    Set-Content -LiteralPath (Join-Path $targetRoot "fanban_backend_runtime.pth") -Value @($backendRuntimeRoot, $backendRoot) -Encoding utf8
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
$minimumProxyTimeoutSeconds = 600
$proxyTimeoutRaw = ""
$proxyTimeoutSeconds = $null
$proxyTimeoutStatus = "skip"

function Resolve-ArrTimeoutValue {
    param([object]$Value)

    if ($null -eq $Value) {
        return $null
    }
    if ($Value -is [TimeSpan]) {
        return $Value
    }
    if ($Value -is [string]) {
        return $Value
    }

    try {
        $valueProperty = $Value.PSObject.Properties["Value"]
        if ($null -ne $valueProperty -and $null -ne $valueProperty.Value) {
            return $valueProperty.Value
        }
    } catch {
    }

    try {
        $attributesProperty = $Value.PSObject.Properties["Attributes"]
        if ($null -ne $attributesProperty -and $null -ne $attributesProperty.Value) {
            $timeoutAttribute = $attributesProperty.Value["timeout"]
            if ($null -ne $timeoutAttribute) {
                $timeoutValueProperty = $timeoutAttribute.PSObject.Properties["Value"]
                if ($null -ne $timeoutValueProperty -and $null -ne $timeoutValueProperty.Value) {
                    return $timeoutValueProperty.Value
                }
                return $timeoutAttribute
            }
        }
    } catch {
    }

    try {
        $timeoutProperty = $Value.PSObject.Properties["timeout"]
        if ($null -ne $timeoutProperty -and $null -ne $timeoutProperty.Value) {
            return Resolve-ArrTimeoutValue -Value $timeoutProperty.Value
        }
    } catch {
    }

    return $Value
}

function Convert-ArrTimeoutToSeconds {
    param([object]$Value)

    if ($null -eq $Value) {
        return $null
    }
    if ($Value -is [TimeSpan]) {
        return [int][Math]::Round($Value.TotalSeconds)
    }

    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text)) {
        return $null
    }

    $parsedTimeSpan = [TimeSpan]::Zero
    if ([TimeSpan]::TryParse($text, [ref]$parsedTimeSpan)) {
        return [int][Math]::Round($parsedTimeSpan.TotalSeconds)
    }

    $parsedSeconds = 0
    if ([int]::TryParse($text, [ref]$parsedSeconds)) {
        return $parsedSeconds
    }

    return $null
}

if ($iisInstalled) {
    $rewriteModule = Get-WebGlobalModule -Name "RewriteModule" -ErrorAction SilentlyContinue
    if ($null -ne $rewriteModule) {
        $rewriteInstalled = $true
    }

    $proxySection = Get-WebConfigurationProperty -PSPath "MACHINE/WEBROOT/APPHOST" -Filter "system.webServer/proxy" -Name "." -ErrorAction SilentlyContinue
    if ($null -ne $proxySection) {
        $arrInstalled = $true
        $proxyTimeoutValue = $null
        try {
            $proxyTimeoutValue = Get-WebConfigurationProperty -PSPath "MACHINE/WEBROOT/APPHOST" -Filter "system.webServer/proxy" -Name "timeout" -ErrorAction SilentlyContinue
        } catch {
            $proxyTimeoutValue = $null
        }
        if ($null -eq $proxyTimeoutValue -and $null -ne $proxySection.timeout) {
            $proxyTimeoutValue = $proxySection.timeout
        }

        $proxyTimeoutResolved = Resolve-ArrTimeoutValue -Value $proxyTimeoutValue
        $proxyTimeoutSeconds = Convert-ArrTimeoutToSeconds -Value $proxyTimeoutResolved
        if ($null -eq $proxyTimeoutSeconds -and $null -ne $proxySection) {
            $proxyTimeoutResolved = Resolve-ArrTimeoutValue -Value $proxySection
            $proxyTimeoutSeconds = Convert-ArrTimeoutToSeconds -Value $proxyTimeoutResolved
        }
        $proxyTimeoutRaw = if ($null -ne $proxyTimeoutResolved) { [string]$proxyTimeoutResolved } else { "" }
        if ($null -eq $proxyTimeoutSeconds) {
            $proxyTimeoutStatus = "unknown"
        } elseif ([int]$proxyTimeoutSeconds -lt $minimumProxyTimeoutSeconds) {
            $proxyTimeoutStatus = "warn"
        } else {
            $proxyTimeoutStatus = "pass"
        }
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
        timeout = $proxyTimeoutRaw
        timeout_seconds = $proxyTimeoutSeconds
        timeout_status = $proxyTimeoutStatus
        minimum_timeout_seconds = $minimumProxyTimeoutSeconds
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
if ($arrInstalled -and $proxyTimeoutStatus -eq "warn") {
    Write-Warning ("ARR proxy timeout 低于 10 分钟，当前为 " + $proxyTimeoutSeconds + " 秒。请执行 configure_iis_site.ps1 或手动设置为 00:10:00。")
}
if ($arrInstalled -and $proxyTimeoutStatus -eq "unknown") {
    Write-Warning "ARR proxy timeout 无法解析，请检查 system.webServer/proxy timeout 设置。"
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
Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name autoStart -Value $true
Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name startMode -Value "AlwaysRunning"
Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name processModel.idleTimeout -Value "00:00:00"
Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name recycling.periodicRestart.time -Value "00:00:00"

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
Set-ItemProperty "IIS:\Sites\$SiteName" -Name serverAutoStart -Value $true

$webConfig = Join-Path $PhysicalPath "web.config"
$proxyWarning = $null
$staticContentConfig = @"
    <staticContent>
      <remove fileExtension=".mjs" />
      <mimeMap fileExtension=".mjs" mimeType="text/javascript" />
      <remove fileExtension=".wasm" />
      <mimeMap fileExtension=".wasm" mimeType="application/wasm" />
    </staticContent>
"@
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
$staticContentConfig
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
            & $appcmd set config -section:system.webServer/proxy /enabled:"True" /timeout:"00:10:00" /commit:apphost | Out-Null
        }
        $webConfigContent = @"
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <system.webServer>
$staticContentConfig
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
$staticContentConfig
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
try {
    Start-WebAppPool -Name $AppPoolName -ErrorAction SilentlyContinue | Out-Null
} catch {
}

function Invoke-FrontendWarmup {
    param([string]$Url)

    $lastError = ""
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10 | Out-Null
            Write-Host ("IIS 前端预热成功: " + $Url)
            return
        } catch {
            $lastError = $_.Exception.Message
            Start-Sleep -Seconds 2
        }
    }

    throw ("IIS 前端预热失败: {0}; {1}" -f $Url, $lastError)
}

if ([string]::IsNullOrWhiteSpace($HostName)) {
    $warmupPort = if ($Port -eq 80) { "" } else { ":" + $Port }
    Invoke-FrontendWarmup -Url ("http://127.0.0.1{0}/" -f $warmupPort)
} else {
    Write-Warning "已跳过本机前端预热：当前使用非空 HostName，请确保部署机和客户端可解析该主机名。"
}

$displayHost = if ([string]::IsNullOrWhiteSpace($HostName)) { "<部署机IP或主机名>" } else { $HostName }
$displayPort = if ($Port -eq 80) { "" } else { ":" + $Port }
Write-Host ("IIS 站点已配置完成。前端访问地址: http://{0}{1}/" -f $displayHost, $displayPort)
Write-Host "frontend-app-pool: AlwaysRunning autoStart=True idleTimeout=00:00:00 periodicRestart=00:00:00"
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
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -Hidden `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1)
$settings.AllowHardTerminate = $true

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
- `documents/AI/`: AI 模型接入配置
- `documents_bin/`: 模板与词库资源
- `scripts/`: 启动、探测、健康检查脚本
- `install/`: 离线运行时安装脚本和安装器目录

## 建议顺序

1. 先执行 `install\check_iis_proxy_prereqs.ps1`
2. 需要时执行 `install\install_iis_proxy_prereqs.ps1`
3. 再执行 `install\install_runtime_prereqs.ps1`
4. 再执行 `scripts\prepare_terminal.ps1`
5. 再执行 `scripts\deep_check_terminal.ps1`
6. 配置 IIS：`install\configure_iis_site.ps1`
7. 注册登录触发任务：`install\register_backend_task.ps1 -UserName "<本机登录账号>"`
8. 等待 `http://127.0.0.1:8000/api/system/ping` 就绪
9. 执行 `scripts\check_health.ps1`
10. 如果只想临时本机调试，可手工执行 `scripts\start_backend.ps1`

等待 API 就绪的推荐命令：

```powershell
$apiReady = $false
$deadline = (Get-Date).AddMinutes(5)
do {
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/system/ping" -TimeoutSec 5 | Out-Null
        $apiReady = $true
    } catch {
        Start-Sleep -Seconds 5
    }
} until ($apiReady -or (Get-Date) -ge $deadline)
if (-not $apiReady) { throw "FanBanBackend API 未在 5 分钟内就绪，请查看 D:\FanBanServer\logs\backend-latest-stderr.log" }
```

## 后端启动模型

- 当前部署包采用 API 与 worker 分离：API 进程只负责网页接口和队列入库，worker 进程负责 CAD/文档长任务。
- 正常安装命令不需要变化，也不需要单独启动 worker；`scripts\start_backend.ps1` 会同时托管 API 和 worker。
- `Stop-ScheduledTask -TaskName FanBanBackend` 会停止登录触发任务；任务停止后脚本会通过 Job Object 结束本次托管的 API 和 worker 子进程。
- `install\register_backend_task.ps1` 会在目标用户已登录时尝试立即启动 `FanBanBackend`；首次安装后不要再额外执行 `Start-ScheduledTask -TaskName FanBanBackend`。
- `install\configure_iis_site.ps1` 负责 IIS 站点和 ARR 反代配置。只覆盖 `frontend-dist` 静态文件通常不需要重新执行；如果 `check_health.ps1` 提示 ARR proxy timeout 低于 600 秒或无法解析，需要重新执行。

## AI 模型接入检查

- AI 接入参数集中在 `documents\AI\ai_model_gateway.yaml`。
- 开发/测试环境默认使用 `development_minimax` profile，通过 MiniMax OpenAI-compatible API 验证。
- 终端内网部署使用 `terminal_cnpe_intranet_qwen_fast` profile，对应 `http://models.ai.cnpe.cc/qwen_fast/v1/chat/completions`、模型 `Qwen3.6-35A3`、流式输出、无鉴权头。
- `prepare_terminal.ps1` 会把 `FANBAN_AI_GATEWAY_CONFIG_PATH` 和 `FANBAN_AI_GATEWAY_PROFILE=terminal_cnpe_intranet_qwen_fast` 写入 `scripts\runtime.env.ps1`，后端启动时会自动加载。
- 部署机上可执行 `scripts\test_ai_model_connectivity.ps1` 生成连通性诊断 JSON；默认输出到 `storage\ai\diagnostics\ai-connectivity-*.json`。
- 诊断 JSON 的 `script.sha256` 应与同包 `package-manifest.json` 中 `scripts/test_ai_model_connectivity.ps1` 的 SHA-256 一致，`environment.config_sha256` 用于确认实际读取的网关配置版本。
- 流式检查会重组多个 SSE delta 后再校验标记；部分兼容网关在完整响应后直接关闭连接而不发送 `[DONE]`，因此 `done_received=false` 不能单独判定为失败，应结合 `status_code`、`response_contains_expected`、`invalid_data_line_count` 和总状态判断。

开发/测试环境验证：

```powershell
powershell -ExecutionPolicy Bypass -File D:\FanBanServer\scripts\test_ai_model_connectivity.ps1
```

终端内网链路验证：

```powershell
powershell -ExecutionPolicy Bypass -File D:\FanBanServer\scripts\test_ai_model_connectivity.ps1 -Profile terminal_cnpe_intranet_qwen_fast
```

脚本会检查配置解析、DNS、TCP、模型列表、非流式对话和流式对话；不会把 API key 明文写入控制台或 JSON。

## 一致性边界

- 部署后运行行为应与本机构建产物一致，但目录结构不会和开发环境逐字节一致。
- 部署包会使用 `backend-runtime/`、`frontend-dist/`、`python-runtime/`、`python-packages/` 这些部署布局。
- 测试、缓存、`__pycache__`、`.lscache`、editable 安装记录和开发绝对路径不应进入部署运行面。
- 真正上线验收以 `prepare_terminal.ps1`、`deep_check_terminal.ps1`、`check_health.ps1` 和样例 DWG 冒烟为准。

## 打包卫生检查

构建机打包后至少检查：

```powershell
rg -n "<开发机绝对路径>|<仓库目录名>" build\fanban-terminal-deploy
rg --files build\fanban-terminal-deploy -g "*.lscache" -g "direct_url.json" -g "_auto_fanban.pth" -g "_editable_impl_auto_fanban.pth" -g "a1_coverage.pth" -g ".build_packages/**"
Get-ChildItem build\fanban-terminal-deploy\backend-runtime,build\fanban-terminal-deploy\scripts,build\fanban-terminal-deploy\install -Recurse -Force | Where-Object { $_.Name -eq "__pycache__" -or $_.Extension -eq ".pyc" }
```

前两条不应命中。第三条不应在后端运行源码、脚本或安装目录中发现源码缓存；第三方依赖自身的 `__pycache__` 不作为阻塞项。

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
    _validate_frontend_preview_assets(repo_root)

    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    for entry in copy_plan:
        _copy_entry(entry, output_root)

    _materialize_ansys_mapdl_skill(repo_root, output_root)
    _materialize_building_standards_skill(repo_root, output_root)
    _materialize_reinforcement_table_skill(repo_root, output_root)
    _write_frontend_web_config(output_root)
    _sanitize_python_packages(output_root)
    _prune_development_artifacts(output_root)
    _overlay_local_managed_plotter_assets(output_root)

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
    def _display_path(path: Path) -> str:
        return Path(os.path.relpath(path, repo_root)).as_posix()

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
            baseline_label=_display_path(output_root),
            target_label=_display_path(output_root),
        )

        if output_root.exists():
            shutil.rmtree(output_root)
        shutil.move(str(staging_root), str(output_root))
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root)

    return DeployArtifacts(full_root=output_root, delta_root=resolved_delta_root)
