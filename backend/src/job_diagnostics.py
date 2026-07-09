from __future__ import annotations

import ast
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any


Diagnostic = dict[str, Any]

_PREFIXED_FLAG_RE = re.compile(r"^\[(?P<label>.+?)\]\s*(?P<reason>.+)$")
_INTERNAL_IN_LABEL_RE = re.compile(r"\((?P<internal>[^()]+)\)\s*$")
_DUPLICATE_RE = re.compile(
    r"检测到重复编码:\s*internal=(?P<internal>\[[^\]]*\]),\s*external=(?P<external>\[[^\]]*\])"
)

_CAD_OUTPUT_KEYWORDS = (
    "DXF执行失败",
    "PDF缺失",
    "DWG缺失",
    "导出失败",
    "PLOT_FAILED",
    "PLOT_WINDOW_FAILED",
    "PLOT_RESULT_MISSING",
    "PLOT_WINDOW_RESULT_MISSING",
    "WBLOCK_FAILED",
)
_OFFICE_EXPORT_KEYWORDS = (
    "封面PDF导出失败",
    "目录PDF导出失败",
    "Excel导出PDF失败",
    "Word导出PDF失败",
    "无法创建 Excel.Application",
    "Excel COM",
    "Word COM",
)
_PARAM_KEYWORDS = (
    "文档参数缺失",
    "文档参数格式错误",
    "required_for_",
    "unsupported_",
    "invalid_",
    "param_errors",
)


def build_job_diagnostics(
    *,
    flags: Sequence[str],
    errors: Sequence[str],
    progress_details: Mapping[str, Any] | None = None,
    font_preflight_summary: Mapping[str, Any] | None = None,
) -> list[Diagnostic]:
    """Convert low-level task flags/errors into user-facing diagnostic groups."""

    normalized_flags = [str(item) for item in flags if str(item or "").strip()]
    normalized_errors = [str(item) for item in errors if str(item or "").strip()]
    parsed_flags = [_parse_prefixed_flag(flag) for flag in normalized_flags]
    used: set[str] = set()
    diagnostics: list[Diagnostic] = []

    duplicate = _build_duplicate_code_diagnostic(normalized_flags, parsed_flags, used)
    if duplicate:
        diagnostics.append(duplicate)

    output = _build_cad_output_diagnostic(parsed_flags, normalized_errors, progress_details or {}, used)
    if output:
        diagnostics.append(output)

    paper_size = _build_paper_size_diagnostic(parsed_flags, used)
    if paper_size:
        diagnostics.append(paper_size)

    font = _build_font_diagnostic(
        normalized_flags,
        normalized_errors,
        font_preflight_summary or {},
        used,
    )
    if font:
        diagnostics.append(font)

    office = _build_simple_text_diagnostic(
        kind="office_export",
        title="文档导出失败",
        summary="封面、目录或 Excel/Word 转 PDF 过程中出现失败。",
        suggestion="请检查 Office 是否仍有残留进程、模板是否可打开，必要时重新执行任务。",
        severity="error",
        items=normalized_flags + normalized_errors,
        keywords=_OFFICE_EXPORT_KEYWORDS,
        used=used,
    )
    if office:
        diagnostics.append(office)

    preview = _build_simple_text_diagnostic(
        kind="preview",
        title="预览 PDF 生成失败",
        summary="任务结果存在，但预览 PDF 没有成功生成。",
        suggestion="可先下载任务包人工检查；若合并版 PDF 缺失，再检查 CAD/PDF 导出阶段。",
        severity="warning",
        items=normalized_flags + normalized_errors,
        keywords=("PREVIEW_PDF_GENERATE_FAILED",),
        used=used,
    )
    if preview:
        diagnostics.append(preview)

    param = _build_simple_text_diagnostic(
        kind="param",
        title="参数缺失或格式不符合要求",
        summary="提交参数存在缺失、格式错误或业务规则不满足。",
        suggestion="请回到配置页补齐红色提示字段后重新提交。",
        severity="error",
        items=normalized_flags + normalized_errors,
        keywords=_PARAM_KEYWORDS,
        used=used,
    )
    if param:
        diagnostics.append(param)

    remaining = [item for item in normalized_flags + normalized_errors if item not in used]
    if remaining:
        diagnostics.append(
            _diagnostic(
                kind="other",
                title="其他未归类问题",
                summary=f"还有 {len(remaining)} 条原始诊断信息未归类。",
                suggestion="请展开原始诊断信息，或将这些信息反馈给维护人员补充分组规则。",
                severity="warning",
                details=[{"label": "原始信息", "items": _unique(remaining)}],
                raw_items=remaining,
            )
        )

    return diagnostics


