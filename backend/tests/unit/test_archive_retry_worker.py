from __future__ import annotations

from datetime import datetime

import pytest

from src.archive.models import ArchiveStatus
from src.archive.retry_worker import ArchiveRetryWorker
from src.models import JobStatus, TaskGroup
from src.task_groups.archive_coordinator import TaskGroupArchiveCoordinator
from src.workflow.models import WorkflowStatus
from src.workload.models import WorkloadContributorEntry, WorkloadSettlementStatus


class _GroupManager:
    def __init__(self, groups: list[TaskGroup]) -> None:
        self.groups = groups

    def load_all_groups(self) -> list[TaskGroup]:
        return self.groups


class _ArchiveService:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.attempts = 0

    def archive_group(self, group: TaskGroup) -> TaskGroup:
        self.attempts += 1
        if self.attempts <= self.failures:
            raise RuntimeError("archive unavailable")
        group.archive.status = ArchiveStatus.SUCCEEDED
        group.archive.completed_at = group.archive.completed_at or datetime.now()
        group.archive.last_error = None
        group.workflow.status = WorkflowStatus.ARCHIVED
        group.workflow.archive_status = "succeeded"
        return group

    def mark_failed(self, group: TaskGroup, error: str) -> TaskGroup:
        group.archive.status = ArchiveStatus.FAILED
        group.archive.last_error = error
        group.archive.retry_count += 1
        group.workflow.status = WorkflowStatus.ARCHIVE_FAILED
        group.workflow.archive_status = "failed"
        return group


class _SettlementService:
    def __init__(self) -> None:
        self.calls = 0

    def settle(self, group: TaskGroup) -> TaskGroup:
        self.calls += 1
        group.workload.settlement_status = WorkloadSettlementStatus.SETTLED
        group.workload.settled_at = group.archive.completed_at
        group.workload.contributor_entries.append(
            WorkloadContributorEntry(role_key="initiator", account_id="owner")
        )
        return group


class _Writer:
    def __init__(self) -> None:
        self.writes: list[str] = []

    def write(self, group: TaskGroup) -> TaskGroup:
        self.writes.append(group.group_id)
        return group


class _FailingWriter(_Writer):
    def write(self, group: TaskGroup) -> TaskGroup:
        super().write(group)
        raise RuntimeError("summary publish failed")


def _failed_group() -> TaskGroup:
    group = TaskGroup(group_id="group-1", project_no="2016")
    group.status = JobStatus.FAILED
    group.archive.status = ArchiveStatus.FAILED
    group.archive.retry_count = 1
    group.workflow.status = WorkflowStatus.ARCHIVE_FAILED
    return group


def _coordinator(archive_service: _ArchiveService, settlement: _SettlementService, writer: _Writer):
    return TaskGroupArchiveCoordinator(
        archive_service=archive_service,
        workload_settlement_service=settlement,
        state_writer=writer,
        settlement_trigger="archive_success",
    )


def test_retry_failed_once_completes_archive_workload_and_group() -> None:
    group = _failed_group()
    archive_service = _ArchiveService()
    settlement = _SettlementService()
    writer = _Writer()
    worker = ArchiveRetryWorker(
        archive_coordinator=_coordinator(archive_service, settlement, writer),
        group_manager=_GroupManager([group]),
    )

    assert worker.retry_failed_once() == 1

    assert group.archive.status is ArchiveStatus.SUCCEEDED
    assert group.workflow.status is WorkflowStatus.ARCHIVED
    assert group.status is JobStatus.SUCCEEDED
    assert group.workload.settlement_status is WorkloadSettlementStatus.SETTLED
    assert settlement.calls == 1
    assert writer.writes == [group.group_id]


def test_archive_completion_is_idempotent() -> None:
    group = _failed_group()
    archive_service = _ArchiveService()
    settlement = _SettlementService()
    writer = _Writer()
    coordinator = _coordinator(archive_service, settlement, writer)

    coordinator.complete(group)
    completed_at = group.archive.completed_at
    finished_at = group.finished_at
    contributors = list(group.workload.contributor_entries)
    coordinator.complete(group)

    assert archive_service.attempts == 1
    assert settlement.calls == 1
    assert group.archive.completed_at == completed_at
    assert group.finished_at == finished_at
    assert group.workload.contributor_entries == contributors


