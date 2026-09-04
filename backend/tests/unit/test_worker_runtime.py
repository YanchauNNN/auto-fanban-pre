from __future__ import annotations

import io
import json
import sqlite3
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from pypdf import PdfWriter

from src.calculation_book.diagnostic_log import CalculationBookDiagnosticLog
from src.config import SpecLoader, reload_config
from src.models import Job, JobStatus, JobType
from src.pipeline.group_manager import GroupManager
from src.pipeline.job_manager import JobManager
from src.pipeline.shared_prep import SharedPrepArtifacts
from src.pipeline.sqlite_queue import SQLiteQueueStore


class FlakyHeartbeatQueue:
    def __init__(self, *, fail_count: int) -> None:
        self.fail_count = fail_count
        self.heartbeat_calls = 0
        self.claim_calls = 0

    def upsert_worker_heartbeat(self, **kwargs: Any) -> dict[str, Any]:
        self.heartbeat_calls += 1
        if self.heartbeat_calls <= self.fail_count:
            raise sqlite3.OperationalError("database is locked")
        return {"worker_id": kwargs["worker_id"]}

    def heartbeat_claim(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.claim_calls += 1
        return {"item_id": args[2]}


def _bare_worker_with_queue(queue_store: Any) -> Any:
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from API.app.worker import DeliverableWorkerRuntime

    worker = DeliverableWorkerRuntime.__new__(DeliverableWorkerRuntime)
    worker.worker_id = "worker-test"
    worker.queue_store = queue_store
    worker.heartbeat_retry_attempts = 3
    worker.heartbeat_retry_delay_seconds = 0
    worker.summary_sync_retry_attempts = 1
    worker.summary_sync_retry_delay_seconds = 0
    worker._stop_event = threading.Event()
    return worker


class SlotBoundProcessor:
    def __init__(self) -> None:
        self.processed: list[str] = []

    def __call__(self, job: Job) -> None:
        self.execute_slot_bound_phase(job)

    def execute_slot_bound_phase(self, job: Job) -> None:
        self.processed.append(job.job_id)
        job.mark_running(stage="TEST_WORKER")
        job.progress.message = "processed by worker"
        job.mark_succeeded()
        return None


class NeverCalledProcessor:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, job: Job) -> None:
        self.calls += 1
        raise AssertionError(f"recovered job must not be executed again: {job.job_id}")


class BlockingSlotBoundProcessor:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(self, job: Job) -> None:
        self.execute_slot_bound_phase(job)

    def execute_slot_bound_phase(self, job: Job) -> None:
        job.mark_running(stage="TEST_WORKER")
        self.started.set()
        if not self.release.wait(timeout=3):
            raise TimeoutError("blocking processor was not released")
        job.mark_succeeded()
        return None


class BlockingCalculationProcessor:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(self, job: Job) -> None:
        self.started.set()
        if not self.release.wait(timeout=3):
            raise TimeoutError("calculation processor was not released")
        job.mark_running(stage="RENDER_CALCULATION_BOOK")
        job.progress.message = "calculation book ready"
        job.mark_succeeded()


class CalculationArtifactProcessor:
    def __call__(self, job: Job) -> None:
        assert job.options["reinforcement_source"] == "ai_suggested"
        job.mark_running(stage="AI_REBAR_SUGGESTION")
        work_dir = job.work_dir
        assert work_dir is not None
        log_path = (
            work_dir
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
            "skill_sha256": "c" * 64,
            "model": "structured-test",
            "call_count": 1,
            "suggested_direction_count": 3,
            "blank_direction_count": 0,
            "repair_round_count": 0,
            "validation": "passed",
        }
        job.mark_succeeded()


class DeferredDocProcessor:
    def __init__(self, package_path: Path) -> None:
        self.package_path = package_path
        self.slot_phase_finished = threading.Event()
        self.release_doc_phase = threading.Event()

    def __call__(self, job: Job) -> None:
        self.execute_slot_bound_phase(job)

    def execute_slot_bound_phase(self, job: Job):
        job.mark_running(stage="GENERATE_DOCS")
        job.progress.percent = 85
        job.progress.message = "waiting for deferred docs"
        self.slot_phase_finished.set()

        def _post_slot_work() -> None:
            if not self.release_doc_phase.wait(timeout=3):
                raise TimeoutError("deferred doc phase was not released")
            self.package_path.parent.mkdir(parents=True, exist_ok=True)
            self.package_path.write_bytes(b"package")
            latest = JobManager().reload_job(job.job_id) or job
            latest.artifacts.package_zip = self.package_path
            latest.progress.stage = "PACKAGE_ZIP"
            latest.progress.message = "package ready"
            latest.mark_succeeded()
            JobManager().update_job(latest)

        return _post_slot_work


