from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4


def _resolve_source_project_root() -> Path:
    this_file = Path(__file__).resolve()
    for parent in this_file.parents:
        if (parent / "backend").exists():
            return parent
    return this_file.parent


SOURCE_PROJECT_ROOT = _resolve_source_project_root()
BACKEND_ROOT = SOURCE_PROJECT_ROOT / "backend"
if not getattr(sys, "frozen", False) and str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.cad.autocad_path_resolver import (  # noqa: E402
    list_available_autocad_installations,
    resolve_autocad_paths,
)
from src.cad.plot_resource_manager import (  # noqa: E402
    MANAGED_CTB_NAME,
    PDF2_PC3_NAME,
    PDF2_PMP_NAME,
)
from src.config import reload_config  # noqa: E402
from src.models import Job, JobType  # noqa: E402
from src.pipeline.executor import PipelineExecutor  # noqa: E402
from src.pipeline.project_no_inference import resolve_project_no  # noqa: E402


@dataclass(frozen=True)
class LauncherRunResult:
    job: Job
    job_dir: Path
    copied_files: int
    selected_output_dir: Path | None


def launcher_settings_path(*, app_root: Path | None = None) -> Path:
    return (app_root or resolve_runtime_root()) / "fanban_m5_settings.json"


def load_launcher_settings(*, app_root: Path | None = None) -> dict:
    path = launcher_settings_path(app_root=app_root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_launcher_settings(settings: dict, *, app_root: Path | None = None) -> Path:
    path = launcher_settings_path(app_root=app_root)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def validate_runtime_bundle(*, bundle_root: Path | None = None) -> list[str]:
    root = (bundle_root or resolve_bundle_root()).resolve()
    errors: list[str] = []
    init_candidates = [root / "_tcl_data" / "init.tcl", root / "tcl_data" / "init.tcl"]
    init_path = next((path for path in init_candidates if path.exists()), None)
    if init_path is None:
        errors.append("缺少 Tcl 运行时文件: _tcl_data/init.tcl")
    else:
        try:
            init_text = init_path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            errors.append(f"无法读取 Tcl 运行时文件: {init_path} ({exc})")
        else:
            if "# init.tcl" not in init_text:
                errors.append(f"Tcl 运行时文件疑似损坏: {init_path}")

    managed_ctb = root / "assets" / "plot_styles" / MANAGED_CTB_NAME
    if not managed_ctb.exists():
        errors.append(f"缺少受管 CTB 资源: {managed_ctb}")
    else:
        try:
            data = managed_ctb.read_bytes()
        except OSError as exc:
            errors.append(f"无法读取受管 CTB: {managed_ctb} ({exc})")
        else:
            if len(data) < 512 or data == b"bundled-ctb":
                errors.append(f"受管 CTB 资源损坏: {managed_ctb}")

    for required in (
        root / "assets" / "plotters" / PDF2_PC3_NAME,
        root / "assets" / "plotters" / PDF2_PMP_NAME,
        root
        / "backend"
        / "src"
        / "cad"
        / "dotnet"
        / "Module5CadBridge"
        / "bin"
        / "Release"
        / "net48"
        / "Module5CadBridge.dll",
    ):
        if not required.exists():
            errors.append(f"缺少关键运行资源: {required}")
    return errors


def _detected_cad_options() -> list[dict]:
    options: list[dict] = []
    for installation in list_available_autocad_installations():
        label = f"AutoCAD {installation.year or 'Unknown'} | {installation.install_dir}"
        options.append(
            {
                "label": label,
                "year": installation.year,
                "install_dir": str(installation.install_dir),
                "accoreconsole_exe": str(installation.accoreconsole_exe) if installation.accoreconsole_exe else "",
                "plotters_dir": str(installation.plotters_dir) if installation.plotters_dir else "",
                "plot_styles_dir": str(installation.plot_styles_dir) if installation.plot_styles_dir else "",
            }
        )
    return options


def get_cad_settings_snapshot(*, app_root: Path | None = None) -> dict:
    runtime_root = (app_root or resolve_runtime_root()).resolve()
    settings = load_launcher_settings(app_root=runtime_root)
    options = _detected_cad_options()
    selected_install_dir = str(settings.get("selected_cad_install_dir", "")).strip()
    selected = next((item for item in options if item["install_dir"] == selected_install_dir), None)
    if selected is None and options:
        selected = options[0]
        selected_install_dir = selected["install_dir"]
    bundle_root = resolve_bundle_root()
    return {
        "selected_install_dir": selected_install_dir,
        "selected": selected,
        "options": options,
        "pc3_name": PDF2_PC3_NAME,
        "ctb_name": MANAGED_CTB_NAME,
        "pc3_asset_path": str(bundle_root / "assets" / "plotters" / PDF2_PC3_NAME),
        "ctb_asset_path": str(bundle_root / "assets" / "plot_styles" / MANAGED_CTB_NAME),
        "bundle_errors": validate_runtime_bundle(bundle_root=bundle_root),
    }


def configure_runtime_environment(*, selected_install_dir: str | Path | None = None) -> Path:
    app_root = resolve_runtime_root()
    bundle_root = resolve_bundle_root()
    os.chdir(app_root)
    os.environ.setdefault("FANBAN_SPEC_PATH", str(bundle_root / "documents" / "参数规范.yaml"))
    os.environ.setdefault(
        "FANBAN_RUNTIME_SPEC_PATH",
        str(bundle_root / "documents" / "参数规范_运行期.yaml"),
    )
    os.environ.setdefault(
        "FANBAN_ODA__EXE_PATH",
        str(bundle_root / "bin" / "ODAFileConverter 25.12.0" / "ODAFileConverter.exe"),
    )
    os.environ.setdefault(
        "FANBAN_MODULE5_EXPORT__CAD_RUNNER__SCRIPT_DIR",
        str(bundle_root / "backend" / "src" / "cad" / "scripts"),
    )
    os.environ.setdefault(
        "FANBAN_MODULE5_EXPORT__DOTNET_BRIDGE__DLL_PATH",
        str(
            bundle_root
            / "backend"
            / "src"
            / "cad"
            / "dotnet"
            / "Module5CadBridge"
            / "bin"
            / "Release"
            / "net48"
            / "Module5CadBridge.dll"
        ),
    )
    os.environ.setdefault("FANBAN_PLOT_ASSET_ROOT", str(bundle_root / "assets"))
    os.environ["FANBAN_MODULE5_EXPORT__PLOT__CTB_NAME"] = MANAGED_CTB_NAME
    selected_candidate = str(selected_install_dir).strip() if selected_install_dir else ""
    if not selected_candidate:
        settings = load_launcher_settings(app_root=app_root)
        selected_candidate = str(settings.get("selected_cad_install_dir", "")).strip()
    autodetected = resolve_autocad_paths(configured_install_dir=selected_candidate or None)
    if autodetected.install_dir is None:
        autodetected = resolve_autocad_paths()
    if autodetected.install_dir is not None:
        os.environ["FANBAN_AUTOCAD_INSTALL_DIR"] = str(autodetected.install_dir)
    if autodetected.accoreconsole_exe is not None:
        os.environ["FANBAN_MODULE5_EXPORT__CAD_RUNNER__ACCORECONSOLE_EXE"] = str(
            autodetected.accoreconsole_exe
        )
    os.environ["FANBAN_AUTOCAD__CTB_PATH"] = str(bundle_root / "assets" / "plot_styles" / MANAGED_CTB_NAME)
    reload_config()
    return app_root


def build_split_only_job(
    *,
    dwg_path: Path,
    project_no: str = "",
    job_id: str | None = None,
) -> Job:
    resolved_dwg = Path(dwg_path).resolve()
    if not resolved_dwg.exists():
        raise FileNotFoundError(f"DWG不存在: {resolved_dwg}")
    if resolved_dwg.suffix.lower() != ".dwg":
        raise ValueError(f"仅支持DWG文件: {resolved_dwg}")

    return Job(
        job_id=job_id or _new_job_id(),
        job_type=JobType.DELIVERABLE,
        project_no=resolve_project_no(project_no, resolved_dwg),
        input_files=[resolved_dwg],
        options={
            "enabled": True,
            "export_pdf": True,
            "split_only": True,
        },
        params={},
    )


def run_split_only_job(
    *,
    dwg_path: Path,
    selected_output_dir: Path | None = None,
    project_no: str = "",
    job_id: str | None = None,
    selected_install_dir: str | Path | None = None,
) -> LauncherRunResult:
    configure_runtime_environment(selected_install_dir=selected_install_dir)
    job = build_split_only_job(dwg_path=dwg_path, project_no=project_no, job_id=job_id)
    executor = PipelineExecutor()
    executor.config.multi_dwg_policy.code_conflict = "warn"
    executor.cad_dxf_executor.config.multi_dwg_policy.code_conflict = "warn"
    executor.execute(job)

    job_dir = (resolve_runtime_root() / "storage" / "jobs" / job.job_id).resolve()
    copied = 0
    target_dir = None
    if selected_output_dir is not None:
        target_dir = Path(selected_output_dir).resolve()
        copied = copy_job_outputs_to_selected_dir(
            job_dir=job_dir,
            selected_output_dir=target_dir,
        )

    return LauncherRunResult(
        job=job,
        job_dir=job_dir,
        copied_files=copied,
        selected_output_dir=target_dir,
    )


def new_job_id() -> str:
    return _new_job_id()


def copy_job_outputs_to_selected_dir(*, job_dir: Path, selected_output_dir: Path) -> int:
    drawings_dir = Path(job_dir) / "output" / "drawings"
    if not drawings_dir.exists():
        raise FileNotFoundError(f"任务产物目录不存在: {drawings_dir}")
    selected_output_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    for file_path in sorted(drawings_dir.iterdir()):
        if not file_path.is_file():
            continue
        shutil.copy2(file_path, selected_output_dir / file_path.name)
        copied += 1
    return copied


def list_recent_jobs(*, storage_dir: Path | None = None, limit: int = 20) -> list[dict]:
    current_cwd = Path.cwd()
    try:
        configure_runtime_environment()
        storage_root = Path(storage_dir) if storage_dir is not None else (resolve_runtime_root() / "storage")
    finally:
        os.chdir(current_cwd)
    jobs_root = storage_root / "jobs"
    if not jobs_root.exists():
        return []

    jobs: list[dict] = []
    for job_file in jobs_root.glob("*/job.json"):
        try:
            data = json.loads(job_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        jobs.append(
            {
                "job_id": str(data.get("job_id", job_file.parent.name)),
                "status": str(data.get("status", "unknown")),
                "project_no": str(data.get("project_no", "")),
                "created_at": str(data.get("created_at", "")),
                "errors": list(data.get("errors", [])),
                "flags": list(data.get("flags", [])),
                "job_dir": str(job_file.parent),
            },
        )

    jobs.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return jobs[:limit]


def resolve_job_dir(job_id: str) -> Path:
    return (resolve_runtime_root() / "storage" / "jobs" / job_id).resolve()


def read_job_trace_excerpt(*, job_dir: Path, max_lines: int = 200) -> str:
    task_root = Path(job_dir) / "work" / "cad_tasks"
    if not task_root.exists():
        return ""

    traces = sorted(task_root.rglob("module5_trace.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not traces:
        return ""

    text = traces[0].read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    return "\n".join(lines[-max_lines:])


def read_job_summary(*, job_dir: Path) -> dict:
    job_file = Path(job_dir) / "job.json"
    if not job_file.exists():
        return {}
    return json.loads(job_file.read_text(encoding="utf-8"))


def read_job_live_snapshot(
    *,
    job_dir: Path | None = None,
    job_id: str | None = None,
    max_trace_lines: int = 200,
) -> dict:
    if job_dir is None:
        if not job_id:
            raise ValueError("job_dir or job_id is required")
        job_dir = resolve_job_dir(job_id)
    resolved_job_dir = Path(job_dir)
    return {
        "job_dir": str(resolved_job_dir),
        "summary": read_job_summary(job_dir=resolved_job_dir),
        "trace": read_job_trace_excerpt(job_dir=resolved_job_dir, max_lines=max_trace_lines),
    }


def _new_job_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"fanban-m5-{timestamp}-{uuid4().hex[:8]}"


def resolve_runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return SOURCE_PROJECT_ROOT


def resolve_bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass).resolve()
        return (resolve_runtime_root() / "_internal").resolve()
    return SOURCE_PROJECT_ROOT
