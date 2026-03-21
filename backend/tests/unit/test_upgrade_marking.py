from __future__ import annotations

import pytest

from src.doc_gen.upgrade_marking import (
    UpgradeSheetCodeParseError,
    get_upgrade_note_text,
    parse_upgrade_sheet_codes,
)


def test_parse_upgrade_sheet_codes_supports_single_values_and_ranges() -> None:
    assert parse_upgrade_sheet_codes("001~003、005,7-8") == [
        "001",
        "002",
        "003",
        "005",
        "007",
        "008",
    ]


def test_parse_upgrade_sheet_codes_zero_pads_and_dedupes() -> None:
    assert parse_upgrade_sheet_codes("1,001,03,3,002") == [
        "001",
        "002",
        "003",
    ]


def test_parse_upgrade_sheet_codes_empty_returns_empty_list() -> None:
    assert parse_upgrade_sheet_codes("") == []


def test_parse_upgrade_sheet_codes_rejects_invalid_fragments() -> None:
    with pytest.raises(UpgradeSheetCodeParseError) as exc_info:
        parse_upgrade_sheet_codes("001~000,abc,1-")

    assert exc_info.value.invalid_fragments == ["001~000", "abc", "1-"]


def test_upgrade_note_text_varies_by_project() -> None:
    assert get_upgrade_note_text("2016") == "升版"
    assert get_upgrade_note_text("1818") == "升版 upgrade"
