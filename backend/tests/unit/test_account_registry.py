from __future__ import annotations

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
