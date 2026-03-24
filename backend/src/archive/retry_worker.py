from __future__ import annotations

import threading

from ..config import RuntimeConfig, get_config
from ..pipeline.group_manager import GroupManager
from .models import ArchiveStatus
from .service import ArchiveService


class ArchiveRetryWorker:
    def __init__(
        self,
        *,
        archive_service: ArchiveService,
        group_manager: GroupManager,
        config: RuntimeConfig | None = None,
    ) -> None:
        self.archive_service = archive_service
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

    def _loop(self) -> None:
        interval = max(int(self.config.management.archive_retry_interval_seconds), 1)
        while not self._stop_event.wait(interval):
            for group in self.group_manager.load_all_groups():
                if group.archive.status != ArchiveStatus.FAILED:
                    continue
                try:
                    self.archive_service.archive_group(group)
                except Exception as exc:  # noqa: BLE001
                    self.archive_service.mark_failed(group, str(exc))
