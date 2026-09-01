from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.calculation_book.archive import SlabReinforcementFigure
from src.calculation_book.ocr import StressLegendReading
from src.calculation_book.reinforcement_input import (
    NormalizedSlabReinforcementRow,
    SlabReinforcementSchedule,
    parse_linear_rebar_cell,
)
from src.calculation_book.slab import (
    RecognizedSlabFigure,
    SlabMatchingError,
    build_ai_slab_plan,
    match_slab_reinforcement,
    slab_rebar_item_id,
)


def _figure(
    elevation: str,
    position: str | None,
    direction: str,
) -> RecognizedSlabFigure:
    stem = (
        f"{elevation}-{position}-{direction}"
        if position is not None
        else f"{elevation}-Z"
    )
    return RecognizedSlabFigure(
        source=SlabReinforcementFigure(
            elevation=elevation,
            position=position,
            direction=direction,
            path=Path(f"{stem}.png"),
            sort_key=(0, 0, 0),
        ),
        reading=StressLegendReading(
            smn=0,
            smx=1000,
            legend_values=tuple(1000 * index / 9 for index in range(10)),
        ),
    )


def _row(
    elevation: str = "11.45",
    *,
    include_middle: bool = False,
) -> NormalizedSlabReinforcementRow:
    source_cells = {
        "elevation": "A2",
        "top_x": "B2",
        "top_y": "C2",
        "middle_x": "D2",
        "middle_y": "E2",
        "bottom_x": "F2",
        "bottom_y": "G2",
        "z": "H2",
    }
    return NormalizedSlabReinforcementRow(
        elevation=elevation,
        top_x=parse_linear_rebar_cell("1D36@200"),
        top_y=parse_linear_rebar_cell("1D40@200"),
        middle_x=(
            parse_linear_rebar_cell("1D32@200") if include_middle else None
        ),
        middle_y=(
            parse_linear_rebar_cell("1D34@200") if include_middle else None
        ),
        bottom_x=parse_linear_rebar_cell("1D30@200"),
        bottom_y=parse_linear_rebar_cell("1D28@200"),
        z=parse_linear_rebar_cell("1D16@200"),
        source_sheet="楼板配筋",
        source_row=2,
        source_cells=source_cells,
    )


def _five_figures() -> list[RecognizedSlabFigure]:
    return [
        _figure("11.45", "TOP", "X"),
        _figure("11.45", "BOTTOM", "X"),
        _figure("11.45", "TOP", "Y"),
        _figure("11.45", "BOTTOM", "Y"),
        _figure("11.45", None, "Z"),
    ]


def test_matches_five_groups_in_approved_output_order() -> None:
    plan = match_slab_reinforcement(
        _five_figures(),
        SlabReinforcementSchedule(rows=(_row(),)),
    )

    assert [assignment.key for assignment in plan.assignments] == [
        "top_x",
        "bottom_x",
        "top_y",
        "bottom_y",
        "z",
    ]
    assert plan.assignments[0].source_cell == "B2"
    assert plan.assignments[-1].rebar_cell.selected.actual_area == pytest.approx(
        3.141592653589793 * 8**2 * 5
    )


def test_middle_pair_expands_level_to_seven_groups() -> None:
    figures = [
        _figure("11.45", "TOP", "X"),
        _figure("11.45", "MIDDLE", "X"),
        _figure("11.45", "BOTTOM", "X"),
        _figure("11.45", "TOP", "Y"),
        _figure("11.45", "MIDDLE", "Y"),
        _figure("11.45", "BOTTOM", "Y"),
        _figure("11.45", None, "Z"),
    ]

    plan = match_slab_reinforcement(
        figures,
        SlabReinforcementSchedule(rows=(_row(include_middle=True),)),
    )

    assert [assignment.key for assignment in plan.assignments] == [
        "top_x",
        "middle_x",
        "bottom_x",
        "top_y",
        "middle_y",
        "bottom_y",
        "z",
    ]


def test_rejects_incomplete_middle_pair() -> None:
    figures = [*_five_figures(), _figure("11.45", "MIDDLE", "X")]

    with pytest.raises(SlabMatchingError, match="MIDDLE-X/Y"):
        match_slab_reinforcement(
            figures,
            SlabReinforcementSchedule(rows=(_row(include_middle=True),)),
        )


def test_rejects_missing_required_figure() -> None:
    figures = [
        figure
        for figure in _five_figures()
        if not (
            figure.source.position == "BOTTOM"
            and figure.source.direction == "Y"
        )
    ]

    with pytest.raises(SlabMatchingError, match="BOTTOM-Y"):
        match_slab_reinforcement(
            figures,
            SlabReinforcementSchedule(rows=(_row(),)),
        )


