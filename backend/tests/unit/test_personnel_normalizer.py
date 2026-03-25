from __future__ import annotations

from src.accounts.account_csv_store import AccountCsvStore
from src.accounts.account_registry import AccountRegistry
from src.accounts.personnel_normalizer import PersonnelNormalizer

from ..management_test_helpers import configure_management_env


def test_personnel_normalizer_prefers_checked_by_account_and_keeps_compound_canonical(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)
    normalizer = PersonnelNormalizer(AccountRegistry(AccountCsvStore()))

    result = normalizer.normalize("ied_checked_by", "张三@wrong-id")

    assert result.status == "matched"
    assert result.matched_account == "zhangsan"
    assert result.normalized_value == "张三@zhangsan"


def test_personnel_normalizer_flags_duplicate_names(monkeypatch, tmp_path) -> None:
    configure_management_env(
        monkeypatch,
        tmp_path,
        rows=[
            {
                "科室编码": "S01",
                "科室": "结构一室",
                "账号": "dup-1",
                "姓名": "重名",
                "角色": "设计人员",
                "密码": "password",
            },
            {
                "科室编码": "S02",
                "科室": "结构二室",
                "账号": "dup-2",
                "姓名": "重名",
                "角色": "设计人员",
                "密码": "password",
            },
        ],
    )
    normalizer = PersonnelNormalizer(AccountRegistry(AccountCsvStore()))

    result = normalizer.normalize("ied_checked_by", "重名")

    assert result.status == "ambiguous"
    assert result.errors == ["duplicate_name_needs_selection"]


def test_personnel_normalizer_returns_candidates_for_duplicate_names(monkeypatch, tmp_path) -> None:
    configure_management_env(
        monkeypatch,
        tmp_path,
        rows=[
            {
                "科室编码": "S01",
                "科室": "结构一室",
                "账号": "dup-1",
                "姓名": "重名",
                "角色": "设计人员",
                "密码": "password",
            },
            {
                "科室编码": "S02",
                "科室": "结构二室",
                "账号": "dup-2",
                "姓名": "重名",
                "角色": "设计人员",
                "密码": "password",
            },
        ],
    )
    normalizer = PersonnelNormalizer(AccountRegistry(AccountCsvStore()))

    result, candidates = normalizer.resolve_with_candidates("ied_checked_by", "重名")

    assert result.status == "ambiguous"
    assert [candidate.account_id for candidate in candidates] == ["dup-1", "dup-2"]
