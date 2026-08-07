from __future__ import annotations

from collections.abc import Callable

from ..models import TaskGroup
from ..pipeline.group_manager import GroupManager


class TaskGroupStateWriter:
    """Persist a task-group mutation, then publish its summary index."""

    def __init__(
        self,
        *,
        group_manager: GroupManager,
        publisher: Callable[[str], None],
    ) -> None:
        self.group_manager = group_manager
        self.publisher = publisher

    def write(self, group: TaskGroup) -> TaskGroup:
        self.group_manager.update_group(group)
        self.publisher(group.group_id)
        return group
