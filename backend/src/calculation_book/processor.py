from __future__ import annotations

import re
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path

from docx import Document as WordDocument
from docx.shared import Mm
from docx.text.paragraph import Paragraph
from docx.text.run import Run
from docxtpl import DocxTemplate, InlineImage

from ..config import load_mechanism_spec
from ..config.mechanism_spec import CalculationBookAiSuggestionMechanismConfig
from .ai_reinforcement_schema import (
    ReinforcementNormalizationWarning,
    ValidatedAiReinforcement,
)
from .archive import (
    ArchiveExtractorSettings,
    ArchiveLimits,
    validate_and_extract_archive,
)
from .matching import (
    RecognizedFigure,
    ReinforcementAssignment,
    ReinforcementMatchingPlan,
    build_ai_reinforcement_plan,
    match_reinforcement,
    wall_rebar_item_id,
)
from .models import CalculationBookParams, ReinforcementSource
from .narrative import (
    build_reinforcement_narrative,
    build_slab_reinforcement_narrative,
    select_calculation_reference,
)
from .ocr import OcrRecognitionError, StressLegendReading, recognize_stress_legend
from .rebar_candidates import generate_rebar_candidates
from .rebar_recommender import (
    RebarSuggestionInput,
    RebarSuggestionResult,
    SelectedRebarSuggestion,
)
from .reinforcement_input import (
    NormalizedReinforcementRow,
    ParsedRebarCell,
    SlabReinforcementSchedule,
    load_reinforcement_schedule,
    load_slab_reinforcement_schedule,
)
from .slab import (
    RecognizedSlabFigure,
    SlabMatchingPlan,
    build_ai_slab_plan,
    match_slab_reinforcement,
    slab_rebar_item_id,
)
from .templates import resolve_template_path, validate_template_context


class CalculationBookStage(StrEnum):
    VALIDATE_ARCHIVE = "VALIDATE_ARCHIVE"
    AI_REINFORCEMENT_NORMALIZATION = "AI_REINFORCEMENT_NORMALIZATION"
    OCR_REINFORCEMENT = "OCR_REINFORCEMENT"
    AI_REBAR_SUGGESTION = "AI_REBAR_SUGGESTION"
    SELECT_REBAR = "SELECT_REBAR"
    RENDER_CALCULATION_BOOK = "RENDER_CALCULATION_BOOK"
    FINALIZE_ARTIFACT = "FINALIZE_ARTIFACT"


class ManualConfirmationRequired(ValueError):
    pass


ProgressCallback = Callable[[CalculationBookStage, int, str, dict[str, object]], None]
OcrRecognizer = Callable[[Path, str], StressLegendReading]
ReinforcementNormalizationCallback = Callable[
    [Path, bool],
    ValidatedAiReinforcement,
]
RebarSuggestionCallback = Callable[
    [tuple[RebarSuggestionInput, ...]],
    RebarSuggestionResult,
]
CalculationBookAudit = Callable[[str, dict[str, object]], None]


@dataclass(frozen=True)
class CalculationBookAssets:
    template_root: Path
    rebar_table: Path | None = None


@dataclass(frozen=True)
class CalculationBookMechanism:
    archive_limits: ArchiveLimits = ArchiveLimits()
    chapter: str = "7.1"
    ai_suggestion: CalculationBookAiSuggestionMechanismConfig = field(
        default_factory=lambda: load_mechanism_spec().calculation_book.ai_suggestion
    )


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
    normalization_warnings: tuple[ReinforcementNormalizationWarning, ...] = ()
    ai_rebar_suggestion: RebarSuggestionResult | None = None
    ai_suggested_direction_count: int = 0
    ai_blank_direction_count: int = 0

    @property
    def warnings(self) -> tuple[ReinforcementNormalizationWarning, ...]:
        return self.normalization_warnings


def _format_number(value: float | int) -> str:
    return f"{float(value):g}"


def _format_actual_area(value: float | int) -> str:
    return f"{round(float(value), 1):g}"


