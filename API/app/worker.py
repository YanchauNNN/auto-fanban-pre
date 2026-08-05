from __future__ import annotations

import logging
import os
import signal
import sqlite3
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Callable

from .runtime import DeliverableApiRuntime

from src.cad import FontPreflightService
from src.config import load_mechanism_spec
from src.models import Job, JobStatus, TaskGroup
from src.pipeline.shared_prep import SharedPrepService
from src.pipeline.sqlite_queue import WORKER_INTERRUPTED_ERROR


logger = logging.getLogger(__name__)


class DeliverableWorkerRuntime:
    def __init__(
        self,
        *,
        worker_id: str | None = None,
        job_processor: Callable[[Job], None] | None = None,
        shared_prep_service: SharedPrepService | None = None,
        font_preflight_service: FontPreflightService | None = None,
        poll_interval_seconds: float = 0.5,
        heartbeat_interval_seconds: float | None = None,
        job_summary_sync_interval_seconds: float | None = None,
        heartbeat_retry_attempts: int = 5,
        heartbeat_retry_delay_seconds: float = 0.2,
        summary_sync_retry_attempts: int = 1,
        summary_sync_retry_delay_seconds: float = 0.2,
        stale_claim_timeout_seconds: float | None = None,
    ) -> None:
        self.worker_id = worker_id or f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.poll_interval_seconds = poll_interval_seconds
        api_runtime_cfg = None
        if (
            heartbeat_interval_seconds is None
            or job_summary_sync_interval_seconds is None
            or stale_claim_timeout_seconds is None
        ):
            api_runtime_cfg = load_mechanism_spec().api_runtime
        if heartbeat_interval_seconds is None:
            assert api_runtime_cfg is not None
            heartbeat_interval_seconds = float(api_runtime_cfg.worker_heartbeat_interval_sec)
        if job_summary_sync_interval_seconds is None:
            assert api_runtime_cfg is not None
            job_summary_sync_interval_seconds = float(
                getattr(api_runtime_cfg, "job_summary_sync_interval_sec", 3.0)
            )
        if stale_claim_timeout_seconds is None:
            assert api_runtime_cfg is not None
            stale_claim_timeout_seconds = float(api_runtime_cfg.worker_claim_timeout_sec)
        self.heartbeat_interval_seconds = float(heartbeat_interval_seconds)
        if self.heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat_interval_seconds must be greater than zero")
        self.job_summary_sync_interval_seconds = max(0.1, float(job_summary_sync_interval_seconds))
        self.stale_claim_timeout_seconds = float(stale_claim_timeout_seconds)
        if self.stale_claim_timeout_seconds <= 0:
            raise ValueError("stale_claim_timeout_seconds must be greater than zero")
        if self.stale_claim_timeout_seconds < 3 * self.heartbeat_interval_seconds:
            raise ValueError(
                "stale_claim_timeout_seconds must be at least three times "
                "heartbeat_interval_seconds"
            )
        self.heartbeat_retry_attempts = max(1, int(heartbeat_retry_attempts))
        self.heartbeat_retry_delay_seconds = max(0.0, float(heartbeat_retry_delay_seconds))
        self.summary_sync_retry_attempts = max(1, int(summary_sync_retry_attempts))
        self.summary_sync_retry_delay_seconds = max(0.0, float(summary_sync_retry_delay_seconds))
        self.runtime = DeliverableApiRuntime(
            job_processor=job_processor,
            shared_prep_service=shared_prep_service,
            font_preflight_service=font_preflight_service,
            process_jobs_in_api=True,
            worker_process_mode=True,
        )
        self.queue_store = self.runtime.queue_store
        self.queue_store.initialize()
        self._stop_event = threading.Event()
        self._heartbeat_lock = threading.Lock()
        self._heartbeat_state = "idle"
        self._heartbeat_current_item_type: str | None = None
        self._heartbeat_current_item_id: str | None = None
        self._heartbeat_message: str | None = None
        self._heartbeat(state="idle")
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"fanban-worker-heartbeat-{self.worker_id}",
            daemon=True,
        )
        self._heartbeat_thread.start()
        self._summary_sync_thread = threading.Thread(
            target=self._summary_sync_loop,
            name=f"fanban-worker-summary-sync-{self.worker_id}",
            daemon=True,
        )
        self._summary_sync_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._heartbeat_thread.join(timeout=3)
        self._summary_sync_thread.join(timeout=3)
        self.runtime.stop()

    def run_once(self) -> bool:
        self._heartbeat(state="polling")
        self._recover_stale_claims(now=datetime.now(UTC))
        item = self.queue_store.claim_next(
            worker_id=self.worker_id,
            now=datetime.now(UTC),
        )
        if item is None:
            self._heartbeat(state="idle")
            return False

        item_type = str(item["item_type"])
        item_id = str(item["item_id"])
        self._heartbeat(
            state="busy",
            current_item_type=item_type,
            current_item_id=item_id,
        )
        try:
            if item_type == "job":
                self.runtime._run_job(item_id)
                latest = self.runtime.job_manager.reload_job(item_id)
                terminal_statuses = {
                    JobStatus.SUCCEEDED,
                    JobStatus.FAILED,
                    JobStatus.CANCELLED,
                }
                if latest is not None and latest.status not in terminal_statuses:
                    self.runtime._wait_for_job_completion(item_id)
            elif item_type == "group":
                self.runtime._process_group(item_id)
            else:
                raise RuntimeError(f"unsupported queue item type: {item_type}")
            self.runtime.refresh_summary_index(item_type, item_id)
            self._finish_owned_claim(
                item,
                status="done",
            )
            self._heartbeat(state="idle")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.exception("worker failed queue item %s:%s", item_type, item_id)
            self._finish_owned_claim(
                item,
                status="failed",
                last_error=str(exc),
            )
            self._heartbeat(state="idle", message=str(exc))
            return True

    def _recover_stale_claims(self, *, now: datetime) -> None:
        recovered = self.queue_store.recover_stale_claims(
            timeout_seconds=self.stale_claim_timeout_seconds,
            now=now,
        )
        if recovered:
            logger.error(
                "recovered %s stale worker claim(s) as failed",
                len(recovered),
            )

        for item in self.queue_store.list_interrupted_claims():
            queue_item_id = int(item["id"])
            claimed_by = str(item["claimed_by"])
            try:
                if self._has_newer_attempt(item):
                    logger.warning(
                        "skipping superseded interrupted item %s:%s queue_id=%s",
                        item.get("item_type"),
                        item.get("item_id"),
                        queue_item_id,
                    )
                elif not self._finalize_interrupted_item(item):
                    continue
                self.queue_store.acknowledge_interrupted_claim(
                    queue_item_id=queue_item_id,
                    claimed_by=claimed_by,
                    now=datetime.now(UTC),
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "failed to reconcile interrupted queue item %s:%s",
                    item.get("item_type"),
                    item.get("item_id"),
                )
                continue

    def _finish_owned_claim(
        self,
        item: dict[str, object],
        *,
        status: str,
        last_error: str | None = None,
    ) -> bool:
        completed = self.queue_store.complete_claim(
            queue_item_id=int(item["id"]),
            worker_id=self.worker_id,
            status=status,
            last_error=last_error,
            now=datetime.now(UTC),
        )
        if completed is not None:
            return True

        current = self.queue_store.get_queue_item(int(item["id"]))
        if current is not None and current.get("last_error") == WORKER_INTERRUPTED_ERROR:
            current_owner = current.get("claimed_by")
            has_newer_attempt = self._has_newer_attempt(current)
            if not has_newer_attempt and current_owner in {None, self.worker_id}:
                self._finalize_interrupted_item(current)
            if current_owner == self.worker_id:
                self.queue_store.acknowledge_interrupted_claim(
                    queue_item_id=int(item["id"]),
                    claimed_by=self.worker_id,
                    now=datetime.now(UTC),
                )
        logger.warning(
            "worker completion rejected after claim ownership changed item=%s:%s queue_id=%s",
            item.get("item_type"),
            item.get("item_id"),
            item.get("id"),
        )
        return False

    def _has_newer_attempt(self, item: dict[str, object]) -> bool:
        return self.queue_store.has_newer_queue_item(
            item_type=str(item["item_type"]),
            item_id=str(item["item_id"]),
            after_queue_item_id=int(item["id"]),
        )

    def _finalize_interrupted_item(self, item: dict[str, object]) -> bool:
        item_type = str(item["item_type"])
        item_id = str(item["item_id"])
        if item_type == "job":
            job = self.runtime.job_manager.reload_job(item_id)
            if job is None:
                logger.warning("interrupted queue job metadata is missing: %s", item_id)
                return False
            if self._mark_interrupted(job):
                self.runtime.job_manager.update_job(job)
            self.runtime.refresh_summary_index("job", item_id)
            return True

        if item_type == "group":
            group = self.runtime.group_manager.reload_group(item_id)
            if group is None:
                logger.warning("interrupted queue group metadata is missing: %s", item_id)
                return False
            if self._mark_interrupted(group):
                self.runtime.group_manager.update_group(group)
            for child_id in group.child_job_ids:
                child = self.runtime.job_manager.reload_job(child_id)
                if child is None or child.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
                    continue
                if self._mark_interrupted(child):
                    self.runtime.job_manager.update_job(child)
                self.runtime.refresh_summary_index("job", child_id)
            self.runtime.refresh_summary_index("group", item_id)
            return True

        logger.warning("unsupported interrupted queue item type: %s", item_type)
        return False

    @staticmethod
    def _mark_interrupted(item: Job | TaskGroup) -> bool:
        expected_stage = "WORKER_INTERRUPTED"
        expected_message = "Worker 中断，任务未完成"
        already_reconciled = (
            item.status == JobStatus.FAILED
            and WORKER_INTERRUPTED_ERROR in item.errors
            and item.finished_at is not None
            and item.progress.stage == expected_stage
            and item.progress.message == expected_message
        )
        if already_reconciled:
            return False
        if WORKER_INTERRUPTED_ERROR not in item.errors:
            item.errors.append(WORKER_INTERRUPTED_ERROR)
        item.status = JobStatus.FAILED
        item.finished_at = datetime.now()
        item.progress.stage = expected_stage
        item.progress.message = expected_message
        return True

    def run_forever(self) -> None:
        while not self._stop_event.is_set():
            try:
                did_work = self.run_once()
            except sqlite3.OperationalError as exc:
                if not self._is_sqlite_locked_error(exc):
                    raise
                logger.warning("worker sqlite database is locked during queue polling; retrying: %s", exc)
                self._stop_event.wait(self.poll_interval_seconds)
                continue
            if not did_work:
                self._stop_event.wait(self.poll_interval_seconds)

    def _heartbeat(
        self,
        *,
        state: str,
        current_item_type: str | None = None,
        current_item_id: str | None = None,
        message: str | None = None,
    ) -> None:
        with self._heartbeat_lock:
            self._heartbeat_state = state
            self._heartbeat_current_item_type = current_item_type
            self._heartbeat_current_item_id = current_item_id
            self._heartbeat_message = message
            snapshot = self._heartbeat_snapshot_locked()
        self._write_heartbeat(snapshot)

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.wait(self.heartbeat_interval_seconds):
            with self._heartbeat_lock:
                snapshot = self._heartbeat_snapshot_locked()
            self._write_heartbeat(snapshot)

    def _summary_sync_loop(self) -> None:
        while not self._stop_event.wait(self.job_summary_sync_interval_seconds):
            with self._heartbeat_lock:
                snapshot = self._heartbeat_snapshot_locked()
            try:
                self._sync_current_summary(snapshot)
            except Exception:  # noqa: BLE001
                logger.exception("worker summary sync failed unexpectedly")

    def _heartbeat_snapshot_locked(self) -> tuple[str, str | None, str | None, str | None]:
        return (
            self._heartbeat_state,
            self._heartbeat_current_item_type,
            self._heartbeat_current_item_id,
            self._heartbeat_message,
        )

    def _write_heartbeat(self, snapshot: tuple[str, str | None, str | None, str | None]) -> None:
        state, current_item_type, current_item_id, message = snapshot
        attempts = max(1, int(getattr(self, "heartbeat_retry_attempts", 1)))
        delay_seconds = max(0.0, float(getattr(self, "heartbeat_retry_delay_seconds", 0.0)))
        last_error: sqlite3.OperationalError | None = None

        for attempt in range(1, attempts + 1):
            try:
                self.queue_store.upsert_worker_heartbeat(
                    worker_id=self.worker_id,
                    pid=os.getpid(),
                    state=state,
                    current_item_type=current_item_type,
                    current_item_id=current_item_id,
                    message=message,
                    now=datetime.now(UTC),
                )
                if current_item_type is not None and current_item_id is not None:
                    self.queue_store.heartbeat_claim(
                        self.worker_id,
                        current_item_type,
                        current_item_id,
                        now=datetime.now(UTC),
                    )
                return
            except sqlite3.OperationalError as exc:
                if not self._is_sqlite_locked_error(exc):
                    raise
                last_error = exc
                if attempt >= attempts:
                    break
                logger.warning(
                    "worker heartbeat sqlite lock; retrying attempt=%s/%s error=%s",
                    attempt,
                    attempts,
                    exc,
                )
                stop_event = getattr(self, "_stop_event", None)
                if delay_seconds <= 0:
                    continue
                if stop_event is not None:
                    if stop_event.wait(delay_seconds):
                        return
                else:
                    time.sleep(delay_seconds)

        logger.warning(
            "worker heartbeat skipped after sqlite lock retries attempts=%s error=%s",
            attempts,
            last_error,
        )

    def _sync_current_summary(
        self,
        snapshot: tuple[str, str | None, str | None, str | None],
    ) -> None:
        _state, current_item_type, current_item_id, _message = snapshot
        if current_item_type is None or current_item_id is None:
            return
        runtime = getattr(self, "runtime", None)
        if runtime is None:
            return

        attempts = max(1, int(getattr(self, "summary_sync_retry_attempts", 1)))
        delay_seconds = max(0.0, float(getattr(self, "summary_sync_retry_delay_seconds", 0.0)))
        last_error: sqlite3.OperationalError | None = None
        for attempt in range(1, attempts + 1):
            try:
                runtime.refresh_summary_index(current_item_type, current_item_id)
                return
            except sqlite3.OperationalError as exc:
                if not self._is_sqlite_locked_error(exc):
                    raise
                last_error = exc
                if attempt >= attempts:
                    break
                logger.warning(
                    "worker summary sync sqlite lock; retrying attempt=%s/%s item=%s:%s error=%s",
                    attempt,
                    attempts,
                    current_item_type,
                    current_item_id,
                    exc,
                )
                stop_event = getattr(self, "_stop_event", None)
                if delay_seconds <= 0:
                    continue
                if stop_event is not None:
                    if stop_event.wait(delay_seconds):
                        return
                else:
                    time.sleep(delay_seconds)

        logger.warning(
            "worker summary sync skipped after sqlite lock retries attempts=%s item=%s:%s error=%s",
            attempts,
            current_item_type,
            current_item_id,
            last_error,
        )

    @staticmethod
    def _is_sqlite_locked_error(exc: BaseException) -> bool:
        message = str(exc).lower()
        return (
            "database is locked" in message
            or "database table is locked" in message
            or "database schema is locked" in message
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    worker = DeliverableWorkerRuntime()

    def _request_stop(signum: int, frame: object) -> None:
        logger.info("received signal %s, stopping worker", signum)
        worker.stop()

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    worker.run_forever()


if __name__ == "__main__":
    main()