def test_rejects_duplicate_figure_key() -> None:
    figures = [*_five_figures(), _figure("11.45", "TOP", "X")]

    with pytest.raises(SlabMatchingError, match="重复"):
        match_slab_reinforcement(
            figures,
            SlabReinforcementSchedule(rows=(_row(),)),
        )


def test_rejects_missing_reinforcement_elevation() -> None:
    with pytest.raises(SlabMatchingError, match="11.45"):
        match_slab_reinforcement(
            _five_figures(),
            SlabReinforcementSchedule(rows=(_row("15.95"),)),
        )


def test_middle_images_require_middle_reinforcement_cells() -> None:
    figures = [
        *_five_figures(),
        _figure("11.45", "MIDDLE", "X"),
        _figure("11.45", "MIDDLE", "Y"),
    ]

    with pytest.raises(SlabMatchingError, match="中层"):
        match_slab_reinforcement(
            figures,
            SlabReinforcementSchedule(rows=(_row(),)),
        )


def test_rejects_empty_slab_figure_set() -> None:
    with pytest.raises(SlabMatchingError, match="没有可识别"):
        match_slab_reinforcement(
            [],
            SlabReinforcementSchedule(rows=(_row(),)),
        )


def test_ai_partial_slab_preserves_all_figures_and_only_blanks_review_field() -> None:
    warning = SimpleNamespace(
        code="needs_review",
        scope="slab",
        identity="11.45",
        direction="top_x",
        source_sheet="AI-slab",
        source_row=7,
        source_cells={
            "elevation": "A7",
            "top_x": "B7",
            "top_y": "C7",
            "bottom_x": "F7",
            "bottom_y": "G7",
            "z": "H7",
        },
        original_values={},
        resolved_values={
            "elevation": "11.45",
            "top_y": "1D40间距200",
            "bottom_x": "1D30间距200",
            "bottom_y": "1D28间距200",
            "z": "1D16间距200",
        },
        reason="top_x 待确认",
        blank_fields=("top_x",),
    )

    plan = match_slab_reinforcement(
        _five_figures(),
        SlabReinforcementSchedule(rows=(_row(),)),
        normalization_warnings=(warning,),
        allow_partial=True,
    )

    assert [item.key for item in plan.assignments] == [
        "top_x",
        "bottom_x",
        "top_y",
        "bottom_y",
        "z",
    ]
    by_key = {item.key: item for item in plan.assignments}
    assert by_key["top_x"].rebar_cell is None
    assert by_key["top_y"].rebar_cell.selected.canonical_specification == "1D40间距200"
    assert {warning.code for warning in plan.warnings} == {"needs_review"}


def test_ai_image_only_slab_keeps_five_blank_assignments() -> None:
    plan = match_slab_reinforcement(
        _five_figures(),
        SlabReinforcementSchedule(rows=()),
        allow_partial=True,
    )

    assert len(plan.assignments) == 5
    assert all(item.rebar_cell is None for item in plan.assignments)
    assert [warning.code for warning in plan.warnings] == ["image_only_slab"]


def test_ai_slab_plan_routes_middle_layers_without_direction_collisions() -> None:
    figures = [
        *_five_figures(),
        _figure("11.45", "MIDDLE", "X"),
        _figure("11.45", "MIDDLE", "Y"),
    ]
    selected = {
        slab_rebar_item_id(figure.source): parse_linear_rebar_cell(
            "1D25@200"
        )
        for figure in figures
        if figure.source.direction != "Z"
    }
    z_figure = next(figure for figure in figures if figure.source.direction == "Z")
    missing_id = slab_rebar_item_id(z_figure.source)

    plan = build_ai_slab_plan(
        figures,
        selected_cells=selected,
        missing_reasons={missing_id: ("AI_NEEDS_REVIEW", "模型未确定")},
    )

    assert [assignment.key for assignment in plan.assignments] == [
        "top_x",
        "middle_x",
        "bottom_x",
        "top_y",
        "middle_y",
        "bottom_y",
        "z",
    ]
    assert len({slab_rebar_item_id(item.figure.source) for item in plan.assignments}) == 7
    assert all(
        item.rebar_cell is not None
        for item in plan.assignments
        if item.key != "z"
    )
    assert plan.assignments[-1].rebar_cell is None
    assert plan.warnings[0].direction == "Z"
    assert plan.warnings[0].blank_fields == ("z",)
