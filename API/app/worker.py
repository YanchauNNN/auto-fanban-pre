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
from src.models import Job, JobStatus
from src.pipeline.shared_prep import SharedPrepService


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
        heartbeat_interval_seconds: float = 10.0,
        heartbeat_retry_attempts: int = 5,
        heartbeat_retry_delay_seconds: float = 0.2,
    ) -> None:
        self.worker_id = worker_id or f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.poll_interval_seconds = poll_interval_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.heartbeat_retry_attempts = max(1, int(heartbeat_retry_attempts))
        self.heartbeat_retry_delay_seconds = max(0.0, float(heartbeat_retry_delay_seconds))
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

    def stop(self) -> None:
        self._stop_event.set()
        self._heartbeat_thread.join(timeout=3)
        self.runtime.stop()

    def run_once(self) -> bool:
        self._heartbeat(state="polling")
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
                if latest is not None and latest.status == JobStatus.RUNNING:
                    self.runtime._wait_for_job_completion(item_id)
            elif item_type == "group":
                self.runtime._process_group(item_id)
            else:
                raise RuntimeError(f"unsupported queue item type: {item_type}")
            self.runtime.refresh_summary_index(item_type, item_id)
            self.queue_store.complete(
                item_type,
                item_id,
                status="done",
                now=datetime.now(UTC),
            )
            self._heartbeat(state="idle")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.exception("worker failed queue item %s:%s", item_type, item_id)
            self.queue_store.complete(
                item_type,
                item_id,
                status="failed",
                last_error=str(exc),
                now=datetime.now(UTC),
            )
            self._heartbeat(state="idle", message=str(exc))
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
