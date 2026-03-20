from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook


def build_catalog_display_title(ctx, spec) -> str:
    parts: list[str] = []

    album_title_cn = str(ctx.params.album_title_cn or "").strip()
    if album_title_cn:
        parts.append(album_title_cn)

    album_code = str(ctx.derived.album_code or "").strip()
    header = spec.get_catalog_bindings().get("header", {})
    title_binding = header.get("album_code_title", {})
    template = title_binding.get("template", "第{album_code}图册图纸(文件)目录")
    if album_code:
        parts.append(str(template).format(album_code=album_code).strip())

    if ctx.is_1818:
        album_title_en = str(ctx.params.album_title_en or "").strip()
        if album_title_en:
            parts.append(album_title_en)

        english_title = _load_1818_catalog_english_line(
            Path(spec.get_template_path("catalog", ctx.params.project_no)),
        )
        if english_title:
            parts.append(english_title)

    return "\n".join(part for part in parts if part)


def _load_1818_catalog_english_line(template_path: Path) -> str:
    workbook = load_workbook(template_path, read_only=False, data_only=False)
    try:
        worksheet = workbook.active
        if worksheet is None:
            return ""
        return _read_merged_value(worksheet, "E5").strip()
    finally:
        workbook.close()


def _read_merged_value(worksheet, cell_ref: str) -> str:
    cell = worksheet[cell_ref]
    if cell.value is not None:
        return str(cell.value)

    for merged_range in worksheet.merged_cells.ranges:
        if cell_ref in merged_range:
            anchor = worksheet[merged_range.start_cell.coordinate]
            return str(anchor.value or "")
    return ""
