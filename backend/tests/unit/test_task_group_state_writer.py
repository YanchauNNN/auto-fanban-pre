from __future__ import annotations

import pytest

from src.models import TaskGroup
from src.task_groups.state_writer import (
    SUMMARY_PUBLICATION_ERROR_KEY,
    SUMMARY_PUBLICATION_PENDING_KEY,
    TaskGroupStateWriter,
)


class _RecordingGroupManager:
    def __init__(
        self,
        trace: list[str] | None = None,
        groups: list[TaskGroup] | None = None,
    ) -> None:
        self.persisted: list[str] = []
        self.trace = trace
        self.groups = groups or []

    def update_group(self, group: TaskGroup) -> None:
        self.persisted.append(group.group_id)
        if self.trace is not None:
            self.trace.append(f"persist:{group.group_id}")

    def load_all_groups(self) -> list[TaskGroup]:
        return self.groups


def test_state_writer_persists_before_publishing() -> None:
    trace: list[str] = []
    manager = _RecordingGroupManager(trace)
    writer = TaskGroupStateWriter(
        group_manager=manager,
        publisher=lambda group_id: trace.append(f"publish:{group_id}"),
    )

    writer.write(TaskGroup(group_id="group-1", project_no="2016"))

    assert manager.persisted == ["group-1", "group-1"]
    assert trace == ["persist:group-1", "publish:group-1", "persist:group-1"]


def test_state_writer_propagates_publish_failure_after_persisting() -> None:
    manager = _RecordingGroupManager()

    def _fail_publish(_group_id: str) -> None:
        raise RuntimeError("summary publish failed")

    writer = TaskGroupStateWriter(group_manager=manager, publisher=_fail_publish)

    group = TaskGroup(group_id="group-1", project_no="2016")
    with pytest.raises(RuntimeError, match="summary publish failed"):
        writer.write(group)

    assert manager.persisted == ["group-1", "group-1"]
    assert group.metadata[SUMMARY_PUBLICATION_PENDING_KEY] is True
    assert group.metadata[SUMMARY_PUBLICATION_ERROR_KEY] == "summary publish failed"


def test_retry_pending_publications_converges_successes_and_continues_after_failure() -> None:
    first = TaskGroup(group_id="group-1", project_no="2016")
    second = TaskGroup(group_id="group-2", project_no="2016")
    first.metadata[SUMMARY_PUBLICATION_PENDING_KEY] = True
    second.metadata[SUMMARY_PUBLICATION_PENDING_KEY] = True
    manager = _RecordingGroupManager(groups=[first, second])
    attempts: list[str] = []

    def _publish(group_id: str) -> None:
        attempts.append(group_id)
        if group_id == first.group_id:
            raise RuntimeError("sqlite busy")

    report = TaskGroupStateWriter(
        group_manager=manager,
        publisher=_publish,
    ).retry_pending_publications()

    assert report.attempted == 2
    assert report.succeeded == 1
    assert report.failed_group_ids == (first.group_id,)
    assert first.metadata[SUMMARY_PUBLICATION_PENDING_KEY] is True
    assert first.metadata[SUMMARY_PUBLICATION_ERROR_KEY] == "sqlite busy"
    assert SUMMARY_PUBLICATION_PENDING_KEY not in second.metadata
    assert SUMMARY_PUBLICATION_ERROR_KEY not in second.metadata
    assert attempts == [first.group_id, second.group_id]