def _apply_manual_confirmations(
    plan: ReinforcementMatchingPlan,
    *,
    confirmations: dict[str, int],
    schedule_rows: tuple[NormalizedReinforcementRow, ...],
) -> tuple[ReinforcementAssignment, ...]:
    # Kept as a compatibility seam for persisted legacy request payloads.
    # Ambiguous rows are represented as blank assignments by matching itself;
    # user-provided row numbers must not make generation block or guess values.
    del confirmations, schedule_rows
    return plan.assignments


def _selection(
    assignment: ReinforcementAssignment,
    direction: str,
) -> AppliedReinforcement | None:
    figure = assignment.figure_for(direction)
    cell = assignment.cell_for(direction)
    if cell is None:
        return None
    if figure.reading is None:
        raise ValueError(
            f"{assignment.output_wall_id}-{direction} 没有有效 OCR 结果却存在配筋值"
        )
    config = cell.selected
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
            if selection is None:
                row[f"{prefix}_calc"] = ""
                row[f"{prefix}_actual"] = ""
                row[f"{prefix}_margin"] = ""
                continue
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
    rows: list[dict[str, str]] = []
    for assignment in assignments:
        row = {"id": assignment.output_wall_id}
        for direction in ("X", "Y", "Z"):
            cell = assignment.cell_for(direction)
            row[f"{direction.lower()}_spec"] = (
                cell.selected.canonical_specification if cell is not None else ""
            )
        rows.append(row)
    return rows


