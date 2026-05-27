from __future__ import annotations

from src.accounts.account_csv_store import AccountCsvStore
from src.accounts.account_registry import AccountRegistry
from src.accounts.personnel_normalizer import PersonnelNormalizer
from src.models import TaskGroup
from src.task_groups.service import TaskGroupService
from src.workflow.assignee_resolver import WorkflowAssigneeResolver
from src.workflow.models import WorkflowNodeState

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


def test_task_group_service_applies_workload_factors_from_yaml_factor_key(monkeypatch, tmp_path) -> None:
    project_root = configure_management_env(monkeypatch, tmp_path)
    spec_path = project_root / "documents" / "参数规范.yaml"
    import yaml

    payload = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    payload["management_features"]["workflow"]["nodes"] = [
        {
            "key": "custom_review",
            "label": "自定义审核",
            "assignee_source": "ied_checked_by",
            "factor_key": "two_review_factor",
        }
    ]
    spec_path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    from src.config import SpecLoader

    SpecLoader.clear_cache()
    group = TaskGroup(group_id="group-factors", project_no="2016")
    group.workflow.nodes = [WorkflowNodeState(node_key="custom_review", node_label="自定义审核", factor=1.08)]
    service = object.__new__(TaskGroupService)
    service.workload_calculator = __import__("src.workload.calculator", fromlist=["WorkloadCalculator"]).WorkloadCalculator()

    TaskGroupService._apply_factors(service, group)

    assert group.workload.one_review_factor == 1.0
    assert group.workload.two_review_factor == 1.08