class FakeCADSlotPool:
    def __init__(self, *, config: Any, slot_count: int) -> None:
        self.config = config
        self.slot_count = slot_count
        self.released: list[str] = []

    def acquire(self, job_id: str, timeout: int) -> Any:
        root = self.config.storage_dir / "fake-slot"
        return SimpleNamespace(
            slot_id="slot-1",
            slot_root=root,
            cad_version="2022",
            accoreconsole_exe=root / "accoreconsole.exe",
            profile_arg_path=root / "profile.arg",
            plotters_dir=root / "plotters",
            pmp_dir=root / "pmp",
            plot_styles_dir=root / "plot_styles",
            spool_dir=root / "spool",
            temp_dir=root / "temp",
        )

    def release(self, slot_id: str) -> None:
        self.released.append(slot_id)


class FakeSharedPrepService:
    def prepare(
        self,
        *,
        group_id: str,
        project_no: str | None = None,
        source_dwg: Path,
        shared_dir: Path,
        font_replace_policy: str = "none",
        font_replacement_font: str | None = None,
        font_replacement_fonts: dict[str, str] | None = None,
        font_compatibility_mode: bool = False,
        slot_runtime: dict[str, str] | None = None,
    ) -> SharedPrepArtifacts:
        shared_dir.mkdir(parents=True, exist_ok=True)
        staged_source = shared_dir / source_dwg.name
        staged_source.write_bytes(source_dwg.read_bytes())
        converted_dxf = shared_dir / "source_converted.dxf"
        converted_dxf.write_text("0\nEOF\n", encoding="utf-8")
        return SharedPrepArtifacts(
            shared_dir=shared_dir,
            source_input_dwg=staged_source,
            source_converted_dxf=converted_dxf,
            font_preflight_summary={
                "filename": staged_source.name,
                "status": "ok",
                "missing_fonts": [],
                "detected_style_count": 0,
                "missing_style_count": 0,
                "font_replacement_applied": False,
                "replacement_font": None,
                "replacement_fonts": {},
                "font_compatibility_mode": font_compatibility_mode,
                "replaced_style_count": 0,
            },
            frames=[],
            sheet_sets=[],
        )


