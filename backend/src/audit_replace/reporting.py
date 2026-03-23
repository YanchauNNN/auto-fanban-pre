from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from ..result_views import build_finding_groups


def build_replace_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    replaced = [entry for entry in entries if entry.get("status") == "replaced"]
    replaced_texts = Counter(str(entry.get("matched_text") or "") for entry in replaced)
    internal_codes = Counter(str(entry.get("internal_code") or "未归属") for entry in replaced)
    skipped = [entry for entry in entries if entry.get("status") != "replaced"]
    return {
        "replacement_count": len(replaced),
        "skipped_count": len(skipped),
        "affected_drawings_count": len(internal_codes),
        "top_replaced_texts": [text for text, _ in replaced_texts.most_common(10) if text],
        "top_internal_codes": [code for code, _ in internal_codes.most_common(10) if code],
    }


def write_replace_report_json(
    path: Path,
    *,
    source_filename: str,
    source_project_no: str,
    target_project_no: str,
    entries: list[dict[str, Any]],
    no_op_tokens: list[str],
    missing_target_tokens: list[str],
) -> dict[str, Any]:
    summary = build_replace_summary(entries)
    payload = {
        "source_filename": source_filename,
        "source_project_no": source_project_no,
        "target_project_no": target_project_no,
        **summary,
        "no_op_tokens": list(no_op_tokens),
        "missing_target_tokens": list(missing_target_tokens),
        "replacement_groups": build_finding_groups(
            [
                {
                    "matched_text": entry.get("matched_text"),
                    "internal_code": entry.get("internal_code"),
                }
                for entry in entries
                if entry.get("status") == "replaced"
            ]
        ),
        "replacements": entries,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def write_replace_report_xlsx(
    path: Path,
    *,
    source_filename: str,
    source_project_no: str,
    target_project_no: str,
    entries: list[dict[str, Any]],
    summary: dict[str, Any],
    no_op_tokens: list[str],
    missing_target_tokens: list[str],
) -> None:
    workbook = Workbook()
    summary_sheet = workbook.active
    assert summary_sheet is not None
    summary_sheet = summary_sheet
    summary_sheet.title = "Summary"
    _append_summary(summary_sheet, source_filename, source_project_no, target_project_no, summary, no_op_tokens, missing_target_tokens)

    replacements_sheet = workbook.create_sheet("Replacements")
    replacements_sheet.append(
        [
            "source_filename",
            "source_project_no",
            "target_project_no",
            "status",
            "matched_text",
            "replacement_text",
            "raw_text",
            "new_text",
            "internal_code",
            "layout_name",
            "entity_type",
            "entity_handle",
            "field_context",
            "block_path",
            "position_x",
            "position_y",
            "message",
        ]
    )
    for entry in entries:
        replacements_sheet.append(
            [
                source_filename,
                source_project_no,
                target_project_no,
                entry.get("status"),
                entry.get("matched_text"),
                entry.get("replacement_text"),
                entry.get("raw_text"),
                entry.get("new_text"),
                entry.get("internal_code") or "未归属",
                entry.get("layout_name"),
                entry.get("entity_type"),
                entry.get("entity_handle"),
                entry.get("field_context"),
                entry.get("block_path"),
                entry.get("position_x"),
                entry.get("position_y"),
                entry.get("message"),
            ]
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    workbook.close()


def _append_summary(
    sheet: Worksheet,
    source_filename: str,
    source_project_no: str,
    target_project_no: str,
    summary: dict[str, Any],
    no_op_tokens: list[str],
    missing_target_tokens: list[str],
) -> None:
    sheet.append(["source_filename", source_filename])
    sheet.append(["source_project_no", source_project_no])
    sheet.append(["target_project_no", target_project_no])
    sheet.append(["replacement_count", summary["replacement_count"]])
    sheet.append(["skipped_count", summary["skipped_count"]])
    sheet.append(["affected_drawings_count", summary["affected_drawings_count"]])
    sheet.append(["top_replaced_texts", ", ".join(summary["top_replaced_texts"])])
    sheet.append(["top_internal_codes", ", ".join(summary["top_internal_codes"])])
    sheet.append(["no_op_tokens", ", ".join(no_op_tokens)])
    sheet.append(["missing_target_tokens", ", ".join(missing_target_tokens)])
