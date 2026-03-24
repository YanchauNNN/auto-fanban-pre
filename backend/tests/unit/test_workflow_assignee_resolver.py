from __future__ import annotations

from src.accounts.account_csv_store import AccountCsvStore
from src.accounts.account_registry import AccountRegistry
from src.accounts.personnel_normalizer import PersonnelNormalizer
from src.workflow.assignee_resolver import WorkflowAssigneeResolver

from ..management_test_helpers import configure_management_env


def test_workflow_assignee_resolver_builds_nodes_from_yaml(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)
    registry = AccountRegistry(AccountCsvStore())
    snapshot = PersonnelNormalizer(registry).normalize_fields(
        {
            "ied_prepared_by": "张三",
            "ied_checked_by": "李四",
            "ied_discipline_leader": "王五",
            "ied_reviewed_by": "王五",
            "ied_approved_by": "管理员",
        }
    )

    nodes = WorkflowAssigneeResolver().build_nodes(snapshot)

    assert [node.node_key for node in nodes] == ["one_review", "two_review", "three_review"]
    assert nodes[0].assignee_account == "lisi"
    assert nodes[0].status.value == "current"
