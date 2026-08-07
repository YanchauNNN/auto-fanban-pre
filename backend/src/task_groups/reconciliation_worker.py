from __future__ import annotations

import logging
import os
import threading
import uuid
from dataclasses import dataclass

from ..config import RuntimeConfig, get_config
from ..pipeline.group_manager import GroupManager
from .archive_coordinator import TaskGroupArchiveCoordinator
from .state_writer import SUMMARY_PUBLICATION_PENDING_KEY, TaskGroupStateWriter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReconciliationRunReport:
    publication_attempted: int = 0
    cleanup_attempted: int = 0
    failed_group_ids: tuple[str, ...] = ()


class TaskGroupReconciliationWorker:
    """Retry durable summary publication and replacement cleanup markers."""

    def __init__(
        self,
        *,
        state_writer: TaskGroupStateWriter,
        archive_coordinator: TaskGroupArchiveCoordinator,
        group_manager: GroupManager,
        config: RuntimeConfig | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.state_writer = state_writer
        self.archive_coordinator = archive_coordinator
        self.group_manager = group_manager
        self.config = config or get_config()
        self.worker_id = worker_id or f"reconciliation-{os.getpid()}-{uuid.uuid4().hex}"
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def interval_seconds(self) -> int:
        return max(
            int(self.config.management.task_group_reconciliation_interval_seconds),
            1,
        )

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="task-group-reconciliation-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                logger.warning("task-group reconciliation worker did not stop")

    def _loop(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            try:
                self.run_once()
            except Exception:  # noqa: BLE001
                logger.exception("task-group reconciliation scan failed")

    def run_once(self) -> ReconciliationRunReport:
        publication_report = self.state_writer.retry_pending_publications()
        cleanup_attempted = 0
        failed_group_ids = list(publication_report.failed_group_ids)

        for group in self.group_manager.load_all_groups():
            if not group.replacement.replaced_record_pending_delete:
                continue
            # Cleanup is only safe after the complete successor summary has
            # been published. A pending publication is retried next cycle.
            if group.metadata.get(SUMMARY_PUBLICATION_PENDING_KEY):
                continue
            if not self.archive_coordinator.is_replacement_cleanup_ready(group):
                continue
            cleanup_attempted += 1
            try:
                self.archive_coordinator.retry_pending_replacement_cleanup(
                    group,
                    claim_owner=self.worker_id,
                )
            except Exception:  # noqa: BLE001
                if group.group_id not in failed_group_ids:
                    failed_group_ids.append(group.group_id)
                logger.exception("replacement cleanup reconciliation failed: %s", group.group_id)

        return ReconciliationRunReport(
            publication_attempted=publication_report.attempted,
            cleanup_attempted=cleanup_attempted,
            failed_group_ids=tuple(failed_group_ids),
        )
