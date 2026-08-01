from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from importlib import import_module
from pathlib import Path

import pytest
from openpyxl import Workbook


def _subject():
    return import_module("src.calculation_book.reinforcement_workbook")


def _add_standard_wall_sheet(workbook: Workbook, *, title: str = "Sheet1"):
    sheet = workbook.create_sheet(title)
    sheet.append(
        [
            "构件编号\n及位置",
            "单侧水平钢筋\n(对称配筋)",
            "单侧竖向钢筋\n(对称配筋)",
            "拉筋",
        ]
    )
    sheet.append(["S7159 墙", "1 28@200", "1D28间距200", "12@200x400"])
    sheet.append(["S7160", "D25@200", "1D25间距200", "1C10间距200*400"])
    return sheet


def _add_standard_slab_sheet(workbook: Workbook):
    sheet = workbook.create_sheet("楼板配筋")
    sheet.append(
        [
            "标高",
            "顶层水平",
            "顶层竖向",
            "中层水平",
            "中层竖向",
            "底层水平",
            "底层竖向",
            "纵向拉筋",
        ]
    )
    return sheet


def test_standard_template_format_does_not_require_ai(tmp_path: Path) -> None:
    subject = _subject()
    workbook = Workbook()
    margin_sheet = workbook.active
    margin_sheet.title = "配筋裕度"
    margin_sheet.append(["构件", "方向", "裕度"])
    margin_sheet.append(["S7159", "X", 0.15])
    _add_standard_wall_sheet(workbook)
    _add_standard_slab_sheet(workbook)
    path = tmp_path / "计算书模板文件.xlsx"
    workbook.save(path)

    inspection = subject.inspect_reinforcement_workbook(path, include_slab=True)

    assert inspection == subject.WorkbookFormatInspection(
        requires_ai_normalization=False,
        reasons=(),
        wall_sheet="Sheet1",
        slab_sheet="楼板配筋",
    )
    with pytest.raises(FrozenInstanceError):
        inspection.wall_sheet = "changed"


def test_format_inspection_does_not_invoke_area_calculation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    from src.calculation_book import reinforcement_input

    workbook = Workbook()
    workbook.remove(workbook.active)
    _add_standard_wall_sheet(workbook)
    _add_standard_slab_sheet(workbook)
    path = tmp_path / "syntax-only.xlsx"
    workbook.save(path)

    def fail_if_called(**_kwargs):
        raise AssertionError("format inspection must not calculate reinforcement area")

    monkeypatch.setattr(reinforcement_input, "_configuration", fail_if_called)

    inspection = subject.inspect_reinforcement_workbook(path, include_slab=True)

    assert inspection.requires_ai_normalization is False


@pytest.mark.parametrize(
    ("address", "value"),
    [
        ("B2", "0D28@200"),
        ("B2", "1D0@200"),
        ("B2", "1D28@0"),
        ("B2", "1D28@-200"),
        ("B2", "1D28@200*400"),
        ("D2", "1C12@200"),
        ("D2", "1C12@200*0"),
        ("D2", "1A8间距400*400"),
    ],
)
def test_nonpositive_or_directionally_invalid_specs_require_ai(
    tmp_path: Path,
    address: str,
    value: str,
) -> None:
    subject = _subject()
    workbook = Workbook()
    workbook.remove(workbook.active)
    sheet = _add_standard_wall_sheet(workbook)
    sheet[address] = value
    path = tmp_path / "invalid-standard-cell.xlsx"
    workbook.save(path)

    inspection = subject.inspect_reinforcement_workbook(path, include_slab=False)

    assert inspection.requires_ai_normalization is True
    assert inspection.reasons[0].code == "wall_value_nonstandard"


