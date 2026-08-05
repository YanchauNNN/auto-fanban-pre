from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .archive import (
    ArchiveLimits,
    CalculationArchiveContents,
    InvalidCalculationArchive,
    validate_and_extract_archive,
)
from .matching import RecognizedFigure, match_reinforcement
from .models import ReinforcementSource
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
        "reinforcement_source": ReinforcementSource.PROVIDED.value,
        "requires_ai_normalization": True,
        "requires_ai_recommendation": False,
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
        "slab_zero_figure_count": 0,
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


def _ai_reading_payload(
    *,
    path: Path,
    direction: str,
    recognize: OcrRecognizer,
    scope: str,
    identity: str,
    review_items: list[dict[str, Any]],
) -> tuple[dict[str, Any], bool, bool]:
    try:
        reading = recognize(path, direction)
    except Exception as exc:
        reason = f"OCR 识别失败：{exc}"
        review_items.append(
            {
                "scope": scope,
                "identity": identity,
                "direction": direction,
                "image_filename": path.name,
                "reason": reason,
            }
        )
        return (
            {
                "image_filename": path.name,
                "smn": None,
                "smx": None,
                "legend_values": [],
                "is_zero_result": False,
                "ocr_status": "review_required",
                "ocr_error": reason,
            },
            False,
            direction == "Z",
        )
    return (
        {
            "image_filename": path.name,
            "smn": reading.smn,
            "smx": reading.smx,
            "legend_values": list(reading.legend_values),
            "is_zero_result": reading.is_zero_result,
            "ocr_status": "recognized",
            "ocr_error": None,
        },
        reading.is_zero_result,
        direction == "Z" and reading.smx == 0,
    )


def _ai_suggested_preflight_payload(
    *,
    contents: CalculationArchiveContents,
    include_slab_stress: bool,
    recognize: OcrRecognizer,
) -> dict[str, Any]:
    review_items: list[dict[str, Any]] = []
    zero_figure_count = 0
    slab_zero_figure_count = 0
    z_zero_or_missing_smx_count = 0
    grouped_figures: dict[str, list[Any]] = {}
    for figure in contents.reinforcement_figures:
        grouped_figures.setdefault(figure.wall_id, []).append(figure)

    walls: list[dict[str, Any]] = []
    for wall_id, figures in grouped_figures.items():
        directions: dict[str, Any] = {}
        for figure in figures:
            if figure.group_index is not None:
                review_items.append(
                    {
                        "code": "split_image_group",
                        "scope": "wall",
                        "identity": wall_id,
                        "direction": figure.direction,
                        "image_filename": figure.path.name,
                        "reason": "-1/-2 应力图组需在任务完成后确认配筋",
                    }
                )
            reading_payload, is_zero, z_zero_or_missing = _ai_reading_payload(
                path=figure.path,
                direction=figure.direction,
                recognize=recognize,
                scope="wall",
                identity=wall_id,
                review_items=review_items,
            )
            zero_figure_count += int(is_zero)
            z_zero_or_missing_smx_count += int(z_zero_or_missing)
            directions[figure.direction] = {
                **reading_payload,
                "source_cell": "",
                "original_text": "",
                "canonical_specification": "",
                "narrative_specification": "",
                "actual_area": "",
            }
        first_figure = figures[0]
        walls.append(
            {
                "wall_id": wall_id,
                "base_wall_id": first_figure.base_wall_id,
                "group_index": first_figure.group_index,
                "suggested_source_row": None,
                "directions": directions,
            }
        )

    selected_slab_figures = (
        contents.slab_figures if include_slab_stress else ()
    )
    slabs: list[dict[str, Any]] = []
    for figure in selected_slab_figures:
        key = (
            "z"
            if figure.position is None
            else f"{figure.position.lower()}_{figure.direction.lower()}"
        )
        reading_payload, is_zero, z_zero_or_missing = _ai_reading_payload(
            path=figure.path,
            direction=figure.direction,
            recognize=recognize,
            scope="slab",
            identity=f"{figure.elevation}:{key}",
            review_items=review_items,
        )
        slab_zero_figure_count += int(is_zero)
        z_zero_or_missing_smx_count += int(z_zero_or_missing)
        slabs.append(
            {
                "elevation": figure.elevation,
                "key": key,
                "position": figure.position,
                "direction": figure.direction,
                **reading_payload,
                "source_row": None,
                "source_cell": "",
                "original_text": "",
                "canonical_specification": "",
                "narrative_specification": "",
                "actual_area": "",
            }
        )

    ignored = [path.name for path in contents.ignored_root_images]
    warnings: list[dict[str, Any]] = []
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
    warnings.extend(
        {"code": "ocr_review_required", **item}
        for item in review_items
    )
    slab_group_count = len(
        {figure.elevation for figure in selected_slab_figures}
    )
    return {
        "reinforcement_source": ReinforcementSource.AI_SUGGESTED.value,
        "requires_ai_normalization": False,
        "requires_ai_recommendation": True,
        "ai_confirmation_message": None,
        "format_inspection": None,
        "figure_count": len(contents.reinforcement_figures),
        "wall_direction_figure_count": len(contents.reinforcement_figures),
        "zero_figure_count": zero_figure_count,
        "z_zero_or_missing_smx_count": z_zero_or_missing_smx_count,
        "wall_count": len(walls),
        "reinforcement_workbook": None,
        "reinforcement_source_row_count": 0,
        "reinforcement_normalized_row_count": 0,
        "reinforcement_issue_row_count": 0,
        "reinforcement_unique_wall_count": 0,
        "normalization_triggered": False,
        "normalization_skill_id": None,
        "normalization_issues": [],
        "image_wall_group_count": len(walls),
        "image_unique_wall_count": len(
            {figure.base_wall_id for figure in contents.reinforcement_figures}
        ),
        "matched_unique_wall_count": 0,
        "image_only_wall_ids": [],
        "workbook_only_wall_ids": [],
        "requires_wall_count_confirmation": False,
        "requires_manual_confirmation": False,
        "requires_ocr_review": any(
            item.get("code", "ocr_review_required")
            == "ocr_review_required"
            for item in review_items
        ),
        "confirmations": [],
        "walls": walls,
        "slab_figure_count": len(selected_slab_figures),
        "slab_zero_figure_count": slab_zero_figure_count,
        "slab_elevation_count": slab_group_count,
        "slab_actual_group_count": slab_group_count,
        "slabs": slabs,
        "ignored_root_images": ignored,
        "review_items": review_items,
        "warnings": warnings,
    }


