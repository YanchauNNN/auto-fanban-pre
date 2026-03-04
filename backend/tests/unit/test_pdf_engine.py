from __future__ import annotations

from pathlib import Path

import pytest

from src.doc_gen.pdf_engine import PDFExporter
from src.interfaces import ExportError


def test_count_pdf_pages_fallback_by_text(temp_dir: Path) -> None:
    pdf_path = temp_dir / "sample.pdf"
    pdf_path.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj<</Type /Pages/Count 2/Kids[2 0 R 3 0 R]>>endobj\n"
        b"2 0 obj<</Type /Page>>endobj\n"
        b"3 0 obj<</Type /Page>>endobj\n"
        b"%%EOF\n"
    )

    exporter = PDFExporter(preferred_engine="office_com")
    assert exporter.count_pdf_pages(pdf_path) == 2


def test_export_docx_fallback_to_libreoffice(monkeypatch, temp_dir: Path) -> None:
    input_docx = temp_dir / "input.docx"
    input_docx.write_bytes(b"dummy")
    output_pdf = temp_dir / "output.pdf"
    exporter = PDFExporter(preferred_engine="office_com")
    exporter.fallback = "libreoffice"

    called = {"fallback": False}

    def fake_com(docx_path: Path, pdf_path: Path) -> None:  # noqa: ARG001
        raise RuntimeError("com failed")

    def fake_libreoffice(input_path: Path, pdf_path: Path) -> None:  # noqa: ARG001
        called["fallback"] = True
        pdf_path.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(exporter, "_export_docx_via_com", fake_com)
    monkeypatch.setattr(exporter, "_export_via_libreoffice", fake_libreoffice)

    exporter.export_docx_to_pdf(input_docx, output_pdf)
    assert called["fallback"] is True
    assert output_pdf.exists()


def test_export_docx_missing_file_raises(temp_dir: Path) -> None:
    exporter = PDFExporter(preferred_engine="office_com")
    with pytest.raises(ExportError):
        exporter.export_docx_to_pdf(temp_dir / "missing.docx", temp_dir / "x.pdf")

