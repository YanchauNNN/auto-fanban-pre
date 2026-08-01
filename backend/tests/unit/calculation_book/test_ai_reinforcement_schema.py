from __future__ import annotations

import math
from dataclasses import FrozenInstanceError
from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from src.calculation_book.ai_reinforcement_schema import (
    AiReinforcementPayload,
    InvalidAiReinforcementPayload,
    validate_ai_reinforcement_payload,
)


def _cell(sheet: str, row: int, column: int, address: str, value: object) -> dict[str, object]:
    return {
        "sheet": sheet,
        "row": row,
        "column": column,
        "address": address,
        "value": value,
        "formula": None,
        "merged_range": None,
    }


def _snapshot(*cells: dict[str, object]) -> dict[str, object]:
    sheet_names = sorted({str(cell["sheet"]) for cell in cells})
    return {
        "workbook": "reinforcement.xlsx",
        "non_empty_cell_count": len(cells),
        "sheets": [
            {"name": sheet_name, "merged_ranges": []}
            for sheet_name in sheet_names
        ],
        "cells": list(cells),
    }


def _wall_cells(
    *,
    row: int = 2,
    wall: object = "S7157 墙",
    x: object = "原表水平筋",
    y: object = "原表竖向筋",
    z: object = "原表拉筋",
) -> list[dict[str, object]]:
    return [
        _cell("墙体配筋", row, 1, f"A{row}", wall),
        _cell("墙体配筋", row, 2, f"B{row}", x),
        _cell("墙体配筋", row, 3, f"C{row}", y),
        _cell("墙体配筋", row, 4, f"D{row}", z),
    ]


def _wall_row(
    *,
    row: int = 2,
    wall_id: str = "S7157",
    source_cells: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "kind": "wall",
        "status": "normalized",
        "wall_id": wall_id,
        "X": "1D36间距200",
        "Y": "1D32间距200",
        "Z": "1C14间距400*400",
        "source_sheet": "墙体配筋",
        "source_row": row,
        "source_cells": source_cells
        or {
            "wall": f"A{row}",
            "X": f"B{row}",
            "Y": f"C{row}",
            "Z": f"D{row}",
        },
    }


def _slab_cells(*, row: int = 2, include_middle: bool = False) -> list[dict[str, object]]:
    values: list[tuple[str, object]] = [
        ("A", "11.20m"),
        ("B", "顶层水平原文"),
        ("C", "顶层竖向原文"),
    ]
    if include_middle:
        values.extend((("D", "中层水平原文"), ("E", "中层竖向原文")))
    values.extend(
        (
            ("F", "底层水平原文"),
            ("G", "底层竖向原文"),
            ("H", "纵向拉筋原文"),
        )
    )
    return [
        _cell("楼板配筋", row, ord(column) - 64, f"{column}{row}", value)
        for column, value in values
    ]


def _slab_row(*, row: int = 2, include_middle: bool = False) -> dict[str, Any]:
    source_cells: dict[str, str | None] = {
        "elevation": f"A{row}",
        "top_x": f"B{row}",
        "top_y": f"C{row}",
        "middle_x": f"D{row}" if include_middle else None,
        "middle_y": f"E{row}" if include_middle else None,
        "bottom_x": f"F{row}",
        "bottom_y": f"G{row}",
        "z": f"H{row}",
    }
    return {
        "kind": "slab",
        "status": "normalized",
        "elevation": "11.2",
        "top_x": "1D36间距200",
        "top_y": "1D40间距200",
        "middle_x": "1D32间距200" if include_middle else None,
        "middle_y": "1D34间距200" if include_middle else None,
        "bottom_x": "1D30间距200",
        "bottom_y": "1D28间距200",
        "z": "1D16间距200",
        "source_sheet": "楼板配筋",
        "source_row": row,
        "source_cells": source_cells,
    }


def _payload(*rows: dict[str, Any], source_row_count: int | None = None) -> AiReinforcementPayload:
    return AiReinforcementPayload.model_validate(
        {
            "schema_version": "1",
            "source_row_count": source_row_count or len(rows),
            "rows": list(rows),
        }
    )


