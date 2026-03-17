from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any, cast

import pytest

from src.doc_gen.pdf_engine import PDFExporter
from src.interfaces import ExportError


def test_count_pdf_pages_fallback_by_text(monkeypatch, temp_dir: Path) -> None:
    pdf_path = temp_dir / "sample.pdf"
    pdf_path.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj<</Type /Pages/Count 2/Kids[2 0 R 3 0 R]>>endobj\n"
        b"2 0 obj<</Type /Page>>endobj\n"
        b"3 0 obj<</Type /Page>>endobj\n"
        b"%%EOF\n"
    )

    real_import = cast(Any, builtins.__import__)

    def fake_import(name: str, *args: Any, **kwargs: Any):
        if name == "pypdf":
            raise ImportError("forced fallback")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
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


class _FakeWordOptions:
    def __init__(self) -> None:
        self.SaveNormalPrompt = True


class _FakeNormalTemplate:
    def __init__(self) -> None:
        self.Saved = False


class _FakeWordApp:
    def __init__(self) -> None:
        self.Visible = True
        self.DisplayAlerts = 1
        self.Options = _FakeWordOptions()
        self.NormalTemplate = _FakeNormalTemplate()


class _FakeWordDoc:
    def __init__(self) -> None:
        self.Saved = False


def test_prepare_word_for_headless_run_suppresses_normal_prompt() -> None:
    exporter = PDFExporter(preferred_engine="office_com")
    word = _FakeWordApp()

    exporter._prepare_word_for_headless_run(word)

    assert word.Visible is False
    assert word.DisplayAlerts == 0
    assert word.Options.SaveNormalPrompt is False


def test_mark_word_normal_template_saved() -> None:
    exporter = PDFExporter(preferred_engine="office_com")
    word = _FakeWordApp()

    exporter._mark_word_normal_template_saved(word)

    assert word.NormalTemplate.Saved is True


def test_mark_word_document_saved() -> None:
    exporter = PDFExporter(preferred_engine="office_com")
    doc = _FakeWordDoc()

    exporter._mark_word_document_saved(doc)

    assert doc.Saved is True
