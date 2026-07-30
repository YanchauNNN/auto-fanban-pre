from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum
from pathlib import Path

from docx.shared import Mm
from docxtpl import DocxTemplate, InlineImage

from .archive import ArchiveLimits, validate_and_extract_archive
from .matching import (
    RecognizedFigure,
    ReinforcementAssignment,
    ReinforcementMatchingPlan,
    match_reinforcement,
)
from .models import CalculationBookParams
from .narrative import (
    build_reinforcement_narrative,
    select_calculation_reference,
)
from .ocr import StressLegendReading, recognize_stress_legend
from .reinforcement_input import (
    NormalizedReinforcementRow,
    ParsedRebarCell,
    load_reinforcement_schedule,
)
from .templates import resolve_template_path, validate_template_context


class CalculationBookStage(StrEnum):
    VALIDATE_ARCHIVE = "VALIDATE_ARCHIVE"
    OCR_REINFORCEMENT = "OCR_REINFORCEMENT"
    SELECT_REBAR = "SELECT_REBAR"
    RENDER_CALCULATION_BOOK = "RENDER_CALCULATION_BOOK"
    FINALIZE_ARTIFACT = "FINALIZE_ARTIFACT"


class ManualConfirmationRequired(ValueError):
    pass


ProgressCallback = Callable[[CalculationBookStage, int, str, dict[str, object]], None]
OcrRecognizer = Callable[[Path, str], StressLegendReading]


@dataclass(frozen=True)
class CalculationBookAssets:
    template_root: Path
    rebar_table: Path | None = None


@dataclass(frozen=True)
class CalculationBookMechanism:
    archive_limits: ArchiveLimits = ArchiveLimits()
    chapter: str = "7.1"


@dataclass(frozen=True)
class AppliedReinforcement:
    wall_id: str
    direction: str
    specification: str
    actual_area: float
    calculation_area: float
    margin_percent: float | None


@dataclass(frozen=True)
class CalculationBookResult:
    output_path: Path
    figure_count: int
    template_type: str
    selections: tuple[AppliedReinforcement, ...]


def _format_number(value: float | int) -> str:
    return f"{float(value):g}"


def _format_actual_area(value: float | int) -> str:
    return f"{round(float(value), 1):g}"


def _cell_for_direction(
    row: NormalizedReinforcementRow,
    direction: str,
) -> ParsedRebarCell:
    return {
        "X": row.x,
        "Y": row.y,
        "Z": row.z,
    }[direction]


def _apply_manual_confirmations(
    plan: ReinforcementMatchingPlan,
    *,
    confirmations: dict[str, int],
    schedule_rows: tuple[NormalizedReinforcementRow, ...],
) -> tuple[ReinforcementAssignment, ...]:
    if not plan.requires_manual_confirmation:
        return plan.assignments

    rows_by_wall: dict[str, list[NormalizedReinforcementRow]] = {}
    for row in schedule_rows:
        rows_by_wall.setdefault(row.wall_id, []).append(row)
    confirmation_by_output = {
        confirmation.output_wall_id: confirmation
        for confirmation in plan.confirmations
    }
    applied: list[ReinforcementAssignment] = []
    for assignment in plan.assignments:
        requirement = confirmation_by_output.get(assignment.output_wall_id)
        if requirement is None:
            applied.append(assignment)
            continue
        selected_row = confirmations.get(assignment.output_wall_id)
        if selected_row is None:
            raise ManualConfirmationRequired(
                f"{assignment.output_wall_id} 存在重复配筋行或 -1/-2 图片组，"
                "必须人工确认后才能创建任务"
            )
        candidates = rows_by_wall[assignment.base_wall_id]
        selected = next(
            (row for row in candidates if row.source_row == selected_row),
            None,
        )
        if selected is None:
            raise ManualConfirmationRequired(
                f"{assignment.output_wall_id} 的人工确认行 {selected_row} "
                f"不在候选行 {requirement.candidate_source_rows} 中"
            )
        applied.append(replace(assignment, rebar_row=selected))
    return tuple(applied)


def _selection(
    assignment: ReinforcementAssignment,
    direction: str,
) -> AppliedReinforcement:
    figure = assignment.figure_for(direction)
    config = _cell_for_direction(assignment.rebar_row, direction).selected
    calculation_area = select_calculation_reference(
        figure.reading,
        actual_area=config.actual_area,
    )
    margin = (
        None
        if calculation_area == 0
        else (config.actual_area - calculation_area) / calculation_area * 100
    )
    return AppliedReinforcement(
        wall_id=assignment.output_wall_id,
        direction=direction,
        specification=config.canonical_specification,
        actual_area=config.actual_area,
        calculation_area=calculation_area,
        margin_percent=margin,
    )


