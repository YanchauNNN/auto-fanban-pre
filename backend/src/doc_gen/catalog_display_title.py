from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook


def build_catalog_display_title(ctx, spec) -> str:
    cn_parts, en_parts = _build_catalog_title_parts(ctx, spec)
    return "\n".join(part for part in [*cn_parts, *en_parts] if part)


def build_catalog_single_line_titles(ctx, spec) -> tuple[str, str]:
    cn_parts, en_parts = _build_catalog_title_parts(ctx, spec)
    return ("".join(cn_parts), "".join(en_parts))


def flatten_title_text(value: str | None) -> str:
    if not value:
        return ""
    return "".join(part.strip() for part in str(value).splitlines() if part.strip())


def _build_catalog_title_parts(ctx, spec) -> tuple[list[str], list[str]]:
    cn_parts: list[str] = []
    en_parts: list[str] = []

    album_title_cn = str(ctx.params.album_title_cn or "").strip()
    if album_title_cn:
        cn_parts.append(album_title_cn)

    album_code = str(ctx.derived.album_code or "").strip()
    header = spec.get_catalog_bindings().get("header", {})
    title_binding = header.get("album_code_title", {})
    template = title_binding.get("template", "?{album_code}????(??)??")
    if album_code:
        cn_parts.append(str(template).format(album_code=album_code).strip())

    if ctx.is_1818:
        album_title_en = str(ctx.params.album_title_en or "").strip()
        if album_title_en:
            en_parts.append(album_title_en)

        english_title = _load_1818_catalog_english_line(
            Path(spec.get_template_path("catalog", ctx.params.project_no)),
        )
        if english_title:
            en_parts.append(english_title)

    return cn_parts, en_parts


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
