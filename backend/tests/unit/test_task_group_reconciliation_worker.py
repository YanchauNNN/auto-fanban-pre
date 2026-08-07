from __future__ import annotations

from types import SimpleNamespace

from src.archive.models import ArchiveStatus
from src.models import JobStatus, TaskGroup
from src.task_groups.reconciliation_worker import TaskGroupReconciliationWorker
from src.task_groups.state_writer import (
    SUMMARY_PUBLICATION_PENDING_KEY,
    PublicationRetryReport,
)
from src.workflow.models import WorkflowStatus
from src.workload.models import WorkloadSettlementStatus


class _GroupManager:
    def __init__(self, groups: list[TaskGroup]) -> None:
        self.groups = groups

    def load_all_groups(self) -> list[TaskGroup]:
        return self.groups


class _StateWriter:
    def __init__(self, groups: list[TaskGroup]) -> None:
        self.groups = groups
        self.calls = 0

    def retry_pending_publications(self) -> PublicationRetryReport:
        self.calls += 1
        attempted = 0
        for group in self.groups:
            if group.metadata.pop(SUMMARY_PUBLICATION_PENDING_KEY, None):
                attempted += 1
        return PublicationRetryReport(attempted=attempted, succeeded=attempted)


class _Coordinator:
    def __init__(self, failing_group_id: str | None = None) -> None:
        self.failing_group_id = failing_group_id
        self.visited: list[str] = []

    def is_replacement_cleanup_ready(self, group: TaskGroup) -> bool:
        return (
            group.archive.status is ArchiveStatus.SUCCEEDED
            and group.workflow.status is WorkflowStatus.ARCHIVED
            and group.workload.settlement_status is WorkloadSettlementStatus.SETTLED
            and group.status is JobStatus.SUCCEEDED
            and not group.metadata.get(SUMMARY_PUBLICATION_PENDING_KEY)
        )

    def retry_pending_replacement_cleanup(
        self,
        group: TaskGroup,
        *,
        claim_owner: str | None = None,
    ) -> bool:
        assert claim_owner is not None
        self.visited.append(group.group_id)
        if group.group_id == self.failing_group_id:
            raise RuntimeError("cleanup publication failed")
        group.replacement.replaced_record_pending_delete = False
        return True


def _config(interval: int = 30):
    return SimpleNamespace(
        management=SimpleNamespace(task_group_reconciliation_interval_seconds=interval)
    )


def _mark_complete(group: TaskGroup) -> None:
    group.archive.status = ArchiveStatus.SUCCEEDED
    group.workflow.status = WorkflowStatus.ARCHIVED
    group.workload.settlement_status = WorkloadSettlementStatus.SETTLED
    group.status = JobStatus.SUCCEEDED


def test_run_once_republishes_before_retrying_cleanup() -> None:
    group = TaskGroup(
        group_id="group-1",
        project_no="2016",
        replacement={
            "replaced_group_id": "group-old",
            "replaced_record_pending_delete": True,
        },
    )
    _mark_complete(group)
    group.metadata[SUMMARY_PUBLICATION_PENDING_KEY] = True
    writer = _StateWriter([group])
    coordinator = _Coordinator()
    worker = TaskGroupReconciliationWorker(
        state_writer=writer,
        archive_coordinator=coordinator,
        group_manager=_GroupManager([group]),
        config=_config(7),
    )

    report = worker.run_once()

    assert report.publication_attempted == 1
    assert report.cleanup_attempted == 1
    assert report.failed_group_ids == ()
    assert coordinator.visited == [group.group_id]
    assert worker.interval_seconds == 7


def test_cleanup_failure_does_not_block_later_group() -> None:
    first = TaskGroup(
        group_id="group-1",
        project_no="2016",
        replacement={"replaced_record_pending_delete": True},
    )
    second = TaskGroup(
        group_id="group-2",
        project_no="2016",
        replacement={"replaced_record_pending_delete": True},
    )
    groups = [first, second]
    _mark_complete(first)
    _mark_complete(second)
    coordinator = _Coordinator(failing_group_id=first.group_id)
    worker = TaskGroupReconciliationWorker(
        state_writer=_StateWriter(groups),
        archive_coordinator=coordinator,
        group_manager=_GroupManager(groups),
        config=_config(),
    )

    report = worker.run_once()

    assert coordinator.visited == [first.group_id, second.group_id]
    assert report.cleanup_attempted == 2
    assert report.failed_group_ids == (first.group_id,)
    assert second.replacement.replaced_record_pending_delete is False


def test_incomplete_successor_is_never_sent_to_cleanup() -> None:
    group = TaskGroup(
        group_id="group-1",
        project_no="2016",
        replacement={"replaced_record_pending_delete": True},
    )
    coordinator = _Coordinator()
    worker = TaskGroupReconciliationWorker(
        state_writer=_StateWriter([group]),
        archive_coordinator=coordinator,
        group_manager=_GroupManager([group]),
        config=_config(),
    )

    report = worker.run_once()

    assert report.cleanup_attempted == 0
    assert coordinator.visited == []
    assert group.replacement.replaced_record_pending_delete is True


def test_loop_survives_one_run_once_exception() -> None:
    worker = TaskGroupReconciliationWorker(
        state_writer=_StateWriter([]),
        archive_coordinator=_Coordinator(),
        group_manager=_GroupManager([]),
        config=_config(),
    )
    calls = 0

    def _fail_once():
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


def test_stop_warns_when_reconciliation_thread_does_not_exit(caplog) -> None:
    worker = TaskGroupReconciliationWorker(
        state_writer=_StateWriter([]),
        archive_coordinator=_Coordinator(),
        group_manager=_GroupManager([]),
        config=_config(),
    )

    class _StuckThread:
        def join(self, timeout: int) -> None:
            assert timeout == 2

        def is_alive(self) -> bool:
            return True

    worker._thread = _StuckThread()  # type: ignore[assignment]

    worker.stop()

    assert "task-group reconciliation worker did not stop" in caplog.text
