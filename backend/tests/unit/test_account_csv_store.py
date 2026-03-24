from __future__ import annotations

from src.accounts.account_csv_store import AccountCsvStore

from ..management_test_helpers import configure_management_env


def test_account_csv_store_reads_and_writes_rows(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)
    store = AccountCsvStore()

    rows, headers = store.read_rows()

    assert headers == ["科室编码", "科室", "账号", "姓名", "角色", "密码"]
    assert rows[0]["账号"] == "zhangsan"

    rows.append(
        {
            "科室编码": "S02",
            "科室": "结构二室",
            "账号": "zhaoliu",
            "姓名": "赵六",
            "角色": "设计人员",
            "密码": "password",
        }
    )
    store.write_rows(rows, headers)

    reloaded, _ = store.read_rows()
    assert any(row["账号"] == "zhaoliu" for row in reloaded)
