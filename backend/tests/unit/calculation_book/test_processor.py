from __future__ import annotations

import math
import zipfile
from pathlib import Path

import pytest
from docx import Document
from openpyxl import Workbook
from PIL import Image

from src.calculation_book.models import CalculationBookParams
from src.calculation_book.ocr import StressLegendReading
from src.calculation_book.processor import (
    CalculationBookAssets,
    CalculationBookProcessor,
    CalculationBookStage,
)

ASSET_ROOT = Path(__file__).resolve().parents[4] / "documents_bin" / "calculation_book"


def _write_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1200, 800), "white").save(path)


def _build_zip(
    tmp_path: Path,
    *,
    include_slab: bool = False,
    include_middle: bool = False,
) -> Path:
    source = tmp_path / "source"
    names = [
        "N5012-X.png",
        "N5012-Y.png",
        "N5012-Z.png",
        "01/layout.png",
        "02/model.png",
    ]
    if include_slab:
        names.extend(
            [
                "11.45-TOP-X.png",
                "11.45-BOTTOM-X.png",
                "11.45-TOP-Y.png",
                "11.45-BOTTOM-Y.png",
                "11.45-Z.png",
            ]
        )
    if include_middle:
        names.extend(("11.45-MIDDLE-X.png", "11.45-MIDDLE-Y.png"))
    for name in names:
        _write_png(source / name)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(
        [
            "构件编号及位置",
            "单侧水平钢筋(对称配筋)",
            "单侧竖向钢筋(对称配筋)",
            "拉筋",
        ]
    )
    sheet.append(
        ["N5012 墙", "1D32间距200", "1D28间距200", "1C14间距400*400"]
    )
    if include_slab:
        slab_sheet = workbook.create_sheet("楼板配筋")
        slab_sheet.append(
            [
                "标高",
                "顶层水平",
                "顶层竖向",
                "中层水平",
                "中层竖向",
                "底层水平",
                "底层竖向",
                "纵向拉筋",
            ]
        )
        slab_sheet.append(
            [
                11.45,
                "1D36@200",
                "1D40@200",
                "1D32@200" if include_middle else None,
                "1D34@200" if include_middle else None,
                "1D30@200",
                "1D28@200",
                "1D16@200",
            ]
        )
    workbook.save(source / "计算书模板文件.xlsx")
    archive_path = tmp_path / "input.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in source.rglob("*"):
            if not path.is_file():
                continue
            archive.write(path, path.relative_to(source).as_posix())
    return archive_path


def _params(*, include_slab_stress: bool = False) -> CalculationBookParams:
    return CalculationBookParams.model_validate(
        {
            "template_type": "internal_structure",
            "project_no": "JQ",
            "project_name": "浙江金七门核电厂1、2号机组",
            "internal_code": "JQ00-NN-001",
            "version": "A",
            "subproject_code": "RX",
            "subproject_name": "内部结构",
            "design_phase": "施工图设计",
            "document_name": "0.000m~15.000m配筋计算书",
            "workshop_length": 72.5,
            "workshop_width": 48.0,
            "raft_slab_top_elevation": -8.5,
            "roof_top_elevation": 31.2,
            "factory_extreme_min_temperature": -18.0,
            "factory_extreme_max_temperature": 39.0,
            "site_soil_temperature": 15.0,
            "include_slab_stress": include_slab_stress,
        }
    )


def _all_paragraphs(document: Document):
    yield from document.paragraphs
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs


def _assert_mm2_uses_true_superscript(document: Document) -> None:
    found = 0
    for paragraph in _all_paragraphs(document):
        runs = paragraph.runs
        for index, run in enumerate(runs):
            for offset, character in enumerate(run.text):
                if character != "2":
                    continue
                prefix = "".join(item.text for item in runs[:index]) + run.text[:offset]
                if not prefix.endswith("mm"):
                    continue
                found += 1
                assert run.font.superscript is True
    assert found > 0


def test_processor_renders_a_real_docx_and_reports_all_stages(tmp_path: Path) -> None:
    stages: list[CalculationBookStage] = []

    def recognize(_path: Path, direction: str) -> StressLegendReading:
        if direction == "Z":
            return StressLegendReading(
                smn=0,
                smx=0,
                legend_values=(),
                is_zero_result=True,
            )
        return StressLegendReading(
            smn=0,
            smx=800,
            legend_values=tuple(800 * index / 9 for index in range(10)),
        )

    processor = CalculationBookProcessor(
        assets=CalculationBookAssets(
            template_root=ASSET_ROOT,
        ),
        ocr_recognizer=recognize,
    )

    result = processor.process(
        archive_path=_build_zip(tmp_path),
        output_dir=tmp_path / "output",
        params=_params(),
        progress=lambda stage, _percent, _message, _details: stages.append(stage),
    )

    assert result.output_path.is_file()
    assert result.output_path.suffix == ".docx"
    assert result.figure_count == 3
    assert len(result.selections) == 3
    assert result.selections[2].actual_area == pytest.approx(
        math.pi * 7**2 * 2.5 * 2.5
    )
    assert stages == [
        CalculationBookStage.VALIDATE_ARCHIVE,
        CalculationBookStage.OCR_REINFORCEMENT,
        CalculationBookStage.SELECT_REBAR,
        CalculationBookStage.RENDER_CALCULATION_BOOK,
        CalculationBookStage.FINALIZE_ARTIFACT,
    ]

    document = Document(result.output_path)
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert (
        "墙N5012-拉筋钢筋计算配筋面积为0mm2/m。"
        "选用钢筋1排14@400x400（配筋面积为962.1 mm2/m）作为构造钢筋。 "
        "配筋结果包络计算结果。"
    ) in text
    _assert_mm2_uses_true_superscript(document)


def test_processor_inserts_five_slab_groups_before_wall_results(
    tmp_path: Path,
) -> None:
    def recognize(_path: Path, direction: str) -> StressLegendReading:
        if direction == "Z":
            return StressLegendReading(
                smn=0,
                smx=0,
                legend_values=(),
                is_zero_result=True,
            )
        return StressLegendReading(
            smn=0,
            smx=800,
            legend_values=tuple(800 * index / 9 for index in range(10)),
        )

    processor = CalculationBookProcessor(
        assets=CalculationBookAssets(template_root=ASSET_ROOT),
        ocr_recognizer=recognize,
    )

    result = processor.process(
        archive_path=_build_zip(tmp_path, include_slab=True),
        output_dir=tmp_path / "output",
        params=_params(include_slab_stress=True),
    )

    assert result.figure_count == 8
    document = Document(result.output_path)
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    transition = (
        "墙体的配筋计算结果如下。"
        "配筋结果为单侧配筋量、其单位为mm2/m。"
    )
    assert text.index("11.45m楼板顶层水平钢筋") < text.index(transition)
    assert text.index(transition) < text.index("墙N5012-水平向钢筋")
    assert "11.45m楼板纵向拉筋计算配筋面积为0mm2/m。" in text
    assert text.count("11.45m楼板") == 5
    _assert_mm2_uses_true_superscript(document)
