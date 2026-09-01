from __future__ import annotations

import logging
import threading

from ..config import RuntimeConfig, get_config
from ..pipeline.group_manager import GroupManager
from ..task_groups.archive_coordinator import TaskGroupArchiveCoordinator

logger = logging.getLogger(__name__)


class ArchiveRetryWorker:
    def __init__(
        self,
        *,
        archive_coordinator: TaskGroupArchiveCoordinator,
        group_manager: GroupManager,
        config: RuntimeConfig | None = None,
    ) -> None:
        self.archive_coordinator = archive_coordinator
        self.group_manager = group_manager
        self.config = config or get_config()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="archive-retry-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                logger.warning("archive retry worker did not stop")

    def _loop(self) -> None:
        interval = max(int(self.config.management.archive_retry_interval_seconds), 1)
        while not self._stop_event.wait(interval):
            try:
                self.run_once()
            except Exception:  # noqa: BLE001
                logger.exception("archive retry publication failed")

    def run_once(self) -> int:
        attempted = 0
        for group in self.group_manager.load_all_groups():
            if not self.archive_coordinator.needs_archive_reconciliation(group):
                continue
            attempted += 1
            try:
                self.archive_coordinator.complete(group)
            except Exception:  # noqa: BLE001
                logger.exception("archive reconciliation failed: %s", group.group_id)
        return attempted

    def retry_failed_once(self) -> int:
        return self.run_once()
