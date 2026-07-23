from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path

from docx.shared import Mm
from docxtpl import DocxTemplate, InlineImage

from .archive import ArchiveLimits, ReinforcementFigure, validate_and_extract_archive
from .models import CalculationBookParams
from .ocr import recognize_sm
from .reinforcement import RebarSelection, load_rebar_area_table, select_rebar
from .templates import resolve_template_path, validate_template_context


class CalculationBookStage(StrEnum):
    VALIDATE_ARCHIVE = "VALIDATE_ARCHIVE"
    OCR_REINFORCEMENT = "OCR_REINFORCEMENT"
    SELECT_REBAR = "SELECT_REBAR"
    RENDER_CALCULATION_BOOK = "RENDER_CALCULATION_BOOK"
    FINALIZE_ARTIFACT = "FINALIZE_ARTIFACT"


ProgressCallback = Callable[[CalculationBookStage, int, str, dict[str, object]], None]
OcrRecognizer = Callable[[Path], int]


@dataclass(frozen=True)
class CalculationBookAssets:
    template_root: Path
    rebar_table: Path


@dataclass(frozen=True)
class CalculationBookMechanism:
    archive_limits: ArchiveLimits = ArchiveLimits()
    row_counts: tuple[int, ...] = (1, 2)
    spacings: tuple[int, ...] = (200, 250)
    max_diameter: int = 40
    extra_ratio: float = 0.2
    chapter: str = "7.1"


@dataclass(frozen=True)
class CalculationBookResult:
    output_path: Path
    figure_count: int
    template_type: str
    selections: tuple[RebarSelection, ...]


@dataclass(frozen=True)
class _RecognizedFigure:
    source: ReinforcementFigure
    sm_value: int
    selection: RebarSelection


def _wall_rows(figures: list[_RecognizedFigure]) -> list[dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for figure in figures:
        row = rows.setdefault(
            figure.source.wall_id,
            {
                "id": figure.source.wall_id,
                "x_calc": "0",
                "x_actual": "",
                "x_margin": "",
                "y_calc": "0",
                "y_actual": "",
                "y_margin": "",
                "z_calc": "0",
                "z_actual": "",
                "z_margin": "",
            },
        )
        prefix = figure.source.direction.lower()
        row[f"{prefix}_calc"] = str(figure.sm_value)
        row[f"{prefix}_actual"] = str(figure.selection.actual_area)
        row[f"{prefix}_margin"] = f"{figure.selection.margin_percent:.1f}%"

    def wall_key(row: dict[str, str]) -> tuple[int, str]:
        match = re.search(r"(\d+)", row["id"])
        return (int(match.group(1)) if match else 0, row["id"])

    return sorted(rows.values(), key=wall_key)


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
        self.ocr_recognizer = ocr_recognizer or recognize_sm

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

        report(
            CalculationBookStage.OCR_REINFORCEMENT,
            30,
            "正在识别配筋图 SM 数值",
            {"figure_count": len(contents.reinforcement_figures)},
        )
        recognized_values = [
            (figure, self.ocr_recognizer(figure.path))
            for figure in contents.reinforcement_figures
        ]

        report(CalculationBookStage.SELECT_REBAR, 55, "正在自动选择钢筋组合", {})
        rebar_table = load_rebar_area_table(self.assets.rebar_table)
        figures = [
            _RecognizedFigure(
                source=figure,
                sm_value=sm_value,
                selection=select_rebar(
                    sm_value,
                    rebar_table,
                    row_counts=self.mechanism.row_counts,
                    spacings=self.mechanism.spacings,
                    max_diameter=self.mechanism.max_diameter,
                    extra_ratio=self.mechanism.extra_ratio,
                ),
            )
            for figure, sm_value in recognized_values
        ]

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
                "wall_table_rows": _wall_rows(figures),
                "reinforcement_figures": [
                    {
                        "figure_number": f"{self.mechanism.chapter}-{index}",
                        "image": InlineImage(document, str(figure.source.path), width=Mm(140)),
                        "caption": (
                            f"{figure.source.wall_id}-"
                            f"{ {'X': '水平向', 'Y': '竖向', 'Z': '拉筋'}[figure.source.direction] }"
                        ),
                        "sm_value": str(figure.sm_value),
                        "rebar_spec": figure.selection.specification,
                        "rebar_area": str(figure.selection.actual_area),
                        "rebar_target_area": str(figure.selection.target_area),
                        "rebar_diameter": str(figure.selection.diameter),
                        "rebar_row_count": str(figure.selection.row_count),
                        "rebar_spacing": str(figure.selection.spacing),
                    }
                    for index, figure in enumerate(figures, start=1)
                ],
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
                "figure_count": len(figures),
                "output_filename": final_path.name,
                "template_type": params.template_type.value,
            },
        )
        return CalculationBookResult(
            output_path=final_path,
            figure_count=len(figures),
            template_type=params.template_type.value,
            selections=tuple(figure.selection for figure in figures),
        )
