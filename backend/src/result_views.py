from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .cad.splitter import output_name_for_frame, output_name_for_sheet_set
from .models import FrameMeta, SheetSet

_DIRECTLY_FILTERED_FLAG_CODES = frozenset(
    {
        "PLOT_FROM_SOURCE_WINDOW",
        "PLOT_WINDOW_USED",
    }
)


def normalize_user_flags(flags: Sequence[str]) -> list[str]:
    auto_fixed_keys = {
        _flag_identity(flag)
        for flag in flags
        if _flag_code(flag) == "PAPER_SIZE_AUTO_FIXED"
    }
    normalized: list[str] = []
    for flag in flags:
        code = _flag_code(flag)
        if code in _DIRECTLY_FILTERED_FLAG_CODES:
            continue
        if code == "PAPER_SIZE_MISMATCH" and _flag_identity(flag) in auto_fixed_keys:
            continue
        if flag not in normalized:
            normalized.append(flag)
    return normalized


def build_finding_groups(findings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for finding in findings:
        matched_text = str(finding.get("matched_text") or "").strip()
        if not matched_text:
            continue
        internal_code = str(finding.get("internal_code") or "未归属").strip() or "未归属"
        bucket = grouped.setdefault(
            matched_text,
            {
                "matched_text": matched_text,
                "count": 0,
                "internal_codes": [],
            },
        )
        bucket["count"] += 1
        if internal_code not in bucket["internal_codes"]:
            bucket["internal_codes"].append(internal_code)
    return sorted(
        grouped.values(),
        key=lambda item: (-int(item["count"]), str(item["matched_text"])),
    )


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
    for frame in _sorted_frames(context.get("frames", [])):
        drawings.append(
            {
                "name": output_name_for_frame(frame),
                "internal_code": frame.titleblock.internal_code,
                "dwg_name": frame.runtime.dwg_path.name if frame.runtime.dwg_path else None,
                "pdf_name": frame.runtime.pdf_path.name if frame.runtime.pdf_path else None,
                "page_total": 1,
            }
        )

    for sheet_set in _sorted_sheet_sets(context.get("sheet_sets", [])):
        titleblock = sheet_set.get_inherited_titleblock()
        drawings.append(
            {
                "name": output_name_for_sheet_set(sheet_set),
                "internal_code": titleblock.get("internal_code"),
                "dwg_name": None,
                "pdf_name": sheet_set.pdf_path.name if sheet_set.pdf_path else None,
                "page_total": sheet_set.generated_page_count or sheet_set.page_total,
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
