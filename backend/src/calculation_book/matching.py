from __future__ import annotations

import re
from dataclasses import dataclass

from .ai_reinforcement_schema import ReinforcementNormalizationWarning
from .archive import ReinforcementFigure
from .ocr import StressLegendReading
from .reinforcement_input import (
    NormalizedReinforcementRow,
    ParsedRebarCell,
    ReinforcementSchedule,
    parse_rebar_cell,
)


class CalculationMatchingError(ValueError):
    pass


@dataclass(frozen=True)
class RecognizedFigure:
    source: ReinforcementFigure
    reading: StressLegendReading


@dataclass(frozen=True)
class ReinforcementAssignment:
    output_wall_id: str
    base_wall_id: str
    group_index: int | None
    figures: tuple[RecognizedFigure, ...]
    rebar_row: NormalizedReinforcementRow | None
    resolved_cells: tuple[tuple[str, ParsedRebarCell], ...] = ()
    blank_fields: tuple[str, ...] = ()

    @property
    def demand_score(self) -> float:
        return max(figure.reading.smx for figure in self.figures)

    def figure_for(self, direction: str) -> RecognizedFigure:
        normalized = direction.strip().upper()
        for figure in self.figures:
            if figure.source.direction == normalized:
                return figure
        raise KeyError(f"{self.output_wall_id} 缺少 {normalized} 向图")

    def cell_for(self, direction: str) -> ParsedRebarCell | None:
        normalized = direction.strip().upper()
        if normalized not in {"X", "Y", "Z"}:
            raise KeyError(f"不支持的配筋方向：{direction}")
        if normalized in self.blank_fields:
            return None
        resolved = dict(self.resolved_cells).get(normalized)
        if resolved is not None:
            return resolved
        if self.rebar_row is None:
            return None
        return {
            "X": self.rebar_row.x,
            "Y": self.rebar_row.y,
            "Z": self.rebar_row.z,
        }[normalized]