def test_nonstandard_wall_and_selected_slab_require_ai(tmp_path: Path) -> None:
    subject = _subject()
    workbook = Workbook()
    wall_sheet = workbook.active
    wall_sheet.title = "墙体自定义表"
    wall_sheet.append(["墙号", "水平筋(X)", "竖向筋(Y)", "拉筋(Z)"])
    wall_sheet.append(
        ["S7159", "双层D28@200", "D28@200", "C12@200x400"]
    )
    slab_sheet = workbook.create_sheet("楼板自定义表")
    slab_sheet.append(["楼层", "上部X", "上部Y", "下部X", "下部Y", "拉筋"])
    slab_sheet.append(
        [11.45, "D20@200", "D20@200", "D18@200", "D18@200", "C12@200x400"]
    )
    path = tmp_path / "nonstandard.xlsx"
    workbook.save(path)

    inspection = subject.inspect_reinforcement_workbook(path, include_slab=True)

    assert inspection.requires_ai_normalization is True
    assert inspection.wall_sheet == "墙体自定义表"
    assert inspection.slab_sheet == "楼板自定义表"
    assert {reason.scope for reason in inspection.reasons} == {"wall", "slab"}
    assert all(reason.sheet is not None for reason in inspection.reasons)


def test_unselected_nonstandard_slab_does_not_require_ai(tmp_path: Path) -> None:
    subject = _subject()
    workbook = Workbook()
    workbook.remove(workbook.active)
    _add_standard_wall_sheet(workbook)
    slab_sheet = workbook.create_sheet("楼板自定义表")
    slab_sheet.append(["楼层", "上部X", "上部Y", "下部X", "下部Y", "拉筋"])
    slab_sheet.append(
        [11.45, "双层D20@200", "D20@200", "D18@200", "D18@200", "C12@200x400"]
    )
    path = tmp_path / "wall-only-selection.xlsx"
    workbook.save(path)

    inspection = subject.inspect_reinforcement_workbook(path, include_slab=False)

    assert inspection.requires_ai_normalization is False
    assert inspection.reasons == ()
    assert inspection.wall_sheet == "Sheet1"
    assert inspection.slab_sheet is None


def test_snapshot_preserves_nonempty_cells_formulas_and_merged_membership(
    tmp_path: Path,
) -> None:
    subject = _subject()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "证据"
    sheet["A1"] = "普通值"
    sheet["B2"] = "=SUM(1,2)"
    sheet.merge_cells("C3:D3")
    sheet["C3"] = "合并值"
    path = tmp_path / "snapshot.xlsx"
    workbook.save(path)

    snapshot = subject.build_workbook_snapshot(path, max_non_empty_cells=3)

    assert snapshot["workbook"] == "snapshot.xlsx"
    assert snapshot["non_empty_cell_count"] == 3
    assert snapshot["sheets"] == [
        {"name": "证据", "merged_ranges": ["C3:D3"]}
    ]
    assert snapshot["cells"] == [
        {
            "sheet": "证据",
            "row": 1,
            "column": 1,
            "address": "A1",
            "value": "普通值",
            "formula": None,
            "merged_range": None,
        },
        {
            "sheet": "证据",
            "row": 2,
            "column": 2,
            "address": "B2",
            "value": "=SUM(1,2)",
            "formula": "=SUM(1,2)",
            "merged_range": None,
        },
        {
            "sheet": "证据",
            "row": 3,
            "column": 3,
            "address": "C3",
            "value": "合并值",
            "formula": None,
            "merged_range": "C3:D3",
        },
    ]
    json.dumps(snapshot, ensure_ascii=False)


def test_snapshot_limit_allows_exact_boundary_and_rejects_overflow(
    tmp_path: Path,
) -> None:
    subject = _subject()
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["A", "B", "C"])
    path = tmp_path / "limit.xlsx"
    workbook.save(path)

    assert subject.build_workbook_snapshot(
        path,
        max_non_empty_cells=3,
    )["non_empty_cell_count"] == 3
    with pytest.raises(ValueError, match="max_non_empty_cells=2"):
        subject.build_workbook_snapshot(path, max_non_empty_cells=2)
    with pytest.raises(ValueError, match="max_non_empty_cells must be greater than 0"):
        subject.build_workbook_snapshot(path, max_non_empty_cells=0)
