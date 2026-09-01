from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient as FastApiTestClient

from src.calculation_book.diagnostic_log import CalculationBookDiagnosticLog
from src.config import SpecLoader, reload_config
from src.models import Job, JobStatus, JobType
from src.pipeline.sqlite_queue import SQLiteQueueStore


class TestClient(FastApiTestClient):
    """Use the default administrator for tests of protected job endpoints."""

    def __enter__(self):
        client = super().__enter__()
        response = client.post(
            "/api/auth/login",
            json={"account_id": "hbjjswd", "password": "password"},
        )
        assert response.status_code == 200, response.text
        client.headers["Authorization"] = f"Bearer {response.json()['token']}"
        return client


class RecordingProcessor:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, job: Job) -> None:
        self.calls += 1
        raise AssertionError("API process must not execute queued work")


def test_worker_processor_routes_calculation_job_through_injected_executor(
    tmp_path: Path,
) -> None:
    from API.app.runtime import PipelineJobProcessor

    calls: list[Job] = []
    fake_executor = SimpleNamespace(execute=lambda job: calls.append(job))
    processor = PipelineJobProcessor(
        calculation_book_executor_factory=lambda: fake_executor,
    )
    job = Job(
        job_id="calculation-worker-job",
        job_type=JobType.CALCULATION_BOOK,
        project_no="JQ",
        work_dir=tmp_path,
    )

    processor(job)

    assert calls == [job]


def test_worker_processor_default_path_constructs_calculation_executor(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import API.app.runtime as runtime_module

    calls: list[Job] = []
    constructions: list[bool] = []

    def build_executor():
        constructions.append(True)
        return SimpleNamespace(execute=lambda job: calls.append(job))

    monkeypatch.setattr(runtime_module, "CalculationBookJobExecutor", build_executor)
    processor = runtime_module.PipelineJobProcessor()
    job = Job(
        job_id="calculation-default-worker-job",
        job_type=JobType.CALCULATION_BOOK,
        project_no="JQ",
        work_dir=tmp_path,
    )

    processor(job)

    assert constructions == [True]
    assert calls == [job]


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


def test_api_mode_summary_backfill_keeps_historical_updated_at(monkeypatch, tmp_path: Path) -> None:
    _configure_api_env(monkeypatch, tmp_path)
    from API.app.runtime import DeliverableApiRuntime

    storage_root = tmp_path / "storage"
    existing_job = Job(
        job_id="job-existing-old",
        job_type=JobType.DELIVERABLE,
        project_no="2016",
        status=JobStatus.SUCCEEDED,
        params=_deliverable_params(),
        source_filename="old-result.dwg",
        created_at=datetime(2026, 3, 27, 17, 16, 36),
        finished_at=datetime(2026, 3, 27, 17, 20, 0),
    )
    job_dir = storage_root / "jobs" / existing_job.job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "job.json").write_text(
        existing_job.model_dump_json(indent=2),
        encoding="utf-8",
    )

    runtime = DeliverableApiRuntime(
        job_processor=RecordingProcessor(),
        process_jobs_in_api=False,
    )
    runtime.queue_store.initialize()
    runtime._backfill_summary_index()

    store = SQLiteQueueStore(storage_root / "runtime" / "fanban_queue.sqlite3")
    [summary] = store.list_summaries()["items"]

    assert summary["created_at"].startswith("2026-03-27T17:16:36")
    assert summary["updated_at"].startswith("2026-03-27T17:20:00")


def test_api_mode_startup_does_not_block_on_summary_backfill(monkeypatch, tmp_path: Path) -> None:
    _configure_api_env(monkeypatch, tmp_path)
    from API.app.runtime import DeliverableApiRuntime

    runtime = DeliverableApiRuntime(
        job_processor=RecordingProcessor(),
        process_jobs_in_api=False,
    )
    backfill_called = threading.Event()

    def _slow_backfill() -> None:
        backfill_called.set()
        time.sleep(1.0)

    runtime._backfill_summary_index = _slow_backfill

    started_at = time.perf_counter()
    runtime.start()
    elapsed = time.perf_counter() - started_at
    try:
        assert elapsed < 0.5
        assert backfill_called.wait(timeout=1.0)
    finally:
        runtime.stop()


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