@dataclass(frozen=True)
class ManualConfirmation:
    output_wall_id: str
    base_wall_id: str
    selected_source_row: int
    candidate_source_rows: tuple[int, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ReinforcementMatchingPlan:
    assignments: tuple[ReinforcementAssignment, ...]
    confirmations: tuple[ManualConfirmation, ...]
    warnings: tuple[ReinforcementNormalizationWarning, ...] = ()
    image_only_wall_ids: tuple[str, ...] = ()
    workbook_only_wall_ids: tuple[str, ...] = ()
    image_wall_group_count: int = 0
    image_unique_wall_count: int = 0
    matched_unique_wall_count: int = 0

    @property
    def requires_wall_count_confirmation(self) -> bool:
        return bool(self.image_only_wall_ids or self.workbook_only_wall_ids)

    @property
    def requires_manual_confirmation(self) -> bool:
        return False


@dataclass(frozen=True)
class _ImageGroup:
    output_wall_id: str
    base_wall_id: str
    group_index: int | None
    figures: tuple[RecognizedFigure, ...]

    @property
    def demand_score(self) -> float:
        return max(figure.reading.smx for figure in self.figures)


def _wall_sort_key(wall_id: str) -> tuple[int, str]:
    match = re.search(r"\d+", wall_id)
    return (int(match.group()) if match is not None else 0, wall_id)


def _supply_score(row: NormalizedReinforcementRow) -> float:
    return max(
        row.x.selected.actual_area,
        row.y.selected.actual_area,
        row.z.selected.actual_area,
    )


def _group_figures(recognized: list[RecognizedFigure]) -> list[_ImageGroup]:
    grouped: dict[str, list[RecognizedFigure]] = {}
    for figure in recognized:
        grouped.setdefault(figure.source.wall_id, []).append(figure)

    groups: list[_ImageGroup] = []
    for wall_id, figures in grouped.items():
        directions = {figure.source.direction for figure in figures}
        missing = [direction for direction in ("X", "Y", "Z") if direction not in directions]
        if missing:
            raise CalculationMatchingError(
                f"{wall_id} 缺少 {'/'.join(missing)} 方向识别结果"
            )
        ordered = tuple(
            sorted(figures, key=lambda figure: "XYZ".index(figure.source.direction))
        )
        source = ordered[0].source
        groups.append(
            _ImageGroup(
                output_wall_id=wall_id,
                base_wall_id=source.base_wall_id,
                group_index=source.group_index,
                figures=ordered,
            )
        )
    groups.sort(key=lambda group: _wall_sort_key(group.output_wall_id))
    return groups


def _pair_groups_and_rows(
    groups: list[_ImageGroup],
    rows: list[NormalizedReinforcementRow],
) -> list[tuple[_ImageGroup, NormalizedReinforcementRow]]:
    if len(groups) == 1:
        return [(groups[0], max(rows, key=_supply_score))]
    if len(rows) == 1:
        return [(group, rows[0]) for group in groups]

    demand_order = sorted(
        groups,
        key=lambda group: (group.demand_score, group.output_wall_id),
    )
    supply_order = sorted(
        rows,
        key=lambda row: (_supply_score(row), row.source_row),
    )
    if len(supply_order) > len(demand_order):
        supply_order = supply_order[-len(demand_order) :]
    return [
        (group, supply_order[min(index, len(supply_order) - 1)])
        for index, group in enumerate(demand_order)
    ]


def match_reinforcement(
    recognized: list[RecognizedFigure],
    schedule: ReinforcementSchedule,
    *,
    normalization_warnings: tuple[ReinforcementNormalizationWarning, ...] = (),
) -> ReinforcementMatchingPlan:
    image_groups = _group_figures(recognized)
    schedule_by_wall: dict[str, list[NormalizedReinforcementRow]] = {}
    for row in schedule.rows:
        schedule_by_wall.setdefault(row.wall_id, []).append(row)

    image_groups_by_base: dict[str, list[_ImageGroup]] = {}
    for group in image_groups:
        image_groups_by_base.setdefault(group.base_wall_id, []).append(group)

    review_by_wall: dict[str, list[ReinforcementNormalizationWarning]] = {}
    for warning in normalization_warnings:
        if warning.scope == "wall" and warning.identity is not None:
            review_by_wall.setdefault(warning.identity.upper(), []).append(warning)

    assignments: list[ReinforcementAssignment] = []
    matching_warnings: list[ReinforcementNormalizationWarning] = [
        warning for warning in normalization_warnings if warning.scope == "wall"
    ]
    image_only_wall_ids: list[str] = []
    for base_wall_id, groups in image_groups_by_base.items():
        rows = schedule_by_wall.get(base_wall_id, [])
        reviews = review_by_wall.get(base_wall_id, [])
        duplicate_rows = (
            base_wall_id in schedule.duplicate_wall_ids
            or len(rows) + len(reviews) > 1
        )
        if duplicate_rows:
            source_sheet, source_row, source_cells = _wall_source(rows, reviews)
            matching_warnings.append(
                _warning(
                    code="duplicate_reinforcement_rows",
                    scope="wall",
                    identity=base_wall_id,
                    source_sheet=source_sheet,
                    source_row=source_row,
                    source_cells=source_cells,
                    reason="同一墙体存在重复配筋行",
                    blank_fields=("X", "Y", "Z"),
                )
            )

        if rows:
            pairs: list[tuple[_ImageGroup, NormalizedReinforcementRow | None]] = [
                (group, row) for group, row in _pair_groups_and_rows(groups, rows)
            ]
        else:
            pairs = [(group, None) for group in groups]

        if not rows and not reviews:
            image_only_wall_ids.append(base_wall_id)
            matching_warnings.append(
                _warning(
                    code="image_only_wall",
                    scope="wall",
                    identity=base_wall_id,
                    reason="应力图中存在墙体，但配筋表没有对应数据",
                    blank_fields=("X", "Y", "Z"),
                )
            )

        for group, row in pairs:
            split_group = group.group_index is not None
            partial_cells = _review_cells(reviews[0]) if len(reviews) == 1 else ()
            blank_fields = (
                ("X", "Y", "Z")
                if duplicate_rows or split_group or (row is None and not reviews)
                else tuple(
                    field
                    for field in (reviews[0].blank_fields if reviews else ())
                    if field in {"X", "Y", "Z"}
                )
            )
            assignment = ReinforcementAssignment(
                output_wall_id=group.output_wall_id,
                base_wall_id=base_wall_id,
                group_index=group.group_index,
                figures=group.figures,
                rebar_row=(None if duplicate_rows or split_group else row),
                resolved_cells=(
                    () if duplicate_rows or split_group else partial_cells
                ),
                blank_fields=blank_fields,
            )
            assignments.append(assignment)
            if split_group:
                source_sheet, source_row, source_cells = _wall_source(rows, reviews)
                matching_warnings.append(
                    _warning(
                        code="split_image_group",
                        scope="wall",
                        identity=group.output_wall_id,
                        source_sheet=source_sheet,
                        source_row=source_row,
                        source_cells=source_cells,
                        reason="-1/-2 应力图组需在任务完成后确认配筋",
                        blank_fields=("X", "Y", "Z"),
                    )
                )

    assignments.sort(key=lambda assignment: _wall_sort_key(assignment.output_wall_id))
    image_base_wall_ids = set(image_groups_by_base)
    workbook_wall_ids = set(schedule_by_wall)
    matched_unique_wall_ids = {
        assignment.base_wall_id
        for assignment in assignments
        if any(assignment.cell_for(direction) is not None for direction in ("X", "Y", "Z"))
    }
    workbook_only_wall_ids = sorted(
        workbook_wall_ids - image_base_wall_ids,
        key=_wall_sort_key,
    )
    for wall_id in workbook_only_wall_ids:
        row = schedule_by_wall[wall_id][0]
        matching_warnings.append(
            _warning(
                code="workbook_only_wall",
                scope="wall",
                identity=wall_id,
                source_sheet=row.source_sheet,
                source_row=row.source_row,
                source_cells=row.source_cells,
                reason="配筋表中存在墙体，但应力图中没有对应图组",
                blank_fields=("X", "Y", "Z"),
            )
        )
    return ReinforcementMatchingPlan(
        assignments=tuple(assignments),
        confirmations=(),
        warnings=tuple(_deduplicate_warnings(matching_warnings)),
        image_only_wall_ids=tuple(
            sorted(set(image_only_wall_ids), key=_wall_sort_key)
        ),
        workbook_only_wall_ids=tuple(workbook_only_wall_ids),
        image_wall_group_count=len(image_groups),
        image_unique_wall_count=len(image_base_wall_ids),
        matched_unique_wall_count=len(matched_unique_wall_ids),
    )


def _review_cells(
    warning: ReinforcementNormalizationWarning,
) -> tuple[tuple[str, ParsedRebarCell], ...]:
    cells: list[tuple[str, ParsedRebarCell]] = []
    for direction in ("X", "Y", "Z"):
        specification = warning.resolved_values.get(direction)
        if specification is None:
            continue
        cells.append(
            (direction, parse_rebar_cell(specification, direction=direction))
        )
    return tuple(cells)


def _wall_source(
    rows: list[NormalizedReinforcementRow],
    reviews: list[ReinforcementNormalizationWarning],
) -> tuple[str, int, dict[str, str]]:
    if rows:
        row = rows[0]
        return row.source_sheet, row.source_row, row.source_cells
    if reviews:
        warning = reviews[0]
        return warning.source_sheet, warning.source_row, warning.source_cells
    return "", 0, {}


def _warning(
    *,
    code: str,
    scope: str,
    identity: str | None,
    reason: str,
    blank_fields: tuple[str, ...],
    source_sheet: str = "",
    source_row: int = 0,
    source_cells: dict[str, str] | None = None,
) -> ReinforcementNormalizationWarning:
    return ReinforcementNormalizationWarning(
        code=code,
        scope=scope,
        identity=identity,
        direction=None,
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
