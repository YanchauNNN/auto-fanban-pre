from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


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
