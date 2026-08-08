from __future__ import annotations

import pytest

from src.accounts.account_csv_store import AccountCsvStore
from src.accounts.account_models import AccountCreatePayload, AccountUpdatePayload
from src.accounts.account_registry import AccountRegistry

from ..management_test_helpers import configure_management_env


def test_account_registry_reports_invalid_rows(monkeypatch, tmp_path) -> None:
    configure_management_env(
        monkeypatch,
        tmp_path,
        rows=[
            {
                "科室编码": "S01",
                "科室": "结构一室",
                "账号": "valid-user",
                "姓名": "张三",
                "角色": "设计人员",
                "密码": "password",
            },
            {
                "科室编码": "S02",
                "科室": "结构二室",
                "账号": "bad-role",
                "姓名": "坏角色",
                "角色": "未知角色",
                "密码": "password",
            },
        ],
    )
    registry = AccountRegistry(AccountCsvStore())

    accounts, invalid_rows = registry.list_accounts()

    assert len(accounts) == 2
    assert invalid_rows[0].errors == ["invalid_role"]


def test_account_registry_create_and_update(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)
    registry = AccountRegistry(AccountCsvStore())

    created = registry.create_account(
        AccountCreatePayload(
            office_code="S02",
            office_name="结构二室",
            account_id="zhaoliu",
            display_name="赵六",
            role="设计人员",
        )
    )
    assert created.password == "password"

    old_account, updated = registry.update_account(
        "zhaoliu",
        AccountUpdatePayload(account_id="zhaoliu-new", office_name="建筑总图室"),
    )

    assert old_account.account_id == "zhaoliu"
    assert updated.account_id == "zhaoliu-new"
    assert updated.office_name == "建筑总图室"


def test_account_registry_rejects_explicit_blank_password_before_writing_csv(
    monkeypatch,
    tmp_path,
) -> None:
    configure_management_env(monkeypatch, tmp_path)
    registry = AccountRegistry(AccountCsvStore())
    original_account_ids = [account.account_id for account in registry.list_valid_accounts()]

    with pytest.raises(ValueError, match="missing password"):
        registry.create_account(
            AccountCreatePayload(
                account_id="blank-password",
                display_name="空密码账号",
                role="设计人员",
                password="   ",
            )
        )

    assert [account.account_id for account in registry.list_valid_accounts()] == original_account_ids

    created = registry.create_account(
        AccountCreatePayload(
            account_id="spaced-password",
            display_name="保留空格密码",
            role="设计人员",
            password="  exact password  ",
        )
    )
    assert created.password == "  exact password  "


def test_account_registry_updates_invalid_row_by_row_number(monkeypatch, tmp_path) -> None:
    configure_management_env(
        monkeypatch,
        tmp_path,
        rows=[
            {
                "科室编码": "S02",
                "科室": "结构二室",
                "账号": "bad-role",
                "姓名": "坏角色",
                "角色": "未知角色",
                "密码": "password",
            },
        ],
    )
    registry = AccountRegistry(AccountCsvStore())

    old_account, updated = registry.update_account_row(
        2,
        AccountUpdatePayload(role="设计人员"),
    )

    assert old_account is None
    assert updated.account_id == "bad-role"
    assert updated.role == "设计人员"
    assert registry.list_invalid_rows() == []
