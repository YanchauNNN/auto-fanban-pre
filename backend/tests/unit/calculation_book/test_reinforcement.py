from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from src.calculation_book.reinforcement import (
    InsufficientRebarCapacity,
    RebarAreaRow,
    load_rebar_area_table,
    select_rebar,
)


def test_loads_the_external_rebar_area_table_shape(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["公称直径", 1, 4, 5])
    sheet.append([12, 113, 452, 565])
    sheet.append([16, 201, 804, 1005])
    path = tmp_path / "rebar.xlsx"
    workbook.save(path)

    rows = load_rebar_area_table(path)

    assert rows == [
        RebarAreaRow(diameter=12, area_by_bar_count={1: 113.0, 4: 452.0, 5: 565.0}),
        RebarAreaRow(diameter=16, area_by_bar_count={1: 201.0, 4: 804.0, 5: 1005.0}),
    ]


def test_selects_the_smallest_actual_area_above_sm_safety_target() -> None:
    rows = [
        RebarAreaRow(diameter=12, area_by_bar_count={4: 452.0, 5: 565.0}),
        RebarAreaRow(diameter=16, area_by_bar_count={4: 804.0, 5: 1005.0}),
    ]

    selection = select_rebar(
        800,
        rows,
        extra_ratio=0.2,
        row_counts=(1, 2),
        spacings=(200, 250),
        max_diameter=40,
    )

    assert selection.specification == "1排16@200"
    assert selection.target_area == 960
    assert selection.actual_area == 1005
    assert selection.margin_percent == pytest.approx(25.625)


def test_rejects_unrecognized_sm_instead_of_returning_zero() -> None:
    with pytest.raises(ValueError, match="SM"):
        select_rebar(0, [RebarAreaRow(diameter=16, area_by_bar_count={5: 1005.0})])


def test_rejects_insufficient_capacity_instead_of_using_maximum_fallback() -> None:
    rows = [RebarAreaRow(diameter=16, area_by_bar_count={4: 804.0, 5: 1005.0})]

    with pytest.raises(InsufficientRebarCapacity, match="24000"):
        select_rebar(20_000, rows, extra_ratio=0.2)
