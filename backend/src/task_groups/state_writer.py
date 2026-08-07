from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from ..models import TaskGroup
from ..pipeline.group_manager import GroupManager

logger = logging.getLogger(__name__)

SUMMARY_PUBLICATION_PENDING_KEY = "summary_publication_pending"
SUMMARY_PUBLICATION_ERROR_KEY = "summary_publication_last_error"


@dataclass(frozen=True)
class PublicationRetryReport:
    attempted: int = 0
    succeeded: int = 0
    failed_group_ids: tuple[str, ...] = ()


class TaskGroupStateWriter:
    """Persist group state and durably reconcile its SQLite summary."""

    def __init__(
        self,
        *,
        group_manager: GroupManager,
        publisher: Callable[[str], None],
    ) -> None:
        self.group_manager = group_manager
        self.publisher = publisher

    def write(self, group: TaskGroup) -> TaskGroup:
        group.metadata[SUMMARY_PUBLICATION_PENDING_KEY] = True
        group.metadata.pop(SUMMARY_PUBLICATION_ERROR_KEY, None)
        self.group_manager.update_group(group)
        self._publish_pending(group)
        return group

    def persist_without_publication(self, group: TaskGroup) -> TaskGroup:
        """Persist hidden reconciliation metadata with the manager CAS."""
        self.group_manager.update_group(group)
        return group

    def retry_pending_publications(self) -> PublicationRetryReport:
        attempted = 0
        succeeded = 0
        failed_group_ids: list[str] = []
        for group in self.group_manager.load_all_groups():
            if not group.metadata.get(SUMMARY_PUBLICATION_PENDING_KEY):
                continue
            attempted += 1
            try:
                self._publish_pending(group)
            except Exception:  # noqa: BLE001
                failed_group_ids.append(group.group_id)
                logger.exception("task-group summary publication retry failed: %s", group.group_id)
            else:
                succeeded += 1
        return PublicationRetryReport(
            attempted=attempted,
            succeeded=succeeded,
            failed_group_ids=tuple(failed_group_ids),
        )

    def _publish_pending(self, group: TaskGroup) -> None:
        try:
            self.publisher(group.group_id)
        except Exception as publish_error:
            group.metadata[SUMMARY_PUBLICATION_PENDING_KEY] = True
            group.metadata[SUMMARY_PUBLICATION_ERROR_KEY] = str(publish_error)
            try:
                self.group_manager.update_group(group)
            except Exception as persist_error:  # noqa: BLE001
                publish_error.add_note(f"failed to persist publication error: {persist_error}")
            raise

        group.metadata.pop(SUMMARY_PUBLICATION_PENDING_KEY, None)
        group.metadata.pop(SUMMARY_PUBLICATION_ERROR_KEY, None)
        try:
            self.group_manager.update_group(group)
        except Exception as persist_error:
            # The on-disk version still contains the pending marker. Restore the
            # in-memory object too so a same-process reconciliation can retry.
            group.metadata[SUMMARY_PUBLICATION_PENDING_KEY] = True
            group.metadata[SUMMARY_PUBLICATION_ERROR_KEY] = str(persist_error)
            raise
