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
)

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
    warnings = (
        [{"code": "ignored_root_images", "filenames": ignored}]
        if ignored
        else []
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
        "warnings": warnings,
    }
