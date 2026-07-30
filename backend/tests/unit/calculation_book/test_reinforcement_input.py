from __future__ import annotations

import math
from pathlib import Path

import pytest
from openpyxl import Workbook

from src.calculation_book.reinforcement_input import (
    InvalidReinforcementWorkbook,
    load_reinforcement_schedule,
    parse_rebar_cell,
)


def test_normalizes_standard_horizontal_and_tie_notation() -> None:
    horizontal = parse_rebar_cell("1   22@200", direction="X")
    tie = parse_rebar_cell("12@200x400", direction="Z")

    assert horizontal.selected.canonical_specification == "1D22间距200"
    assert horizontal.selected.narrative_specification == "1排22@200"
    assert horizontal.selected.actual_area == pytest.approx(
        math.pi * 11**2 * 5
    )
    assert tie.selected.canonical_specification == "1C12间距200*400"
    assert tie.selected.narrative_specification == "1排12@200x400"
    assert tie.selected.actual_area == pytest.approx(
        math.pi * 6**2 * 5 * 2.5
    )


def test_normalizes_a_marker_to_c_and_preserves_two_tie_layers() -> None:
    single = parse_rebar_cell("1A8间距400*400#", direction="Z")
    double = parse_rebar_cell("2 12@200x400", direction="Z")

    assert single.selected.canonical_specification == "1C8间距400*400"
    assert "#" not in single.selected.canonical_specification
    assert double.selected.canonical_specification == "2C12间距200*400"
    assert double.selected.actual_area == pytest.approx(
        2 * math.pi * 6**2 * 5 * 2.5
    )


def test_parenthetical_configuration_is_selected_as_actual_reinforcement() -> None:
    parsed = parse_rebar_cell(
        "1D28间距200(N5057-N5059:1D40间距200#)",
        direction="Y",
    )

    assert parsed.selected.canonical_specification == "1D40间距200"
    assert parsed.selected.actual_area == pytest.approx(
        math.pi * 20**2 * 5
    )
    assert parsed.original_text.endswith("#)")


def test_largest_parenthetical_configuration_is_selected() -> None:
    parsed = parse_rebar_cell(
        "1D28间距200（局部:1D32间距200；洞口:1D40间距200）",
        direction="Y",
    )

    assert parsed.selected.canonical_specification == "1D40间距200"
    assert len(parsed.candidates) == 3


def test_rejects_tie_without_two_direction_spacings() -> None:
    with pytest.raises(InvalidReinforcementWorkbook, match="两个方向"):
        parse_rebar_cell("1C14间距400", direction="Z")


def test_loads_standard_four_column_workbook_and_flags_duplicate_wall(
    tmp_path: Path,
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(
        [
            "构件编号\n及位置",
            "单侧水平钢筋\n(对称配筋)",
            "单侧竖向钢筋\n(对称配筋)",
            "拉筋",
        ]
    )
    sheet.append(["S7157 墙", "1 36@200", "1 36@200", "12@200x400"])
    sheet.append(["S7157 墙", "1 32@200", "1 32@200", "12@200x400"])
    sheet.append(["S7157a 墙", "1 28@200", "1 28@200", "1A8间距400*400"])
    path = tmp_path / "schedule.xlsx"
    workbook.save(path)

    schedule = load_reinforcement_schedule(path)

    assert [row.wall_id for row in schedule.rows] == ["S7157", "S7157", "S7157A"]
    assert schedule.duplicate_wall_ids == ("S7157",)
    assert schedule.requires_manual_confirmation
    assert schedule.rows[2].z.selected.canonical_specification == "1C8间距400*400"


def test_selects_canonical_wall_number_column_in_wide_workbook(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "2016墙体配筋"
    sheet.append(
        [
            "层位",
            "墙号",
            "墙号",
            "墙厚",
            "水平筋",
            "竖向筋",
            "拉筋",
        ]
    )
    sheet.append(
        [
            "N5",
            "012墙",
            "N5012",
            600,
            "1D32间距200",
            "1D28间距200",
            "1C14间距400*400",
        ]
    )
    path = tmp_path / "wide.xlsx"
    workbook.save(path)

    schedule = load_reinforcement_schedule(path)

    assert len(schedule.rows) == 1
    assert schedule.rows[0].wall_id == "N5012"
    assert schedule.rows[0].z.selected.actual_area == pytest.approx(
        math.pi * 7**2 * 2.5 * 2.5
    )
