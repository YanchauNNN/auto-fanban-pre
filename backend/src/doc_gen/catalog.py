"""
目录生成器 - Excel文档生成

职责：
1. 打开目录模板
2. 写入表头和明细行
3. 计算页数（优先Excel分页信息，兜底PDF计页）
4. 回填页数后导出PDF

依赖：
- openpyxl: Excel操作
- 参数规范.yaml: catalog_bindings配置

测试要点：
- test_generate_catalog_common: 通用目录生成
- test_generate_catalog_1818: 1818目录（中英文标题同格）
- test_catalog_row_order: 行顺序（封面→目录→图纸）
- test_catalog_page_count: 页数计算
- test_catalog_upgrade_note: 升版标记
"""

from __future__ import annotations

import contextlib
import gc
import math
import os
from copy import copy
from pathlib import Path
from typing import TYPE_CHECKING

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

from ..config import load_spec
from ..interfaces import GenerationError, ICatalogGenerator
from .naming import make_document_output_name
from .pdf_engine import PDFExporter

if TYPE_CHECKING:
    from ..models import DocContext


class CatalogGenerator(ICatalogGenerator):
    """目录生成器实现"""

    BODY_ROW_HEIGHT = 36
    THREE_LINE_HEIGHT = 50
    FOUR_LINE_HEIGHT = 60
    EXTRA_LINE_STEP = 12

    def __init__(
        self,
        spec_path: str | None = None,
        pdf_exporter: PDFExporter | None = None,
    ):
        self.spec = load_spec(spec_path) if spec_path else load_spec()
        self.pdf_exporter = pdf_exporter or PDFExporter()

    def generate(self, ctx: DocContext, output_dir: Path) -> tuple[Path, Path, int]:
        """生成目录文档"""
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1. 选择模板
        template_path = self._get_template_path(ctx)
        if not Path(template_path).exists():
            raise GenerationError(f"目录模板不存在: {template_path}")

        # 2. 获取落点配置
        bindings = self.spec.get_catalog_bindings()

        # 3. 写入Excel
        output_stem = self._build_output_stem(ctx)
        output_xlsx = output_dir / f"{output_stem}.xlsx"
        self._write_catalog(template_path, output_xlsx, bindings, ctx)

        # 4. 计算页数（优先Excel分页信息）
        page_count = self._count_pages(output_xlsx)

        # 5. 回填目录行页数
        self._backfill_page_count(output_xlsx, page_count, bindings)

        # 6. 导出PDF
        output_pdf = output_dir / f"{output_stem}.pdf"
        self.pdf_exporter.export_xlsx_to_pdf(output_xlsx, output_pdf)

        return output_xlsx, output_pdf, page_count

    def _build_output_stem(self, ctx: DocContext) -> str:
        return make_document_output_name(
            external_code=ctx.derived.catalog_external_code,
            revision=ctx.derived.catalog_revision,
            status=ctx.params.doc_status,
            internal_code=ctx.derived.catalog_internal_code,
            fallback_name="目录",
        )

    def _get_template_path(self, ctx: DocContext) -> str:
        """获取模板路径"""
        return self.spec.get_template_path("catalog", ctx.params.project_no)

    def _write_catalog(
        self,
        template_path: str,
        output_path: Path,
        bindings: dict,
        ctx: DocContext,
    ) -> None:
        """写入目录Excel"""
        wb = load_workbook(template_path)
        ws = wb.active

        # 写入表头
        self._write_header(ws, bindings, ctx)

        # 写入明细行
        start_row = bindings.get("detail", {}).get("start_row", 9)
        current_row = start_row

        # 行顺序：封面 → 目录 → 图纸（按internal_code尾号升序）
        rows = self._build_detail_rows(ctx)

        for row_data in rows:
            self._write_detail_row(ws, current_row, row_data, bindings, ctx)
            current_row += 1

        # 动态设置打印区域，保证目录计页与实际行数一致
        last_row = max(start_row, current_row - 1)
        ws.print_area = f"$A$1:$I${last_row}"
        self._apply_detail_layout(ws, start_row, last_row)

        # 保存
        wb.save(output_path)
        self._refine_detail_layout_via_com(output_path, start_row, last_row)

    def _write_header(self, ws, bindings: dict, ctx: DocContext) -> None:
        """写入表头"""
        header = bindings.get("header", {})
        derived = ctx.derived
        params = ctx.params

        if ctx.is_1818:
            self._normalize_1818_title_merges(ws)

        # engineering_no → C1
        if "engineering_no" in header:
            cell = self._resolve_writable_cell(ws, header["engineering_no"].get("cell", "C1"))
            ws[cell] = params.engineering_no

        if "album_title_cn" in header and params.album_title_cn:
            cell = self._resolve_writable_cell(ws, header["album_title_cn"].get("cell", "D1:E1"))
            ws[cell] = params.album_title_cn

        if (
            ctx.is_1818
            and "album_title_en" in header
            and params.album_title_en
        ):
            cell = self._resolve_writable_cell(ws, header["album_title_en"].get("cell", "D2:E2"))
            ws[cell] = params.album_title_en

        # catalog_internal_code → H1
        if "catalog_internal_code" in header:
            cell = self._resolve_writable_cell(ws, header["catalog_internal_code"].get("cell", "H1"))
            ws[cell] = derived.catalog_internal_code

        # catalog_external_code → H3
        if "catalog_external_code" in header:
            cell = self._resolve_writable_cell(ws, header["catalog_external_code"].get("cell", "H3"))
            ws[cell] = derived.catalog_external_code

        # subitem_no → C5
        if "subitem_no" in header:
            cell = self._resolve_writable_cell(ws, header["subitem_no"].get("cell", "C5"))
            ws[cell] = params.subitem_no

        # catalog_revision → H5
        if "catalog_revision" in header:
            cell = self._resolve_writable_cell(ws, header["catalog_revision"].get("cell", "H5"))
            ws[cell] = derived.catalog_revision

        if "album_code_title" in header and derived.album_code:
            title_binding = header["album_code_title"]
            cell_ref = (
                title_binding.get("cell_1818")
                if ctx.is_1818 and title_binding.get("cell_1818")
                else title_binding.get("cell", "D3:E3")
            )
            cell = self._resolve_writable_cell(ws, cell_ref)
            template = header["album_code_title"].get(
                "template",
                "第{album_code}图册图纸(文件)目录",
            )
            ws[cell] = template.format(album_code=derived.album_code)

    def _resolve_writable_cell(self, ws, cell_ref: str) -> str:
        anchor = cell_ref.split(":")[0]
        if not isinstance(ws[anchor], MergedCell):
            return anchor
        for merged_range in ws.merged_cells.ranges:
            if anchor in merged_range:
                return merged_range.start_cell.coordinate
        return anchor

    def _normalize_1818_title_merges(self, ws) -> None:
        merged_ranges = {str(rng) for rng in ws.merged_cells.ranges}
        if "D2:E3" not in merged_ranges:
            return

        source = ws["D2"]
        source_style = copy(source._style)
        source_alignment = copy(source.alignment)
        source_font = copy(source.font)
        source_fill = copy(source.fill)
        source_border = copy(source.border)
        source_number_format = source.number_format
        source_protection = copy(source.protection)

        ws.unmerge_cells("D2:E3")
        ws.merge_cells("D2:E2")
        ws.merge_cells("D3:E3")

        for cell_ref in ("D2", "E2", "D3", "E3"):
            cell = ws[cell_ref]
            cell._style = copy(source_style)
            cell.alignment = copy(source_alignment)
            cell.font = copy(source_font)
            cell.fill = copy(source_fill)
            cell.border = copy(source_border)
            cell.number_format = source_number_format
            cell.protection = copy(source_protection)

    def _build_detail_rows(self, ctx: DocContext) -> list[dict]:
        """构建明细行数据"""
        rows = []
        derived = ctx.derived
        params = ctx.params

        # 1. 封面行
        rows.append({
            "type": "cover",
            "internal_code": derived.cover_internal_code,
            "external_code": derived.cover_external_code,
            "title_cn": derived.cover_title_cn,
            "title_en": derived.cover_title_en,
            "revision": params.cover_revision,
            "status": params.doc_status,
            "page_total": 1,
            "upgrade_note": "",
        })

        # 2. 目录行
        rows.append({
            "type": "catalog",
            "internal_code": derived.catalog_internal_code,
            "external_code": derived.catalog_external_code,
            "title_cn": derived.catalog_title_cn,
            "title_en": derived.catalog_title_en,
            "revision": derived.catalog_revision,
            "status": params.doc_status,
            "page_total": 0,  # 占位，后续回填
            "upgrade_note": "",
        })

        # 3. 图纸行（按internal_code尾号升序）
        for frame in ctx.get_sorted_document_frames():
            tb = frame.titleblock
            seq_no = tb.get_seq_no()

            # 判断是否需要升版标记
            upgrade_note = ""
            if (
                params.upgrade_start_seq is not None
                and params.upgrade_end_seq is not None
                and seq_no is not None
                and params.upgrade_start_seq <= seq_no <= params.upgrade_end_seq
            ):
                upgrade_note = params.upgrade_note_text

            rows.append({
                "type": "drawing",
                "internal_code": tb.internal_code,
                "external_code": tb.external_code,
                "title_cn": tb.title_cn,
                "title_en": tb.title_en,
                "revision": tb.revision,
                "status": tb.status,
                "page_total": tb.page_total or 1,
                "upgrade_note": upgrade_note,
            })

        return rows

    def _write_detail_row(
        self,
        ws,
        row: int,
        data: dict,
        bindings: dict,
        ctx: DocContext,
    ) -> None:
        """写入单行明细"""
        columns = bindings.get("detail", {}).get("columns", {})

        # A: 序号
        ws[f"A{row}"] = row - bindings.get("detail", {}).get("start_row", 9) + 1

        # B: 图纸编号（internal_code）
        if "B" in columns:
            ws[f"B{row}"] = data.get("internal_code", "")

        # D: 文件编码（external_code）
        if "D" in columns:
            ws[f"D{row}"] = data.get("external_code", "")

        # E: 名称（1818需要中英文换行）
        if "E" in columns:
            title = data.get("title_cn", "")
            if ctx.is_1818 and data.get("title_en"):
                title = f"{title}\n{data['title_en']}"
            ws[f"E{row}"] = title
            cell = ws[f"E{row}"]
            alignment = copy(cell.alignment)
            alignment.horizontal = "center"
            alignment.vertical = "center"
            alignment.wrapText = True
            cell.alignment = alignment

        # F: 版次
        if "F" in columns:
            ws[f"F{row}"] = data.get("revision", "")

        # G: 状态
        if "G" in columns:
            ws[f"G{row}"] = data.get("status", "")

        # H: 页数
        if "H" in columns:
            ws[f"H{row}"] = data.get("page_total", 1)

        # I: 附注（升版标记）
        if "I" in columns:
            ws[f"I{row}"] = data.get("upgrade_note", "")

    def _apply_detail_layout(self, ws, start_row: int, last_row: int) -> None:
        column_width = ws.column_dimensions["E"].width or 30
        for row in range(start_row, last_row + 1):
            text = str(ws[f"E{row}"].value or "")
            line_count = self._estimate_wrapped_line_count(text, column_width)
            ws.row_dimensions[row].height = self._bucket_row_height_for_line_count(line_count)

    def _refine_detail_layout_via_com(
        self,
        xlsx_path: Path,
        start_row: int,
        last_row: int,
    ) -> None:
        if not self._should_use_excel_com():
            return

        pythoncom = None
        try:
            import pythoncom  # type: ignore[import]
            import win32com.client
        except ImportError:
            return

        excel = None
        workbook = None
        worksheet = None
        row_range = None
        try:
            pythoncom.CoInitialize()
            excel = win32com.client.DispatchEx("Excel.Application")
            excel.Visible = False
            excel.DisplayAlerts = False
            workbook = excel.Workbooks.Open(str(xlsx_path.absolute()))
            worksheet = workbook.Worksheets(1)
            row_range = worksheet.Rows(f"{start_row}:{last_row}")
            row_range.AutoFit()
            row_range = None

            for row in range(start_row, last_row + 1):
                auto_height = float(worksheet.Rows(row).RowHeight or 0)
                bucket_height = self._bucket_row_height_from_measured_height(auto_height)
                if bucket_height:
                    worksheet.Rows(row).RowHeight = bucket_height

            workbook.Save()
        except Exception:
            return
        finally:
            worksheet = None
            row_range = None
            if workbook:
                with contextlib.suppress(Exception):
                    workbook.Close(False)
            workbook = None
            if excel:
                with contextlib.suppress(Exception):
                    excel.Quit()
            excel = None
            gc.collect()
            if pythoncom is not None:
                with contextlib.suppress(Exception):
                    pythoncom.CoUninitialize()

    def _estimate_wrapped_line_count(self, text: str, column_width: float) -> int:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
        if not normalized:
            return 1

        effective_width = max(8.0, float(column_width) * 0.9)
        total_lines = 0
        for raw_line in normalized.split("\n"):
            display_width = sum(self._char_display_width(ch) for ch in raw_line)
            wrapped_lines = max(1, math.ceil(display_width / effective_width))
            total_lines += wrapped_lines
        return max(1, total_lines)

    def _char_display_width(self, char: str) -> float:
        if not char:
            return 0
        if char.isspace():
            return 0.35
        if ord(char) > 127:
            return 1.0
        if char.isalnum():
            return 0.55
        return 0.65

    def _bucket_row_height_for_line_count(self, line_count: int) -> int:
        if line_count <= 2:
            return self.BODY_ROW_HEIGHT
        if line_count == 3:
            return self.THREE_LINE_HEIGHT
        if line_count == 4:
            return self.FOUR_LINE_HEIGHT
        return self.FOUR_LINE_HEIGHT + (line_count - 4) * self.EXTRA_LINE_STEP

    def _bucket_row_height_from_measured_height(self, measured_height: float) -> int:
        if measured_height <= 0:
            return self.BODY_ROW_HEIGHT
        if measured_height <= self.BODY_ROW_HEIGHT:
            return self.BODY_ROW_HEIGHT
        if measured_height <= self.THREE_LINE_HEIGHT:
            return self.THREE_LINE_HEIGHT
        if measured_height <= self.FOUR_LINE_HEIGHT:
            return self.FOUR_LINE_HEIGHT
        extra_steps = math.ceil((measured_height - self.FOUR_LINE_HEIGHT) / self.EXTRA_LINE_STEP)
        return self.FOUR_LINE_HEIGHT + max(1, extra_steps) * self.EXTRA_LINE_STEP

    def _count_pages(self, xlsx_path: Path) -> int:
        """计算目录页数"""
        # 优先尝试 Excel COM 的分页信息
        if self._should_use_excel_com():
            try:
                return self._count_pages_via_com(xlsx_path)
            except Exception:
                pass

        # 优先尝试Excel分页信息
        try:
            wb = load_workbook(xlsx_path)
            ws = wb.active

            # 尝试通过分页符计算
            h_breaks = len(ws.page_breaks.horizontalBreaks) if hasattr(ws, 'page_breaks') else 0
            if h_breaks > 0:
                return h_breaks + 1
        except Exception:
            pass

        # 兜底：导出PDF计页
        try:
            temp_pdf = xlsx_path.with_suffix(".temp.pdf")
            self.pdf_exporter.export_xlsx_to_pdf(xlsx_path, temp_pdf)
            count = self.pdf_exporter.count_pdf_pages(temp_pdf)
            temp_pdf.unlink(missing_ok=True)
            return count
        except Exception:
            return 1  # 默认1页

    def _count_pages_via_com(self, xlsx_path: Path) -> int:
        pythoncom = None
        try:
            import pythoncom  # type: ignore[import]
            import win32com.client
        except ImportError as exc:
            raise RuntimeError("pywin32 不可用") from exc

        excel = None
        wb = None
        ws = None
        try:
            pythoncom.CoInitialize()
            excel = win32com.client.DispatchEx("Excel.Application")
            excel.Visible = False
            excel.DisplayAlerts = False
            wb = excel.Workbooks.Open(str(xlsx_path.absolute()))
            ws = wb.Worksheets(1)
            page_count = int(ws.HPageBreaks.Count) + 1
            return max(1, page_count)
        finally:
            ws = None
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

    @staticmethod
    def _should_use_excel_com() -> bool:
        return "PYTEST_CURRENT_TEST" not in os.environ

    def _backfill_page_count(
        self,
        xlsx_path: Path,
        page_count: int,
        bindings: dict,
    ) -> None:
        """回填目录行页数"""
        wb = load_workbook(xlsx_path)
        ws = wb.active

        # 目录行是第2行明细（封面后）
        start_row = bindings.get("detail", {}).get("start_row", 9)
        catalog_row = start_row + 1

        ws[f"H{catalog_row}"] = page_count

        wb.save(xlsx_path)
