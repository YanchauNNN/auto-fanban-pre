from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

from openpyxl import load_workbook

from .reinforcement_input import (
    InvalidReinforcementWorkbook,
    _find_columns,
    _find_slab_columns,
    _header_text,
    _normalized_cell_text,
    _uses_standard_layout,
    normalize_slab_elevation,
    normalize_wall_id,
)


@dataclass(frozen=True)
class FormatReason:
    scope: Literal["wall", "slab"]
    code: str
    sheet: str | None
    message: str


@dataclass(frozen=True)
class WorkbookFormatInspection:
    requires_ai_normalization: bool
    reasons: tuple[FormatReason, ...]
    wall_sheet: str | None
    slab_sheet: str | None


_STANDARD_LINEAR_SPEC = re.compile(
    r"(?:"
    r"(?P<layers_space>\d+)\s+(?P<diameter_space>\d+)"
    r"|(?P<layers_marked>\d+)\s*D\s*(?P<diameter_marked>\d+)"
    r"|D\s*(?P<diameter_only_marked>\d+)"
    r"|(?P<diameter_only>\d+)"
    r")\s*(?:@|间距)\s*(?P<spacing_primary>\d+)",
    re.IGNORECASE,
)
_STANDARD_GRID_SPEC = re.compile(
    r"(?:"
    r"(?P<layers_space>\d+)\s+(?P<diameter_space>\d+)"
    r"|(?P<layers_marked>\d+)\s*C\s*(?P<diameter_marked>\d+)"
    r"|C\s*(?P<diameter_only_marked>\d+)"
    r"|(?P<diameter_only>\d+)"
    r")\s*(?:@|间距)\s*(?P<spacing_primary>\d+)"
    r"\s*[*xX]\s*(?P<spacing_secondary>\d+)",
    re.IGNORECASE,
)
_STANDARD_WALL_TEXT = re.compile(
    r"[A-Za-z]+\d+[A-Za-z]?(?:-\d+)?\s*墙?",
    re.IGNORECASE,
)


def _is_standard_rebar(value: object, *, direction: str) -> bool:
    normalized = _normalized_cell_text(value)
    pattern = _STANDARD_GRID_SPEC if direction == "Z" else _STANDARD_LINEAR_SPEC
    match = pattern.fullmatch(normalized)
    if match is None:
        return False
    return all(
        int(component) > 0
        for component in match.groupdict().values()
        if component is not None
    )


def _is_standard_wall_text(value: object) -> bool:
    if normalize_wall_id(value) is None:
        return False
    return _STANDARD_WALL_TEXT.fullmatch(str(value).strip()) is not None


def _wall_candidates(workbook):
    candidates = []
    for sheet in workbook.worksheets:
        columns = _find_columns(sheet)
        if columns is not None:
            candidates.append((sheet, columns))
    return candidates


def _wall_value_reason(sheet, columns) -> FormatReason | None:
    header_row, wall_column, x_column, y_column, z_column = columns
    for row in range(header_row + 1, sheet.max_row + 1):
        values = {
            "wall": sheet.cell(row=row, column=wall_column).value,
            "X": sheet.cell(row=row, column=x_column).value,
            "Y": sheet.cell(row=row, column=y_column).value,
            "Z": sheet.cell(row=row, column=z_column).value,
        }
        if not any(value is not None and str(value).strip() for value in values.values()):
            continue
        if not _is_standard_wall_text(values["wall"]) or any(
            not _is_standard_rebar(values[direction], direction=direction)
            for direction in ("X", "Y", "Z")
        ):
            return FormatReason(
                scope="wall",
                code="wall_value_nonstandard",
                sheet=sheet.title,
                message=f"{sheet.title} 第 {row} 行不是标准墙体配筋写法",
            )
    return None


def _find_slab_like_header(sheet) -> int | None:
    max_row = sheet.max_row or 0
    max_column = sheet.max_column or 0
    for row in range(1, min(max_row, 20) + 1):
        headers = [
            _header_text(sheet.cell(row=row, column=column).value)
            for column in range(1, max_column + 1)
        ]
        has_elevation = any("标高" in header or "楼层" in header for header in headers)
        has_top_x = any(
            ("顶层" in header or "上部" in header)
            and ("水平" in header or "X" in header.upper())
            for header in headers
        )
        has_top_y = any(
            ("顶层" in header or "上部" in header)
            and ("竖向" in header or "Y" in header.upper())
            for header in headers
        )
        has_bottom_x = any(
            ("底层" in header or "下部" in header)
            and ("水平" in header or "X" in header.upper())
            for header in headers
        )
        has_bottom_y = any(
            ("底层" in header or "下部" in header)
            and ("竖向" in header or "Y" in header.upper())
            for header in headers
        )
        has_tie = any("拉筋" in header for header in headers)
        if all(
            (
                has_elevation,
                has_top_x,
                has_top_y,
                has_bottom_x,
                has_bottom_y,
                has_tie,
            )
        ):
            return row
    return None


def _slab_candidates(workbook):
    candidates = []
    for sheet in workbook.worksheets:
        columns = _find_slab_columns(sheet)
        like_header_row = _find_slab_like_header(sheet)
        if columns is not None or like_header_row is not None:
            candidates.append((sheet, columns, like_header_row))
    return candidates


def _uses_standard_slab_layout(sheet, found) -> bool:
    if found is None:
        return False
    header_row, columns = found
    return (
        sheet.title == "楼板配筋"
        and header_row == 1
        and tuple(columns.values()) == tuple(range(1, 9))
    )


