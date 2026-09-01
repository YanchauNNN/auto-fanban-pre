from __future__ import annotations

import math

from src.calculation_book.narrative import (
    build_reinforcement_narrative,
    build_slab_reinforcement_narrative,
)
from src.calculation_book.ocr import StressLegendReading


def test_uses_largest_legend_value_below_actual_area_when_smx_exceeds_actual() -> None:
    reading = StressLegendReading(
        smn=912,
        smx=6953,
        legend_values=(912, 1583, 2254, 2925, 3597, 4268, 4939, 5610, 6281, 6953),
    )

    assert build_reinforcement_narrative(
        wall_id="N5007",
        direction="Y",
        reading=reading,
        rebar_specification="1排40 @200",
        actual_area=6280,
    ) == (
        "墙N5007-竖向钢筋计算配筋面积大部分小于5610 mm²/m。"
        "选用钢筋1排40 @200（配筋面积为6280 mm²/m）。 配筋结果包络计算结果。"
    )


def test_exact_pi_area_can_envelope_the_next_legend_value() -> None:
    reading = StressLegendReading(
        smn=912,
        smx=6953,
        legend_values=(912, 1583, 2254, 2925, 3597, 4268, 4939, 5610, 6281, 6953),
    )

    assert build_reinforcement_narrative(
        wall_id="N5007",
        direction="Y",
        reading=reading,
        rebar_specification="1排40@200",
        actual_area=math.pi * 20**2 * 5,
    ) == (
        "墙N5007-竖向钢筋计算配筋面积大部分小于6281 mm²/m。"
        "选用钢筋1排40@200（配筋面积为6283.2 mm²/m）。 配筋结果包络计算结果。"
    )


def test_uses_smx_as_maximum_when_actual_area_envelopes_smx() -> None:
    reading = StressLegendReading(
        smn=1115,
        smx=4756,
        legend_values=(1115, 1520, 1924, 2329, 2733, 3138, 3543, 3947, 4352, 4756),
    )

    assert build_reinforcement_narrative(
        wall_id="N5008",
        direction="Y",
        reading=reading,
        rebar_specification="1排36 @200",
        actual_area=5089.4,
    ) == (
        "墙N5008-竖向钢筋计算配筋面积的最大值为4756 mm²/m。"
        "选用钢筋1排36 @200（配筋面积为5089.4 mm²/m）。 配筋结果包络计算结果。"
    )


def test_z_without_smx_uses_constructor_reinforcement_wording() -> None:
    reading = StressLegendReading(
        smn=0,
        smx=0,
        legend_values=(),
        is_zero_result=True,
    )

    assert build_reinforcement_narrative(
        wall_id="N5012",
        direction="Z",
        reading=reading,
        rebar_specification="1排14@400x400",
        actual_area=3.141592653589793 * 7**2 * 2.5 * 2.5,
    ) == (
        "墙N5012-拉筋钢筋计算配筋面积为0mm²/m。"
        "选用钢筋1排14@400x400（配筋面积为962.1 mm²/m）作为构造钢筋。 "
        "配筋结果包络计算结果。"
    )


def test_builds_slab_layer_narrative_with_exact_actual_area() -> None:
    reading = StressLegendReading(
        smn=0,
        smx=4888,
        legend_values=(0, 543, 1086, 1629, 2172, 2715, 3259, 3802, 4345, 4888),
    )

    assert build_slab_reinforcement_narrative(
        elevation="11.45",
        layer_label="顶层水平",
        reading=reading,
        rebar_specification="1排36@200",
        actual_area=math.pi * 18**2 * 5,
        is_z=False,
    ) == (
        "11.45m楼板顶层水平钢筋计算配筋面积的最大值为4888 mm²/m。"
        "选用钢筋1排36@200（配筋面积为5089.4 mm²/m）。 "
        "配筋结果包络计算结果。"
    )


def test_builds_zero_slab_z_narrative_as_constructor_reinforcement() -> None:
    reading = StressLegendReading(
        smn=0,
        smx=0,
        legend_values=(),
        is_zero_result=True,
    )

    assert build_slab_reinforcement_narrative(
        elevation="11.45",
        layer_label="纵向拉筋",
        reading=reading,
        rebar_specification="1排16@200",
        actual_area=math.pi * 8**2 * 5,
        is_z=True,
    ) == (
        "11.45m楼板纵向拉筋计算配筋面积为0mm²/m。"
        "选用钢筋1排16@200（配筋面积为1005.3 mm²/m）作为构造钢筋。 "
        "配筋结果包络计算结果。"
    )


def test_ai_wall_narrative_marks_selection_as_a_suggestion() -> None:
    reading = StressLegendReading(
        smn=0,
        smx=1000,
        legend_values=tuple(1000 * index / 9 for index in range(10)),
    )

    narrative = build_reinforcement_narrative(
        wall_id="S7157A",
        direction="X",
        reading=reading,
        rebar_specification="1排18@200",
        actual_area=1272.345,
        is_ai_suggested=True,
    )

    assert "建议选用钢筋1排18@200" in narrative
    assert "。选用钢筋" not in narrative


def test_ai_slab_narrative_marks_selection_as_a_suggestion() -> None:
    reading = StressLegendReading(
        smn=0,
        smx=1000,
        legend_values=tuple(1000 * index / 9 for index in range(10)),
    )

    narrative = build_slab_reinforcement_narrative(
        elevation="11.45",
        layer_label="中层竖向",
        reading=reading,
        rebar_specification="1排18@200",
        actual_area=1272.345,
        is_z=False,
        is_ai_suggested=True,
    )

    assert "建议选用钢筋1排18@200" in narrative
    assert "。选用钢筋" not in narrative
