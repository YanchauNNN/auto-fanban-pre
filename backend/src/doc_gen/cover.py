"""
封面生成器 - Word文档生成

职责：
1. 打开封面模板（含内嵌Excel OLE）
2. 写入字段到指定单元格
3. 处理标题分割（中英文）
4. 导出PDF

依赖：
- python-docx: Word操作
- 参数规范.yaml: cover_bindings配置

测试要点：
- test_generate_cover_common: 通用封面生成
- test_generate_cover_1818: 1818封面生成（落点不同）
- test_title_split_cn: 中文标题分割
- test_title_split_en: 英文标题分割
- test_cover_revision_append: 版次追加模式
- test_external_code_19chars: 19位外部编码逐格写入
"""

from __future__ import annotations

import contextlib
import re
import shutil
import time
import zipfile
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter

from ..config import load_spec
from ..config.spec_loader import CoverBinding
from ..interfaces import GenerationError, ICoverGenerator
from .naming import make_document_output_name
from .pdf_engine import PDFExporter

if TYPE_CHECKING:
    from ..models import DocContext

_CELL_RE = re.compile(r"^([A-Za-z]+)(\d+)$")


class CoverGenerator(ICoverGenerator):
    """封面生成器实现"""

    def __init__(
        self,
        spec_path: str | None = None,
        pdf_exporter: PDFExporter | None = None,
    ):
        self.spec = load_spec(spec_path) if spec_path else load_spec()
        self.pdf_exporter = pdf_exporter or PDFExporter()

    def generate(self, ctx: DocContext, output_dir: Path) -> tuple[Path, Path]:
        """生成封面文档"""
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1. 选择模板
        template_path = self._get_template_path(ctx)
        if not Path(template_path).exists():
            raise GenerationError(f"封面模板不存在: {template_path}")

        # 2. 获取落点配置
        bindings = self.spec.get_cover_bindings(ctx.params.project_no)

        # 3. 准备写入数据
        data = self._prepare_data(ctx)

        # 4. 写入Word文档
        output_stem = self._build_output_stem(ctx)
        output_docx = output_dir / f"{output_stem}.docx"
        self._write_cover(template_path, output_docx, bindings, data, ctx)

        # 5. 导出PDF
        output_pdf = output_dir / f"{output_stem}.pdf"
        self.pdf_exporter.export_docx_to_pdf(output_docx, output_pdf)

        return output_docx, output_pdf

    def _build_output_stem(self, ctx: DocContext) -> str:
        return make_document_output_name(
            external_code=ctx.derived.cover_external_code,
            revision=ctx.params.cover_revision,
            status=ctx.params.doc_status,
            internal_code=ctx.derived.cover_internal_code,
            fallback_name="封面",
        )

    def _get_template_path(self, ctx: DocContext) -> str:
        """获取模板路径"""
        variant = ""
        if ctx.params.cover_variant == "压力容器":
            variant = "压力容器版"
        elif ctx.params.cover_variant == "核安全设备":
            variant = "核安全设备版"
        return self.spec.get_template_path(
            "cover",
            ctx.params.project_no,
            variant
        )

    def _prepare_data(self, ctx: DocContext) -> dict:
        """准备写入数据"""
        params = ctx.params
        derived = ctx.derived

        return {
            "engineering_no": params.engineering_no,
            "subitem_no": params.subitem_no,
            "subitem_name": params.subitem_name,
            "subitem_name_en": params.subitem_name_en,  # 仅1818
            "design_phase": derived.design_phase,
            "design_phase_en": derived.design_phase_en,  # 仅1818
            "discipline": params.discipline,
            "discipline_en": derived.discipline_en,  # 仅1818
            "album_title_cn": params.album_title_cn,
            "album_title_en": params.album_title_en,  # 仅1818
            "album_code": derived.album_code,
            "album_internal_code": derived.album_internal_code,
            "cover_revision": params.cover_revision,
            "doc_status": params.doc_status,
            "cover_external_code": derived.cover_external_code,
        }

    def _write_cover(
        self,
        template_path: str,
        output_path: Path,
        bindings: dict,
        data: dict,
        ctx: DocContext,
    ) -> None:
        """写入封面文档"""
        shutil.copy(template_path, output_path)

        com_error: Exception | None = None
        try:
            self._write_cover_via_com(
                output_path=output_path,
                bindings=bindings,
                data=data,
            )
            return
        except Exception as exc:
            com_error = exc

        embedded_xlsx = self._find_embedded_xlsx(output_path)
        if embedded_xlsx:
            try:
                self._write_cover_via_embedded_xlsx(
                    output_path=output_path,
                    embedded_xlsx_path=embedded_xlsx,
                    bindings=bindings,
                    data=data,
                )
                return
            except Exception as embedded_exc:
                raise GenerationError(
                    f"封面写入失败: COM={com_error}; embedded_xlsx={embedded_exc}"
                ) from embedded_exc

        raise GenerationError(f"封面写入失败: {com_error}") from com_error

    def _write_cover_via_embedded_xlsx(
        self,
        *,
        output_path: Path,
        embedded_xlsx_path: str,
        bindings: dict[str, CoverBinding],
        data: dict[str, Any],
    ) -> None:
        with zipfile.ZipFile(output_path, "r") as zf:
            package = {name: zf.read(name) for name in zf.namelist()}

        workbook_bytes = package.get(embedded_xlsx_path)
        if workbook_bytes is None:
            raise GenerationError(f"嵌入工作簿不存在: {embedded_xlsx_path}")

        wb = load_workbook(BytesIO(workbook_bytes))
        ws = wb["封面"] if "封面" in wb.sheetnames else wb.active

        def read_cell(cell: str) -> Any:
            return ws[cell].value

        def write_cell(cell: str, value: Any) -> None:
            ws[cell] = value

        self._apply_bindings(bindings, data, read_cell, write_cell)

        buf = BytesIO()
        wb.save(buf)
        package[embedded_xlsx_path] = buf.getvalue()

        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, payload in package.items():
                zf.writestr(name, payload)

    def _write_cover_via_com(
        self,
        *,
        output_path: Path,
        bindings: dict[str, CoverBinding],
        data: dict[str, Any],
    ) -> None:
        pythoncom = None
        try:
            import pythoncom  # type: ignore[import]
            import win32com.client
        except ImportError as exc:
            raise GenerationError("缺少 pywin32，无法写入 OLE 封面模板") from exc

        word = None
        doc = None
        try:
            pythoncom.CoInitialize()
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0
            doc = word.Documents.Open(str(output_path.absolute()))
            time.sleep(1.0)
            ws = self._get_embedded_excel_sheet(doc)
            if ws is None:
                raise GenerationError("未找到封面中的嵌入 Excel 对象")

            def read_cell(cell: str) -> Any:
                return self._com_call_with_retry(
                    lambda: ws.Range(cell).Value,
                    f"Range({cell}).Value",
                )

            def write_cell(cell: str, value: Any) -> None:
                self._com_call_with_retry(
                    lambda: setattr(ws.Range(cell), "Value", value),
                    f"Range({cell}).Value={value}",
                )

            self._apply_bindings(bindings, data, read_cell, write_cell)
            self._com_call_with_retry(doc.Save, "Document.Save")
        finally:
            if doc is not None:
                self._close_com_object(lambda: doc.Close(False), "Document.Close")
            if word is not None:
                self._close_com_object(word.Quit, "Word.Quit")
            if pythoncom is not None:
                with contextlib.suppress(Exception):
                    pythoncom.CoUninitialize()

    def _get_embedded_excel_sheet(self, doc: Any) -> Any | None:
        for collection_name in ("InlineShapes", "Shapes"):
            collection = getattr(doc, collection_name, None)
            if collection is None:
                continue
            try:
                count = int(
                    self._com_call_with_retry(
                        lambda: collection.Count,
                        f"{collection_name}.Count",
                    )
                )
            except Exception:
                continue

            for idx in range(1, count + 1):
                try:
                    shape = self._com_call_with_retry(
                        lambda: collection.Item(idx),
                        f"{collection_name}.Item({idx})",
                    )
                    ole_format = self._com_call_with_retry(
                        lambda: shape.OLEFormat,
                        f"{collection_name}.Item({idx}).OLEFormat",
                    )
                    self._com_call_with_retry(
                        ole_format.Activate,
                        f"{collection_name}.Item({idx}).OLEFormat.Activate",
                    )
                    time.sleep(0.8)
                    ole_obj = self._com_call_with_retry(
                        lambda: ole_format.Object,
                        f"{collection_name}.Item({idx}).OLEFormat.Object",
                    )
                except Exception:
                    continue

                sheet = self._to_excel_sheet(ole_obj)
                if sheet is not None:
                    return sheet
        return None

    def _to_excel_sheet(self, ole_obj: Any) -> Any | None:
        if ole_obj is None:
            return None

        try:
            parent = self._com_call_with_retry(
                lambda: getattr(ole_obj, "Parent", None),
                "OLEObject.Parent",
            )
            if parent is not None and hasattr(parent, "Worksheets"):
                return self._com_call_with_retry(
                    lambda: parent.Worksheets(1),
                    "OLEObject.Parent.Worksheets(1)",
                )
        except Exception:
            pass

        try:
            if hasattr(ole_obj, "Worksheets"):
                return self._com_call_with_retry(
                    lambda: ole_obj.Worksheets(1),
                    "OLEObject.Worksheets(1)",
                )
        except Exception:
            pass

        if hasattr(ole_obj, "Range"):
            return ole_obj

        return None

    def _find_embedded_xlsx(self, docx_path: Path) -> str | None:
        with zipfile.ZipFile(docx_path, "r") as zf:
            for name in zf.namelist():
                if name.startswith("word/embeddings/") and name.lower().endswith(".xlsx"):
                    return name
        return None

    def _apply_bindings(
        self,
        bindings: dict[str, CoverBinding],
        data: dict[str, Any],
        read_cell: Callable[[str], Any],
        write_cell: Callable[[str, Any], None],
    ) -> None:
        for key, binding in bindings.items():
            if key == "册次":
                continue

            cell_ref = binding.cell
            value = data.get(key)

            if key == "cover_external_code":
                self._write_external_code_chars(
                    cell_ref,
                    value if isinstance(value, str) else "",
                    write_cell,
                )
                continue

            if binding.split_rule and "+" in cell_ref:
                left_cell, right_cell = self._split_two_cells_ref(cell_ref)
                left, right = self._split_text_by_rule(str(value or ""), binding.split_rule)
                write_cell(left_cell, left)
                write_cell(right_cell, right)
                continue

            target_cell = self._first_cell(cell_ref)
            if binding.write_mode == "append_after_label":
                if self._is_empty(value):
                    continue
                current = read_cell(target_cell)
                merged = self._append_after_label(
                    current=str(current or ""),
                    label=binding.label or "",
                    value=str(value),
                )
                write_cell(target_cell, merged)
                continue

            if not self._is_empty(value):
                write_cell(target_cell, value)

    @staticmethod
    def _is_empty(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip() == ""
        return False

    def _split_text_by_rule(self, text: str, split_rule: str) -> tuple[str, str]:
        if split_rule.startswith("cn_split"):
            return self._split_cn_two_cells(text)
        if split_rule.startswith("en_split"):
            return self._split_en_two_cells(text)
        return text, ""

    def _split_cn_two_cells(self, text: str) -> tuple[str, str]:
        s = text.strip()
        if not s:
            return "", ""
        mid = len(s) // 2
        candidates = [idx for idx in range(1, len(s)) if self._is_cjk(s[idx])]
        if not candidates:
            return s, ""
        idx = min(candidates, key=lambda n: abs(n - mid))
        return s[:idx].rstrip(), s[idx:].lstrip()

    def _split_en_two_cells(self, text: str) -> tuple[str, str]:
        s = re.sub(r"\s+", " ", text.strip())
        if not s:
            return "", ""
        mid = len(s) // 2
        candidates = [m.start() for m in re.finditer(r"\s+", s)]
        if not candidates:
            return s, ""

        def score(i: int) -> tuple[int, int]:
            right = s[i:].lstrip()
            right_ok = 0 if (right and right[0].isalpha()) else 1
            return right_ok, abs(i - mid)

        idx = min(candidates, key=score)
        return s[:idx].rstrip(), s[idx:].lstrip()

    @staticmethod
    def _is_cjk(ch: str) -> bool:
        if not ch:
            return False
        code = ord(ch)
        return 0x4E00 <= code <= 0x9FFF

    def _write_external_code_chars(
        self,
        range_ref: str,
        code: str,
        write_cell: Callable[[str, Any], None],
    ) -> None:
        start_ref, end_ref = self._split_range_ref(range_ref)
        start_col, start_row = self._parse_cell_ref(start_ref)
        end_col, end_row = self._parse_cell_ref(end_ref)
        if start_row != end_row:
            raise GenerationError(f"外部编码落点必须是单行范围: {range_ref}")

        start_idx = column_index_from_string(start_col)
        end_idx = column_index_from_string(end_col)
        if end_idx < start_idx:
            start_idx, end_idx = end_idx, start_idx

        chars = list((code or "")[:19].ljust(19))
        for i, col_idx in enumerate(range(start_idx, end_idx + 1)):
            char = chars[i] if i < len(chars) else ""
            write_cell(f"{get_column_letter(col_idx)}{start_row}", char)

    def _append_after_label(self, current: str, label: str, value: str) -> str:
        if not current:
            return f"{label}{value}" if label else value
        if label and label in current:
            prefix, _, _ = current.partition(label)
            return f"{prefix}{label}{value}"
        if current.endswith(value):
            return current
        return f"{current}{value}"

    def _first_cell(self, cell_ref: str) -> str:
        if "+" in cell_ref:
            return cell_ref.split("+", 1)[0].strip()
        if ":" in cell_ref:
            return cell_ref.split(":", 1)[0].strip()
        return cell_ref.strip()

    def _split_two_cells_ref(self, cell_ref: str) -> tuple[str, str]:
        left, right = cell_ref.split("+", 1)
        return left.strip(), right.strip()

    def _split_range_ref(self, ref: str) -> tuple[str, str]:
        if ":" not in ref:
            return ref.strip(), ref.strip()
        left, right = ref.split(":", 1)
        return left.strip(), right.strip()

    def _parse_cell_ref(self, ref: str) -> tuple[str, int]:
        m = _CELL_RE.match(ref)
        if m is None:
            raise GenerationError(f"非法单元格引用: {ref}")
        return m.group(1).upper(), int(m.group(2))

    def _com_call_with_retry(
        self,
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
                time.sleep(0.8 if self._is_call_rejected(exc) else 0.3)
        raise RuntimeError(f"COM 调用失败 {desc}: {last_exc}") from last_exc

    def _close_com_object(self, fn: Callable[[], Any], desc: str) -> None:
        try:
            self._com_call_with_retry(fn, desc, retries=6)
        except Exception:
            pass

    @staticmethod
    def _is_call_rejected(exc: Exception) -> bool:
        if getattr(exc, "hresult", None) == -2147418111:
            return True
        msg = str(exc).lower()
        return "call was rejected by callee" in msg or "拒绝接收呼叫" in msg