def test_jobs_activity_stream_emits_initial_and_changed_events() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from API.app.routers.jobs import _jobs_activity_event_stream

    class Runtime:
        def __init__(self) -> None:
            self.calls = 0

        def jobs_activity(self) -> dict[str, Any]:
            self.calls += 1
            if self.calls == 1:
                return {"total": 1, "active": 1, "last_changed_at": "2026-07-07T00:00:00"}
            return {"total": 1, "active": 0, "last_changed_at": "2026-07-07T00:00:03"}

    class Request:
        def __init__(self) -> None:
            self.disconnect_checks = 0

        async def is_disconnected(self) -> bool:
            self.disconnect_checks += 1
            return self.disconnect_checks > 4

    async def _collect() -> list[str]:
        chunks: list[str] = []
        stream = _jobs_activity_event_stream(
            SimpleNamespace(is_disconnected=Request().is_disconnected),
            Runtime(),
            poll_interval_sec=0.001,
            keepalive_sec=10,
            max_duration_sec=60,
            retry_ms=5000,
        )
        async for chunk in stream:
            chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
            if len(chunks) >= 2:
                break
        return chunks

    first, second = asyncio.run(_collect())

    assert "event: jobs_activity" in first
    assert "retry: 5000" in first
    assert 'id: "1:1:2026-07-07T00:00:00"' not in first
    assert "id: 1:1:2026-07-07T00:00:00" in first
    assert '"active":1' in first
    assert "id: 1:0:2026-07-07T00:00:03" in second
    assert '"active":0' in second


def test_jobs_activity_stream_closes_before_iis_requests_become_stale() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from API.app.routers.jobs import _jobs_activity_event_stream

    class Runtime:
        def jobs_activity(self) -> dict[str, Any]:
            return {"total": 1, "active": 1, "last_changed_at": "2026-07-07T00:00:00"}

    async def is_disconnected() -> bool:
        return False

    async def _collect() -> list[str]:
        chunks: list[str] = []
        stream = _jobs_activity_event_stream(
            SimpleNamespace(is_disconnected=is_disconnected),
            Runtime(),
            poll_interval_sec=0.001,
            keepalive_sec=10,
            max_duration_sec=0.001,
            retry_ms=5000,
        )
        async for chunk in stream:
            chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
        return chunks

    chunks = asyncio.run(asyncio.wait_for(_collect(), timeout=1))

    assert "event: jobs_activity" in chunks[0]
    assert "retry: 5000" in chunks[0]
    assert chunks[-1].startswith(": stream-close ")


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


def test_api_mode_reload_restores_ai_calculation_source_summary_and_log(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_api_env(monkeypatch, tmp_path)
    from API.app.main import create_app

    from src.config import get_config
    from src.pipeline.job_manager import JobManager

    manager = JobManager()
    job = manager.create_job(
        job_type=JobType.CALCULATION_BOOK.value,
        project_no="JQ",
        options={
            "mode": "calculation_book",
            "reinforcement_source": "ai_suggested",
            "ai_rebar_suggestion": True,
            "ai_reinforcement_normalization": False,
        },
        params={"reinforcement_source": "ai_suggested"},
        source_filename="cloud-images.rar",
    )
    job.work_dir = get_config().get_job_dir(job.job_id)
    log_path = (
        job.work_dir
        / "calculation-book"
        / "logs"
        / f"calculation-book-{job.job_id}.log"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with CalculationBookDiagnosticLog.create(
        log_path,
        job_id=job.job_id,
        correlation_id=job.job_id,
        max_bytes=8_192,
    ) as diagnostic_log:
        diagnostic_log.write(
            "task_completed",
            duration_ms=1,
            figure_count=1,
            warning_count=0,
            output_filename="result.docx",
        )
    job.artifacts.calculation_log = log_path
    job.progress.details["ai_rebar_suggestion"] = {
        "skill_id": "recommend-rebar-from-smx",
        "skill_version": "1.0.0",
        "skill_sha256": "b" * 64,
        "model": "structured-test",
        "call_count": 4,
        "suggested_direction_count": 12,
        "blank_direction_count": 1,
        "repair_round_count": 1,
        "validation": "passed_with_warnings",
    }
    job.mark_succeeded()
    manager.update_job(job)

    app = create_app(job_processor=RecordingProcessor(), process_jobs_in_api=False)
    with TestClient(app) as client:
        detail_response = client.get(f"/api/jobs/{job.job_id}")
        log_response = client.get(
            f"/api/jobs/{job.job_id}/download/calculation-book-log"
        )

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["calculation_book_output"]["reinforcement_source"] == (
        "ai_suggested"
    )
    assert detail["calculation_book_output"]["ai_rebar_suggestion"] == {
        "skill_id": "recommend-rebar-from-smx",
        "skill_version": "1.0.0",
        "skill_sha256": "b" * 64,
        "model": "structured-test",
        "call_count": 4,
        "suggested_direction_count": 12,
        "blank_direction_count": 1,
        "repair_round_count": 1,
        "validation": "passed_with_warnings",
    }
    assert detail["artifacts"]["calculation_log_available"] is True
    assert log_response.status_code == 200
    assert json.loads(log_response.content.splitlines()[-1])["event"] == (
        "task_completed"
    )
