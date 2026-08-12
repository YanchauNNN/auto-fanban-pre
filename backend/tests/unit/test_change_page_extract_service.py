from __future__ import annotations

import json
from pathlib import Path

import pytest
from pypdf import PdfWriter

from src.change_page_extract import ChangePageExtractError, ChangePageExtractService


def _write_pdf(path: Path, pages: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=100, height=100)
    with path.open("wb") as handle:
        writer.write(handle)


def test_build_result_natural_sorts_attachment_numbers_and_formats_text(tmp_path: Path) -> None:
    extracted = tmp_path / "extracted"
    _write_pdf(extracted / "附图10：十号图.pdf", 2)
    _write_pdf(extracted / "附图2：二号图.PDF", 3)
    _write_pdf(extracted / "附图1：一号图.pdf", 1)
    (extracted / "readme.txt").write_text("ignored", encoding="utf-8")

    result = ChangePageExtractService().build_result(
        archive_name="样例.zip",
        extraction_root=extracted,
        output_path=tmp_path / "result.json",
    )

    assert [item.name for item in result.items] == ["附图1：一号图", "附图2：二号图", "附图10：十号图"]
    assert result.text.splitlines() == [
        "附图1：一号图，共1页；",
        "附图2：二号图，共3页；",
        "附图10：十号图，共2页；",
    ]
    assert result.pdf_count == 3
    assert result.ignored_file_count == 1
    assert json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))["pdf_count"] == 3


def test_duplicate_pdf_basenames_use_relative_paths(tmp_path: Path) -> None:
    extracted = tmp_path / "extracted"
    _write_pdf(extracted / "一组" / "附图1.pdf", 1)
    _write_pdf(extracted / "二组" / "附图1.pdf", 2)

    result = ChangePageExtractService().build_result(
        archive_name="重复.zip",
        extraction_root=extracted,
    )

    assert [item.name for item in result.items] == ["一组/附图1", "二组/附图1"]


def test_corrupt_pdf_is_a_failed_scan_not_zero_pages(tmp_path: Path) -> None:
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    (extracted / "附图1：损坏文件.pdf").write_bytes(b"not a pdf")

    with pytest.raises(ChangePageExtractError, match="PDF 无法读取"):
        ChangePageExtractService().build_result(
            archive_name="损坏.zip",
            extraction_root=extracted,
        )


def test_archive_without_pdf_fails_explicitly(tmp_path: Path) -> None:
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    (extracted / "readme.txt").write_text("no pdf", encoding="utf-8")

    with pytest.raises(ChangePageExtractError, match="没有 PDF"):
        ChangePageExtractService().build_result(
            archive_name="空包.zip",
            extraction_root=extracted,
        )
