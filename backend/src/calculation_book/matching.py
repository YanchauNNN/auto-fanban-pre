from __future__ import annotations

import re
from dataclasses import dataclass

from .archive import ReinforcementFigure
from .ocr import StressLegendReading
from .reinforcement_input import (
    NormalizedReinforcementRow,
    ReinforcementSchedule,
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
    rebar_row: NormalizedReinforcementRow

    @property
    def demand_score(self) -> float:
        return max(figure.reading.smx for figure in self.figures)

    def figure_for(self, direction: str) -> RecognizedFigure:
        normalized = direction.strip().upper()
        for figure in self.figures:
            if figure.source.direction == normalized:
                return figure
        raise KeyError(f"{self.output_wall_id} 缺少 {normalized} 向图")


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

    @property
    def requires_manual_confirmation(self) -> bool:
        return bool(self.confirmations)


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
) -> ReinforcementMatchingPlan:
    image_groups = _group_figures(recognized)
    schedule_by_wall: dict[str, list[NormalizedReinforcementRow]] = {}
    for row in schedule.rows:
        schedule_by_wall.setdefault(row.wall_id, []).append(row)

    image_groups_by_base: dict[str, list[_ImageGroup]] = {}
    for group in image_groups:
        image_groups_by_base.setdefault(group.base_wall_id, []).append(group)

    assignments: list[ReinforcementAssignment] = []
    confirmations: list[ManualConfirmation] = []
    for base_wall_id, groups in image_groups_by_base.items():
        rows = schedule_by_wall.get(base_wall_id, [])
        if not rows:
            raise CalculationMatchingError(
                f"墙体配筋表中未找到图片墙号 {base_wall_id}"
            )
        duplicate_rows = len(rows) > 1
        for group, row in _pair_groups_and_rows(groups, rows):
            assignment = ReinforcementAssignment(
                output_wall_id=group.output_wall_id,
                base_wall_id=base_wall_id,
                group_index=group.group_index,
                figures=group.figures,
                rebar_row=row,
            )
            assignments.append(assignment)
            reasons: list[str] = []
            if duplicate_rows:
                reasons.append("duplicate_reinforcement_rows")
            if group.group_index is not None:
                reasons.append("split_image_group")
            if reasons:
                confirmations.append(
                    ManualConfirmation(
                        output_wall_id=group.output_wall_id,
                        base_wall_id=base_wall_id,
                        selected_source_row=row.source_row,
                        candidate_source_rows=tuple(
                            candidate.source_row for candidate in rows
                        ),
                        reasons=tuple(reasons),
                    )
                )

    assignments.sort(key=lambda assignment: _wall_sort_key(assignment.output_wall_id))
    confirmations.sort(
        key=lambda confirmation: _wall_sort_key(confirmation.output_wall_id)
    )
    return ReinforcementMatchingPlan(
        assignments=tuple(assignments),
        confirmations=tuple(confirmations),
    )
