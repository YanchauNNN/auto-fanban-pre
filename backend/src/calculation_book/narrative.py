from __future__ import annotations

import math

from .ocr import StressLegendReading

_DIRECTION_LABELS = {
    "X": "水平向",
    "Y": "竖向",
    "Z": "拉筋",
}


def _format_number(value: float | int) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("配筋面积必须是有限数字")
    return f"{number:g}"


def _format_actual_area(value: float | int) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("配筋面积必须是有限数字")
    return f"{round(number, 1):g}"


def select_calculation_reference(
    reading: StressLegendReading,
    *,
    actual_area: float | int,
) -> float:
    actual = float(actual_area)
    if reading.is_zero_result:
        return 0.0
    if actual >= reading.smx:
        return reading.smx
    lower_values = [value for value in reading.legend_values if value < actual]
    if not lower_values:
        raise ValueError(
            f"实际配筋面积 {_format_number(actual)} 小于或等于图例最小值，"
            "无法生成包络文案"
        )
    return max(lower_values)


def build_reinforcement_narrative(
    *,
    wall_id: str,
    direction: str,
    reading: StressLegendReading,
    rebar_specification: str,
    actual_area: float | int,
) -> str:
    normalized_direction = direction.strip().upper()
    try:
        direction_label = _DIRECTION_LABELS[normalized_direction]
    except KeyError as exc:
        raise ValueError(f"不支持的配筋方向：{direction}") from exc

    actual = float(actual_area)
    actual_text = _format_actual_area(actual)
    prefix = f"墙{wall_id}-{direction_label}钢筋"
    selection = (
        f"选用钢筋{rebar_specification}"
        f"（配筋面积为{actual_text} mm²/m）"
    )
    conclusion = " 配筋结果包络计算结果。"

    if reading.is_zero_result:
        if normalized_direction != "Z":
            raise ValueError("只有 Z 向图可以使用无 SMX 的零值结果")
        return (
            f"{prefix}计算配筋面积为0mm²/m。"
            f"{selection}作为构造钢筋。"
            f"{conclusion}"
        )

    if actual >= reading.smx:
        return (
            f"{prefix}计算配筋面积的最大值为{_format_number(reading.smx)} mm²/m。"
            f"{selection}。"
            f"{conclusion}"
        )

    reference = select_calculation_reference(reading, actual_area=actual)
    return (
        f"{prefix}计算配筋面积大部分小于{_format_number(reference)} mm²/m。"
        f"{selection}。"
        f"{conclusion}"
    )


def build_slab_reinforcement_narrative(
    *,
    elevation: str,
    layer_label: str,
    reading: StressLegendReading,
    rebar_specification: str,
    actual_area: float | int,
    is_z: bool,
) -> str:
    actual = float(actual_area)
    actual_text = _format_actual_area(actual)
    prefix = (
        f"{elevation}m楼板{layer_label}"
        f"{'' if is_z else '钢筋'}"
    )
    selection = (
        f"选用钢筋{rebar_specification}"
        f"（配筋面积为{actual_text} mm²/m）"
    )
    conclusion = " 配筋结果包络计算结果。"

    if reading.is_zero_result:
        if not is_z:
            raise ValueError("只有楼板纵向拉筋图可以使用无 SMX 的零值结果")
        return (
            f"{prefix}计算配筋面积为0mm²/m。"
            f"{selection}作为构造钢筋。"
            f"{conclusion}"
        )

    if actual >= reading.smx:
        return (
            f"{prefix}计算配筋面积的最大值为{_format_number(reading.smx)} mm²/m。"
            f"{selection}。"
            f"{conclusion}"
        )

    reference = select_calculation_reference(reading, actual_area=actual)
    return (
        f"{prefix}计算配筋面积大部分小于{_format_number(reference)} mm²/m。"
        f"{selection}。"
        f"{conclusion}"
    )