def _build_duplicate_code_diagnostic(
    flags: Sequence[str],
    parsed_flags: Sequence[dict[str, str | None]],
    used: set[str],
) -> Diagnostic | None:
    internal_codes: set[str] = set()
    external_codes: set[str] = set()
    raw_items: list[str] = []
    for flag in flags:
        match = _DUPLICATE_RE.search(flag)
        if not match:
            continue
        internal_codes.update(_safe_literal_list(match.group("internal")))
        external_codes.update(_safe_literal_list(match.group("external")))
        raw_items.append(flag)
        used.add(flag)

    if not internal_codes and not external_codes:
        return None

    details: list[dict[str, Any]] = []
    for code in sorted(internal_codes):
        drawings = sorted(
            _unique(
                parsed["internal_code"]
                for parsed in parsed_flags
                if parsed.get("internal_code") == code
            )
        )
        details.append({"label": f"内部编码 {code}", "items": drawings or ["未匹配到具体图纸"]})

    for code in sorted(external_codes):
        drawings = sorted(
            _unique(
                parsed["internal_code"]
                for parsed in parsed_flags
                if parsed.get("external_code") and str(parsed["external_code"]).startswith(code)
            )
        )
        details.append({"label": f"外部编码 {code}", "items": drawings or ["未匹配到具体图纸"]})

    return _diagnostic(
        kind="duplicate_code",
        title="检测到重复编码",
        summary=f"发现 {len(internal_codes)} 个重复内部编码、{len(external_codes)} 个重复外部编码。",
        suggestion="请检查图签中的内部编码/外部编码；同一编码只能在符合多页图族规则时重复。",
        severity="error",
        details=details,
        raw_items=raw_items,
    )


def _build_cad_output_diagnostic(
    parsed_flags: Sequence[dict[str, str | None]],
    errors: Sequence[str],
    progress_details: Mapping[str, Any],
    used: set[str],
) -> Diagnostic | None:
    by_drawing: dict[str, list[str]] = defaultdict(list)
    raw_items: list[str] = []

    for parsed in parsed_flags:
        raw = str(parsed.get("raw") or "")
        reason = str(parsed.get("reason") or "")
        if not _contains_any(reason, _CAD_OUTPUT_KEYWORDS):
            continue
        internal_code = str(parsed.get("internal_code") or "").strip() or "未识别图纸"
        _append_unique(by_drawing[internal_code], reason)
        raw_items.append(raw)
        used.add(raw)

    for error in errors:
        if _contains_any(error, _CAD_OUTPUT_KEYWORDS) or "export_done=" in error:
            raw_items.append(error)
            used.add(error)

    if not by_drawing and not raw_items:
        return None

    export_total = _coerce_int(progress_details.get("export_total"))
    export_done = _coerce_int(progress_details.get("export_done"))
    if export_total is not None and export_done is not None and export_done < export_total:
        summary = f"CAD 导出未完成：已导出 {export_done}/{export_total}。"
    else:
        summary = f"{len(by_drawing)} 张图纸存在 CAD 导出、PDF 或 DWG 产物缺失问题。"

    details = [
        {"label": drawing, "items": reasons}
        for drawing, reasons in sorted(by_drawing.items(), key=lambda item: item[0])
    ]
    if not details and raw_items:
        details = [{"label": "导出错误", "items": _unique(raw_items)}]

    return _diagnostic(
        kind="cad_output",
        title="CAD 导出或产物缺失",
        summary=summary,
        suggestion="请优先处理前面列出的根因；若是 CAD/plotter 问题，再检查 CAD 环境和打印资源。",
        severity="error",
        details=details,
        raw_items=raw_items,
    )


