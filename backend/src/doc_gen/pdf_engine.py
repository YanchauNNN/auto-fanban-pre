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
import subprocess
from pathlib import Path

from ..config import get_config
from ..interfaces import ExportError, IPDFExporter


class PDFExporter(IPDFExporter):
    """PDF导出器实现"""

    def __init__(self, preferred_engine: str | None = None):
        config = get_config()
        self.preferred = preferred_engine or config.pdf_engine.preferred
        self.fallback = config.pdf_engine.fallback
        self.timeout = config.timeouts.pdf_export_sec

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
                if self.fallback:
                    pass  # 降级到fallback
                else:
                    raise ExportError(f"Word导出PDF失败: {e}") from e

        # 尝试LibreOffice
        if self.fallback == "libreoffice" or self.preferred == "libreoffice":
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
            except Exception as e:
                if self.fallback:
                    pass
                else:
                    raise ExportError(f"Excel导出PDF失败: {e}") from e

        # 尝试LibreOffice
        if self.fallback == "libreoffice" or self.preferred == "libreoffice":
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

    def _export_docx_via_com(self, docx_path: Path, pdf_path: Path) -> None:
        """通过Office COM导出Word到PDF"""
        pythoncom = None
        try:
            import pythoncom  # type: ignore[import]
            import win32com.client
        except ImportError:
            raise ExportError("pywin32未安装，无法使用Office COM")

        word = None
        doc = None
        try:
            pythoncom.CoInitialize()
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0

            doc = word.Documents.Open(str(docx_path.absolute()))
            doc.ExportAsFixedFormat(str(pdf_path.absolute()), 17)  # 17 = PDF
        finally:
            if doc:
                with contextlib.suppress(Exception):
                    doc.Close(False)
            doc = None
            if word:
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
        except ImportError:
            raise ExportError("pywin32未安装，无法使用Office COM")

        excel = None
        wb = None
        try:
            pythoncom.CoInitialize()
            excel = win32com.client.DispatchEx("Excel.Application")
            excel.Visible = False
            excel.DisplayAlerts = False

            wb = excel.Workbooks.Open(str(xlsx_path.absolute()))
            wb.ExportAsFixedFormat(0, str(pdf_path.absolute()))  # 0 = PDF
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
