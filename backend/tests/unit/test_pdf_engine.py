from __future__ import annotations

import builtins
import shutil
from pathlib import Path
from types import SimpleNamespace
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


def test_export_xlsx_does_not_fallback_when_disabled(monkeypatch, temp_dir: Path) -> None:
    input_xlsx = temp_dir / "input.xlsx"
    input_xlsx.write_bytes(b"dummy")
    output_pdf = temp_dir / "output.pdf"
    exporter = PDFExporter(preferred_engine="office_com")
    exporter.fallback = "disabled"

    called = {"fallback": False}

    def fake_com(xlsx_path: Path, pdf_path: Path) -> None:  # noqa: ARG001
        raise RuntimeError("excel com boom")

    def fake_libreoffice(input_path: Path, pdf_path: Path) -> None:  # noqa: ARG001
        called["fallback"] = True
        raise ExportError("should not be called")

    monkeypatch.setattr(exporter, "_export_xlsx_via_com", fake_com)
    monkeypatch.setattr(exporter, "_export_via_libreoffice", fake_libreoffice)

    with pytest.raises(ExportError) as exc_info:
        exporter.export_xlsx_to_pdf(input_xlsx, output_pdf)

    assert "excel com boom" in str(exc_info.value)
    assert called["fallback"] is False


def test_export_xlsx_reports_original_com_error_when_fallback_also_fails(
    monkeypatch,
    temp_dir: Path,
) -> None:
    input_xlsx = temp_dir / "input.xlsx"
    input_xlsx.write_bytes(b"dummy")
    output_pdf = temp_dir / "output.pdf"
    exporter = PDFExporter(preferred_engine="office_com")
    exporter.fallback = "libreoffice"

    def fake_com(xlsx_path: Path, pdf_path: Path) -> None:  # noqa: ARG001
        raise RuntimeError("excel com boom")

    def fake_libreoffice(input_path: Path, pdf_path: Path) -> None:  # noqa: ARG001
        raise ExportError("libreoffice missing")

    monkeypatch.setattr(exporter, "_export_xlsx_via_com", fake_com)
    monkeypatch.setattr(exporter, "_export_via_libreoffice", fake_libreoffice)

    with pytest.raises(ExportError) as exc_info:
        exporter.export_xlsx_to_pdf(input_xlsx, output_pdf)

    message = str(exc_info.value)
    assert "excel com boom" in message
    assert "libreoffice missing" in message


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


class _FakeExcelApp:
    def __init__(self) -> None:
        self.Visible = True
        self.DisplayAlerts = True
        self.AskToUpdateLinks = True
        self.EnableEvents = True
        self.ScreenUpdating = True
        self.DisplayStatusBar = True
        self.UserControl = True
        self.Interactive = True
        self.AutomationSecurity = 1


class _FakeRejectedComError(RuntimeError):
    def __init__(self, message: str, *, hresult: int | None = None) -> None:
        super().__init__(message)
        self.hresult = hresult


class _FakeWorkbookCollection:
    def __init__(self) -> None:
        self.open_attempts = 0

    def Open(self, path: str, update_links: int, read_only: bool) -> dict[str, object]:  # noqa: N802
        self.open_attempts += 1
        if self.open_attempts == 1:
            raise _FakeRejectedComError(
                "call was rejected by callee",
                hresult=-2147418111,
            )
        return {
            "path": path,
            "update_links": update_links,
            "read_only": read_only,
        }


class _FakeExcelWithBusyWorkbooks:
    def __init__(self) -> None:
        self.workbook_access_attempts = 0
        self.collection = _FakeWorkbookCollection()

    @property
    def Workbooks(self) -> _FakeWorkbookCollection:  # noqa: N802
        self.workbook_access_attempts += 1
        if self.workbook_access_attempts == 1:
            raise _FakeRejectedComError(
                "被呼叫方拒绝接收呼叫。",
                hresult=-2147418111,
            )
        return self.collection


class _FakeBrokenExcelComClient:
    def __init__(self) -> None:
        self.active_object: object | None = None
        self.dispatch_calls = 0
        self.get_active_calls = 0

    def DispatchEx(self, prog_id: str) -> object:  # noqa: N802
        self.dispatch_calls += 1
        raise _FakeRejectedComError(
            "系统找不到指定的文件。",
            hresult=-2147024894,
        )

    def GetActiveObject(self, prog_id: str) -> object:  # noqa: N802
        self.get_active_calls += 1
        if self.active_object is None:
            raise RuntimeError("active object unavailable")
        return self.active_object


