from __future__ import annotations

import yaml

from src.accounts.account_csv_store import AccountCsvStore
from src.accounts.account_registry import AccountRegistry
from src.accounts.personnel_normalizer import PersonnelNormalizer
from src.config import MechanismSpecLoader
from src.models import TaskGroup
from src.workflow.service import WorkflowService

from ..management_test_helpers import configure_management_env


def _build_group_with_personnel(registry: AccountRegistry, group_id: str = "group-1") -> TaskGroup:
    normalizer = PersonnelNormalizer(registry)
    group = TaskGroup(group_id=group_id, project_no="2016")
    group.personnel_snapshot = normalizer.normalize_fields(
        {
            "ied_prepared_by": "zhangsan",
            "ied_checked_by": "lisi",
            "ied_discipline_leader": "wangwu",
            "ied_reviewed_by": "wangwu",
            "ied_approved_by": "admin",
        }
    )
    return group


def test_workflow_service_start_and_approve(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)
    registry = AccountRegistry(AccountCsvStore())
    group = _build_group_with_personnel(registry)
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


def test_workflow_service_uses_yaml_terminal_status(monkeypatch, tmp_path) -> None:
    project_root = configure_management_env(monkeypatch, tmp_path)
    mechanism_path = project_root / "documents" / "参数规范-3.yaml"
    payload = yaml.safe_load(mechanism_path.read_text(encoding="utf-8"))
    payload["backend_mechanism"]["workflow_runtime"] = {
        "approval_terminal_status": "archived",
    }
    mechanism_path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    MechanismSpecLoader.clear_cache()

    registry = AccountRegistry(AccountCsvStore())
    group = _build_group_with_personnel(registry, group_id="group-yaml-terminal")
    service = WorkflowService()
    service.start(group, registry.to_snapshot("zhangsan"))

    service.approve(group, registry.to_snapshot("lisi"), 1.0)
    service.approve(group, registry.to_snapshot("wangwu"), 1.0)
    service.approve(group, registry.to_snapshot("admin"), 1.0)

    assert group.workflow.status.value == "archived"
