from __future__ import annotations

import pytest

from src.doc_gen.upgrade_marking import (
    UpgradeEntryParseError,
    UpgradeSheetCodeParseError,
    get_added_note_text,
    get_upgrade_note_text,
    parse_upgrade_entries,
    parse_upgrade_sheet_codes,
    resolve_highest_upgrade_revision,
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


def test_added_note_text_varies_by_project() -> None:
    assert get_added_note_text("2016") == "新增"
    assert get_added_note_text("1818") == "新增Add"


def test_parse_upgrade_entries_normalizes_revision_codes_and_added_flag() -> None:
    entries = parse_upgrade_entries(
        '[{"revision":"b","sheet_codes":"001~003","is_added":false},'
        '{"revision":"d","sheet_codes":"21-24","is_added":true}]'
    )

    assert [entry.revision for entry in entries] == ["B", "D"]
    assert entries[0].sheet_codes == ["001", "002", "003"]
    assert entries[0].is_added is False
    assert entries[1].sheet_codes == ["021", "022", "023", "024"]
    assert entries[1].is_added is True


def test_parse_upgrade_entries_rejects_duplicate_sheet_codes() -> None:
    with pytest.raises(UpgradeEntryParseError) as exc_info:
        parse_upgrade_entries(
            [
                {"revision": "B", "sheet_codes": "001~003", "is_added": False},
                {"revision": "C", "sheet_codes": "003", "is_added": True},
            ]
        )

    assert exc_info.value.error_code == "duplicate_sheet_code"


def test_parse_upgrade_entries_rejects_added_rows_without_sheet_codes() -> None:
    with pytest.raises(UpgradeEntryParseError) as exc_info:
        parse_upgrade_entries('[{"revision":"B","sheet_codes":"","is_added":true}]')

    assert exc_info.value.error_code == "added_without_sheet_codes"


def test_resolve_highest_upgrade_revision_uses_structured_rows() -> None:
    entries = parse_upgrade_entries(
        '[{"revision":"B","sheet_codes":"001","is_added":false},'
        '{"revision":"D","sheet_codes":"021~024","is_added":true}]'
    )

    assert resolve_highest_upgrade_revision(entries) == "D"
