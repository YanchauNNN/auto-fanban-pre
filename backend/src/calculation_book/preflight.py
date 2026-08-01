from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .archive import (
    ArchiveLimits,
    CalculationArchiveContents,
    validate_and_extract_archive,
)
from .matching import RecognizedFigure, match_reinforcement
from .ocr import StressLegendReading, recognize_stress_legend
from .reinforcement_input import (
    InvalidReinforcementWorkbook,
    NormalizedReinforcementRow,
    ParsedRebarCell,
    load_reinforcement_schedule,
    load_slab_reinforcement_schedule,
)
from .reinforcement_workbook import (
    WorkbookFormatInspection,
    inspect_reinforcement_workbook,
)
from .slab import RecognizedSlabFigure, match_slab_reinforcement

OcrRecognizer = Callable[[Path, str], StressLegendReading]
AI_CONFIRMATION_MESSAGE = "您上传的墙体配筋表非标准格式，程序将启动人工智能。"


def _format_inspection_payload(
    inspection: WorkbookFormatInspection,
) -> dict[str, Any]:
    return {
        "wall_sheet": inspection.wall_sheet,
        "slab_sheet": inspection.slab_sheet,
        "reasons": [
            {
                "scope": reason.scope,
                "code": reason.code,
                "sheet": reason.sheet,
                "message": reason.message,
            }
            for reason in inspection.reasons
        ],
    }


def _nonstandard_preflight_payload(
    *,
    contents: CalculationArchiveContents,
    inspection: WorkbookFormatInspection,
    include_slab_stress: bool,
) -> dict[str, Any]:
    wall_groups = {
        (figure.base_wall_id, figure.group_index)
        for figure in contents.reinforcement_figures
    }
    wall_ids = {
        figure.base_wall_id
        for figure in contents.reinforcement_figures
    }
    selected_slab_figures = (
        contents.slab_figures if include_slab_stress else ()
    )
    warnings: list[dict[str, Any]] = []
    ignored = [path.name for path in contents.ignored_root_images]
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
    return {
        "requires_ai_normalization": True,
        "ai_reinforcement_expected_source_row_count": (
            inspection.ai_reinforcement_expected_source_row_count
        ),
        "ai_confirmation_message": AI_CONFIRMATION_MESSAGE,
        "format_inspection": _format_inspection_payload(inspection),
        "figure_count": len(contents.reinforcement_figures),
        "zero_figure_count": 0,
        "wall_count": 0,
        "reinforcement_workbook": contents.reinforcement_workbook.name,
        "reinforcement_source_row_count": 0,
        "reinforcement_normalized_row_count": 0,
        "reinforcement_issue_row_count": 0,
        "reinforcement_unique_wall_count": 0,
        "normalization_triggered": False,
        "normalization_skill_id": None,
        "normalization_issues": [],
        "image_wall_group_count": len(wall_groups),
        "image_unique_wall_count": len(wall_ids),
        "matched_unique_wall_count": 0,
        "image_only_wall_ids": [],
        "workbook_only_wall_ids": [],
        "requires_wall_count_confirmation": False,
        "requires_manual_confirmation": False,
        "confirmations": [],
        "walls": [],
        "slab_figure_count": len(selected_slab_figures),
        "slab_elevation_count": len(
            {figure.elevation for figure in selected_slab_figures}
        ),
        "slabs": [],
        "warnings": warnings,
    }


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
    inspection = inspect_reinforcement_workbook(
        contents.reinforcement_workbook,
        include_slab=include_slab_stress,
    )
    if inspection.requires_ai_normalization:
        expected_source_row_count = (
            inspection.ai_reinforcement_expected_source_row_count
        )
        if (
            isinstance(expected_source_row_count, bool)
            or not isinstance(expected_source_row_count, int)
            or expected_source_row_count <= 0
        ):
            raise InvalidReinforcementWorkbook(
                "无法可靠统计非标准配筋表数据行"
            )
        return _nonstandard_preflight_payload(
            contents=contents,
            inspection=inspection,
            include_slab_stress=include_slab_stress,
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
        "requires_ai_normalization": False,
        "ai_confirmation_message": None,
        "format_inspection": _format_inspection_payload(inspection),
        "figure_count": len(recognized),
        "zero_figure_count": sum(
            figure.reading.is_zero_result for figure in recognized
        ),
        "wall_count": len(plan.assignments),
        "reinforcement_workbook": contents.reinforcement_workbook.name,
        "reinforcement_source_row_count": schedule.source_row_count,
        "reinforcement_normalized_row_count": schedule.normalized_row_count,
        "reinforcement_issue_row_count": schedule.issue_row_count,
        "reinforcement_unique_wall_count": schedule.unique_wall_count,
        "normalization_triggered": schedule.normalization_triggered,
        "normalization_skill_id": (
            "reinforcement_table_normalizer"
            if schedule.normalization_triggered
            else None
        ),
        "normalization_issues": [
            {
                "source_sheet": issue.source_sheet,
                "source_row": issue.source_row,
                "source_cells": issue.source_cells,
                "original_values": issue.original_values,
                "original_wall_text": issue.original_wall_text,
                "wall_id": issue.wall_id,
                "error": issue.error,
            }
            for issue in schedule.issues
        ],
        "image_wall_group_count": plan.image_wall_group_count,
        "image_unique_wall_count": plan.image_unique_wall_count,
        "matched_unique_wall_count": plan.matched_unique_wall_count,
        "image_only_wall_ids": list(plan.image_only_wall_ids),
        "workbook_only_wall_ids": list(plan.workbook_only_wall_ids),
        "requires_wall_count_confirmation": (
            plan.requires_wall_count_confirmation
        ),
        "requires_manual_confirmation": (
            plan.requires_manual_confirmation
            or schedule.requires_manual_confirmation
        ),
        "confirmations": confirmations,
        "walls": walls,
        "slab_figure_count": len(recognized_slabs),
        "slab_elevation_count": (
            slab_plan.elevation_count if slab_plan is not None else 0
        ),
        "slabs": slabs,
        "warnings": warnings,
    }