def _wall_rows(
    assignments: tuple[ReinforcementAssignment, ...],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for assignment in assignments:
        row = {"id": assignment.output_wall_id}
        for direction in ("X", "Y", "Z"):
            selection = _selection(assignment, direction)
            prefix = direction.lower()
            row[f"{prefix}_calc"] = _format_number(selection.calculation_area)
            row[f"{prefix}_actual"] = _format_actual_area(selection.actual_area)
            row[f"{prefix}_margin"] = (
                "-"
                if selection.margin_percent is None
                else f"{selection.margin_percent:.1f}%"
            )
        rows.append(row)
    return rows


def _actual_rebar_rows(
    assignments: tuple[ReinforcementAssignment, ...],
) -> list[dict[str, str]]:
    return [
        {
            "id": assignment.output_wall_id,
            "x_spec": assignment.rebar_row.x.selected.canonical_specification,
            "y_spec": assignment.rebar_row.y.selected.canonical_specification,
            "z_spec": assignment.rebar_row.z.selected.canonical_specification,
        }
        for assignment in assignments
    ]


def _reinforcement_figure_rows(
    *,
    document: DocxTemplate,
    assignments: tuple[ReinforcementAssignment, ...],
    chapter: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    direction_labels = {"X": "水平向", "Y": "竖向", "Z": "拉筋"}
    for assignment in assignments:
        for figure in assignment.figures:
            cell = _cell_for_direction(
                assignment.rebar_row,
                figure.source.direction,
            )
            rows.append(
                {
                    "figure_number": f"{chapter}-{len(rows) + 1}",
                    "image": InlineImage(
                        document,
                        str(figure.source.path),
                        width=Mm(140),
                    ),
                    "caption": (
                        f"{assignment.output_wall_id}-"
                        f"{direction_labels[figure.source.direction]}"
                    ),
                    "narrative": build_reinforcement_narrative(
                        wall_id=assignment.output_wall_id,
                        direction=figure.source.direction,
                        reading=figure.reading,
                        rebar_specification=cell.selected.narrative_specification,
                        actual_area=cell.selected.actual_area,
                    ),
                    "sm_value": _format_number(
                        select_calculation_reference(
                            figure.reading,
                            actual_area=cell.selected.actual_area,
                        )
                    ),
                    "rebar_spec": cell.selected.narrative_specification,
                    "rebar_area": _format_actual_area(cell.selected.actual_area),
                }
            )
    return rows


def _safe_output_name(params: CalculationBookParams) -> str:
    template_label = {
        "internal_structure": "内部结构计算书",
        "nuclear_island_plant": "核岛厂房计算书",
    }[params.template_type.value]
    raw = f"{params.project_number}{params.document_name}{template_label}"
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw).strip(" .")
    return f"{safe[:180] or '计算书'}.docx"


class CalculationBookProcessor:
    def __init__(
        self,
        *,
        assets: CalculationBookAssets,
        mechanism: CalculationBookMechanism | None = None,
        ocr_recognizer: OcrRecognizer | None = None,
    ) -> None:
        self.assets = assets
        self.mechanism = mechanism or CalculationBookMechanism()
        self.ocr_recognizer = ocr_recognizer or (
            lambda path, direction: recognize_stress_legend(
                path,
                direction=direction,
            )
        )

    def process(
        self,
        *,
        archive_path: Path,
        output_dir: Path,
        params: CalculationBookParams,
        progress: ProgressCallback | None = None,
    ) -> CalculationBookResult:
        report = progress or (lambda _stage, _percent, _message, _details: None)
        extraction_root = output_dir / "extracted"

        report(CalculationBookStage.VALIDATE_ARCHIVE, 10, "正在校验计算图片 ZIP", {})
        contents = validate_and_extract_archive(
            archive_path,
            extraction_root,
            limits=self.mechanism.archive_limits,
        )
        schedule = load_reinforcement_schedule(contents.reinforcement_workbook)

        report(
            CalculationBookStage.OCR_REINFORCEMENT,
            30,
            "正在识别底部应力图例",
            {"figure_count": len(contents.reinforcement_figures)},
        )
        recognized = [
            RecognizedFigure(
                source=figure,
                reading=self.ocr_recognizer(figure.path, figure.direction),
            )
            for figure in contents.reinforcement_figures
        ]

        report(CalculationBookStage.SELECT_REBAR, 55, "正在匹配并核验实配钢筋", {})
        plan = match_reinforcement(recognized, schedule)
        assignments = _apply_manual_confirmations(
            plan,
            confirmations=params.manual_confirmations,
            schedule_rows=schedule.rows,
        )
        selections = tuple(
            _selection(assignment, direction)
            for assignment in assignments
            for direction in ("X", "Y", "Z")
        )

        report(CalculationBookStage.RENDER_CALCULATION_BOOK, 75, "正在渲染 Word 计算书", {})
        template_path = resolve_template_path(self.assets.template_root, params.template_type)
        document = DocxTemplate(template_path)
        context = params.model_dump(mode="python")
        context.update(
            {
                "record_1_version": params.version,
                "record_1_date": date.today().isoformat(),
                "image_plant_elevation_layout": InlineImage(
                    document, str(contents.layout_image), width=Mm(150)
                ),
                "image_wall_fem_calculation_model": InlineImage(
                    document, str(contents.model_image), width=Mm(160)
                ),
                "actual_rebar_rows": _actual_rebar_rows(assignments),
                "wall_table_rows": _wall_rows(assignments),
                "reinforcement_figures": _reinforcement_figure_rows(
                    document=document,
                    assignments=assignments,
                    chapter=self.mechanism.chapter,
                ),
            }
        )
        validate_template_context(template_path, context)
        document.render(context)

        output_dir.mkdir(parents=True, exist_ok=True)
        final_path = output_dir / _safe_output_name(params)
        temporary_path = final_path.with_suffix(".docx.tmp")
        document.save(temporary_path)
        temporary_path.replace(final_path)

        report(
            CalculationBookStage.FINALIZE_ARTIFACT,
            95,
            "计算书生成完成",
            {
                "figure_count": len(recognized),
                "output_filename": final_path.name,
                "template_type": params.template_type.value,
            },
        )
        return CalculationBookResult(
            output_path=final_path,
            figure_count=len(recognized),
            template_type=params.template_type.value,
            selections=selections,
        )