def _build_paper_size_diagnostic(
    parsed_flags: Sequence[dict[str, str | None]],
    used: set[str],
) -> Diagnostic | None:
    by_drawing: dict[str, list[str]] = defaultdict(list)
    raw_items: list[str] = []
    for parsed in parsed_flags:
        reason = str(parsed.get("reason") or "")
        if "PAPER_SIZE_" not in reason:
            continue
        raw = str(parsed.get("raw") or "")
        internal_code = str(parsed.get("internal_code") or "").strip() or "未识别图纸"
        label = "图幅已自动修正" if "PAPER_SIZE_AUTO_FIXED" in reason else "图幅识别不一致"
        _append_unique(by_drawing[internal_code], label)
        raw_items.append(raw)
        used.add(raw)

    if not by_drawing:
        return None

    return _diagnostic(
        kind="paper_size",
        title="图幅识别或自动修正",
        summary=f"{len(by_drawing)} 张图纸存在图幅不一致或自动修正记录。",
        suggestion="请重点核对这些图纸的图幅、打印比例和最终 PDF 版面。",
        severity="warning",
        details=[
            {"label": drawing, "items": reasons}
            for drawing, reasons in sorted(by_drawing.items(), key=lambda item: item[0])
        ],
        raw_items=raw_items,
    )


def _build_font_diagnostic(
    flags: Sequence[str],
    errors: Sequence[str],
    font_preflight_summary: Mapping[str, Any],
    used: set[str],
) -> Diagnostic | None:
    raw_items = [
        item
        for item in flags + errors
        if "FONT_" in item or "字体" in item or "font" in item.lower()
    ]
    missing_styles: list[str] = []
    for file_info in font_preflight_summary.get("files", []) or []:
        if not isinstance(file_info, Mapping):
            continue
        for missing in file_info.get("missing_fonts", []) or []:
            if isinstance(missing, Mapping):
                style_name = str(missing.get("style_name") or missing.get("name") or "").strip()
                font_name = str(missing.get("font") or missing.get("font_name") or "").strip()
                value = " / ".join(part for part in [style_name, font_name] if part)
                if value:
                    missing_styles.append(value)

    if not raw_items and not missing_styles:
        return None

    for item in raw_items:
        used.add(item)

    details: list[dict[str, Any]] = []
    if missing_styles:
        details.append({"label": "缺失字体样式", "items": _unique(missing_styles)})
    if raw_items:
        details.append({"label": "字体处理记录", "items": _unique(raw_items)})

    return _diagnostic(
        kind="font",
        title="字体风险",
        summary="检测到字体缺失、空字体样式或字体替换未完全处理。",
        suggestion="请使用字体兼容模式出图，并在出图后人工核查图签、页码和外部编码。",
        severity="warning",
        details=details,
        raw_items=raw_items,
    )


def _build_simple_text_diagnostic(
    *,
    kind: str,
    title: str,
    summary: str,
    suggestion: str,
    severity: str,
    items: Sequence[str],
    keywords: Sequence[str],
    used: set[str],
) -> Diagnostic | None:
    raw_items = [item for item in items if _contains_any(item, keywords)]
    if not raw_items:
        return None
    for item in raw_items:
        used.add(item)
    return _diagnostic(
        kind=kind,
        title=title,
        summary=summary,
        suggestion=suggestion,
        severity=severity,
        details=[{"label": "具体信息", "items": _unique(raw_items)}],
        raw_items=raw_items,
    )


def _parse_prefixed_flag(flag: str) -> dict[str, str | None]:
    match = _PREFIXED_FLAG_RE.match(flag)
    if not match:
        return {
            "raw": flag,
            "label": None,
            "external_code": None,
            "internal_code": None,
            "reason": flag,
        }

    label = match.group("label").strip()
    reason = match.group("reason").strip()
    internal_code = None
    external_code = label
    internal_match = _INTERNAL_IN_LABEL_RE.search(label)
    if internal_match:
        internal_code = internal_match.group("internal").strip()
        external_code = label[: internal_match.start()].strip()
    return {
        "raw": flag,
        "label": label,
        "external_code": external_code.strip() or None,
        "internal_code": internal_code,
        "reason": reason,
    }


def _safe_literal_list(value: str) -> list[str]:
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _diagnostic(
    *,
    kind: str,
    title: str,
    summary: str,
    suggestion: str,
    severity: str,
    details: list[dict[str, Any]],
    raw_items: Sequence[str],
) -> Diagnostic:
    return {
        "kind": kind,
        "severity": severity,
        "title": title,
        "summary": summary,
        "suggestion": suggestion,
        "details": details,
        "raw_items": _unique(raw_items),
    }


def _contains_any(value: str, keywords: Sequence[str]) -> bool:
    return any(keyword in value for keyword in keywords)


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _unique(items: Any) -> list[str]:
    result: list[str] = []
    for item in items or []:
        if item is None:
            continue
        value = str(item).strip()
        if value and value not in result:
            result.append(value)
    return result


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
