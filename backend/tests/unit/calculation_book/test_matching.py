from __future__ import annotations

from pathlib import Path

import pytest

from src.calculation_book.ai_reinforcement_schema import (
    ReinforcementNormalizationWarning,
)
from src.calculation_book.archive import ReinforcementFigure
from src.calculation_book.matching import (
    CalculationMatchingError,
    RecognizedFigure,
    match_reinforcement,
)
from src.calculation_book.ocr import StressLegendReading
from src.calculation_book.reinforcement_input import (
    NormalizedReinforcementRow,
    ReinforcementSchedule,
    parse_rebar_cell,
)


def _row(
    wall_id: str,
    *,
    diameter: int,
    source_row: int,
) -> NormalizedReinforcementRow:
    return NormalizedReinforcementRow(
        wall_id=wall_id,
        x=parse_rebar_cell(f"1D{diameter}间距200", direction="X"),
        y=parse_rebar_cell(f"1D{diameter}间距200", direction="Y"),
        z=parse_rebar_cell("1C14间距400*400", direction="Z"),
        source_sheet="Sheet1",
        source_row=source_row,
        source_cells={
            "wall": f"A{source_row}",
            "X": f"B{source_row}",
            "Y": f"C{source_row}",
            "Z": f"D{source_row}",
        },
    )


def _recognized(
    wall_id: str,
    direction: str,
    smx: float,
    *,
    base_wall_id: str | None = None,
    group_index: int | None = None,
) -> RecognizedFigure:
    return RecognizedFigure(
        source=ReinforcementFigure(
            wall_id=wall_id,
            base_wall_id=base_wall_id or wall_id,
            group_index=group_index,
            direction=direction,
            path=Path(f"{wall_id}-{direction}.JPEG"),
            sort_key=(1, "", group_index or 0, "XYZ".index(direction), wall_id),
        ),
        reading=StressLegendReading(
            smn=0,
            smx=smx,
            legend_values=tuple(smx * index / 9 for index in range(10)),
        ),
    )


def _group(
    wall_id: str,
    demand: float,
    *,
    base_wall_id: str | None = None,
    group_index: int | None = None,
) -> list[RecognizedFigure]:
    return [
        _recognized(
            wall_id,
            direction,
            demand,
            base_wall_id=base_wall_id,
            group_index=group_index,
        )
        for direction in ("X", "Y", "Z")
    ]


def test_matches_unique_wall_without_manual_confirmation() -> None:
    schedule = ReinforcementSchedule(
        rows=(_row("S7159", diameter=28, source_row=2),),
        duplicate_wall_ids=(),
    )

    plan = match_reinforcement(_group("S7159", 2000), schedule)

    assert len(plan.assignments) == 1
    assert plan.assignments[0].output_wall_id == "S7159"
    assert plan.assignments[0].rebar_row.source_row == 2
    assert not plan.requires_manual_confirmation


def test_single_image_group_uses_largest_duplicate_configuration_as_envelope() -> None:
    schedule = ReinforcementSchedule(
        rows=(
            _row("S7157", diameter=36, source_row=28),
            _row("S7157", diameter=32, source_row=29),
        ),
        duplicate_wall_ids=("S7157",),
    )

    plan = match_reinforcement(_group("S7157", 4000), schedule)

    assert plan.assignments[0].rebar_row is None
    assert plan.assignments[0].cell_for("X") is None
    assert not plan.requires_manual_confirmation
    assert {warning.code for warning in plan.warnings} == {
        "duplicate_reinforcement_rows"
    }


def test_two_image_groups_pair_larger_demand_with_larger_configuration() -> None:
    schedule = ReinforcementSchedule(
        rows=(
            _row("S7157", diameter=36, source_row=28),
            _row("S7157", diameter=32, source_row=29),
        ),
        duplicate_wall_ids=("S7157",),
    )
    recognized = [
        *_group("S7157-1", 3000, base_wall_id="S7157", group_index=1),
        *_group("S7157-2", 5000, base_wall_id="S7157", group_index=2),
    ]

    plan = match_reinforcement(recognized, schedule)
    by_output = {
        assignment.output_wall_id: assignment
        for assignment in plan.assignments
    }

    assert by_output["S7157-1"].rebar_row is None
    assert by_output["S7157-2"].rebar_row is None
    assert all(
        assignment.blank_fields == ("X", "Y", "Z")
        for assignment in by_output.values()
    )
    assert {warning.code for warning in plan.warnings} == {
        "duplicate_reinforcement_rows",
        "split_image_group",
    }