def run_calculation_book_preflight(
    *,
    archive_path: Path,
    extraction_root: Path,
    reinforcement_source: ReinforcementSource | str = ReinforcementSource.PROVIDED,
    include_slab_stress: bool = False,
    ocr_recognizer: OcrRecognizer | None = None,
    archive_limits: ArchiveLimits | None = None,
) -> dict[str, Any]:
    active_reinforcement_source = ReinforcementSource(reinforcement_source)
    contents = validate_and_extract_archive(
        archive_path,
        extraction_root,
        reinforcement_source=active_reinforcement_source,
        limits=archive_limits,
    )
    if include_slab_stress and not contents.slab_figures:
        raise InvalidCalculationArchive(
            "已启用楼板应力，但压缩包根目录没有可识别的楼板应力图片"
        )
    recognize = ocr_recognizer or (
        lambda path, direction: recognize_stress_legend(
            path,
            direction=direction,
        )
    )
    if active_reinforcement_source is ReinforcementSource.AI_SUGGESTED:
        return _ai_suggested_preflight_payload(
            contents=contents,
            include_slab_stress=include_slab_stress,
            recognize=recognize,
        )
    assert contents.reinforcement_workbook is not None
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
            cell = assignment.cell_for(direction)
            source_cell = (
                assignment.rebar_row.source_cells.get(direction, "")
                if assignment.rebar_row is not None
                else ""
            )
            directions[direction] = {
                "image_filename": figure.source.path.name,
                "smn": figure.reading.smn,
                "smx": figure.reading.smx,
                "legend_values": list(figure.reading.legend_values),
                "is_zero_result": figure.reading.is_zero_result,
                "source_cell": source_cell,
                "original_text": cell.original_text if cell is not None else "",
                "canonical_specification": (
                    cell.selected.canonical_specification
                    if cell is not None
                    else ""
                ),
                "narrative_specification": (
                    cell.selected.narrative_specification
                    if cell is not None
                    else ""
                ),
                "actual_area": (
                    round(cell.selected.actual_area, 1)
                    if cell is not None
                    else ""
                ),
            }
        walls.append(
            {
                "wall_id": assignment.output_wall_id,
                "base_wall_id": assignment.base_wall_id,
                "group_index": assignment.group_index,
                "suggested_source_row": (
                    assignment.rebar_row.source_row
                    if assignment.rebar_row is not None
                    else None
                ),
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
    warnings.extend(
        {
            "code": warning.code,
            "scope": warning.scope,
            "identity": warning.identity,
            "direction": warning.direction,
            "source_sheet": warning.source_sheet,
            "source_row": warning.source_row,
            "source_cells": warning.source_cells,
            "reason": warning.reason,
            "blank_fields": list(warning.blank_fields),
        }
        for warning in plan.warnings
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
                    "original_text": cell.original_text if cell is not None else "",
                    "canonical_specification": (
                        cell.selected.canonical_specification
                        if cell is not None
                        else ""
                    ),
                    "narrative_specification": (
                        cell.selected.narrative_specification
                        if cell is not None
                        else ""
                    ),
                    "actual_area": (
                        round(cell.selected.actual_area, 1)
                        if cell is not None
                        else ""
                    ),
                }
            )
    return {
        "reinforcement_source": ReinforcementSource.PROVIDED.value,
        "requires_ai_normalization": False,
        "requires_ai_recommendation": False,
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
        "requires_manual_confirmation": False,
        "confirmations": confirmations,
        "walls": walls,
        "slab_figure_count": len(recognized_slabs),
        "slab_zero_figure_count": sum(
            figure.reading.is_zero_result for figure in recognized_slabs
        ),
        "slab_elevation_count": (
            slab_plan.elevation_count if slab_plan is not None else 0
        ),
        "slabs": slabs,
        "warnings": warnings,
    }
