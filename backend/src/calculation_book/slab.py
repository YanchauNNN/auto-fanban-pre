from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from .ai_reinforcement_schema import ReinforcementNormalizationWarning
from .archive import SlabReinforcementFigure
from .ocr import StressLegendReading
from .reinforcement_input import (
    NormalizedSlabReinforcementRow,
    ParsedRebarCell,
    SlabReinforcementSchedule,
    parse_linear_rebar_cell,
)


class SlabMatchingError(ValueError):
    pass


@dataclass(frozen=True)
class RecognizedSlabFigure:
    source: SlabReinforcementFigure
    reading: StressLegendReading | None


@dataclass(frozen=True)
class SlabAssignment:
    elevation: str
    key: str
    position: str | None
    direction: str
    figure: RecognizedSlabFigure
    rebar_cell: ParsedRebarCell | None
    source_cell: str | None
    source_row: int | None


@dataclass(frozen=True)
class SlabMatchingPlan:
    assignments: tuple[SlabAssignment, ...]
    warnings: tuple[ReinforcementNormalizationWarning, ...] = ()

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


def slab_rebar_item_id(figure: SlabReinforcementFigure) -> str:
    """Return the stable backend-owned route for one slab layer image."""

    return f"slab:{figure.elevation}:{_figure_key(figure)}"


def build_ai_slab_plan(
    figures: list[RecognizedSlabFigure] | tuple[RecognizedSlabFigure, ...],
    *,
    selected_cells: Mapping[str, ParsedRebarCell],
    missing_reasons: Mapping[str, tuple[str, str]] | None = None,
) -> SlabMatchingPlan:
    """Build a partial five/seven-layer slab plan keyed by elevation and layer."""

    base = match_slab_reinforcement(
        figures,
        SlabReinforcementSchedule(rows=()),
        allow_partial=True,
    )
    known_item_ids = {
        slab_rebar_item_id(assignment.figure.source)
        for assignment in base.assignments
    }
    unknown_item_ids = set(selected_cells) - known_item_ids
    if unknown_item_ids:
        raise SlabMatchingError(
            "AI 配筋结果包含未知楼板方向：" + ", ".join(sorted(unknown_item_ids))
        )

    reasons = missing_reasons or {}
    assignments: list[SlabAssignment] = []
    warnings: list[ReinforcementNormalizationWarning] = []
    for assignment in base.assignments:
        item_id = slab_rebar_item_id(assignment.figure.source)
        cell = selected_cells.get(item_id)
        if cell is not None and assignment.figure.reading is None:
            raise SlabMatchingError(
                f"{item_id} 没有有效 OCR 结果却存在 AI 配筋建议"
            )
        assignments.append(
            replace(
                assignment,
                rebar_cell=cell,
                source_cell=None,
                source_row=None,
            )
        )
        if cell is not None:
            continue
        code, reason = reasons.get(
            item_id,
            ("AI_NEEDS_REVIEW", "当前方向没有通过后端验算的 AI 配筋建议"),
        )
        warnings.append(
            _warning(
                code=code,
                identity=assignment.elevation,
                direction=assignment.direction,
                reason=reason,
                blank_fields=(assignment.key,),
            )
        )
    return SlabMatchingPlan(
        assignments=tuple(assignments),
        warnings=tuple(warnings),
    )


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
    *,
    normalization_warnings: tuple[ReinforcementNormalizationWarning, ...] = (),
    allow_partial: bool = False,
) -> SlabMatchingPlan:
    if not figures:
        raise SlabMatchingError("压缩包根目录没有可识别的楼板应力图片")

    rows_by_elevation = {row.elevation: row for row in schedule.rows}
    reviews_by_elevation = {
        warning.identity: warning
        for warning in normalization_warnings
        if warning.scope == "slab" and warning.identity is not None
    }
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
    matching_warnings: list[ReinforcementNormalizationWarning] = [
        warning for warning in normalization_warnings if warning.scope == "slab"
    ]
    for elevation, elevation_figures in figures_by_elevation.items():
        row = rows_by_elevation.get(elevation)
        review = reviews_by_elevation.get(elevation)
        if row is None and review is None and not allow_partial:
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
        if row is None and review is None:
            matching_warnings.append(
                _warning(
                    code="image_only_slab",
                    identity=elevation,
                    reason="应力图中存在楼板标高，但配筋表没有对应数据",
                    blank_fields=tuple(order),
                )
            )

        for key in order:
            cell = _row_cell(row, key) if row is not None else None
            if review is not None:
                if key in review.blank_fields:
                    cell = None
                else:
                    specification = review.resolved_values.get(key)
                    if specification is not None:
                        cell = parse_linear_rebar_cell(specification)
            if cell is None and not allow_partial:
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
                    source_cell=(
                        row.source_cells.get(key)
                        if row is not None
                        else (
                            review.source_cells.get(key)
                            if review is not None
                            else None
                        )
                    ),
                    source_row=(
                        row.source_row
                        if row is not None
                        else (review.source_row if review is not None else None)
                    ),
                )
            )

    if allow_partial:
        for elevation, row in rows_by_elevation.items():
            if elevation in figures_by_elevation:
                continue
            matching_warnings.append(
                _warning(
                    code="workbook_only_slab",
                    identity=elevation,
                    source_sheet=row.source_sheet,
                    source_row=row.source_row,
                    source_cells=row.source_cells,
                    reason="配筋表中存在楼板标高，但应力图中没有对应图组",
                    blank_fields=(),
                )
            )

    return SlabMatchingPlan(
        assignments=tuple(assignments),
        warnings=tuple(_deduplicate_warnings(matching_warnings)),
    )


def _warning(
    *,
    code: str,
    identity: str,
    reason: str,
    blank_fields: tuple[str, ...],
    direction: str | None = None,
    source_sheet: str = "",
    source_row: int = 0,
    source_cells: dict[str, str] | None = None,
) -> ReinforcementNormalizationWarning:
    return ReinforcementNormalizationWarning(
        code=code,
        scope="slab",
        identity=identity,
        direction=direction,
        source_sheet=source_sheet,
        source_row=source_row,
        source_cells=source_cells or {},
        original_values={},
        resolved_values={},
        reason=reason,
        blank_fields=blank_fields,
    )


def _deduplicate_warnings(
    warnings: list[ReinforcementNormalizationWarning],
) -> list[ReinforcementNormalizationWarning]:
    seen: set[tuple[object, ...]] = set()
    result: list[ReinforcementNormalizationWarning] = []
    for warning in warnings:
        key = (
            warning.code,
            warning.scope,
            warning.identity,
            warning.direction,
            warning.source_sheet,
            warning.source_row,
            warning.blank_fields,
        )
        if key not in seen:
            seen.add(key)
            result.append(warning)
    return result
