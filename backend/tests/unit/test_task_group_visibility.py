from __future__ import annotations

import yaml

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


def test_task_group_visibility_reads_role_scopes_from_yaml(monkeypatch, tmp_path) -> None:
    spec_path = tmp_path / "documents" / "参数规范.yaml"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "2.0",
                "management_features": {
                    "task_visibility": {
                        "roles": {
                            "自定义管理员": "all",
                            "自定义主任": "office_only",
                            "自定义设计": "self_only",
                        },
                        "legacy_default_scope": "self_only",
                    }
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FANBAN_SPEC_PATH", str(spec_path))
    group = TaskGroup(group_id="group-1", project_no="2016")
    group.owner_snapshot = TaskOwnerSnapshot(
        creator_account="creator",
        creator_name="创建人",
        creator_role="自定义设计",
        creator_office="结构一室",
    )
    visibility = TaskGroupVisibility()

    assert visibility.can_view(group, AccountSnapshot(account_id="root", display_name="管理员", role="自定义管理员"))
    assert visibility.can_view(
        group,
        AccountSnapshot(account_id="lead", display_name="主任", role="自定义主任", office_name="结构一室"),
    )
    assert not visibility.can_view(
        group,
        AccountSnapshot(account_id="lead2", display_name="主任", role="自定义主任", office_name="结构二室"),
    )
