"""
PDF导出引擎 - Word/Excel导出PDF

职责：
1. Word文档导出PDF（优先Office COM）
2. Excel文档导出PDF
3. PDF页数计算

依赖：
- pywin32: Windows COM自动化（优先）
- libreoffice: 兜底方案

测试要点：
- test_export_docx_to_pdf: Word导出PDF
- test_export_xlsx_to_pdf: Excel导出PDF
- test_count_pdf_pages: PDF页数计算
- test_fallback_to_libreoffice: COM失败时降级
"""

from __future__ import annotations

import contextlib
import gc
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, cast

from ..config import get_config
from ..interfaces import ExportError, IPDFExporter

_RPC_CALL_REJECTED = -2147418111


class PDFExporter(IPDFExporter):
    """PDF导出器实现"""

    def __init__(self, preferred_engine: str | None = None):
        config = get_config()
        self.preferred = preferred_engine or config.pdf_engine.preferred
        self.fallback = config.pdf_engine.fallback
        self.timeout = config.timeouts.pdf_export_sec

    def _should_use_libreoffice_fallback(self) -> bool:
        return self.fallback == "libreoffice"

    def export_docx_to_pdf(self, docx_path: Path, pdf_path: Path) -> None:
        """Word文档导出PDF"""
        if not docx_path.exists():
            raise ExportError(f"Word文档不存在: {docx_path}")

        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        # 尝试Office COM
        if self.preferred == "office_com":
            try:
                self._export_docx_via_com(docx_path, pdf_path)
                return
            except Exception as e:
                if self._should_use_libreoffice_fallback():
                    pass  # 降级到fallback
                else:
                    raise ExportError(f"Word导出PDF失败: {e}") from e

        # 尝试LibreOffice
        if self._should_use_libreoffice_fallback() or self.preferred == "libreoffice":
            self._export_via_libreoffice(docx_path, pdf_path)
        else:
            raise ExportError("无可用的PDF导出引擎")

    def export_xlsx_to_pdf(self, xlsx_path: Path, pdf_path: Path) -> None:
        """Excel文档导出PDF"""
        if not xlsx_path.exists():
            raise ExportError(f"Excel文档不存在: {xlsx_path}")

        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        # 尝试Office COM
        if self.preferred == "office_com":
            try:
                self._export_xlsx_via_com(xlsx_path, pdf_path)
                return
            except Exception as com_error:
                if self._should_use_libreoffice_fallback():
                    try:
                        self._export_via_libreoffice(xlsx_path, pdf_path)
                        return
                    except Exception as fallback_error:
                        raise ExportError(
                            "Excel export failed via Office COM, and LibreOffice fallback also failed. "
                            f"COM error: {com_error}; fallback error: {fallback_error}"
                        ) from fallback_error
                else:
                    raise ExportError(f"Excel导出PDF失败: {com_error}") from com_error
        elif self._should_use_libreoffice_fallback() or self.preferred == "libreoffice":
            self._export_via_libreoffice(xlsx_path, pdf_path)
        else:
            raise ExportError("无可用的PDF导出引擎")

    def count_pdf_pages(self, pdf_path: Path) -> int:
        """计算PDF页数"""
        if not pdf_path.exists():
            raise ExportError(f"PDF文件不存在: {pdf_path}")

        # 尝试使用PyPDF2
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(pdf_path))
            return len(reader.pages)
        except ImportError:
            pass

        # 兜底：通过字符串匹配
        try:
            with open(pdf_path, "rb") as f:
                content = f.read()
            count = content.count(b"/Type /Page")
            # 减去可能的/Type /Pages
            count -= content.count(b"/Type /Pages")
            return max(1, count)
        except Exception:
            return 1

    @staticmethod
    def _prepare_word_for_headless_run(word: object) -> None:
        word_app = cast(Any, word)
        word_app.Visible = False
        word_app.DisplayAlerts = 0
        with contextlib.suppress(Exception):
            options = getattr(word_app, "Options", None)
            if options is not None:
                cast(Any, options).SaveNormalPrompt = False

    @staticmethod
    def _mark_word_document_saved(doc: object | None) -> None:
        if doc is None:
            return
        with contextlib.suppress(Exception):
            cast(Any, doc).Saved = True

    @staticmethod
    def _mark_word_normal_template_saved(word: object | None) -> None:
        if word is None:
            return
        with contextlib.suppress(Exception):
            template = getattr(cast(Any, word), "NormalTemplate", None)
            if template is not None:
                cast(Any, template).Saved = True

    @staticmethod
    def _prepare_excel_for_headless_run(excel: object) -> None:
        excel_app = cast(Any, excel)
        excel_app.Visible = False
        excel_app.DisplayAlerts = False
        with contextlib.suppress(Exception):
            excel_app.AskToUpdateLinks = False
        with contextlib.suppress(Exception):
            excel_app.EnableEvents = False
        with contextlib.suppress(Exception):
            excel_app.ScreenUpdating = False
        with contextlib.suppress(Exception):
            excel_app.DisplayStatusBar = False
        with contextlib.suppress(Exception):
            excel_app.UserControl = False
        with contextlib.suppress(Exception):
            excel_app.Interactive = False
        with contextlib.suppress(Exception):
            excel_app.AutomationSecurity = 3

    @staticmethod
    def _clear_windows_zone_identifier(path: Path) -> None:
        ads_path = str(path) + ":Zone.Identifier"
        with contextlib.suppress(OSError, FileNotFoundError):
            os.remove(ads_path)

    @staticmethod
    def _sanitize_excel_label(label: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", label).strip("_")
        return normalized or "workbook"

    @staticmethod
    def _is_call_rejected(exc: Exception) -> bool:
        with contextlib.suppress(Exception):
            if getattr(exc, "hresult", None) == _RPC_CALL_REJECTED:
                return True
        message = str(exc).lower()
        return ("被呼叫方拒绝接收呼叫" in str(exc)) or ("call was rejected by callee" in message)

    @classmethod
    def _retry_excel_com_call(
        cls,
        fn: Callable[[], Any],
        desc: str,
        *,
        retries: int = 10,
    ) -> Any:
        last_exc: Exception | None = None
        for _ in range(retries):
            try:
                return fn()
            except Exception as exc:
                last_exc = exc
                time.sleep(0.8 if cls._is_call_rejected(exc) else 0.3)
        raise RuntimeError(f"Excel COM 调用失败 {desc}: {last_exc}") from last_exc

    @classmethod
    def _prepare_excel_path_for_com(cls, xlsx_path: Path, *, label: str) -> tuple[Path, Path]:
        temp_dir = Path(tempfile.mkdtemp(prefix="fanban_excel_com_"))
        working_copy = temp_dir / f"{cls._sanitize_excel_label(label)}{xlsx_path.suffix.lower()}"
        shutil.copy2(xlsx_path, working_copy)
        cls._clear_windows_zone_identifier(working_copy)
        return working_copy, temp_dir

    @classmethod
    def _open_excel_workbook(cls, excel: object, workbook_path: Path, *, read_only: bool) -> object:
        excel_app = cast(Any, excel)
        workbooks = cls._retry_excel_com_call(
            lambda: excel_app.Workbooks,
            "Excel.Workbooks",
        )
        return cls._retry_excel_com_call(
            lambda: cast(Any, workbooks).Open(str(workbook_path.absolute()), 0, read_only),
            f"Excel.Workbooks.Open({workbook_path.name})",
        )

    def _export_docx_via_com(self, docx_path: Path, pdf_path: Path) -> None:
        """通过Office COM导出Word到PDF"""
        pythoncom = None
        try:
            import pythoncom  # type: ignore[import]
            import win32com.client
        except ImportError as err:
            raise ExportError("pywin32未安装，无法使用Office COM") from err

        word = None
        doc = None
        try:
            pythoncom.CoInitialize()
            word = win32com.client.DispatchEx("Word.Application")
            self._prepare_word_for_headless_run(word)

            doc = word.Documents.Open(str(docx_path.absolute()))
            doc.ExportAsFixedFormat(str(pdf_path.absolute()), 17)  # 17 = PDF
        finally:
            if doc:
                self._mark_word_document_saved(doc)
                with contextlib.suppress(Exception):
                    doc.Close(False)
            doc = None
            if word:
                self._mark_word_normal_template_saved(word)
                with contextlib.suppress(Exception):
                    word.Quit()
            word = None
            gc.collect()
            if pythoncom is not None:
                with contextlib.suppress(Exception):
                    pythoncom.CoUninitialize()

    def _export_xlsx_via_com(self, xlsx_path: Path, pdf_path: Path) -> None:
        """通过Office COM导出Excel到PDF"""
        pythoncom = None
        try:
            import pythoncom  # type: ignore[import]
            import win32com.client
        except ImportError as err:
            raise ExportError("pywin32未安装，无法使用Office COM") from err

        excel = None
        wb = None
        temp_dir = None
        try:
            pythoncom.CoInitialize()
            excel = win32com.client.DispatchEx("Excel.Application")
            self._prepare_excel_for_headless_run(excel)
            working_copy, temp_dir = self._prepare_excel_path_for_com(
                xlsx_path,
                label=pdf_path.stem or xlsx_path.stem,
            )

            wb = self._open_excel_workbook(excel, working_copy, read_only=True)
            self._retry_excel_com_call(
                lambda: cast(Any, wb).ExportAsFixedFormat(0, str(pdf_path.absolute())),
                "Workbook.ExportAsFixedFormat",
            )
        finally:
            if wb:
                with contextlib.suppress(Exception):
                    wb.Close(False)
            wb = None
            if excel:
                with contextlib.suppress(Exception):
                    excel.Quit()
            excel = None
            gc.collect()
            if pythoncom is not None:
                with contextlib.suppress(Exception):
                    pythoncom.CoUninitialize()
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _export_via_libreoffice(self, input_path: Path, pdf_path: Path) -> None:
        """通过LibreOffice导出PDF"""
        cmd = [
            "soffice",
            "--headless",
            "--convert-to", "pdf",
            "--outdir", str(pdf_path.parent),
            str(input_path),
        ]

        try:
            subprocess.run(
                cmd,
                capture_output=True,
                timeout=self.timeout,
                check=True,
            )
        except FileNotFoundError as e:
            raise ExportError("LibreOffice 未安装或 soffice 不在 PATH 中") from e
        except subprocess.TimeoutExpired as e:
            raise ExportError(f"LibreOffice导出超时: {input_path}") from e
        except subprocess.CalledProcessError as e:
            raise ExportError(f"LibreOffice导出失败: {e.stderr}") from e

        # LibreOffice输出文件名可能不同
        expected = pdf_path.parent / f"{input_path.stem}.pdf"
        if expected != pdf_path and expected.exists():
            expected.rename(pdf_path)
