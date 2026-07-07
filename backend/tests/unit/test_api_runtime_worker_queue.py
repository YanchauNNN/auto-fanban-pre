from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from src.config import SpecLoader, reload_config
from src.models import Job, JobStatus, JobType
from src.pipeline.sqlite_queue import SQLiteQueueStore


class RecordingProcessor:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, job: Job) -> None:
        self.calls += 1
        raise AssertionError("API process must not execute queued work")


def _configure_api_env(monkeypatch: Any, tmp_path: Path) -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    spec_path = repo_root / "documents" / "参数规范.yaml"
    runtime_spec_path = repo_root / "documents" / "参数规范_运行期.yaml"

    monkeypatch.setenv("FANBAN_SPEC_PATH", str(spec_path))
    monkeypatch.setenv("FANBAN_RUNTIME_SPEC_PATH", str(runtime_spec_path))
    monkeypatch.setenv("FANBAN_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("FANBAN_UPLOAD_LIMITS__MAX_FILES", "3")
    monkeypatch.setenv("FANBAN_UPLOAD_LIMITS__MAX_TOTAL_MB", "1")

    SpecLoader.clear_cache()
    reload_config()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    return repo_root


def _deliverable_params() -> dict[str, str]:
    return {
        "project_no": "2016",
        "classification": "闈炲瘑",
        "subitem_name": "绀轰緥瀛愰」",
        "album_title_cn": "绀轰緥鍥惧唽",
        "wbs_code": "WBS-001",
        "file_category": "1 鎬讳綋鏂囦欢",
        "ied_status": "缂栧埗",
        "ied_doc_type": "鍥惧唽",
        "cover_variant": "閫氱敤",
    }


def test_api_mode_enqueues_batch_without_executing_processor(monkeypatch, tmp_path: Path) -> None:
    _configure_api_env(monkeypatch, tmp_path)
    from API.app.main import create_app

    processor = RecordingProcessor()
    app = create_app(job_processor=processor, process_jobs_in_api=False)

    with TestClient(app) as client:
        response = client.post(
            "/api/jobs/batch",
            data={"params_json": json.dumps(_deliverable_params(), ensure_ascii=False)},
            files=[("files[]", ("A01.dwg", b"dwg-a", "application/acad"))],
        )

        assert response.status_code == 201
        job_id = response.json()["jobs"][0]["job_id"]
        detail = client.get(f"/api/jobs/{job_id}").json()

    store = SQLiteQueueStore(tmp_path / "storage" / "runtime" / "fanban_queue.sqlite3")
    queue_items = store.list_queue_items()

    assert processor.calls == 0
    assert detail["status"] == "queued"
    assert [(item["item_type"], item["item_id"], item["status"]) for item in queue_items] == [
        ("job", job_id, "queued")
    ]


def test_api_mode_startup_does_not_fail_running_jobs(monkeypatch, tmp_path: Path) -> None:
    _configure_api_env(monkeypatch, tmp_path)
    from API.app.main import create_app

    storage_root = tmp_path / "storage"
    running_job = Job(
        job_id="job-running-1",
        job_type=JobType.DELIVERABLE,
        project_no="2016",
        status=JobStatus.RUNNING,
        params=_deliverable_params(),
    )
    running_job.progress.stage = "GENERATE_DOCS"
    running_job.progress.message = "generating docs"
    job_dir = storage_root / "jobs" / running_job.job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "job.json").write_text(
        running_job.model_dump_json(indent=2),
        encoding="utf-8",
    )

    app = create_app(job_processor=RecordingProcessor(), process_jobs_in_api=False)

    with TestClient(app) as client:
        response = client.get(f"/api/jobs/{running_job.job_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "running"
    assert "service_restarted_before_completion" not in payload["errors"]


def test_api_mode_startup_backfills_summary_index_once(monkeypatch, tmp_path: Path) -> None:
    _configure_api_env(monkeypatch, tmp_path)
    from API.app.main import create_app

    storage_root = tmp_path / "storage"
    existing_job = Job(
        job_id="job-existing-1",
        job_type=JobType.DELIVERABLE,
        project_no="2016",
        status=JobStatus.SUCCEEDED,
        params=_deliverable_params(),
        source_filename="existing.dwg",
    )
    job_dir = storage_root / "jobs" / existing_job.job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "job.json").write_text(
        existing_job.model_dump_json(indent=2),
        encoding="utf-8",
    )

    app = create_app(job_processor=RecordingProcessor(), process_jobs_in_api=False)

    with TestClient(app) as client:
        def _fail_scan(*args: Any, **kwargs: Any) -> list[Any]:
            raise AssertionError("job list must use startup summary index after backfill")

        client.app.state.runtime.job_manager.load_all_jobs = _fail_scan
        client.app.state.runtime.group_manager.load_all_groups = _fail_scan
        response = client.get("/api/jobs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["job_id"] == "job-existing-1"
    assert payload["items"][0]["source_filename"] == "existing.dwg"


def test_api_mode_list_jobs_uses_sqlite_summary_index(monkeypatch, tmp_path: Path) -> None:
    _configure_api_env(monkeypatch, tmp_path)
    from API.app.main import create_app

    app = create_app(job_processor=RecordingProcessor(), process_jobs_in_api=False)

    with TestClient(app) as client:
        response = client.post(
            "/api/jobs/batch",
            data={"params_json": json.dumps(_deliverable_params(), ensure_ascii=False)},
            files=[("files[]", ("A01.dwg", b"dwg-a", "application/acad"))],
        )
        assert response.status_code == 201
        job_id = response.json()["jobs"][0]["job_id"]

        def _fail_scan(*args: Any, **kwargs: Any) -> list[Any]:
            raise AssertionError("job list must not scan job/group JSON files per request")

        client.app.state.runtime.job_manager.load_all_jobs = _fail_scan
        client.app.state.runtime.group_manager.load_all_groups = _fail_scan

        list_response = client.get("/api/jobs")

    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["job_id"] == job_id
    assert payload["items"][0]["source_filename"] == "A01.dwg"


def test_jobs_activity_endpoint_returns_lightweight_marker(monkeypatch, tmp_path: Path) -> None:
    _configure_api_env(monkeypatch, tmp_path)
    from API.app.main import create_app

    app = create_app(job_processor=RecordingProcessor(), process_jobs_in_api=False)

    with TestClient(app) as client:
        response = client.post(
            "/api/jobs/batch",
            data={"params_json": json.dumps(_deliverable_params(), ensure_ascii=False)},
            files=[("files[]", ("A01.dwg", b"dwg-a", "application/acad"))],
        )
        assert response.status_code == 201

        activity_response = client.get("/api/jobs/activity")

    assert activity_response.status_code == 200
    assert activity_response.json()["total"] == 1
    assert activity_response.json()["active"] == 1
    assert activity_response.json()["last_changed_at"]


def test_api_mode_health_uses_sqlite_worker_heartbeat(monkeypatch, tmp_path: Path) -> None:
    _configure_api_env(monkeypatch, tmp_path)
    from API.app.main import create_app

    app = create_app(job_processor=RecordingProcessor(), process_jobs_in_api=False)

    with TestClient(app) as client:
        client.app.state.runtime.queue_store.upsert_worker_heartbeat(
            worker_id="worker-test",
            pid=1234,
            state="idle",
        )
        response = client.get("/api/system/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is True
    assert payload["worker_alive"] is True
    assert payload["queue_depth"] == 0


def test_api_mode_detail_and_download_reload_worker_written_job_json(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_api_env(monkeypatch, tmp_path)
    from API.app.main import create_app
    from src.pipeline.job_manager import JobManager

    app = create_app(job_processor=RecordingProcessor(), process_jobs_in_api=False)

    with TestClient(app) as client:
        response = client.post(
            "/api/jobs/batch",
            data={"params_json": json.dumps(_deliverable_params(), ensure_ascii=False)},
            files=[("files[]", ("A01.dwg", b"dwg-a", "application/acad"))],
        )
        assert response.status_code == 201
        job_id = response.json()["jobs"][0]["job_id"]

        worker_manager = JobManager()
        worker_job = worker_manager.reload_job(job_id)
        assert worker_job is not None
        package_zip = tmp_path / "storage" / "jobs" / job_id / "package.zip"
        package_zip.write_bytes(b"zip-result")
        worker_job.artifacts.package_zip = package_zip
        worker_job.progress.stage = "PACKAGE_ZIP"
        worker_job.progress.message = "done by worker"
        worker_job.mark_succeeded()
        worker_manager.update_job(worker_job)

        detail_response = client.get(f"/api/jobs/{job_id}")
        download_response = client.get(f"/api/jobs/{job_id}/download/package")

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["status"] == "succeeded"
    assert detail["stage"] == "PACKAGE_ZIP"
    assert detail["artifacts"]["package_available"] is True
    assert detail["artifacts"]["package_download_url"] == f"/api/jobs/{job_id}/download/package"
    assert download_response.status_code == 200
    assert download_response.content == b"zip-result"