def _configure_env(monkeypatch: Any, tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    monkeypatch.setenv("FANBAN_SPEC_PATH", str(repo_root / "documents" / "参数规范.yaml"))
    monkeypatch.setenv(
        "FANBAN_RUNTIME_SPEC_PATH",
        str(repo_root / "documents" / "参数规范_运行期.yaml"),
    )
    monkeypatch.setenv("FANBAN_STORAGE_DIR", str(tmp_path / "storage"))
    SpecLoader.clear_cache()
    reload_config()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def test_worker_run_once_claims_and_executes_queued_job(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    import API.app.runtime as runtime_mod

    monkeypatch.setattr(runtime_mod, "CADSlotPool", FakeCADSlotPool)

    manager = JobManager()
    job = manager.create_job(
        job_type=JobType.DELIVERABLE.value,
        project_no="2016",
        options={"enabled": True},
        params={},
    )
    manager.update_job(job)

    queue_store = SQLiteQueueStore(tmp_path / "storage" / "runtime" / "fanban_queue.sqlite3")
    queue_store.initialize()
    queue_store.enqueue("job", job.job_id)

    from API.app.worker import DeliverableWorkerRuntime

    processor = SlotBoundProcessor()
    worker = DeliverableWorkerRuntime(worker_id="worker-test", job_processor=processor)

    assert worker.run_once() is True

    persisted = manager.reload_job(job.job_id)
    assert persisted is not None
    assert persisted.status == JobStatus.SUCCEEDED
    assert processor.processed == [job.job_id]
    assert queue_store.list_queue_items()[0]["status"] == "done"


def test_worker_run_once_executes_change_page_extract_without_cad_slot(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_env(monkeypatch, tmp_path)

    archive_path = tmp_path / "storage" / "incoming" / "pages.zip"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(pdf)
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("附图1 第一份.pdf", pdf.getvalue())

    manager = JobManager()
    job = manager.create_job(
        job_type=JobType.CHANGE_PAGE_EXTRACT.value,
        project_no="",
        input_files=[archive_path],
        source_filename=archive_path.name,
        task_role="change_page_extract",
    )
    manager.update_job(job)

    queue_store = SQLiteQueueStore(tmp_path / "storage" / "runtime" / "fanban_queue.sqlite3")
    queue_store.initialize()
    queue_store.enqueue("job", job.job_id)

    from API.app.worker import DeliverableWorkerRuntime

    worker = DeliverableWorkerRuntime(worker_id="worker-change-page-test")
    try:
        assert worker.run_once() is True
    finally:
        worker.stop()

    persisted = manager.reload_job(job.job_id)
    assert persisted is not None
    assert persisted.status == JobStatus.SUCCEEDED
    assert persisted.slot_id is None
    assert persisted.artifacts.change_page_result_json is not None
    assert persisted.artifacts.change_page_result_json.is_file()
    assert queue_store.list_queue_items()[0]["status"] == "done"


def test_worker_constructor_rejects_timeout_shorter_than_three_heartbeats(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_env(monkeypatch, tmp_path)
    import API.app.runtime as runtime_mod

    monkeypatch.setattr(runtime_mod, "CADSlotPool", FakeCADSlotPool)
    from API.app.worker import DeliverableWorkerRuntime

    created_worker = None
    try:
        with pytest.raises(ValueError, match="three times heartbeat_interval_seconds"):
            created_worker = DeliverableWorkerRuntime(
                worker_id="worker-invalid-timing",
                heartbeat_interval_seconds=10,
                stale_claim_timeout_seconds=29,
            )
    finally:
        if created_worker is not None:
            created_worker.stop()


def test_worker_recovers_stale_calculation_claim_without_reopening_exclusive_log(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_env(monkeypatch, tmp_path)
    import API.app.runtime as runtime_mod

    monkeypatch.setattr(runtime_mod, "CADSlotPool", FakeCADSlotPool)

    manager = JobManager()
    job = manager.create_job(
        job_type=JobType.CALCULATION_BOOK.value,
        project_no="JQ",
        options={
            "mode": "calculation_book",
            "reinforcement_source": "ai_suggested",
        },
        params={"reinforcement_source": "ai_suggested"},
    )
    job.mark_running(stage="AI_REBAR_SUGGESTION")
    log_path = (
        tmp_path
        / "storage"
        / "jobs"
        / job.job_id
        / "calculation-book"
        / "logs"
        / f"calculation-book-{job.job_id}.log"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    original_log = b'{"event":"task_started"}\n'
    log_path.write_bytes(original_log)
    job.artifacts.calculation_log = log_path
    manager.update_job(job)

    queue_store = SQLiteQueueStore(
        tmp_path / "storage" / "runtime" / "fanban_queue.sqlite3"
    )
    queue_store.initialize()
    stale_at = datetime.now(UTC) - timedelta(minutes=5)
    queue_store.enqueue("job", job.job_id, now=stale_at)
    queue_store.claim_next(worker_id="worker-dead", now=stale_at)

    from API.app.worker import DeliverableWorkerRuntime

    processor = NeverCalledProcessor()
    worker = DeliverableWorkerRuntime(
        worker_id="worker-recovery",
        job_processor=processor,
        stale_claim_timeout_seconds=90,
    )
    try:
        assert worker.run_once() is False
    finally:
        worker.stop()

    persisted = manager.reload_job(job.job_id)
    assert persisted is not None
    assert persisted.status == JobStatus.FAILED
    assert persisted.errors.count("worker_interrupted_before_completion") == 1
    assert persisted.artifacts.calculation_log == log_path
    assert log_path.read_bytes() == original_log
    assert processor.calls == 0
    queue_item = queue_store.list_queue_items()[0]
    assert queue_item["status"] == "failed"
    assert queue_item["last_error"] == "worker_interrupted_before_completion"
    assert queue_item["attempt_count"] == 1
    assert queue_item["claimed_by"] is None

    first_finished_at = persisted.finished_at
    time.sleep(0.02)
    restarted_worker = DeliverableWorkerRuntime(
        worker_id="worker-restarted",
        job_processor=processor,
        stale_claim_timeout_seconds=90,
    )
    try:
        assert restarted_worker.run_once() is False
    finally:
        restarted_worker.stop()
    after_restart = manager.reload_job(job.job_id)
    assert after_restart is not None
    assert after_restart.finished_at == first_finished_at


def test_worker_recovers_stale_group_and_nonterminal_children(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    import API.app.runtime as runtime_mod

    monkeypatch.setattr(runtime_mod, "CADSlotPool", FakeCADSlotPool)

    group_manager = GroupManager()
    job_manager = JobManager()
    group = group_manager.create_group(
        batch_id="batch-stale",
        source_filenames=["stale.dwg"],
        project_no="2016",
        run_audit_check=False,
    )
    child = job_manager.create_job(
        job_type=JobType.DELIVERABLE.value,
        project_no="2016",
        group_id=group.group_id,
    )
    child.mark_running(stage="GENERATE_DOCS")
    job_manager.update_job(child)
    group.child_job_ids = [child.job_id]
    group.mark_running("DOCS_AND_PACKAGE")
    group_manager.update_group(group)

    queue_store = SQLiteQueueStore(
        tmp_path / "storage" / "runtime" / "fanban_queue.sqlite3"
    )
    queue_store.initialize()
    stale_at = datetime.now(UTC) - timedelta(minutes=5)
    queue_store.enqueue("group", group.group_id, now=stale_at)
    queue_store.claim_next(worker_id="worker-dead", now=stale_at)

    from API.app.worker import DeliverableWorkerRuntime

    processor = NeverCalledProcessor()
    worker = DeliverableWorkerRuntime(
        worker_id="worker-recovery",
        job_processor=processor,
        stale_claim_timeout_seconds=90,
    )
    try:
        assert worker.run_once() is False
    finally:
        worker.stop()

    recovered_group = group_manager.reload_group(group.group_id)
    recovered_child = job_manager.reload_job(child.job_id)
    assert recovered_group is not None
    assert recovered_group.status == JobStatus.FAILED
    assert recovered_group.errors.count("worker_interrupted_before_completion") == 1
    assert recovered_child is not None
    assert recovered_child.status == JobStatus.FAILED
    assert recovered_child.errors.count("worker_interrupted_before_completion") == 1
    assert processor.calls == 0


def test_interrupted_reconciliation_is_idempotent_when_worker_crashes_before_ack(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_env(monkeypatch, tmp_path)
    manager = JobManager()
    job = manager.create_job(
        job_type=JobType.CALCULATION_BOOK.value,
        project_no="JQ",
    )
    job.mark_running(stage="RENDER_CALCULATION_BOOK")
    manager.update_job(job)

    queue_store = SQLiteQueueStore(
        tmp_path / "storage" / "runtime" / "fanban_queue.sqlite3"
    )
    queue_store.initialize()
    stale_at = datetime.now(UTC) - timedelta(minutes=5)
    queue_store.enqueue("job", job.job_id, now=stale_at)
    queue_store.claim_next(worker_id="worker-dead", now=stale_at)
    interrupted = queue_store.recover_stale_claims(
        timeout_seconds=90,
        now=datetime.now(UTC),
    )[0]

    from API.app.worker import DeliverableWorkerRuntime

    crashed_worker = DeliverableWorkerRuntime.__new__(DeliverableWorkerRuntime)
    crashed_worker.queue_store = queue_store
    crashed_worker.runtime = SimpleNamespace(
        job_manager=manager,
        group_manager=GroupManager(),
        refresh_summary_index=lambda *_args: None,
    )
    assert crashed_worker._finalize_interrupted_item(interrupted) is True
    first_finished_at = manager.reload_job(job.job_id).finished_at
    assert queue_store.list_interrupted_claims()

    restarted_worker = DeliverableWorkerRuntime.__new__(DeliverableWorkerRuntime)
    restarted_worker.worker_id = "worker-restarted"
    restarted_worker.queue_store = queue_store
    restarted_worker.stale_claim_timeout_seconds = 90
    restarted_worker.runtime = crashed_worker.runtime
    time.sleep(0.02)
    restarted_worker._recover_stale_claims(now=datetime.now(UTC))

    persisted = manager.reload_job(job.job_id)
    assert persisted is not None
    assert persisted.finished_at == first_finished_at
    assert queue_store.list_interrupted_claims() == []


def test_late_worker_after_ack_without_retry_reasserts_interrupted_job_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_env(monkeypatch, tmp_path)
    manager = JobManager()
    job = manager.create_job(
        job_type=JobType.CALCULATION_BOOK.value,
        project_no="JQ",
    )
    job.mark_running(stage="RENDER_CALCULATION_BOOK")
    manager.update_job(job)

    queue_store = SQLiteQueueStore(
        tmp_path / "storage" / "runtime" / "fanban_queue.sqlite3"
    )
    queue_store.initialize()
    stale_at = datetime.now(UTC) - timedelta(minutes=5)
    queue_store.enqueue("job", job.job_id, now=stale_at)
    stale_claim = queue_store.claim_next(worker_id="worker-old", now=stale_at)

    from API.app.worker import DeliverableWorkerRuntime

    recovery_worker = DeliverableWorkerRuntime.__new__(DeliverableWorkerRuntime)
    recovery_worker.worker_id = "worker-recovery"
    recovery_worker.queue_store = queue_store
    recovery_worker.stale_claim_timeout_seconds = 90
    recovery_worker.runtime = SimpleNamespace(
        job_manager=manager,
        group_manager=GroupManager(),
        refresh_summary_index=lambda *_args: None,
    )
    recovery_worker._recover_stale_claims(now=datetime.now(UTC))
    assert queue_store.get_queue_item(stale_claim["id"])["claimed_by"] is None

    late_job = manager.reload_job(job.job_id)
    assert late_job is not None
    late_job.mark_succeeded()
    manager.update_job(late_job)

    worker = DeliverableWorkerRuntime.__new__(DeliverableWorkerRuntime)
    worker.worker_id = "worker-old"
    worker.queue_store = queue_store
    worker.runtime = SimpleNamespace(
        job_manager=manager,
        group_manager=GroupManager(),
        refresh_summary_index=lambda *_args: None,
    )

    assert worker._finish_owned_claim(stale_claim, status="done") is False
    persisted = manager.reload_job(job.job_id)
    assert persisted is not None
    assert persisted.status == JobStatus.FAILED
    assert persisted.errors.count("worker_interrupted_before_completion") == 1


def test_newer_retry_fences_acknowledged_interruption_and_late_old_worker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_env(monkeypatch, tmp_path)
    manager = JobManager()
    job = manager.create_job(
        job_type=JobType.CALCULATION_BOOK.value,
        project_no="JQ",
    )
    job.mark_running(stage="RENDER_CALCULATION_BOOK")
    manager.update_job(job)

    queue_store = SQLiteQueueStore(
        tmp_path / "storage" / "runtime" / "fanban_queue.sqlite3"
    )
    queue_store.initialize()
    stale_at = datetime.now(UTC) - timedelta(minutes=5)
    queue_store.enqueue("job", job.job_id, now=stale_at)
    stale_claim = queue_store.claim_next(worker_id="worker-old", now=stale_at)

    from API.app.worker import DeliverableWorkerRuntime

    recovery_worker = DeliverableWorkerRuntime.__new__(DeliverableWorkerRuntime)
    recovery_worker.worker_id = "worker-recovery"
    recovery_worker.queue_store = queue_store
    recovery_worker.stale_claim_timeout_seconds = 90
    recovery_worker.runtime = SimpleNamespace(
        job_manager=manager,
        group_manager=GroupManager(),
        refresh_summary_index=lambda *_args: None,
    )
    recovery_worker._recover_stale_claims(now=datetime.now(UTC))

    queue_store.enqueue("job", job.job_id, now=datetime.now(UTC))
    retry_claim = queue_store.claim_next(worker_id="worker-new", now=datetime.now(UTC))
    retried_job = manager.reload_job(job.job_id)
    assert retried_job is not None
    retried_job.mark_succeeded()
    manager.update_job(retried_job)

    old_worker = DeliverableWorkerRuntime.__new__(DeliverableWorkerRuntime)
    old_worker.worker_id = "worker-old"
    old_worker.queue_store = queue_store
    old_worker.runtime = SimpleNamespace(
        job_manager=manager,
        group_manager=GroupManager(),
        refresh_summary_index=lambda *_args: None,
    )

    assert old_worker._finish_owned_claim(stale_claim, status="done") is False
    persisted = manager.reload_job(job.job_id)
    assert persisted is not None
    assert persisted.status == JobStatus.SUCCEEDED
    assert queue_store.get_queue_item(retry_claim["id"])["status"] == "claimed"


def test_worker_heartbeat_retries_transient_sqlite_lock() -> None:
    queue_store = FlakyHeartbeatQueue(fail_count=1)
    worker = _bare_worker_with_queue(queue_store)

    worker._write_heartbeat(("busy", "job", "job-1", None))

    assert queue_store.heartbeat_calls == 2
    assert queue_store.claim_calls == 1


def test_worker_summary_sync_skips_sqlite_lock_without_crashing() -> None:
    queue_store = FlakyHeartbeatQueue(fail_count=0)
    worker = _bare_worker_with_queue(queue_store)
    calls: list[tuple[str, str]] = []

    def _refresh(item_type: str, item_id: str) -> None:
        calls.append((item_type, item_id))
        raise sqlite3.OperationalError("database is locked")

    worker.runtime = SimpleNamespace(refresh_summary_index=_refresh)

    worker._sync_current_summary(("busy", "job", "job-1", None))

    assert calls == [("job", "job-1")]


def test_worker_heartbeat_skips_persistent_sqlite_lock_without_crashing() -> None:
    queue_store = FlakyHeartbeatQueue(fail_count=10)
    worker = _bare_worker_with_queue(queue_store)
    worker.heartbeat_retry_attempts = 2

    worker._write_heartbeat(("polling", None, None, None))

    assert queue_store.heartbeat_calls == 2
    assert queue_store.claim_calls == 0


def test_worker_refreshes_heartbeats_while_processing_long_item(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    import API.app.runtime as runtime_mod

    monkeypatch.setattr(runtime_mod, "CADSlotPool", FakeCADSlotPool)

    manager = JobManager()
    job = manager.create_job(
        job_type=JobType.DELIVERABLE.value,
        project_no="2016",
        options={"enabled": True},
        params={},
    )
    manager.update_job(job)

    queue_store = SQLiteQueueStore(tmp_path / "storage" / "runtime" / "fanban_queue.sqlite3")
    queue_store.initialize()
    queue_store.enqueue("job", job.job_id)

    from API.app.worker import DeliverableWorkerRuntime

    processor = BlockingSlotBoundProcessor()
    worker = DeliverableWorkerRuntime(
        worker_id="worker-test",
        job_processor=processor,
        heartbeat_interval_seconds=0.05,
    )
    result: dict[str, bool] = {}
    worker_thread = threading.Thread(
        target=lambda: result.setdefault("processed", worker.run_once()),
        daemon=True,
    )
    worker_thread.start()

    assert processor.started.wait(timeout=2)
    initial_worker_seen = queue_store.worker_status(max_age_seconds=3600)["last_seen_at"]
    initial_queue_heartbeat = queue_store.list_queue_items(status="claimed")[0]["heartbeat_at"]

    time.sleep(0.2)

    refreshed_worker_seen = queue_store.worker_status(max_age_seconds=3600)["last_seen_at"]
    refreshed_queue_heartbeat = queue_store.list_queue_items(status="claimed")[0]["heartbeat_at"]
    assert queue_store.recover_stale_claims(
        timeout_seconds=1,
        now=datetime.now(UTC),
    ) == []
    processor.release.set()
    worker_thread.join(timeout=2)
    worker.stop()

    assert result == {"processed": True}
    assert refreshed_worker_seen != initial_worker_seen
    assert refreshed_queue_heartbeat != initial_queue_heartbeat


def test_worker_heartbeat_refreshes_running_job_summary(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    import API.app.runtime as runtime_mod

    monkeypatch.setattr(runtime_mod, "CADSlotPool", FakeCADSlotPool)

    manager = JobManager()
    job = manager.create_job(
        job_type=JobType.DELIVERABLE.value,
        project_no="2016",
        options={"enabled": True},
        params={},
    )
    manager.update_job(job)

    queue_store = SQLiteQueueStore(tmp_path / "storage" / "runtime" / "fanban_queue.sqlite3")
    queue_store.initialize()
    queue_store.enqueue("job", job.job_id)

    from API.app.worker import DeliverableWorkerRuntime

    processor = BlockingSlotBoundProcessor()
    worker = DeliverableWorkerRuntime(
        worker_id="worker-test",
        job_processor=processor,
        heartbeat_interval_seconds=10.0,
        job_summary_sync_interval_seconds=0.05,
    )
    worker.runtime.refresh_summary_index("job", job.job_id)
    initial_summary = queue_store.list_summaries()["items"][0]
    assert initial_summary["status"] == "queued"

    result: dict[str, bool] = {}
    worker_thread = threading.Thread(
        target=lambda: result.setdefault("processed", worker.run_once()),
        daemon=True,
    )
    worker_thread.start()

    assert processor.started.wait(timeout=2)
    running_summary = initial_summary
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        running_summary = queue_store.list_summaries()["items"][0]
        if running_summary["status"] == "running":
            break
        time.sleep(0.02)

    processor.release.set()
    worker_thread.join(timeout=2)
    worker.stop()

    assert result == {"processed": True}
    assert running_summary["status"] == "running"
    assert running_summary["stage"] == "TEST_WORKER"


def test_worker_run_once_executes_group_children_inside_worker(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    import API.app.runtime as runtime_mod

    monkeypatch.setattr(runtime_mod, "CADSlotPool", FakeCADSlotPool)
    monkeypatch.setattr(
        runtime_mod,
        "load_mechanism_spec",
        lambda: SimpleNamespace(
            api_runtime=SimpleNamespace(job_completion_wait_timeout_sec=0.2)
        ),
    )

    source_dwg = tmp_path / "source.dwg"
    source_dwg.write_bytes(b"dwg")

    group_manager = GroupManager()
    job_manager = JobManager()
    group = group_manager.create_group(
        batch_id="batch-1",
        source_filenames=[source_dwg.name],
        project_no="2016",
        run_audit_check=True,
    )
    group.metadata["source_input_path"] = str(source_dwg)
    group.shared_dir = tmp_path / "storage" / "groups" / group.group_id / "shared" / "source"

    deliverable_job = job_manager.create_job(
        job_type=JobType.DELIVERABLE.value,
        project_no="2016",
        options={"enabled": True},
        params={},
        batch_id="batch-1",
        source_filename=source_dwg.name,
        group_id=group.group_id,
        task_role="deliverable_main",
        shared_run_id=group.shared_run_id,
    )
    audit_job = job_manager.create_job(
        job_type=JobType.AUDIT_REPLACE.value,
        project_no="2016",
        options={"mode": "check"},
        params={},
        batch_id="batch-1",
        source_filename=source_dwg.name,
        group_id=group.group_id,
        task_role="audit_check",
        shared_run_id=group.shared_run_id,
    )
    group.child_job_ids = [deliverable_job.job_id, audit_job.job_id]
    group_manager.update_group(group)

    queue_store = SQLiteQueueStore(tmp_path / "storage" / "runtime" / "fanban_queue.sqlite3")
    queue_store.initialize()
    queue_store.enqueue("group", group.group_id)

    from API.app.worker import DeliverableWorkerRuntime

    processor = SlotBoundProcessor()
    worker = DeliverableWorkerRuntime(
        worker_id="worker-test",
        job_processor=processor,
        shared_prep_service=FakeSharedPrepService(),
    )

    assert worker.run_once() is True

    fresh_group = GroupManager().get_group(group.group_id)
    fresh_jobs = [JobManager().get_job(job_id) for job_id in group.child_job_ids]
    assert fresh_group is not None
    assert fresh_group.status == JobStatus.SUCCEEDED
    assert [job.status for job in fresh_jobs if job is not None] == [
        JobStatus.SUCCEEDED,
        JobStatus.SUCCEEDED,
    ]
    assert set(processor.processed) == {deliverable_job.job_id, audit_job.job_id}
    assert queue_store.list_queue_items()[0]["status"] == "done"


def test_worker_waits_for_deferred_doc_phase_before_completing_queue_item(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_env(monkeypatch, tmp_path)
    import API.app.runtime as runtime_mod

    monkeypatch.setattr(runtime_mod, "CADSlotPool", FakeCADSlotPool)

    manager = JobManager()
    job = manager.create_job(
        job_type=JobType.DELIVERABLE.value,
        project_no="2016",
        options={"enabled": True},
        params={},
    )
    manager.update_job(job)

    queue_store = SQLiteQueueStore(tmp_path / "storage" / "runtime" / "fanban_queue.sqlite3")
    queue_store.initialize()
    queue_store.enqueue("job", job.job_id)

    from API.app.worker import DeliverableWorkerRuntime

    package_path = tmp_path / "storage" / "jobs" / job.job_id / "package.zip"
    processor = DeferredDocProcessor(package_path)
    worker = DeliverableWorkerRuntime(
        worker_id="worker-test",
        job_processor=processor,
        heartbeat_interval_seconds=0.05,
    )
    result: dict[str, bool] = {}
    worker_thread = threading.Thread(
        target=lambda: result.setdefault("processed", worker.run_once()),
        daemon=True,
    )
    worker_thread.start()

    assert processor.slot_phase_finished.wait(timeout=2)
    time.sleep(0.1)

    assert result == {}
    claimed_items = queue_store.list_queue_items(status="claimed")
    assert [(item["item_type"], item["item_id"]) for item in claimed_items] == [
        ("job", job.job_id)
    ]

    processor.release_doc_phase.set()
    worker_thread.join(timeout=2)
    worker.stop()

    assert result == {"processed": True}
    persisted = manager.reload_job(job.job_id)
    assert persisted is not None
    assert persisted.status == JobStatus.SUCCEEDED
    assert persisted.artifacts.package_zip == package_path
    assert queue_store.list_queue_items()[0]["status"] == "done"
    summary = queue_store.list_summaries()["items"][0]
    assert summary["status"] == "succeeded"
    assert summary["stage"] == "PACKAGE_ZIP"
    assert summary["artifacts"]["package_available"] is True


def test_worker_waits_when_calculation_doc_thread_has_not_persisted_running_status(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_env(monkeypatch, tmp_path)
    import API.app.runtime as runtime_mod

    monkeypatch.setattr(runtime_mod, "CADSlotPool", FakeCADSlotPool)

    manager = JobManager()
    job = manager.create_job(
        job_type=JobType.CALCULATION_BOOK.value,
        project_no="2016",
        options={"mode": "calculation_book"},
        params={},
    )
    manager.update_job(job)

    queue_store = SQLiteQueueStore(
        tmp_path / "storage" / "runtime" / "fanban_queue.sqlite3"
    )
    queue_store.initialize()
    queue_store.enqueue("job", job.job_id)

    from API.app.worker import DeliverableWorkerRuntime

    processor = BlockingCalculationProcessor()
    worker = DeliverableWorkerRuntime(
        worker_id="worker-test",
        job_processor=processor,
        heartbeat_interval_seconds=0.05,
    )
    result: dict[str, bool] = {}
    worker_thread = threading.Thread(
        target=lambda: result.setdefault("processed", worker.run_once()),
        daemon=True,
    )
    worker_thread.start()

    assert processor.started.wait(timeout=2)
    time.sleep(0.1)
    assert result == {}
    assert queue_store.list_queue_items(status="claimed")

    processor.release.set()
    worker_thread.join(timeout=2)
    worker.stop()

    assert result == {"processed": True}
    summary = queue_store.list_summaries()["items"][0]
    assert summary["status"] == "succeeded"
    assert summary["stage"] == "RENDER_CALCULATION_BOOK"


def test_worker_persists_ai_calculation_source_summary_and_log_artifact(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_env(monkeypatch, tmp_path)
    import API.app.runtime as runtime_mod

    monkeypatch.setattr(runtime_mod, "CADSlotPool", FakeCADSlotPool)

    manager = JobManager()
    job = manager.create_job(
        job_type=JobType.CALCULATION_BOOK.value,
        project_no="JQ",
        options={
            "mode": "calculation_book",
            "reinforcement_source": "ai_suggested",
            "ai_rebar_suggestion": True,
        },
        params={"reinforcement_source": "ai_suggested"},
    )
    manager.update_job(job)

    queue_store = SQLiteQueueStore(
        tmp_path / "storage" / "runtime" / "fanban_queue.sqlite3"
    )
    queue_store.initialize()
    queue_store.enqueue("job", job.job_id)

    from API.app.worker import DeliverableWorkerRuntime

    worker = DeliverableWorkerRuntime(
        worker_id="worker-test",
        job_processor=CalculationArtifactProcessor(),
        heartbeat_interval_seconds=0.05,
    )
    try:
        assert worker.run_once() is True
    finally:
        worker.stop()

    persisted = manager.reload_job(job.job_id)
    assert persisted is not None
    assert persisted.status == JobStatus.SUCCEEDED
    assert persisted.options["reinforcement_source"] == "ai_suggested"
    assert persisted.artifacts.calculation_log is not None
    persisted_log = persisted.artifacts.calculation_log.read_bytes()
    assert json.loads(persisted_log.splitlines()[-1])["event"] == (
        "task_completed"
    )
    assert persisted.progress.details["ai_rebar_suggestion"][
        "suggested_direction_count"
    ] == 3
    summary = queue_store.list_summaries()["items"][0]
    assert summary["status"] == "succeeded"
    assert summary["artifacts"]["calculation_log_available"] is True