def test_retry_failed_once_persists_another_failed_attempt() -> None:
    group = _failed_group()
    archive_service = _ArchiveService(failures=1)
    settlement = _SettlementService()
    writer = _Writer()
    worker = ArchiveRetryWorker(
        archive_coordinator=_coordinator(archive_service, settlement, writer),
        group_manager=_GroupManager([group]),
    )

    assert worker.run_once() == 1

    assert group.archive.status is ArchiveStatus.FAILED
    assert group.workflow.status is WorkflowStatus.ARCHIVE_FAILED
    assert group.status is JobStatus.FAILED
    assert group.archive.retry_count == 2
    assert settlement.calls == 0
    assert writer.writes == [group.group_id]


def test_archive_completion_does_not_convert_publish_failure_into_archive_failure() -> None:
    group = _failed_group()
    archive_service = _ArchiveService()
    settlement = _SettlementService()
    writer = _FailingWriter()
    coordinator = _coordinator(archive_service, settlement, writer)

    with pytest.raises(RuntimeError, match="summary publish failed"):
        coordinator.complete(group)

    assert group.archive.status is ArchiveStatus.SUCCEEDED
    assert group.workflow.status is WorkflowStatus.ARCHIVED
    assert group.status is JobStatus.SUCCEEDED
    assert group.workload.settlement_status is WorkloadSettlementStatus.SETTLED


def test_retry_continues_with_later_groups_without_raising_one_publish_failure() -> None:
    first = _failed_group()
    second = _failed_group()
    second.group_id = "group-2"
    visited: list[str] = []

    class _Coordinator:
        def needs_archive_reconciliation(self, group: TaskGroup) -> bool:
            return group.archive.status is ArchiveStatus.FAILED

        def complete(self, group: TaskGroup) -> TaskGroup:
            visited.append(group.group_id)
            if group.group_id == first.group_id:
                raise RuntimeError("summary publish failed")
            group.archive.status = ArchiveStatus.SUCCEEDED
            return group

    worker = ArchiveRetryWorker(
        archive_coordinator=_Coordinator(),
        group_manager=_GroupManager([first, second]),
    )

    assert worker.run_once() == 2

    assert visited == ["group-1", "group-2"]
    assert second.archive.status is ArchiveStatus.SUCCEEDED


def test_retry_resumes_settlement_without_recopying_succeeded_archive() -> None:
    group = _failed_group()
    group.archive.status = ArchiveStatus.SUCCEEDED
    group.archive.completed_at = datetime.now()
    group.workflow.status = WorkflowStatus.ARCHIVED
    archive_service = _ArchiveService()
    settlement = _SettlementService()
    worker = ArchiveRetryWorker(
        archive_coordinator=_coordinator(archive_service, settlement, _Writer()),
        group_manager=_GroupManager([group]),
    )

    assert worker.run_once() == 1

    assert archive_service.attempts == 0
    assert settlement.calls == 1
    assert group.status is JobStatus.SUCCEEDED
    assert group.workload.settlement_status is WorkloadSettlementStatus.SETTLED


def test_archive_retry_loop_survives_one_run_once_exception() -> None:
    worker = ArchiveRetryWorker(
        archive_coordinator=_coordinator(_ArchiveService(), _SettlementService(), _Writer()),
        group_manager=_GroupManager([]),
    )
    calls = 0

    def _fail_once() -> int:
        nonlocal calls
        calls += 1
        raise RuntimeError("scan unavailable")

    class _StopAfterOneRun:
        def __init__(self) -> None:
            self.waits = 0

        def wait(self, _interval: int) -> bool:
            self.waits += 1
            return self.waits > 1

    worker.run_once = _fail_once  # type: ignore[method-assign]
    worker._stop_event = _StopAfterOneRun()  # type: ignore[assignment]

    worker._loop()

    assert calls == 1


def test_stop_warns_when_archive_retry_thread_does_not_exit(caplog) -> None:
    worker = ArchiveRetryWorker(
        archive_coordinator=_coordinator(_ArchiveService(), _SettlementService(), _Writer()),
        group_manager=_GroupManager([]),
    )

    class _StuckThread:
        def join(self, timeout: int) -> None:
            assert timeout == 2

        def is_alive(self) -> bool:
            return True

    worker._thread = _StuckThread()  # type: ignore[assignment]

    worker.stop()

    assert "archive retry worker did not stop" in caplog.text