def test_validates_wall_and_five_group_slab_and_recalculates_exact_area() -> None:
    payload = _payload(_wall_row(), _slab_row())
    snapshot = _snapshot(*_wall_cells(), *_slab_cells())

    validated = validate_ai_reinforcement_payload(payload, snapshot=snapshot)

    wall = validated.wall_schedule.rows[0]
    assert wall.wall_id == "S7157"
    assert wall.x.selected.actual_area == pytest.approx(math.pi * 18**2 * 5)
    assert wall.x.original_text == "原表水平筋"
    assert validated.slab_schedule is not None
    slab = validated.slab_schedule.rows[0]
    assert slab.elevation == "11.2"
    assert slab.middle_x is None
    assert slab.middle_y is None
    assert slab.z.selected.actual_area == pytest.approx(math.pi * 8**2 * 5)
    assert validated.source_row_count == 2


def test_validates_seven_group_slab_with_middle_reinforcement() -> None:
    payload = _payload(_wall_row(), _slab_row(include_middle=True))
    snapshot = _snapshot(*_wall_cells(), *_slab_cells(include_middle=True))

    validated = validate_ai_reinforcement_payload(payload, snapshot=snapshot)

    assert validated.slab_schedule is not None
    slab = validated.slab_schedule.rows[0]
    assert slab.middle_x is not None
    assert slab.middle_y is not None
    assert slab.middle_x.selected.actual_area == pytest.approx(math.pi * 16**2 * 5)


def test_forbids_model_supplied_actual_area_and_other_extra_fields() -> None:
    row = _wall_row()
    row["actual_area"] = 123.4
    with pytest.raises(ValidationError, match="actual_area"):
        _payload(row)

    row = _wall_row()
    row["source_cells"]["actual_area"] = "E2"
    with pytest.raises(ValidationError, match="actual_area"):
        _payload(row)


@pytest.mark.parametrize(
    "row_update",
    [
        {"X": None},
        {"status": "needs_review", "wall_id": None, "reason": None, "blank_fields": ["wall_id"]},
        {"status": "needs_review", "wall_id": None, "reason": "墙号不明确", "blank_fields": []},
    ],
)
def test_rejects_invalid_status_and_field_combinations(row_update: dict[str, object]) -> None:
    row = _wall_row()
    row.update(row_update)

    with pytest.raises(ValidationError):
        _payload(row)


def test_rejects_duplicate_source_row_even_when_addresses_differ() -> None:
    duplicate = _wall_row(
        source_cells={"wall": "E2", "X": "F2", "Y": "G2", "Z": "H2"}
    )
    payload = _payload(_wall_row(), duplicate)
    snapshot = _snapshot(
        *_wall_cells(),
        _cell("墙体配筋", 2, 5, "E2", "S7158"),
        _cell("墙体配筋", 2, 6, "F2", "1D32@200"),
        _cell("墙体配筋", 2, 7, "G2", "1D32@200"),
        _cell("墙体配筋", 2, 8, "H2", "1C14@400x400"),
    )

    with pytest.raises(InvalidAiReinforcementPayload, match="墙体配筋.*第 2 行.*重复"):
        validate_ai_reinforcement_payload(payload, snapshot=snapshot)


def test_rejects_missing_and_cross_row_source_addresses() -> None:
    missing = _payload(_wall_row(source_cells={"wall": "A2", "X": "Z2", "Y": "C2", "Z": "D2"}))
    with pytest.raises(InvalidAiReinforcementPayload, match="墙体配筋.*Z2.*不存在"):
        validate_ai_reinforcement_payload(missing, snapshot=_snapshot(*_wall_cells()))

    cross_row = _payload(_wall_row(source_cells={"wall": "A2", "X": "B3", "Y": "C2", "Z": "D2"}))
    with pytest.raises(InvalidAiReinforcementPayload, match="墙体配筋.*第 2 行.*B3.*跨行"):
        validate_ai_reinforcement_payload(cross_row, snapshot=_snapshot(*_wall_cells()))


def test_rejects_source_count_mismatches() -> None:
    payload = _payload(_wall_row(), source_row_count=2)
    with pytest.raises(InvalidAiReinforcementPayload, match="source_row_count.*rows"):
        validate_ai_reinforcement_payload(payload, snapshot=_snapshot(*_wall_cells()))

    payload = _payload(_wall_row())
    with pytest.raises(InvalidAiReinforcementPayload, match="expected_source_row_count"):
        validate_ai_reinforcement_payload(
            payload,
            snapshot=_snapshot(*_wall_cells()),
            expected_source_row_count=2,
        )


