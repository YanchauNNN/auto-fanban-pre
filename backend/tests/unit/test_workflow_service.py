from __future__ import annotations

from src.accounts.account_csv_store import AccountCsvStore
from src.accounts.account_registry import AccountRegistry
from src.accounts.personnel_normalizer import PersonnelNormalizer
from src.models import TaskGroup
from src.workflow.service import WorkflowService

from ..management_test_helpers import configure_management_env


def test_workflow_service_start_and_approve(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)
    registry = AccountRegistry(AccountCsvStore())
    normalizer = PersonnelNormalizer(registry)
    group = TaskGroup(group_id="group-1", project_no="2016")
    group.personnel_snapshot = normalizer.normalize_fields(
        {
            "ied_prepared_by": "张三",
            "ied_checked_by": "李四",
            "ied_discipline_leader": "王五",
            "ied_reviewed_by": "王五",
            "ied_approved_by": "管理员",
        }
    )
    initiator = registry.to_snapshot("zhangsan")
    service = WorkflowService()

    service.start(group, initiator)
    assert group.workflow.current_node_key == "one_review"
    assert group.owner_snapshot is not None
    assert group.owner_snapshot.creator_account == "zhangsan"

    service.approve(group, registry.to_snapshot("lisi"), 1.0)
    assert group.workflow.current_node_key == "two_review"

    service.approve(group, registry.to_snapshot("wangwu"), 1.05)
    assert group.workflow.current_node_key == "three_review"

    service.approve(group, registry.to_snapshot("admin"), 0.95)
    assert group.workflow.status.value == "three_review_approved"
