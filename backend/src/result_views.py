from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .config import load_mechanism_spec
from .cad.splitter import output_name_for_frame, output_name_for_sheet_set
from .models import FrameMeta, SheetSet


def normalize_user_flags(flags: Sequence[str]) -> list[str]:
    directly_filtered = set(load_mechanism_spec().audit_display.directly_filtered_flag_codes)
    auto_fixed_keys = {
        _flag_identity(flag)
        for flag in flags
        if _flag_code(flag) == "PAPER_SIZE_AUTO_FIXED"
    }
    normalized: list[str] = []
    for flag in flags:
        code = _flag_code(flag)
        if code in directly_filtered:
            continue
        if code == "PAPER_SIZE_MISMATCH" and _flag_identity(flag) in auto_fixed_keys:
            continue
        if flag not in normalized:
            normalized.append(flag)
    return normalized


def build_finding_groups(findings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    group_priority = load_mechanism_spec().audit_display.finding_group_priority
    grouped: dict[str, dict[str, Any]] = {}
    for finding in findings:
        matched_text = str(finding.get("matched_text") or "").strip()
        if not matched_text:
            continue
        context_kind = str(finding.get("context_kind") or "")
        details = finding.get("details") if isinstance(finding.get("details"), Mapping) else {}
        internal_code = str(finding.get("internal_code") or "未归属").strip() or "未归属"
        bucket = grouped.setdefault(
            matched_text,
            {
                "matched_text": matched_text,
                "count": 0,
                "internal_codes": [],
            },
        )
        if context_kind.startswith("standard_review") and "category" not in bucket:
            bucket.update(_standard_review_group_fields(context_kind, details))
        bucket["count"] += 1
        if internal_code not in bucket["internal_codes"]:
            bucket["internal_codes"].append(internal_code)
    return sorted(
        grouped.values(),
        key=lambda item: (
            group_priority.get(str(item["matched_text"]), 1),
            -int(item["count"]),
            str(item["matched_text"]),
        ),
    )


def _standard_review_group_fields(
    context_kind: str,
    details: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "category": "规范审查",
        "context_kind": context_kind,
        "issue_type": str(details.get("issue_type") or ""),
        "summary": _standard_review_summary(context_kind, details),
        "details": _standard_review_detail_items(details),
    }


def _standard_review_summary(context_kind: str, details: Mapping[str, Any]) -> str:
    actual_code = str(details.get("actual_code") or "").strip()
    expected_code = str(details.get("expected_code") or "").strip()
    expected_name = str(details.get("expected_name") or "").strip()
    if context_kind == "standard_review_year":
        return f"标准号年限不一致：{actual_code} 应为 {expected_code}"
    if context_kind == "standard_review_name":
        actual_name = str(details.get("actual_name") or "").strip()
        return f"标准号与标准名称不对应：{actual_code} 附近为 {actual_name or '未识别名称'}，应为 {expected_name}"
    return f"规范审查问题：{actual_code or expected_code}"


def _standard_review_detail_items(details: Mapping[str, Any]) -> list[str]:
    items: list[str] = []
    labels = [
        ("actual_code", "实际标准号"),
        ("expected_code", "期望标准号"),
        ("actual_year", "实际年限"),
        ("expected_year", "期望年限"),
        ("actual_name", "实际标准名称"),
        ("expected_name", "期望标准名称"),
    ]
    for key, label in labels:
        value = str(details.get(key) or "").strip()
        if value:
            items.append(f"{label}：{value}")
    return items


def build_deliverable_outputs(
    *,
    context: Mapping[str, Any],
    docs_dir: Path | None,
) -> dict[str, Any]:
    drawings = _build_drawing_outputs(context)
    documents = _collect_documents(docs_dir)
    return {
        "dwg_count": sum(1 for item in drawings if item["dwg_name"]),
        "pdf_count": sum(1 for item in drawings if item["pdf_name"]),
        "documents": documents,
        "drawings": drawings,
    }


def _build_drawing_outputs(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    drawings: list[dict[str, Any]] = []
    for item in _sorted_drawing_items(context.get("frames", []), context.get("sheet_sets", [])):
        if isinstance(item, FrameMeta):
            drawings.append(
                {
                    "name": output_name_for_frame(item),
                    "internal_code": item.titleblock.internal_code,
                    "dwg_name": item.runtime.dwg_path.name if item.runtime.dwg_path else None,
                    "pdf_name": item.runtime.pdf_path.name if item.runtime.pdf_path else None,
                    "page_total": 1,
                }
            )
            continue

        titleblock = item.get_inherited_titleblock()
        drawings.append(
            {
                "name": output_name_for_sheet_set(item),
                "internal_code": titleblock.get("internal_code"),
                "dwg_name": item.dwg_path.name if item.dwg_path else None,
                "pdf_name": item.pdf_path.name if item.pdf_path else None,
                "page_total": item.generated_page_count or item.page_total,
            }
        )
    return drawings


def _collect_documents(docs_dir: Path | None) -> list[dict[str, str]]:
    if docs_dir is None or not docs_dir.exists():
        return []
    return [
        {
            "name": path.name,
            "kind": path.suffix.lstrip(".").lower(),
        }
        for path in sorted(docs_dir.iterdir(), key=lambda item: item.name.lower())
        if path.is_file()
    ]


def _sorted_frames(frames: Iterable[Any]) -> list[FrameMeta]:
    validated = [frame for frame in frames if isinstance(frame, FrameMeta)]
    return sorted(validated, key=_frame_sort_key)


def _sorted_sheet_sets(sheet_sets: Iterable[Any]) -> list[SheetSet]:
    validated = [sheet_set for sheet_set in sheet_sets if isinstance(sheet_set, SheetSet)]
    return sorted(validated, key=_sheet_set_sort_key)


def _sorted_drawing_items(
    frames: Iterable[Any],
    sheet_sets: Iterable[Any],
) -> list[FrameMeta | SheetSet]:
    items: list[FrameMeta | SheetSet] = []
    items.extend(_sorted_frames(frames))
    items.extend(_sorted_sheet_sets(sheet_sets))
    return sorted(items, key=_drawing_item_sort_key)


def _frame_sort_key(frame: FrameMeta) -> tuple[int, str]:
    seq = frame.titleblock.get_seq_no()
    internal_code = frame.titleblock.internal_code or ""
    return (seq if seq is not None else 9999, internal_code)


def _sheet_set_sort_key(sheet_set: SheetSet) -> tuple[int, str]:
    titleblock = sheet_set.get_inherited_titleblock()
    internal_code = str(titleblock.get("internal_code") or "")
    suffix = internal_code.rsplit("-", 1)[-1] if "-" in internal_code else ""
    seq = int(suffix) if suffix.isdigit() else 9999
    return (seq, internal_code)


def _drawing_item_sort_key(item: FrameMeta | SheetSet) -> tuple[int, str, int]:
    if isinstance(item, FrameMeta):
        seq, internal_code = _frame_sort_key(item)
        return (seq, internal_code, 0)
    seq, internal_code = _sheet_set_sort_key(item)
    return (seq, internal_code, 1)


def _flag_identity(flag: str) -> str:
    prefix, _ = _split_flag(flag)
    return prefix


def _flag_code(flag: str) -> str:
    _, code = _split_flag(flag)
    return code


def _split_flag(flag: str) -> tuple[str, str]:
    if "] " in flag:
        prefix, code = flag.split("] ", 1)
        return prefix + "] ", code
    return "", flag
