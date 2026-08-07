from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.archive.models import ArchiveStatus
from src.models import JobStatus, TaskGroup
from src.task_groups.archive_coordinator import (
    TASK_GROUP_RECONCILIATION_ERROR_KEY,
    TaskGroupArchiveCoordinator,
)
from src.workflow.models import WorkflowStatus
from src.workload.models import WorkloadSettlementStatus


class _ArchiveService:
    def __init__(self) -> None:
        self.calls = 0

    def archive_group(self, group: TaskGroup) -> TaskGroup:
        self.calls += 1
        group.archive.status = ArchiveStatus.SUCCEEDED
        group.archive.completed_at = group.archive.completed_at or datetime.now()
        group.workflow.status = WorkflowStatus.ARCHIVED
        group.workflow.archive_status = "succeeded"
        return group

    def mark_failed(self, group: TaskGroup, error: str) -> TaskGroup:
        group.archive.status = ArchiveStatus.FAILED
        group.archive.last_error = error
        group.archive.retry_count += 1
        group.workflow.status = WorkflowStatus.ARCHIVE_FAILED
        return group


class _SettlementService:
    def __init__(self, *, failures: int = 0) -> None:
        self.failures = failures
        self.calls = 0

    def settle(self, group: TaskGroup) -> TaskGroup:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("settlement unavailable")
        group.workload.settlement_status = WorkloadSettlementStatus.SETTLED
        group.workload.settled_at = group.archive.completed_at
        return group


class _Writer:
    def __init__(
        self,
        *,
        storage_dir: Path,
        failures: int = 0,
        trace: list[str] | None = None,
    ) -> None:
        self.failures = failures
        self.calls = 0
        self.trace = trace
        self.group_manager = _MemoryGroupManager(storage_dir)

    def write(self, group: TaskGroup) -> TaskGroup:
        self.calls += 1
        if self.trace is not None:
            self.trace.append(f"write:{group.status.value}")
        if self.calls <= self.failures:
            raise RuntimeError("summary publish failed")
        self.group_manager.update_group(group)
        return group

    def persist_without_publication(self, group: TaskGroup) -> TaskGroup:
        self.group_manager.update_group(group)
        return group


class _MemoryGroupManager:
    def __init__(self, storage_dir: Path) -> None:
        self.config = SimpleNamespace(
            storage_dir=storage_dir,
            management=SimpleNamespace(
                task_group_lock_timeout_seconds=1.0,
                task_group_lock_poll_interval_seconds=0.01,
            ),
        )
        self._groups: dict[str, TaskGroup] = {}

    def update_group(self, group: TaskGroup) -> None:
        group.state_version += 1
        self._groups[group.group_id] = group.model_copy(deep=True)

    def reload_group(self, group_id: str) -> TaskGroup | None:
        group = self._groups.get(group_id)
        return group.model_copy(deep=True) if group is not None else None


class _OverwriteService:
    def __init__(self, *, failures: int = 0, trace: list[str] | None = None) -> None:
        self.failures = failures
        self.calls = 0
        self.trace = trace

    def cleanup_replaced_group(self, group: TaskGroup) -> None:
        self.calls += 1
        if self.trace is not None:
            self.trace.append("cleanup")
        if self.calls <= self.failures:
            raise RuntimeError("old child locked")


def _replacement_group() -> TaskGroup:
    return TaskGroup(
        group_id="group-new",
        project_no="2016",
        replacement={
            "replaced_group_id": "group-old",
            "replaced_record_pending_delete": True,
        },
    )


def _coordinator(
    *,
    archive: _ArchiveService,
    settlement: _SettlementService,
    writer: _Writer,
    overwrite: _OverwriteService | None = None,
) -> TaskGroupArchiveCoordinator:
    return TaskGroupArchiveCoordinator(
        archive_service=archive,
        workload_settlement_service=settlement,
        state_writer=writer,
        settlement_trigger="archive_success",
        overwrite_service=overwrite,
    )


