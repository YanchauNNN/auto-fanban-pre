from __future__ import annotations

import math

from src.calculation_book.narrative import build_reinforcement_narrative
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