def test_alpha_suffix_wall_does_not_merge_with_base_wall() -> None:
    schedule = ReinforcementSchedule(
        rows=(
            _row("S7157", diameter=36, source_row=2),
            _row("S7157A", diameter=28, source_row=3),
        ),
        duplicate_wall_ids=(),
    )

    plan = match_reinforcement(
        [*_group("S7157", 3000), *_group("S7157A", 2000)],
        schedule,
    )

    assert {
        (assignment.output_wall_id, assignment.rebar_row.wall_id)
        for assignment in plan.assignments
    } == {("S7157", "S7157"), ("S7157A", "S7157A")}


def test_records_image_and_workbook_only_walls_and_keeps_matched_subset() -> None:
    schedule = ReinforcementSchedule(
        rows=(
            _row("S7159", diameter=28, source_row=2),
            _row("S7160", diameter=32, source_row=3),
        ),
        duplicate_wall_ids=(),
    )

    plan = match_reinforcement(
        [*_group("S7159", 2000), *_group("NDTJ1", 1000)],
        schedule,
    )

    assert [item.output_wall_id for item in plan.assignments] == ["NDTJ1", "S7159"]
    assert plan.assignments[0].rebar_row is None
    assert plan.image_only_wall_ids == ("NDTJ1",)
    assert plan.workbook_only_wall_ids == ("S7160",)
    assert plan.image_unique_wall_count == 2
    assert plan.matched_unique_wall_count == 1
    assert plan.requires_wall_count_confirmation is True
    assert plan.requires_manual_confirmation is False
    assert {warning.code for warning in plan.warnings} == {
        "image_only_wall",
        "workbook_only_wall",
    }


def test_duplicate_workbook_only_wall_is_always_reported_for_review() -> None:
    schedule = ReinforcementSchedule(
        rows=(
            _row("S7159", diameter=28, source_row=2),
            _row("N7004A", diameter=32, source_row=3),
            _row("N7004A", diameter=36, source_row=4),
        ),
        duplicate_wall_ids=("N7004A",),
    )

    plan = match_reinforcement(_group("S7159", 2000), schedule)

    duplicate_warnings = [
        warning
        for warning in plan.warnings
        if warning.code == "duplicate_reinforcement_rows"
    ]
    assert len(duplicate_warnings) == 1
    assert duplicate_warnings[0].identity == "N7004A"
    assert duplicate_warnings[0].blank_fields == ("X", "Y", "Z")
    assert duplicate_warnings[0].source_row == 3
    assert plan.workbook_only_wall_ids == ("N7004A",)
    assert not any(
        assignment.base_wall_id == "N7004A"
        for assignment in plan.assignments
    )


def test_ai_review_row_keeps_resolved_directions_and_blanks_only_requested_field() -> None:
    warning = ReinforcementNormalizationWarning(
        code="needs_review",
        scope="wall",
        identity="N5012",
        direction="X",
        source_sheet="AI",
        source_row=7,
        source_cells={"wall": "A7", "X": "B7", "Y": "C7", "Z": "D7"},
        original_values={"wall": "N5012", "X": "?", "Y": "1D28@200", "Z": "1C14@400*400"},
        resolved_values={
            "wall_id": "N5012",
            "Y": "1D28间距200",
            "Z": "1C14间距400*400",
        },
        reason="X 向写法无法唯一确定",
        blank_fields=("X",),
    )

    plan = match_reinforcement(
        _group("N5012", 2000),
        ReinforcementSchedule(rows=(), duplicate_wall_ids=()),
        normalization_warnings=(warning,),
    )

    assignment = plan.assignments[0]
    assert assignment.cell_for("X") is None
    assert assignment.cell_for("Y").selected.canonical_specification == "1D28间距200"
    assert assignment.cell_for("Z").selected.canonical_specification == "1C14间距400*400"
    assert assignment.blank_fields == ("X",)


def test_unknown_review_identity_keeps_image_group_fully_blank() -> None:
    warning = ReinforcementNormalizationWarning(
        code="needs_review",
        scope="wall",
        identity=None,
        direction=None,
        source_sheet="AI",
        source_row=8,
        source_cells={"wall": "A8"},
        original_values={"wall": "?"},
        resolved_values={},
        reason="墙号无法识别",
        blank_fields=("wall_id", "X", "Y", "Z"),
    )

    plan = match_reinforcement(
        _group("IMG9001", 2000),
        ReinforcementSchedule(rows=(), duplicate_wall_ids=()),
        normalization_warnings=(warning,),
    )

    assert plan.assignments[0].output_wall_id == "IMG9001"
    assert plan.assignments[0].blank_fields == ("X", "Y", "Z")
    assert all(plan.assignments[0].cell_for(item) is None for item in "XYZ")


def test_missing_wall_direction_remains_a_hard_archive_structure_failure() -> None:
    with pytest.raises(CalculationMatchingError, match="缺少 Z"):
        match_reinforcement(
            _group("S7159", 2000)[:2],
            ReinforcementSchedule(
                rows=(_row("S7159", diameter=28, source_row=2),),
                duplicate_wall_ids=(),
            ),
        )
