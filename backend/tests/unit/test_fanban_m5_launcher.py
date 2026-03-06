from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

from src.config import reload_config


PROJECT_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER_PATH = PROJECT_ROOT / "test" / "dist" / "src" / "fanban_m5_launcher.py"


def _load_launcher():
    spec = importlib.util.spec_from_file_location("fanban_m5_launcher", LAUNCHER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_split_only_job_sets_expected_flags(tmp_path: Path):
    launcher = _load_launcher()
    dwg = tmp_path / "sample.dwg"
    dwg.write_text("dwg", encoding="utf-8")

    job = launcher.build_split_only_job(
        dwg_path=dwg,
        project_no="2016",
        job_id="job-launcher-1",
    )

    assert job.job_id == "job-launcher-1"
    assert job.project_no == "2016"
    assert job.input_files == [dwg.resolve()]
    assert job.options["enabled"] is True
    assert job.options["export_pdf"] is True
    assert job.options["split_only"] is True


def test_copy_job_outputs_to_selected_dir_copies_drawings(tmp_path: Path):
    launcher = _load_launcher()
    job_dir = tmp_path / "storage" / "jobs" / "job-1"
    drawings_dir = job_dir / "output" / "drawings"
    drawings_dir.mkdir(parents=True)
    (drawings_dir / "A.pdf").write_text("pdf", encoding="utf-8")
    (drawings_dir / "A.dwg").write_text("dwg", encoding="utf-8")
    target_dir = tmp_path / "selected"

    copied = launcher.copy_job_outputs_to_selected_dir(job_dir=job_dir, selected_output_dir=target_dir)

    assert copied == 2
    assert (target_dir / "A.pdf").read_text(encoding="utf-8") == "pdf"
    assert (target_dir / "A.dwg").read_text(encoding="utf-8") == "dwg"


def test_list_recent_jobs_reads_storage_job_json(tmp_path: Path):
    launcher = _load_launcher()
    storage_dir = tmp_path / "storage"
    jobs_dir = storage_dir / "jobs"
    job_a = jobs_dir / "job-a"
    job_b = jobs_dir / "job-b"
    job_a.mkdir(parents=True)
    job_b.mkdir(parents=True)
    (job_a / "job.json").write_text(
        json.dumps(
            {
                "job_id": "job-a",
                "status": "failed",
                "project_no": "2016",
                "created_at": "2026-03-06T10:00:00",
                "errors": ["boom"],
                "flags": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (job_b / "job.json").write_text(
        json.dumps(
            {
                "job_id": "job-b",
                "status": "succeeded",
                "project_no": "1818",
                "created_at": "2026-03-06T11:00:00",
                "errors": [],
                "flags": ["OK"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    jobs = launcher.list_recent_jobs(storage_dir=storage_dir, limit=2)

    assert [job["job_id"] for job in jobs] == ["job-b", "job-a"]
    assert jobs[0]["status"] == "succeeded"
    assert jobs[1]["errors"] == ["boom"]


def test_configure_runtime_environment_uses_internal_bundle_root_when_frozen(
    tmp_path: Path,
    monkeypatch,
):
    launcher = _load_launcher()
    exe_dir = tmp_path / "fanban_m5"
    internal_dir = exe_dir / "_internal"
    exe_dir.mkdir(parents=True)
    internal_dir.mkdir()
    exe_path = exe_dir / "fanban_m5.exe"
    exe_path.write_text("exe", encoding="utf-8")

    old_cwd = Path.cwd()
    try:
        monkeypatch.setattr(launcher.sys, "frozen", True, raising=False)
        monkeypatch.setattr(launcher.sys, "_MEIPASS", str(internal_dir), raising=False)
        monkeypatch.setattr(launcher.sys, "executable", str(exe_path), raising=False)
        monkeypatch.delenv("FANBAN_SPEC_PATH", raising=False)
        monkeypatch.delenv("FANBAN_RUNTIME_SPEC_PATH", raising=False)
        monkeypatch.delenv("FANBAN_ODA__EXE_PATH", raising=False)
        monkeypatch.delenv("FANBAN_MODULE5_EXPORT__CAD_RUNNER__SCRIPT_DIR", raising=False)
        monkeypatch.delenv("FANBAN_MODULE5_EXPORT__DOTNET_BRIDGE__DLL_PATH", raising=False)
        monkeypatch.delenv("FANBAN_PLOT_ASSET_ROOT", raising=False)

        launcher.configure_runtime_environment()

        assert Path(os.environ["FANBAN_SPEC_PATH"]) == internal_dir / "documents" / "参数规范.yaml"
        assert Path(os.environ["FANBAN_RUNTIME_SPEC_PATH"]) == (
            internal_dir / "documents" / "参数规范_运行期.yaml"
        )
        assert Path(os.environ["FANBAN_ODA__EXE_PATH"]) == (
            internal_dir / "bin" / "ODAFileConverter 25.12.0" / "ODAFileConverter.exe"
        )
        assert Path(os.environ["FANBAN_MODULE5_EXPORT__CAD_RUNNER__SCRIPT_DIR"]) == (
            internal_dir / "backend" / "src" / "cad" / "scripts"
        )
        assert Path(os.environ["FANBAN_MODULE5_EXPORT__DOTNET_BRIDGE__DLL_PATH"]) == (
            internal_dir
            / "backend"
            / "src"
            / "cad"
            / "dotnet"
            / "Module5CadBridge"
            / "bin"
            / "Release"
            / "net48"
            / "Module5CadBridge.dll"
        )
        assert Path(os.environ["FANBAN_PLOT_ASSET_ROOT"]) == internal_dir / "assets"
        assert Path.cwd() == exe_dir.resolve()
    finally:
        os.chdir(old_cwd)


def test_list_recent_jobs_defaults_to_app_storage_when_frozen(tmp_path: Path, monkeypatch):
    launcher = _load_launcher()
    exe_dir = tmp_path / "fanban_m5"
    internal_dir = exe_dir / "_internal"
    exe_dir.mkdir(parents=True)
    internal_dir.mkdir()
    exe_path = exe_dir / "fanban_m5.exe"
    exe_path.write_text("exe", encoding="utf-8")
    job_dir = exe_dir / "storage" / "jobs" / "job-frozen-1"
    job_dir.mkdir(parents=True)
    (job_dir / "job.json").write_text(
        json.dumps(
            {
                "job_id": "job-frozen-1",
                "status": "succeeded",
                "project_no": "2016",
                "created_at": "2026-03-06T12:00:00",
                "errors": [],
                "flags": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(launcher.sys, "frozen", True, raising=False)
    monkeypatch.setattr(launcher.sys, "_MEIPASS", str(internal_dir), raising=False)
    monkeypatch.setattr(launcher.sys, "executable", str(exe_path), raising=False)

    jobs = launcher.list_recent_jobs(limit=5)

    assert [job["job_id"] for job in jobs] == ["job-frozen-1"]


def test_configure_runtime_environment_keeps_storage_dir_usable_in_runtime_config(
    tmp_path: Path,
    monkeypatch,
):
    launcher = _load_launcher()
    exe_dir = tmp_path / "fanban_m5"
    internal_dir = exe_dir / "_internal"
    docs_dir = internal_dir / "documents"
    exe_dir.mkdir(parents=True)
    docs_dir.mkdir(parents=True)
    (docs_dir / "参数规范_运行期.yaml").write_text(
        """
runtime_options:
  concurrency:
    max_workers:
      type: int
      default: 2
""".strip(),
        encoding="utf-8",
    )
    exe_path = exe_dir / "fanban_m5.exe"
    exe_path.write_text("exe", encoding="utf-8")

    old_cwd = Path.cwd()
    try:
        monkeypatch.setattr(launcher.sys, "frozen", True, raising=False)
        monkeypatch.setattr(launcher.sys, "_MEIPASS", str(internal_dir), raising=False)
        monkeypatch.setattr(launcher.sys, "executable", str(exe_path), raising=False)
        launcher.configure_runtime_environment()

        config = reload_config()

        assert config.get_job_dir("job-1").resolve() == (
            exe_dir.resolve() / "storage" / "jobs" / "job-1"
        )
    finally:
        os.chdir(old_cwd)
