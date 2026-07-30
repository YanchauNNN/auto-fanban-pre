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


def _build_zip(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    for name in (
        "N5012-X.png",
        "N5012-Y.png",
        "N5012-Z.png",
        "01/layout.png",
        "02/model.png",
    ):
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
    workbook.save(source / "计算书模板文件.xlsx")
    archive_path = tmp_path / "input.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in source.rglob("*"):
            if not path.is_file():
                continue
            archive.write(path, path.relative_to(source).as_posix())
    return archive_path


def _params() -> CalculationBookParams:
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
        }
    )


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
        "墙N5012-拉筋钢筋计算配筋面积为0mm²/m。"
        "选用钢筋1排14@400x400（配筋面积为962.1 mm²/m）作为构造钢筋。 "
        "配筋结果包络计算结果。"
    ) in text
