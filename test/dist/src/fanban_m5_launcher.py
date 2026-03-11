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

from src.cad.autocad_path_resolver import resolve_autocad_paths  # noqa: E402
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


def configure_runtime_environment() -> Path:
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
    autodetected = resolve_autocad_paths()
    if autodetected.install_dir is not None:
        os.environ["FANBAN_AUTOCAD_INSTALL_DIR"] = str(autodetected.install_dir)
    if autodetected.accoreconsole_exe is not None:
        os.environ["FANBAN_MODULE5_EXPORT__CAD_RUNNER__ACCORECONSOLE_EXE"] = str(
            autodetected.accoreconsole_exe
        )
    if autodetected.monochrome_ctb_path is not None:
        os.environ["FANBAN_AUTOCAD__CTB_PATH"] = str(autodetected.monochrome_ctb_path)
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
) -> LauncherRunResult:
    configure_runtime_environment()
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
