from __future__ import annotations

from ..archive.models import ArchiveStatus
from ..archive.overwrite_service import ArchiveOverwriteService
from ..archive.service import ArchiveService
from ..models import JobStatus, TaskGroup
from ..workflow.models import WorkflowStatus
from ..workload.models import WorkloadSettlementStatus
from ..workload.settlement_service import WorkloadSettlementService
from .state_writer import TaskGroupStateWriter


class TaskGroupArchiveCoordinator:
    """Complete archive, settlement, group status and publication as one state transition."""

    def __init__(
        self,
        *,
        archive_service: ArchiveService,
        workload_settlement_service: WorkloadSettlementService,
        state_writer: TaskGroupStateWriter,
        settlement_trigger: str,
        overwrite_service: ArchiveOverwriteService | None = None,
    ) -> None:
        self.archive_service = archive_service
        self.workload_settlement_service = workload_settlement_service
        self.state_writer = state_writer
        self.settlement_trigger = settlement_trigger
        self.overwrite_service = overwrite_service

    def complete(self, group: TaskGroup) -> TaskGroup:
        if self._is_complete(group):
            return self.state_writer.write(group)

        try:
            self.archive_service.archive_group(group)
            if self._should_settle(group) and (
                group.workload.settlement_status is not WorkloadSettlementStatus.SETTLED
            ):
                self.workload_settlement_service.settle(group)
            if group.status is not JobStatus.SUCCEEDED:
                group.mark_succeeded()
            if self.overwrite_service is not None:
                self.overwrite_service.cleanup_replaced_group(group)
        except Exception as exc:  # noqa: BLE001
            self.archive_service.mark_failed(group, str(exc))
            group.mark_failed(str(exc))
        return self.state_writer.write(group)

    def _should_settle(self, group: TaskGroup) -> bool:
        if self.settlement_trigger == "archive_success":
            return group.archive.status is ArchiveStatus.SUCCEEDED
        if self.settlement_trigger == "approval_terminal":
            return True
        raise ValueError(f"unsupported workload settlement trigger: {self.settlement_trigger}")

    @staticmethod
    def _is_complete(group: TaskGroup) -> bool:
        return (
            group.archive.status is ArchiveStatus.SUCCEEDED
            and group.workflow.status is WorkflowStatus.ARCHIVED
            and group.status is JobStatus.SUCCEEDED
            and group.workload.settlement_status is WorkloadSettlementStatus.SETTLED
        )
