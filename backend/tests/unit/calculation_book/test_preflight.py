from __future__ import annotations

import zipfile
from pathlib import Path

from openpyxl import Workbook
from PIL import Image

from src.calculation_book.ocr import StressLegendReading
from src.calculation_book.preflight import run_calculation_book_preflight


def _build_duplicate_archive(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    for group, _smx in ((1, 3000), (2, 5000)):
        for direction in ("X", "Y", "Z"):
            Image.new("RGB", (1200, 800), "white").save(
                source / f"S7157-{group}-{direction}.png"
            )
    (source / "01").mkdir()
    (source / "02").mkdir()
    Image.new("RGB", (1200, 800), "white").save(source / "01" / "layout.png")
    Image.new("RGB", (1200, 800), "white").save(source / "02" / "model.png")

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["构件编号及位置", "水平筋", "竖向筋", "拉筋"])
    sheet.append(["S7157墙", "1D36间距200", "1D36间距200", "1C14间距400*400"])
    sheet.append(["S7157墙", "1D32间距200", "1D32间距200", "1C14间距400*400"])
    workbook.save(source / "计算书模板文件.xlsx")

    archive_path = tmp_path / "input.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in source.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())
    return archive_path


def test_preflight_returns_structured_evidence_and_manual_confirmation_candidates(
    tmp_path: Path,
) -> None:
    archive_path = _build_duplicate_archive(tmp_path)

    def recognize(path: Path, _direction: str) -> StressLegendReading:
        smx = 3000.0 if "-1-" in path.name else 5000.0
        return StressLegendReading(
            smn=0,
            smx=smx,
            legend_values=tuple(smx * index / 9 for index in range(10)),
        )

    result = run_calculation_book_preflight(
        archive_path=archive_path,
        extraction_root=tmp_path / "extracted",
        ocr_recognizer=recognize,
    )

    assert result["figure_count"] == 6
    assert result["wall_count"] == 2
    assert result["requires_manual_confirmation"] is True
    assert [item["wall_id"] for item in result["confirmations"]] == [
        "S7157-1",
        "S7157-2",
    ]
    assert result["confirmations"][0]["suggested_source_row"] == 3
    assert result["confirmations"][1]["suggested_source_row"] == 2
    assert {
        candidate["directions"]["Y"]["narrative_specification"]
        for candidate in result["confirmations"][0]["candidates"]
    } == {"1排32@200", "1排36@200"}
    assert result["walls"][0]["directions"]["X"]["legend_values"][0] == 0
    assert result["walls"][0]["directions"]["X"]["source_cell"] == "B3"
