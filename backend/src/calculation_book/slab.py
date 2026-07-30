from __future__ import annotations

from dataclasses import dataclass

from .archive import SlabReinforcementFigure
from .ocr import StressLegendReading
from .reinforcement_input import (
    NormalizedSlabReinforcementRow,
    ParsedRebarCell,
    SlabReinforcementSchedule,
)


class SlabMatchingError(ValueError):
    pass


@dataclass(frozen=True)
class RecognizedSlabFigure:
    source: SlabReinforcementFigure
    reading: StressLegendReading


@dataclass(frozen=True)
class SlabAssignment:
    elevation: str
    key: str
    position: str | None
    direction: str
    figure: RecognizedSlabFigure
    rebar_cell: ParsedRebarCell
    source_cell: str
    source_row: int


@dataclass(frozen=True)
class SlabMatchingPlan:
    assignments: tuple[SlabAssignment, ...]

    @property
    def elevation_count(self) -> int:
        return len({assignment.elevation for assignment in self.assignments})


_REQUIRED_KEYS = ("top_x", "bottom_x", "top_y", "bottom_y", "z")
_ORDER_WITHOUT_MIDDLE = ("top_x", "bottom_x", "top_y", "bottom_y", "z")
_ORDER_WITH_MIDDLE = (
    "top_x",
    "middle_x",
    "bottom_x",
    "top_y",
    "middle_y",
    "bottom_y",
    "z",
)


def _figure_key(figure: SlabReinforcementFigure) -> str:
    if figure.direction == "Z":
        return "z"
    if figure.position is None:
        raise SlabMatchingError(
            f"楼板图 {figure.path.name} 的 X/Y 方向缺少 TOP/MIDDLE/BOTTOM"
        )
    return f"{figure.position.lower()}_{figure.direction.lower()}"


def _row_cell(
    row: NormalizedSlabReinforcementRow,
    key: str,
) -> ParsedRebarCell | None:
    return {
        "top_x": row.top_x,
        "middle_x": row.middle_x,
        "bottom_x": row.bottom_x,
        "top_y": row.top_y,
        "middle_y": row.middle_y,
        "bottom_y": row.bottom_y,
        "z": row.z,
    }[key]


def match_slab_reinforcement(
    figures: list[RecognizedSlabFigure] | tuple[RecognizedSlabFigure, ...],
    schedule: SlabReinforcementSchedule,
) -> SlabMatchingPlan:
    if not figures:
        raise SlabMatchingError("压缩包根目录没有可识别的楼板应力图片")

    rows_by_elevation = {row.elevation: row for row in schedule.rows}
    figures_by_elevation: dict[str, dict[str, RecognizedSlabFigure]] = {}

    for figure in figures:
        elevation_figures = figures_by_elevation.setdefault(
            figure.source.elevation,
            {},
        )
        key = _figure_key(figure.source)
        if key in elevation_figures:
            raise SlabMatchingError(
                f"楼板标高 {figure.source.elevation} 存在重复图片：{key}"
            )
        elevation_figures[key] = figure

    assignments: list[SlabAssignment] = []
    for elevation, elevation_figures in figures_by_elevation.items():
        row = rows_by_elevation.get(elevation)
        if row is None:
            raise SlabMatchingError(
                f"楼板标高 {elevation} 在“楼板配筋”Sheet中没有对应数据行"
            )

        missing = [
            key
            for key in _REQUIRED_KEYS
            if key not in elevation_figures
        ]
        if missing:
            names = "/".join(key.replace("_", "-").upper() for key in missing)
            raise SlabMatchingError(
                f"楼板标高 {elevation} 缺少 {names} 应力图片"
            )

        has_middle_x = "middle_x" in elevation_figures
        has_middle_y = "middle_y" in elevation_figures
        if has_middle_x != has_middle_y:
            raise SlabMatchingError(
                f"楼板标高 {elevation} 的 MIDDLE-X/Y 图片必须成对出现"
            )
        order = (
            _ORDER_WITH_MIDDLE
            if has_middle_x and has_middle_y
            else _ORDER_WITHOUT_MIDDLE
        )

        for key in order:
            cell = _row_cell(row, key)
            if cell is None:
                raise SlabMatchingError(
                    f"楼板标高 {elevation} 包含中层图片，但配筋表中层实配钢筋为空"
                )
            figure = elevation_figures[key]
            assignments.append(
                SlabAssignment(
                    elevation=elevation,
                    key=key,
                    position=figure.source.position,
                    direction=figure.source.direction,
                    figure=figure,
                    rebar_cell=cell,
                    source_cell=row.source_cells[key],
                    source_row=row.source_row,
                )
            )

    return SlabMatchingPlan(assignments=tuple(assignments))
