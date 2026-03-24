from __future__ import annotations

from src.accounts.account_csv_store import AccountCsvStore
from src.accounts.account_registry import AccountRegistry
from src.accounts.personnel_normalizer import PersonnelNormalizer
from src.workflow.input_validator import WorkflowInputValidator

from ..management_test_helpers import configure_management_env


def test_workflow_input_validator_uses_checked_by_not_discipline_leader(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)
    registry = AccountRegistry(AccountCsvStore())
    snapshot = PersonnelNormalizer(registry).normalize_fields(
        {
            "ied_prepared_by": "张三",
            "ied_checked_by": "lisi",
            "ied_discipline_leader": "wangwu",
            "ied_reviewed_by": "wangwu",
            "ied_approved_by": "admin",
        }
    )

    errors = WorkflowInputValidator().validate_submit(snapshot)

    assert errors == []


def test_workflow_input_validator_blocks_missing_checked_by(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)
    registry = AccountRegistry(AccountCsvStore())
    snapshot = PersonnelNormalizer(registry).normalize_fields(
        {
            "ied_prepared_by": "张三",
            "ied_checked_by": "",
            "ied_discipline_leader": "lisi",
            "ied_reviewed_by": "wangwu",
            "ied_approved_by": "admin",
        }
    )

    errors = WorkflowInputValidator().validate_submit(snapshot)

    assert "ied_checked_by_required" in errors


def test_workflow_input_validator_blocks_duplicate_roles(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)
    registry = AccountRegistry(AccountCsvStore())
    snapshot = PersonnelNormalizer(registry).normalize_fields(
        {
            "ied_prepared_by": "张三",
            "ied_checked_by": "张三",
            "ied_discipline_leader": "李四",
            "ied_reviewed_by": "王五",
            "ied_approved_by": "管理员",
        }
    )

    errors = WorkflowInputValidator().validate_submit(snapshot)

    assert any(item.startswith("workflow_role_duplicate:") for item in errors)