def test_rejects_payload_without_any_wall_row() -> None:
    payload = _payload(_slab_row())

    with pytest.raises(InvalidAiReinforcementPayload, match="至少包含一条 wall"):
        validate_ai_reinforcement_payload(payload, snapshot=_snapshot(*_slab_cells()))


def test_rejects_malformed_normalized_spec_with_source_location() -> None:
    row = _wall_row()
    row["X"] = "模型无法解析的规格"
    payload = _payload(row)

    with pytest.raises(
        InvalidAiReinforcementPayload,
        match="墙体配筋.*第 2 行.*B2.*无法识别配筋写法",
    ):
        validate_ai_reinforcement_payload(payload, snapshot=_snapshot(*_wall_cells()))


def test_needs_review_returns_warning_and_snapshot_originals_without_raising() -> None:
    row = {
        "kind": "wall",
        "status": "needs_review",
        "wall_id": None,
        "X": None,
        "Y": "1D32间距200",
        "Z": "1C14间距400*400",
        "reason": "墙号和水平筋写法无法确定",
        "blank_fields": ["wall_id", "X"],
        "source_sheet": "墙体配筋",
        "source_row": 2,
        "source_cells": {"wall": "A2", "X": "B2", "Y": "C2", "Z": "D2"},
    }
    payload = _payload(row)
    snapshot = _snapshot(
        *_wall_cells(
            wall="待确认墙",
            x=date(2026, 8, 1),
            y=32,
            z={"type": "array", "ref": "D2:D3", "text": "=SUM(A1:A2)"},
        )
    )

    validated = validate_ai_reinforcement_payload(payload, snapshot=snapshot)

    assert validated.wall_schedule.rows == ()
    assert len(validated.wall_schedule.issues) == 1
    assert validated.wall_schedule.issues[0].wall_id is None
    warning = validated.warnings[0]
    assert warning.code == "needs_review"
    assert warning.source_cells == {"wall": "A2", "X": "B2", "Y": "C2", "Z": "D2"}
    assert warning.original_values == {
        "wall": "待确认墙",
        "X": "2026-08-01",
        "Y": "32",
        "Z": '{"ref":"D2:D3","text":"=SUM(A1:A2)","type":"array"}',
    }
    assert warning.blank_fields == ("wall_id", "X")


def test_wall_review_warning_preserves_only_deterministically_resolved_values() -> None:
    row = _wall_row()
    row.update(
        {
            "status": "needs_review",
            "X": None,
            "reason": "水平筋存在业务歧义",
            "blank_fields": ["X"],
        }
    )
    payload = _payload(row)

    validated = validate_ai_reinforcement_payload(
        payload,
        snapshot=_snapshot(*_wall_cells()),
    )

    warning = validated.warnings[0]
    assert warning.resolved_values == {
        "wall_id": "S7157",
        "Y": "1D32间距200",
        "Z": "1C14间距400*400",
    }
    assert "X" not in warning.resolved_values
    with pytest.raises(FrozenInstanceError):
        warning.resolved_values = {}  # type: ignore[misc]


def test_needs_review_blank_fields_require_source_cell_evidence() -> None:
    row = {
        "kind": "wall",
        "status": "needs_review",
        "wall_id": "S7157",
        "X": None,
        "Y": "1D32间距200",
        "Z": "1C14间距400*400",
        "reason": "水平筋存在业务歧义",
        "blank_fields": ["X"],
        "source_sheet": "墙体配筋",
        "source_row": 2,
        "source_cells": {"wall": "A2", "X": None, "Y": "C2", "Z": "D2"},
    }

    with pytest.raises(ValidationError, match="blank_fields.*来源证据"):
        _payload(row)