class _FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self._exited = False

    def poll(self) -> int | None:
        return 0 if self._exited else None

    def terminate(self) -> None:
        self._exited = True

    def wait(self, timeout: float | None = None) -> int:  # noqa: ARG002
        self._exited = True
        return 0


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


def test_prepare_excel_for_headless_run_disables_interactive_features() -> None:
    exporter = PDFExporter(preferred_engine="office_com")
    excel = _FakeExcelApp()

    exporter._prepare_excel_for_headless_run(excel)

    assert excel.Visible is False
    assert excel.DisplayAlerts is False
    assert excel.AskToUpdateLinks is False
    assert excel.EnableEvents is False
    assert excel.ScreenUpdating is False
    assert excel.DisplayStatusBar is False
    assert excel.UserControl is False
    assert excel.Interactive is False
    assert excel.AutomationSecurity == 3


def test_prepare_excel_path_for_com_creates_ascii_temp_copy(temp_dir: Path) -> None:
    exporter = PDFExporter(preferred_engine="office_com")
    source = temp_dir / "目录模板文件.xlsx"
    source.write_bytes(b"excel-bytes")

    working_copy, cleanup_dir = exporter._prepare_excel_path_for_com(
        source,
        label="common_catalog",
    )

    assert working_copy.name == "common_catalog.xlsx"
    assert working_copy.read_bytes() == b"excel-bytes"
    assert cleanup_dir.exists()


def test_open_excel_workbook_retries_when_call_is_rejected(monkeypatch, temp_dir: Path) -> None:
    exporter = PDFExporter(preferred_engine="office_com")
    source = temp_dir / "input.xlsx"
    source.write_bytes(b"excel-bytes")
    working_copy, cleanup_dir = exporter._prepare_excel_path_for_com(
        source,
        label="common_catalog",
    )
    excel = _FakeExcelWithBusyWorkbooks()

    workbook = cast(dict[str, object], exporter._open_excel_workbook(excel, working_copy, read_only=True))

    assert workbook["path"] == str(working_copy.absolute())
    assert workbook["read_only"] is True
    assert excel.workbook_access_attempts == 2
    assert excel.collection.open_attempts == 2
    shutil.rmtree(cleanup_dir, ignore_errors=True)


def test_create_excel_application_falls_back_to_excel_executable_candidates(
    monkeypatch,
) -> None:
    exporter = PDFExporter(preferred_engine="office_com")
    win32_client = _FakeBrokenExcelComClient()
    fake_excel = _FakeExcelApp()
    launched: list[Path] = []

    monkeypatch.setattr(
        PDFExporter,
        "_iter_excel_executable_candidates",
        classmethod(lambda cls: [Path("C:/Office15/EXCEL.EXE"), Path("C:/Office16/EXCEL.EXE")]),
    )

    def fake_launch(cls, candidate: Path):  # noqa: ANN001
        launched.append(candidate)
        if candidate.name == "EXCEL.EXE" and "Office16" in candidate.as_posix():
            win32_client.active_object = fake_excel
            return _FakeProcess(4242)
        return _FakeProcess(3131)

    monkeypatch.setattr(
        PDFExporter,
        "_launch_excel_candidate_for_automation",
        classmethod(fake_launch),
    )
    monkeypatch.setattr(
        PDFExporter,
        "_wait_for_excel_active_object",
        classmethod(lambda cls, module: module.client.GetActiveObject("Excel.Application")),
    )
    monkeypatch.setattr(
        PDFExporter,
        "_excel_app_matches_pid",
        classmethod(lambda cls, excel, pid: pid == 4242),
    )

    excel, owned = exporter._create_excel_application(SimpleNamespace(client=win32_client))

    assert excel is fake_excel
    assert owned is True
    assert launched == [Path("C:/Office15/EXCEL.EXE"), Path("C:/Office16/EXCEL.EXE")]
    assert win32_client.dispatch_calls == 1


def test_create_excel_application_uses_dispatchex_when_available() -> None:
    exporter = PDFExporter(preferred_engine="office_com")
    excel = _FakeExcelApp()

    class _Client:
        def __init__(self) -> None:
            self.dispatch_calls = 0

        def DispatchEx(self, prog_id: str) -> object:  # noqa: N802
            self.dispatch_calls += 1
            return excel

    client = _Client()
    acquired, owned = exporter._create_excel_application(SimpleNamespace(client=client))

    assert acquired is excel
    assert owned is True
    assert client.dispatch_calls == 1