def _slab_value_reason(sheet, found) -> FormatReason | None:
    header_row, columns = found
    for row in range(header_row + 1, sheet.max_row + 1):
        values = {
            key: sheet.cell(row=row, column=column).value
            for key, column in columns.items()
        }
        if not any(value is not None and str(value).strip() for value in values.values()):
            continue
        try:
            normalize_slab_elevation(values["elevation"])
        except InvalidReinforcementWorkbook:
            return FormatReason(
                scope="slab",
                code="slab_value_nonstandard",
                sheet=sheet.title,
                message=f"{sheet.title} 第 {row} 行的楼板标高不是标准写法",
            )
        for key in (
            "top_x",
            "top_y",
            "middle_x",
            "middle_y",
            "bottom_x",
            "bottom_y",
            "z",
        ):
            value = values[key]
            if key in {"middle_x", "middle_y"} and value in (None, ""):
                continue
            if not _is_standard_rebar(value, direction="X"):
                return FormatReason(
                    scope="slab",
                    code="slab_value_nonstandard",
                    sheet=sheet.title,
                    message=f"{sheet.title} 第 {row} 行不是标准楼板配筋写法",
                )
    return None


def inspect_reinforcement_workbook(
    path: Path,
    *,
    include_slab: bool,
) -> WorkbookFormatInspection:
    workbook = load_workbook(path, data_only=False, read_only=True)
    reasons: list[FormatReason] = []
    wall_sheet_name: str | None = None
    slab_sheet_name: str | None = None
    try:
        wall_candidates = _wall_candidates(workbook)
        standard_walls = [
            candidate
            for candidate in wall_candidates
            if _uses_standard_layout(candidate[0], candidate[1])
        ]
        selected_wall = (standard_walls or wall_candidates or [None])[0]
        if selected_wall is None:
            reasons.append(
                FormatReason(
                    scope="wall",
                    code="wall_sheet_missing",
                    sheet=None,
                    message="未找到墙体配筋输入表",
                )
            )
        else:
            wall_sheet, wall_columns = selected_wall
            wall_sheet_name = wall_sheet.title
            if not _uses_standard_layout(wall_sheet, wall_columns):
                reasons.append(
                    FormatReason(
                        scope="wall",
                        code="wall_layout_nonstandard",
                        sheet=wall_sheet.title,
                        message=f"{wall_sheet.title} 不是标准四列墙体配筋模板",
                    )
                )
            else:
                wall_reason = _wall_value_reason(wall_sheet, wall_columns)
                if wall_reason is not None:
                    reasons.append(wall_reason)

        if include_slab:
            slab_candidates = _slab_candidates(workbook)
            standard_slabs = [
                candidate
                for candidate in slab_candidates
                if _uses_standard_slab_layout(candidate[0], candidate[1])
            ]
            selected_slab = (standard_slabs or slab_candidates or [None])[0]
            if selected_slab is None:
                reasons.append(
                    FormatReason(
                        scope="slab",
                        code="slab_sheet_missing",
                        sheet=None,
                        message="已启用楼板计算，但未找到楼板配筋输入表",
                    )
                )
            else:
                slab_sheet, slab_columns, _ = selected_slab
                slab_sheet_name = slab_sheet.title
                if not _uses_standard_slab_layout(slab_sheet, slab_columns):
                    reasons.append(
                        FormatReason(
                            scope="slab",
                            code="slab_layout_nonstandard",
                            sheet=slab_sheet.title,
                            message=f"{slab_sheet.title} 不是标准八列楼板配筋模板",
                        )
                    )
                else:
                    slab_reason = _slab_value_reason(slab_sheet, slab_columns)
                    if slab_reason is not None:
                        reasons.append(slab_reason)
    finally:
        workbook.close()

    return WorkbookFormatInspection(
        requires_ai_normalization=bool(reasons),
        reasons=tuple(reasons),
        wall_sheet=wall_sheet_name,
        slab_sheet=slab_sheet_name,
    )


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def build_workbook_snapshot(
    path: Path,
    *,
    max_non_empty_cells: int,
) -> dict[str, object]:
    if max_non_empty_cells <= 0:
        raise ValueError("max_non_empty_cells must be greater than 0")

    workbook = load_workbook(path, data_only=False, read_only=False)
    sheets: list[dict[str, object]] = []
    cells: list[dict[str, object]] = []
    try:
        for sheet in workbook.worksheets:
            merged_cell_ranges = sorted(sheet.merged_cells.ranges, key=str)
            merged_ranges = [str(cell_range) for cell_range in merged_cell_ranges]
            sheets.append(
                {
                    "name": sheet.title,
                    "merged_ranges": merged_ranges,
                }
            )
            for row in sheet.iter_rows():
                for cell in row:
                    if cell.value in (None, ""):
                        continue
                    if len(cells) >= max_non_empty_cells:
                        raise ValueError(
                            "workbook contains more non-empty cells than "
                            f"max_non_empty_cells={max_non_empty_cells}"
                        )
                    merged_range = next(
                        (
                            str(cell_range)
                            for cell_range in merged_cell_ranges
                            if cell.coordinate in cell_range
                        ),
                        None,
                    )
                    formula = cell.value if cell.data_type == "f" else None
                    cells.append(
                        {
                            "sheet": sheet.title,
                            "row": cell.row,
                            "column": cell.column,
                            "address": cell.coordinate,
                            "value": _json_value(cell.value),
                            "formula": formula,
                            "merged_range": merged_range,
                        }
                    )
    finally:
        workbook.close()

    return {
        "workbook": path.name,
        "non_empty_cell_count": len(cells),
        "sheets": sheets,
        "cells": cells,
    }