def _reinforcement_figure_rows(
    *,
    document: DocxTemplate,
    assignments: tuple[ReinforcementAssignment, ...],
    chapter: str,
    start_index: int = 1,
    is_ai_suggested: bool = False,
    audit: CalculationBookAudit | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    direction_labels = {"X": "水平向", "Y": "竖向", "Z": "拉筋"}
    for assignment in assignments:
        for figure in assignment.figures:
            cell = assignment.cell_for(figure.source.direction)
            narrative = ""
            sm_value = ""
            rebar_spec = ""
            rebar_area = ""
            if cell is not None:
                if figure.reading is None:
                    raise ValueError(
                        f"{assignment.output_wall_id}-{figure.source.direction} "
                        "没有有效 OCR 结果却存在配筋值"
                    )
                narrative = build_reinforcement_narrative(
                    wall_id=assignment.output_wall_id,
                    direction=figure.source.direction,
                    reading=figure.reading,
                    rebar_specification=cell.selected.narrative_specification,
                    actual_area=cell.selected.actual_area,
                    is_ai_suggested=is_ai_suggested,
                )
                sm_value = _format_number(
                    select_calculation_reference(
                        figure.reading,
                        actual_area=cell.selected.actual_area,
                    )
                )
                rebar_spec = cell.selected.narrative_specification
                rebar_area = _format_actual_area(cell.selected.actual_area)
            _audit(
                audit,
                "word_entry_written",
                member_kind="wall",
                member_id=assignment.output_wall_id,
                direction=figure.source.direction,
                spec=(cell.selected.canonical_specification if cell else None),
                actual_area=(cell.selected.actual_area if cell else None),
                smx=(figure.reading.smx if figure.reading else None),
                image_name=figure.source.path.name,
            )
            rows.append(
                {
                    "figure_number": f"{chapter}-{start_index + len(rows)}",
                    "image": InlineImage(
                        document,
                        str(figure.source.path),
                        width=Mm(140),
                    ),
                    "caption": (
                        f"{assignment.output_wall_id}-"
                        f"{direction_labels[figure.source.direction]}"
                    ),
                    "narrative": narrative,
                    "sm_value": sm_value,
                    "rebar_spec": rebar_spec,
                    "rebar_area": rebar_area,
                }
            )
    return rows


_SLAB_LAYER_LABELS = {
    "top_x": "顶层水平",
    "middle_x": "中层水平",
    "bottom_x": "底层水平",
    "top_y": "顶层竖向",
    "middle_y": "中层竖向",
    "bottom_y": "底层竖向",
    "z": "纵向拉筋",
}


def _slab_figure_rows(
    *,
    document: DocxTemplate,
    plan: SlabMatchingPlan,
    chapter: str,
    is_ai_suggested: bool = False,
    audit: CalculationBookAudit | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for assignment in plan.assignments:
        label = _SLAB_LAYER_LABELS[assignment.key]
        cell = assignment.rebar_cell
        narrative = ""
        if cell is not None:
            if assignment.figure.reading is None:
                raise ValueError(
                    f"楼板 {assignment.elevation}-{assignment.key} "
                    "没有有效 OCR 结果却存在配筋值"
                )
            narrative = build_slab_reinforcement_narrative(
                elevation=assignment.elevation,
                layer_label=label,
                reading=assignment.figure.reading,
                rebar_specification=(cell.selected.narrative_specification),
                actual_area=cell.selected.actual_area,
                is_z=assignment.direction == "Z",
                is_ai_suggested=is_ai_suggested,
            )
        _audit(
            audit,
            "word_entry_written",
            member_kind="slab",
            member_id=f"{assignment.elevation}:{assignment.key}",
            direction=assignment.direction,
            spec=(cell.selected.canonical_specification if cell else None),
            actual_area=(cell.selected.actual_area if cell else None),
            smx=(assignment.figure.reading.smx if assignment.figure.reading else None),
            image_name=assignment.figure.source.path.name,
        )
        rows.append(
            {
                "figure_number": f"{chapter}-{len(rows) + 1}",
                "image": InlineImage(
                    document,
                    str(assignment.figure.source.path),
                    width=Mm(140),
                ),
                "caption": f"{assignment.elevation}m 楼板{label}",
                "narrative": narrative,
            }
        )
    return rows


def _unmatched_figure_rows(
    *,
    document: DocxTemplate,
    image_paths: tuple[Path, ...],
    chapter: str,
    start_index: int,
    audit: CalculationBookAudit | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for image_path in image_paths:
        _audit(
            audit,
            "word_entry_written",
            member_kind="unknown",
            member_id=image_path.stem,
            direction="UNKNOWN",
            spec=None,
            actual_area=None,
            smx=None,
            image_name=image_path.name,
        )
        rows.append(
            {
                "figure_number": f"{chapter}-{start_index + len(rows)}",
                "image": InlineImage(document, str(image_path), width=Mm(140)),
                "caption": f"无法识别的应力图：{image_path.stem}",
                "narrative": "",
                "sm_value": "",
                "rebar_spec": "",
                "rebar_area": "",
            }
        )
    return rows


def _audit(
    sink: CalculationBookAudit | None,
    event: str,
    **payload: object,
) -> None:
    if sink is not None:
        sink(event, payload)


_MM2_PATTERN = re.compile(r"mm(?:2|²)")


def _superscript_mm2(path: Path) -> None:
    document = WordDocument(str(path))
    paragraph_elements = list(document.element.body.iter())
    for section in document.sections:
        paragraph_elements.extend(section.header._element.iter())
        paragraph_elements.extend(section.footer._element.iter())

    seen: set[int] = set()
    for element in paragraph_elements:
        if not element.tag.endswith("}p") or id(element) in seen:
            continue
        seen.add(id(element))
        paragraph = Paragraph(element, element.getparent())
        for run in list(paragraph.runs):
            if _MM2_PATTERN.search(run.text) is None:
                continue
            pieces = _MM2_PATTERN.split(run.text)
            matches = list(_MM2_PATTERN.finditer(run.text))
            replacement: list[tuple[str, bool]] = []
            for index, piece in enumerate(pieces):
                if piece:
                    replacement.append((piece, False))
                if index < len(matches):
                    replacement.extend((("mm", False), ("2", True)))

            parent = run._r.getparent()
            insertion_index = parent.index(run._r)
            for text, superscript in replacement:
                clone = deepcopy(run._r)
                clone_run = Run(clone, paragraph)
                clone_run.text = text
                if superscript:
                    clone_run.font.superscript = True
                parent.insert(insertion_index, clone)
                insertion_index += 1
            parent.remove(run._r)
    document.save(str(path))


def _safe_output_name(params: CalculationBookParams) -> str:
    template_label = {
        "internal_structure": "内部结构计算书",
        "nuclear_island_plant": "核岛厂房计算书",
    }[params.template_type.value]
    raw = f"{params.project_number}{params.document_name}{template_label}"
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw).strip(" .")
    return f"{safe[:180] or '计算书'}.docx"


def _recognize_ai_wall_figures(
    *,
    figures,
    recognizer: OcrRecognizer,
    archive_root: Path,
    audit: CalculationBookAudit | None,
) -> tuple[list[RecognizedFigure], dict[str, tuple[str, str]]]:
    recognized: list[RecognizedFigure] = []
    failures: dict[str, tuple[str, str]] = {}
    for figure in figures:
        item_id = wall_rebar_item_id(figure)
        _audit(
            audit,
            "image_grouped",
            image_name=figure.path.name,
            relative_path=figure.path.relative_to(archive_root).as_posix(),
            member_kind="wall",
            member_id=figure.wall_id,
            direction=figure.direction,
            group=figure.group_index,
        )
        if figure.group_index is not None:
            recognized.append(RecognizedFigure(source=figure, reading=None))
            continue
        try:
            reading = recognizer(figure.path, figure.direction)
        except OcrRecognitionError as exc:
            failures[item_id] = ("OCR_RECOGNITION_FAILED", str(exc))
            recognized.append(RecognizedFigure(source=figure, reading=None))
            _audit(
                audit,
                "ocr_failed",
                image_name=figure.path.name,
                member_kind="wall",
                member_id=figure.wall_id,
                direction=figure.direction,
                error_code="OCR_RECOGNITION_FAILED",
            )
            continue
        recognized.append(RecognizedFigure(source=figure, reading=reading))
        _audit(
            audit,
            "ocr_completed",
            image_name=figure.path.name,
            member_kind="wall",
            member_id=figure.wall_id,
            direction=figure.direction,
            smx=reading.smx,
            legend_values=list(reading.legend_values),
            zero_smx=reading.is_zero_result,
        )
    return recognized, failures


def _recognize_ai_slab_figures(
    *,
    figures,
    recognizer: OcrRecognizer,
    archive_root: Path,
    audit: CalculationBookAudit | None,
) -> tuple[list[RecognizedSlabFigure], dict[str, tuple[str, str]]]:
    recognized: list[RecognizedSlabFigure] = []
    failures: dict[str, tuple[str, str]] = {}
    for figure in figures:
        item_id = slab_rebar_item_id(figure)
        _audit(
            audit,
            "image_grouped",
            image_name=figure.path.name,
            relative_path=figure.path.relative_to(archive_root).as_posix(),
            member_kind="slab",
            member_id=figure.elevation,
            direction=figure.direction,
            group=figure.position,
        )
        try:
            reading = recognizer(figure.path, figure.direction)
        except OcrRecognitionError as exc:
            failures[item_id] = ("OCR_RECOGNITION_FAILED", str(exc))
            recognized.append(RecognizedSlabFigure(source=figure, reading=None))
            _audit(
                audit,
                "ocr_failed",
                image_name=figure.path.name,
                member_kind="slab",
                member_id=figure.elevation,
                direction=figure.direction,
                error_code="OCR_RECOGNITION_FAILED",
            )
            continue
        recognized.append(RecognizedSlabFigure(source=figure, reading=reading))
        _audit(
            audit,
            "ocr_completed",
            image_name=figure.path.name,
            member_kind="slab",
            member_id=figure.elevation,
            direction=figure.direction,
            smx=reading.smx,
            legend_values=list(reading.legend_values),
            zero_smx=reading.is_zero_result,
        )
    return recognized, failures


def _recommendation_items(
    *,
    walls: list[RecognizedFigure],
    slabs: list[RecognizedSlabFigure],
    config: CalculationBookAiSuggestionMechanismConfig,
) -> tuple[RebarSuggestionInput, ...]:
    items: list[RebarSuggestionInput] = []
    margin_multiplier = 1 + float(config.margin_ratio)
    for figure in walls:
        if figure.source.group_index is not None or figure.reading is None:
            continue
        smx = figure.reading.smx
        items.append(
            RebarSuggestionInput(
                item_id=wall_rebar_item_id(figure.source),
                member_kind="wall",
                member_id=figure.source.wall_id,
                direction=figure.source.direction,
                smx=smx,
                target_area=smx * margin_multiplier,
                candidates=generate_rebar_candidates(
                    smx=smx,
                    direction=figure.source.direction,
                    config=config,
                ),
            )
        )
    for figure in slabs:
        if figure.reading is None:
            continue
        item_id = slab_rebar_item_id(figure.source)
        key = item_id.rsplit(":", 1)[-1]
        direction = config.slab_direction_mapping[key].strip().upper()
        smx = figure.reading.smx
        items.append(
            RebarSuggestionInput(
                item_id=item_id,
                member_kind="slab",
                member_id=f"{figure.source.elevation}:{key}",
                direction=direction,
                smx=smx,
                target_area=smx * margin_multiplier,
                candidates=generate_rebar_candidates(
                    smx=smx,
                    direction=direction,
                    config=config,
                ),
            )
        )
    return tuple(items)


def _selected_cell(selection: SelectedRebarSuggestion) -> ParsedRebarCell:
    configuration = selection.configuration
    return ParsedRebarCell(
        original_text=configuration.canonical_specification,
        normalized_text=configuration.canonical_specification,
        candidates=(configuration,),
        selected=configuration,
    )


def _route_recommendation_result(
    *,
    items: tuple[RebarSuggestionInput, ...],
    result: RebarSuggestionResult,
) -> tuple[dict[str, ParsedRebarCell], dict[str, tuple[str, str]]]:
    expected = {item.item_id: item for item in items}
    selected_cells: dict[str, ParsedRebarCell] = {}
    missing_reasons: dict[str, tuple[str, str]] = {}
    for selection in result.selected:
        source = expected.get(selection.item_id)
        if source is None:
            raise ValueError(f"AI 返回未知 item_id：{selection.item_id}")
        if selection.item_id in selected_cells or selection.item_id in missing_reasons:
            raise ValueError(f"AI 返回重复 item_id：{selection.item_id}")
        if (
            selection.member_kind != source.member_kind
            or selection.member_id != source.member_id
            or selection.direction != source.direction
            or selection.smx != source.smx
            or selection.target_area != source.target_area
        ):
            raise ValueError(f"AI 返回的条目标识与请求不一致：{selection.item_id}")
        selected_cells[selection.item_id] = _selected_cell(selection)
    for warning in result.warnings:
        source = expected.get(warning.item_id)
        if source is None:
            raise ValueError(f"AI 返回未知 item_id：{warning.item_id}")
        if warning.item_id in selected_cells or warning.item_id in missing_reasons:
            raise ValueError(f"AI 返回重复 item_id：{warning.item_id}")
        if (
            warning.member_kind != source.member_kind
            or warning.member_id != source.member_id
            or warning.direction != source.direction
        ):
            raise ValueError(f"AI 返回的条目标识与请求不一致：{warning.item_id}")
        missing_reasons[warning.item_id] = (warning.code, warning.message)
    for item_id in expected.keys() - selected_cells.keys() - missing_reasons.keys():
        missing_reasons[item_id] = (
            "AI_NEEDS_REVIEW",
            "AI 推荐结果没有返回该方向，当前方向已留空",
        )
    return selected_cells, missing_reasons


def _unknown_image_warnings(
    paths: tuple[Path, ...],
) -> tuple[ReinforcementNormalizationWarning, ...]:
    return tuple(
        ReinforcementNormalizationWarning(
            code="UNKNOWN_IMAGE_NAME",
            scope="image",
            identity=path.name,
            direction=None,
            source_sheet="",
            source_row=0,
            source_cells={},
            original_values={"filename": path.name},
            resolved_values={},
            reason="图片名称无法识别为墙体或楼板方向，已保留图片并留空配筋",
            blank_fields=("X", "Y", "Z"),
        )
        for path in paths
    )


class CalculationBookProcessor:
    def __init__(
        self,
        *,
        assets: CalculationBookAssets,
        mechanism: CalculationBookMechanism | None = None,
        ocr_recognizer: OcrRecognizer | None = None,
        archive_extractor: ArchiveExtractorSettings | None = None,
    ) -> None:
        self.assets = assets
        self.mechanism = mechanism or CalculationBookMechanism()
        self.archive_extractor = archive_extractor
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
        reinforcement_normalizer: ReinforcementNormalizationCallback | None = None,
        rebar_suggester: RebarSuggestionCallback | None = None,
        audit: CalculationBookAudit | None = None,
    ) -> CalculationBookResult:
        report = progress or (lambda _stage, _percent, _message, _details: None)
        extraction_root = output_dir / "extracted"

        report(
            CalculationBookStage.VALIDATE_ARCHIVE,
            10,
            "正在校验计算图片压缩包",
            {},
        )
        contents = validate_and_extract_archive(
            archive_path,
            extraction_root,
            reinforcement_source=params.reinforcement_source,
            limits=self.mechanism.archive_limits,
            archive_extractor=self.archive_extractor,
        )
        _audit(
            audit,
            "archive_validated",
            file_count=len(contents.extracted_files),
            image_count=(
                len(contents.reinforcement_figures)
                + len(contents.slab_figures)
                + len(contents.ignored_root_images)
                + 2
            ),
            relative_paths=sorted(
                path.relative_to(contents.root).as_posix()
                for path in contents.extracted_files
            ),
        )

        report(
            CalculationBookStage.OCR_REINFORCEMENT,
            30,
            "正在识别底部应力图例",
            {"figure_count": len(contents.reinforcement_figures)},
        )
        ai_result: RebarSuggestionResult | None = None
        normalization_warnings: tuple[ReinforcementNormalizationWarning, ...] = ()
        recognized: list[RecognizedFigure]
        slab_plan = SlabMatchingPlan(assignments=())
        recognized_slabs: list[RecognizedSlabFigure] = []
        if params.reinforcement_source is ReinforcementSource.PROVIDED:
            workbook = contents.reinforcement_workbook
            if workbook is None:
                raise ValueError("实配钢筋模式缺少 Excel 配筋表")
            normalized = (
                reinforcement_normalizer(
                    workbook,
                    params.include_slab_stress,
                )
                if reinforcement_normalizer is not None
                else None
            )
            schedule = (
                normalized.wall_schedule
                if normalized is not None
                else load_reinforcement_schedule(workbook)
            )
            normalization_warnings = (
                normalized.warnings if normalized is not None else ()
            )
            recognized = []
            for figure in contents.reinforcement_figures:
                _audit(
                    audit,
                    "image_grouped",
                    image_name=figure.path.name,
                    relative_path=figure.path.relative_to(contents.root).as_posix(),
                    member_kind="wall",
                    member_id=figure.wall_id,
                    direction=figure.direction,
                    group=figure.group_index,
                )
                reading = self.ocr_recognizer(figure.path, figure.direction)
                recognized.append(RecognizedFigure(source=figure, reading=reading))
                _audit(
                    audit,
                    "ocr_completed",
                    image_name=figure.path.name,
                    member_kind="wall",
                    member_id=figure.wall_id,
                    direction=figure.direction,
                    smx=reading.smx,
                    legend_values=list(reading.legend_values),
                    zero_smx=reading.is_zero_result,
                )
            report(
                CalculationBookStage.SELECT_REBAR,
                55,
                "正在匹配并核验实配钢筋",
                {},
            )
            plan = match_reinforcement(
                recognized,
                schedule,
                normalization_warnings=normalization_warnings,
            )
            assignments = _apply_manual_confirmations(
                plan,
                confirmations=params.manual_confirmations,
                schedule_rows=schedule.rows,
            )
            if params.include_slab_stress:
                slab_schedule = (
                    normalized.slab_schedule
                    if normalized is not None
                    else load_slab_reinforcement_schedule(workbook, required=True)
                )
                for figure in contents.slab_figures:
                    _audit(
                        audit,
                        "image_grouped",
                        image_name=figure.path.name,
                        relative_path=figure.path.relative_to(contents.root).as_posix(),
                        member_kind="slab",
                        member_id=figure.elevation,
                        direction=figure.direction,
                        group=figure.position,
                    )
                    reading = self.ocr_recognizer(figure.path, figure.direction)
                    recognized_slabs.append(
                        RecognizedSlabFigure(source=figure, reading=reading)
                    )
                    _audit(
                        audit,
                        "ocr_completed",
                        image_name=figure.path.name,
                        member_kind="slab",
                        member_id=figure.elevation,
                        direction=figure.direction,
                        smx=reading.smx,
                        legend_values=list(reading.legend_values),
                        zero_smx=reading.is_zero_result,
                    )
                if normalized is None:
                    assert slab_schedule is not None
                    slab_plan = match_slab_reinforcement(
                        recognized_slabs,
                        slab_schedule,
                    )
                else:
                    slab_plan = match_slab_reinforcement(
                        recognized_slabs,
                        slab_schedule or SlabReinforcementSchedule(rows=()),
                        normalization_warnings=normalization_warnings,
                        allow_partial=True,
                    )
        else:
            if rebar_suggester is None:
                raise ValueError("无实配钢筋模式缺少 AI 配筋推荐器")
            recognized, wall_failures = _recognize_ai_wall_figures(
                figures=contents.reinforcement_figures,
                recognizer=self.ocr_recognizer,
                archive_root=contents.root,
                audit=audit,
            )
            slab_failures: dict[str, tuple[str, str]] = {}
            if params.include_slab_stress:
                recognized_slabs, slab_failures = _recognize_ai_slab_figures(
                    figures=contents.slab_figures,
                    recognizer=self.ocr_recognizer,
                    archive_root=contents.root,
                    audit=audit,
                )
            for image_path in contents.ignored_root_images:
                _audit(
                    audit,
                    "image_grouped",
                    image_name=image_path.name,
                    relative_path=image_path.relative_to(contents.root).as_posix(),
                    member_kind="unknown",
                    member_id=image_path.stem,
                    direction="UNKNOWN",
                    group=None,
                )
            items = _recommendation_items(
                walls=recognized,
                slabs=recognized_slabs,
                config=self.mechanism.ai_suggestion,
            )
            report(
                CalculationBookStage.AI_REBAR_SUGGESTION,
                50,
                "正在生成并验算 AI 配筋建议",
                {"item_count": len(items)},
            )
            ai_result = rebar_suggester(items)
            selected_cells, suggestion_failures = _route_recommendation_result(
                items=items,
                result=ai_result,
            )
            report(
                CalculationBookStage.SELECT_REBAR,
                60,
                "正在匹配并核验 AI 配筋建议",
                {},
            )
            plan = build_ai_reinforcement_plan(
                recognized,
                selected_cells={
                    item_id: cell
                    for item_id, cell in selected_cells.items()
                    if item_id.startswith("wall:")
                },
                missing_reasons={**suggestion_failures, **wall_failures},
            )
            assignments = plan.assignments
            if params.include_slab_stress:
                slab_plan = build_ai_slab_plan(
                    recognized_slabs,
                    selected_cells={
                        item_id: cell
                        for item_id, cell in selected_cells.items()
                        if item_id.startswith("slab:")
                    },
                    missing_reasons={**suggestion_failures, **slab_failures},
                )

        selections = tuple(
            selection
            for assignment in assignments
            for direction in ("X", "Y", "Z")
            if (selection := _selection(assignment, direction)) is not None
        )
        ai_suggested_direction_count = 0
        ai_blank_direction_count = 0
        if params.reinforcement_source is ReinforcementSource.AI_SUGGESTED:
            wall_direction_count = len(assignments) * 3
            slab_direction_count = len(slab_plan.assignments)
            ai_suggested_direction_count = sum(
                assignment.cell_for(direction) is not None
                for assignment in assignments
                for direction in ("X", "Y", "Z")
            ) + sum(
                assignment.rebar_cell is not None
                for assignment in slab_plan.assignments
            )
            ai_blank_direction_count = (
                wall_direction_count
                + slab_direction_count
                - ai_suggested_direction_count
            )

        report(CalculationBookStage.RENDER_CALCULATION_BOOK, 75, "正在渲染 Word 计算书", {})
        template_path = resolve_template_path(self.assets.template_root, params.template_type)
        document = DocxTemplate(template_path)
        context = params.model_dump(mode="python")
        slab_figure_rows = _slab_figure_rows(
            document=document,
            plan=slab_plan,
            chapter=self.mechanism.chapter,
            is_ai_suggested=(
                params.reinforcement_source is ReinforcementSource.AI_SUGGESTED
            ),
            audit=audit,
        )
        reinforcement_figure_rows = _reinforcement_figure_rows(
            document=document,
            assignments=assignments,
            chapter=self.mechanism.chapter,
            start_index=len(slab_figure_rows) + 1,
            is_ai_suggested=(
                params.reinforcement_source is ReinforcementSource.AI_SUGGESTED
            ),
            audit=audit,
        )
        unmatched_rows = (
            _unmatched_figure_rows(
                document=document,
                image_paths=contents.ignored_root_images,
                chapter=self.mechanism.chapter,
                start_index=len(slab_figure_rows) + len(reinforcement_figure_rows) + 1,
                audit=audit,
            )
            if params.reinforcement_source is ReinforcementSource.AI_SUGGESTED
            else []
        )
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
                "slab_figures": slab_figure_rows,
                "reinforcement_figures": [
                    *reinforcement_figure_rows,
                    *unmatched_rows,
                ],
                "ai_rebar_disclosure": (
                    self.mechanism.ai_suggestion.word_declaration
                    if params.reinforcement_source
                    is ReinforcementSource.AI_SUGGESTED
                    else ""
                ),
            }
        )
        validate_template_context(template_path, context)
        document.render(context)

        output_dir.mkdir(parents=True, exist_ok=True)
        final_path = output_dir / _safe_output_name(params)
        temporary_path = final_path.with_suffix(".docx.tmp")
        document.save(temporary_path)
        _superscript_mm2(temporary_path)
        temporary_path.replace(final_path)

        report(
            CalculationBookStage.FINALIZE_ARTIFACT,
            95,
            "计算书生成完成",
            {
                "figure_count": (
                    len(recognized) + len(recognized_slabs) + len(unmatched_rows)
                ),
                "output_filename": final_path.name,
                "template_type": params.template_type.value,
            },
        )
        return CalculationBookResult(
            output_path=final_path,
            figure_count=len(recognized) + len(recognized_slabs) + len(unmatched_rows),
            template_type=params.template_type.value,
            selections=selections,
            normalization_warnings=_deduplicate_warnings(
                (
                    *normalization_warnings,
                    *plan.warnings,
                    *slab_plan.warnings,
                    *(
                        _unknown_image_warnings(contents.ignored_root_images)
                        if params.reinforcement_source
                        is ReinforcementSource.AI_SUGGESTED
                        else ()
                    ),
                )
            ),
            ai_rebar_suggestion=ai_result,
            ai_suggested_direction_count=ai_suggested_direction_count,
            ai_blank_direction_count=ai_blank_direction_count,
        )


def _deduplicate_warnings(
    warnings: tuple[ReinforcementNormalizationWarning, ...],
) -> tuple[ReinforcementNormalizationWarning, ...]:
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
    return tuple(result)