def test_successor_is_durable_before_replaced_records_are_deleted(tmp_path: Path) -> None:
    trace: list[str] = []
    group = _replacement_group()
    coordinator = _coordinator(
        archive=_ArchiveService(),
        settlement=_SettlementService(),
        writer=_Writer(storage_dir=tmp_path, trace=trace),
        overwrite=_OverwriteService(trace=trace),
    )

    coordinator.complete(group)

    assert trace == ["write:succeeded", "cleanup", "write:succeeded"]
    assert group.replacement.replaced_record_pending_delete is False


def test_publish_failure_prevents_replaced_record_cleanup(tmp_path: Path) -> None:
    group = _replacement_group()
    overwrite = _OverwriteService()
    coordinator = _coordinator(
        archive=_ArchiveService(),
        settlement=_SettlementService(),
        writer=_Writer(storage_dir=tmp_path, failures=1),
        overwrite=overwrite,
    )

    with pytest.raises(RuntimeError, match="summary publish failed"):
        coordinator.complete(group)

    assert overwrite.calls == 0
    assert group.replacement.replaced_record_pending_delete is True


def test_direct_cleanup_refuses_incomplete_successor(tmp_path: Path) -> None:
    group = _replacement_group()
    overwrite = _OverwriteService()
    coordinator = _coordinator(
        archive=_ArchiveService(),
        settlement=_SettlementService(),
        writer=_Writer(storage_dir=tmp_path),
        overwrite=overwrite,
    )

    assert coordinator.retry_pending_replacement_cleanup(group) is False

    assert overwrite.calls == 0
    assert group.replacement.replaced_record_pending_delete is True


def test_cleanup_failure_keeps_successor_complete_and_pending_for_retry(tmp_path: Path) -> None:
    group = _replacement_group()
    archive = _ArchiveService()
    settlement = _SettlementService()
    overwrite = _OverwriteService(failures=1)
    writer = _Writer(storage_dir=tmp_path)
    coordinator = _coordinator(
        archive=archive,
        settlement=settlement,
        writer=writer,
        overwrite=overwrite,
    )

    coordinator.complete(group)

    assert group.archive.status is ArchiveStatus.SUCCEEDED
    assert group.workflow.status is WorkflowStatus.ARCHIVED
    assert group.workload.settlement_status is WorkloadSettlementStatus.SETTLED
    assert group.status is JobStatus.SUCCEEDED
    assert group.replacement.replaced_record_pending_delete is True
    assert group.metadata[TASK_GROUP_RECONCILIATION_ERROR_KEY] == {
        "stage": "replacement_cleanup",
        "message": "old child locked",
    }

    assert coordinator.retry_pending_replacement_cleanup(group) is True
    assert overwrite.calls == 2
    assert group.replacement.replaced_record_pending_delete is False
    assert TASK_GROUP_RECONCILIATION_ERROR_KEY not in group.metadata


def test_settlement_failure_does_not_recopy_archive_and_later_converges(tmp_path: Path) -> None:
    group = TaskGroup(group_id="group-1", project_no="2016")
    archive = _ArchiveService()
    settlement = _SettlementService(failures=1)
    writer = _Writer(storage_dir=tmp_path)
    coordinator = _coordinator(
        archive=archive,
        settlement=settlement,
        writer=writer,
    )

    coordinator.complete(group)

    assert archive.calls == 1
    assert group.archive.status is ArchiveStatus.SUCCEEDED
    assert group.workflow.status is WorkflowStatus.ARCHIVED
    assert group.status is JobStatus.FAILED
    assert group.workload.settlement_status is WorkloadSettlementStatus.PENDING
    assert group.metadata[TASK_GROUP_RECONCILIATION_ERROR_KEY]["stage"] == "settlement"

    coordinator.complete(group)

    assert archive.calls == 1
    assert settlement.calls == 2
    assert group.archive.status is ArchiveStatus.SUCCEEDED
    assert group.status is JobStatus.SUCCEEDED
    assert group.workload.settlement_status is WorkloadSettlementStatus.SETTLED
    assert TASK_GROUP_RECONCILIATION_ERROR_KEY not in group.metadata