def test_needs_review_rejects_malformed_nonblank_rule_field() -> None:
    row = {
        "kind": "wall",
        "status": "needs_review",
        "wall_id": "S7157",
        "X": None,
        "Y": "模型声称已确定但仍非法",
        "Z": "1C14间距400*400",
        "reason": "仅水平筋存在业务歧义",
        "blank_fields": ["X"],
        "source_sheet": "墙体配筋",
        "source_row": 2,
        "source_cells": {"wall": "A2", "X": "B2", "Y": "C2", "Z": "D2"},
    }
    payload = _payload(row)

    with pytest.raises(
        InvalidAiReinforcementPayload,
        match="墙体配筋.*第 2 行.*C2.*无法识别配筋写法",
    ):
        validate_ai_reinforcement_payload(payload, snapshot=_snapshot(*_wall_cells()))


def test_slab_needs_review_keeps_partial_row_as_a_normalized_identity_warning() -> None:
    slab = _slab_row()
    slab.update(
        {
            "status": "needs_review",
            "elevation": "11.20m",
            "top_x": None,
            "reason": "顶层水平配筋存在业务歧义",
            "blank_fields": ["top_x"],
        }
    )
    payload = _payload(_wall_row(), slab)
    snapshot = _snapshot(*_wall_cells(), *_slab_cells())

    validated = validate_ai_reinforcement_payload(payload, snapshot=snapshot)

    assert validated.slab_schedule is None
    assert len(validated.warnings) == 1
    warning = validated.warnings[0]
    assert warning.scope == "slab"
    assert warning.identity == "11.2"
    assert warning.blank_fields == ("top_x",)
    assert warning.source_cells == {
        "elevation": "A2",
        "top_x": "B2",
        "top_y": "C2",
        "bottom_x": "F2",
        "bottom_y": "G2",
        "z": "H2",
    }
    assert warning.original_values == {
        "elevation": "11.20m",
        "top_x": "顶层水平原文",
        "top_y": "顶层竖向原文",
        "bottom_x": "底层水平原文",
        "bottom_y": "底层竖向原文",
        "z": "纵向拉筋原文",
    }
    assert warning.resolved_values == {
        "elevation": "11.2",
        "top_y": "1D40间距200",
        "bottom_x": "1D30间距200",
        "bottom_y": "1D28间距200",
        "z": "1D16间距200",
    }
    assert "top_x" not in warning.resolved_values


@pytest.mark.parametrize(
    "review_fields",
    [
        {"reason": None, "blank_fields": ["top_x"]},
        {"reason": "顶层水平配筋存在业务歧义", "blank_fields": []},
    ],
)
def test_rejects_slab_needs_review_without_reason_or_blank_fields(
    review_fields: dict[str, object],
) -> None:
    slab = _slab_row()
    slab.update(
        {
            "status": "needs_review",
            "top_x": None,
            **review_fields,
        }
    )

    with pytest.raises(ValidationError):
        _payload(_wall_row(), slab)


def test_duplicate_wall_ids_are_preserved_and_warned_without_failing() -> None:
    second = _wall_row(row=3, wall_id="s7157 墙")
    payload = _payload(_wall_row(), second)
    snapshot = _snapshot(*_wall_cells(), *_wall_cells(row=3, wall="S7157"))

    validated = validate_ai_reinforcement_payload(payload, snapshot=snapshot)

    assert validated.wall_schedule.duplicate_wall_ids == ("S7157",)
    assert [warning.code for warning in validated.warnings] == ["duplicate_wall_id"]
    assert validated.warnings[0].identity == "S7157"
    assert validated.warnings[0].resolved_values == {
        "wall_id": "S7157",
        "X": "1D36间距200",
        "Y": "1D32间距200",
        "Z": "1C14间距400*400",
    }


def test_known_wall_id_in_needs_review_still_participates_in_duplicate_detection() -> None:
    review = _wall_row(row=3)
    review.update(
        {
            "status": "needs_review",
            "X": None,
            "reason": "水平筋存在业务歧义",
            "blank_fields": ["X"],
        }
    )
    payload = _payload(_wall_row(), review)
    snapshot = _snapshot(*_wall_cells(), *_wall_cells(row=3, wall="S7157"))

    validated = validate_ai_reinforcement_payload(payload, snapshot=snapshot)

    assert validated.wall_schedule.duplicate_wall_ids == ("S7157",)
    assert [warning.code for warning in validated.warnings] == [
        "needs_review",
        "duplicate_wall_id",
    ]
