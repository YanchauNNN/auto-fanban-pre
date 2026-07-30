from __future__ import annotations

from pathlib import Path

import pytest

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

    assert plan.assignments[0].rebar_row.source_row == 28
    assert plan.requires_manual_confirmation
    assert plan.confirmations[0].reasons == ("duplicate_reinforcement_rows",)


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

    assert by_output["S7157-1"].rebar_row.source_row == 29
    assert by_output["S7157-2"].rebar_row.source_row == 28
    assert plan.requires_manual_confirmation
    assert all(
        confirmation.reasons
        == ("duplicate_reinforcement_rows", "split_image_group")
        for confirmation in plan.confirmations
    )


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


def test_rejects_image_wall_missing_from_reinforcement_schedule() -> None:
    schedule = ReinforcementSchedule(
        rows=(_row("S7159", diameter=28, source_row=2),),
        duplicate_wall_ids=(),
    )

    with pytest.raises(CalculationMatchingError, match="NDTJ1"):
        match_reinforcement(_group("NDTJ1", 1000), schedule)
