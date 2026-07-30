from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .archive import ArchiveLimits, validate_and_extract_archive
from .matching import RecognizedFigure, match_reinforcement
from .ocr import StressLegendReading, recognize_stress_legend
from .reinforcement_input import (
    NormalizedReinforcementRow,
    ParsedRebarCell,
    load_reinforcement_schedule,
    load_slab_reinforcement_schedule,
)
from .slab import RecognizedSlabFigure, match_slab_reinforcement

OcrRecognizer = Callable[[Path, str], StressLegendReading]


def _cell_for_direction(
    row: NormalizedReinforcementRow,
    direction: str,
) -> ParsedRebarCell:
    return {"X": row.x, "Y": row.y, "Z": row.z}[direction]


def _candidate_payload(row: NormalizedReinforcementRow) -> dict[str, Any]:
    return {
        "source_row": row.source_row,
        "source_sheet": row.source_sheet,
        "directions": {
            direction: {
                "source_cell": row.source_cells[direction],
                "original_text": _cell_for_direction(
                    row,
                    direction,
                ).original_text,
                "canonical_specification": _cell_for_direction(
                    row,
                    direction,
                ).selected.canonical_specification,
                "narrative_specification": _cell_for_direction(
                    row,
                    direction,
                ).selected.narrative_specification,
                "actual_area": round(
                    _cell_for_direction(
                        row,
                        direction,
                    ).selected.actual_area,
                    1,
                ),
            }
            for direction in ("X", "Y", "Z")
        },
    }


def run_calculation_book_preflight(
    *,
    archive_path: Path,
    extraction_root: Path,
    include_slab_stress: bool = False,
    ocr_recognizer: OcrRecognizer | None = None,
    archive_limits: ArchiveLimits | None = None,
) -> dict[str, Any]:
    contents = validate_and_extract_archive(
        archive_path,
        extraction_root,
        limits=archive_limits,
    )
    schedule = load_reinforcement_schedule(contents.reinforcement_workbook)
    recognize = ocr_recognizer or (
        lambda path, direction: recognize_stress_legend(
            path,
            direction=direction,
        )
    )
    recognized = [
        RecognizedFigure(
            source=figure,
            reading=recognize(figure.path, figure.direction),
        )
        for figure in contents.reinforcement_figures
    ]
    plan = match_reinforcement(recognized, schedule)
    slab_plan = None
    recognized_slabs: list[RecognizedSlabFigure] = []
    if include_slab_stress:
        slab_schedule = load_slab_reinforcement_schedule(
            contents.reinforcement_workbook,
            required=True,
        )
        assert slab_schedule is not None
        recognized_slabs = [
            RecognizedSlabFigure(
                source=figure,
                reading=recognize(figure.path, figure.direction),
            )
            for figure in contents.slab_figures
        ]
        slab_plan = match_slab_reinforcement(
            recognized_slabs,
            slab_schedule,
        )

    rows_by_wall: dict[str, list[NormalizedReinforcementRow]] = {}
    for row in schedule.rows:
        rows_by_wall.setdefault(row.wall_id, []).append(row)

    confirmations = []
    for requirement in plan.confirmations:
        confirmations.append(
            {
                "wall_id": requirement.output_wall_id,
                "base_wall_id": requirement.base_wall_id,
                "reasons": list(requirement.reasons),
                "suggested_source_row": requirement.selected_source_row,
                "candidates": [
                    _candidate_payload(row)
                    for row in rows_by_wall[requirement.base_wall_id]
                ],
            }
        )

    walls = []
    for assignment in plan.assignments:
        directions: dict[str, Any] = {}
        for direction in ("X", "Y", "Z"):
            figure = assignment.figure_for(direction)
            cell = _cell_for_direction(assignment.rebar_row, direction)
            directions[direction] = {
                "image_filename": figure.source.path.name,
                "smn": figure.reading.smn,
                "smx": figure.reading.smx,
                "legend_values": list(figure.reading.legend_values),
                "is_zero_result": figure.reading.is_zero_result,
                "source_cell": assignment.rebar_row.source_cells[direction],
                "original_text": cell.original_text,
                "canonical_specification": cell.selected.canonical_specification,
                "narrative_specification": cell.selected.narrative_specification,
                "actual_area": round(cell.selected.actual_area, 1),
            }
        walls.append(
            {
                "wall_id": assignment.output_wall_id,
                "base_wall_id": assignment.base_wall_id,
                "group_index": assignment.group_index,
                "suggested_source_row": assignment.rebar_row.source_row,
                "directions": directions,
            }
        )

    ignored = [path.name for path in contents.ignored_root_images]
    warnings = []
    if ignored:
        warnings.append(
            {"code": "ignored_root_images", "filenames": ignored}
        )
    if contents.slab_figures and not include_slab_stress:
        warnings.append(
            {
                "code": "slab_ignored_by_choice",
                "filenames": [
                    figure.path.name for figure in contents.slab_figures
                ],
            }
        )

    slabs = []
    if slab_plan is not None:
        for slab_assignment in slab_plan.assignments:
            cell = slab_assignment.rebar_cell
            reading = slab_assignment.figure.reading
            slabs.append(
                {
                    "elevation": slab_assignment.elevation,
                    "key": slab_assignment.key,
                    "position": slab_assignment.position,
                    "direction": slab_assignment.direction,
                    "image_filename": slab_assignment.figure.source.path.name,
                    "smn": reading.smn,
                    "smx": reading.smx,
                    "legend_values": list(reading.legend_values),
                    "is_zero_result": reading.is_zero_result,
                    "source_row": slab_assignment.source_row,
                    "source_cell": slab_assignment.source_cell,
                    "original_text": cell.original_text,
                    "canonical_specification": (
                        cell.selected.canonical_specification
                    ),
                    "narrative_specification": (
                        cell.selected.narrative_specification
                    ),
                    "actual_area": round(cell.selected.actual_area, 1),
                }
            )
    return {
        "figure_count": len(recognized),
        "zero_figure_count": sum(
            figure.reading.is_zero_result for figure in recognized
        ),
        "wall_count": len(plan.assignments),
        "reinforcement_workbook": contents.reinforcement_workbook.name,
        "requires_manual_confirmation": plan.requires_manual_confirmation,
        "confirmations": confirmations,
        "walls": walls,
        "slab_figure_count": len(recognized_slabs),
        "slab_elevation_count": (
            slab_plan.elevation_count if slab_plan is not None else 0
        ),
        "slabs": slabs,
        "warnings": warnings,
    }
