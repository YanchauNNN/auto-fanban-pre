from __future__ import annotations

from pathlib import Path

import yaml


WORKTREE_ROOT = Path(__file__).resolve().parents[4]
VALIDATION_SET = (
    WORKTREE_ROOT / "documents" / "AI" / "建筑结构总图规范验证集.yaml"
)


def test_validation_set_has_twenty_unique_workbook_records() -> None:
    payload = yaml.safe_load(VALIDATION_SET.read_text(encoding="utf-8"))
    items = payload["items"]

    assert len(items) == 20
    assert len({item["source_id"] for item in items}) == 20
    assert len({item["code"] for item in items}) == 20


def test_validation_set_covers_required_families_and_all_majors() -> None:
    payload = yaml.safe_load(VALIDATION_SET.read_text(encoding="utf-8"))
    items = payload["items"]

    assert {item["family"] for item in items} == {
        "GB",
        "GB/T",
        "NB/T",
        "JGJ",
        "HAF",
        "正版图集",
        "内部JT",
        "内部CP",
    }
    assert {item["major"] for item in items} == {"建筑", "结构", "总图"}


def test_validation_set_does_not_claim_unavailable_sources_are_acquired() -> None:
    payload = yaml.safe_load(VALIDATION_SET.read_text(encoding="utf-8"))

    for item in payload["items"]:
        status = item["acquisition_status"]
        assert status
        assert any(token in status for token in ("待", "已核验"))
        assert "已入库" not in status
