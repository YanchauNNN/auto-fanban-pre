from __future__ import annotations

import pytest

from src.models import TaskGroup
from src.task_groups.state_writer import TaskGroupStateWriter


class _RecordingGroupManager:
    def __init__(self, trace: list[str] | None = None) -> None:
        self.persisted: list[str] = []
        self.trace = trace

    def update_group(self, group: TaskGroup) -> None:
        self.persisted.append(group.group_id)
        if self.trace is not None:
            self.trace.append(f"persist:{group.group_id}")


def test_state_writer_persists_before_publishing() -> None:
    trace: list[str] = []
    manager = _RecordingGroupManager(trace)
    writer = TaskGroupStateWriter(
        group_manager=manager,
        publisher=lambda group_id: trace.append(f"publish:{group_id}"),
    )

    writer.write(TaskGroup(group_id="group-1", project_no="2016"))

    assert manager.persisted == ["group-1"]
    assert trace == ["persist:group-1", "publish:group-1"]


def test_state_writer_propagates_publish_failure_after_persisting() -> None:
    manager = _RecordingGroupManager()

    def _fail_publish(_group_id: str) -> None:
        raise RuntimeError("summary publish failed")

    writer = TaskGroupStateWriter(group_manager=manager, publisher=_fail_publish)

    with pytest.raises(RuntimeError, match="summary publish failed"):
        writer.write(TaskGroup(group_id="group-1", project_no="2016"))

    assert manager.persisted == ["group-1"]
