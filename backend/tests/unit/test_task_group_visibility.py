from __future__ import annotations

from src.models import AccountSnapshot, TaskGroup, TaskOwnerSnapshot
from src.task_groups.visibility import TaskGroupVisibility


def test_task_group_visibility_obeys_role_scope() -> None:
    group = TaskGroup(group_id="group-1", project_no="2016")
    group.owner_snapshot = TaskOwnerSnapshot(
        creator_account="zhangsan",
        creator_name="张三",
        creator_role="设计人员",
        creator_office="结构一室",
    )
    visibility = TaskGroupVisibility()

    assert visibility.can_view(group, AccountSnapshot(account_id="admin", display_name="管理员", role="管理员"))
    assert visibility.can_view(group, AccountSnapshot(account_id="lisi", display_name="李四", role="室主任", office_name="结构一室"))
    assert not visibility.can_view(group, AccountSnapshot(account_id="wangwu", display_name="王五", role="设计人员"))
