from __future__ import annotations

import json
from pathlib import Path

from src.config import reload_config
from src.pipeline.job_manager import JobManager


def test_load_all_jobs_keeps_cached_jobs_when_one_job_file_is_temporarily_unreadable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FANBAN_STORAGE_DIR", str(tmp_path / "storage"))
    reload_config()

    manager = JobManager()
    job_a = manager.create_job(job_type="deliverable", project_no="2016")
    job_b = manager.create_job(job_type="deliverable", project_no="2016")

    original_json_load = json.load
    failing_job_file = str((manager.config.get_job_dir(job_b.job_id) / "job.json").resolve())

    def flaky_json_load(fp, *args, **kwargs):
        if str(Path(fp.name).resolve()) == failing_job_file:
            raise json.JSONDecodeError("temporary partial write", "", 0)
        return original_json_load(fp, *args, **kwargs)

    monkeypatch.setattr("src.pipeline.job_manager.json.load", flaky_json_load)

    loaded = manager.load_all_jobs()

    assert {job.job_id for job in loaded} == {job_a.job_id, job_b.job_id}


def test_update_job_retries_when_atomic_replace_hits_transient_windows_lock(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FANBAN_STORAGE_DIR", str(tmp_path / "storage"))
    reload_config()

    manager = JobManager()
    job = manager.create_job(job_type="deliverable", project_no="2016")

    original_replace = Path.replace
    replace_calls = {"count": 0}

    def flaky_replace(self: Path, target: Path):
        replace_calls["count"] += 1
        if replace_calls["count"] == 1 and self.name == "job.json.tmp":
            raise PermissionError("[WinError 5] access denied")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)

    manager.update_job(job)

    assert replace_calls["count"] >= 2
    assert (manager.config.get_job_dir(job.job_id) / "job.json").exists()
