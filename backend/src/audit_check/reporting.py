from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, cast

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from ..result_views import build_finding_groups
from .models import AuditFinding


def build_summary(findings: list[AuditFinding]) -> dict[str, Any]:
    wrong_texts = Counter(finding.matched_text for finding in findings)
    internal_codes = Counter(
        finding.internal_code or "未归属"
        for finding in findings
    )
    return {
        "findings_count": len(findings),
        "affected_drawings_count": len(internal_codes),
        "top_wrong_texts": [text for text, _ in wrong_texts.most_common(10)],
        "top_internal_codes": [code for code, _ in internal_codes.most_common(10)],
    }


def write_report_json(
    path: Path,
    *,
    source_filename: str,
    project_no: str,
    findings: list[AuditFinding],
) -> dict[str, Any]:
    summary = build_summary(findings)
    payload = {
        "source_filename": source_filename,
        "project_no": project_no,
        **summary,
        "finding_groups": build_finding_groups(
            [
                {
                    "matched_text": finding.matched_text,
                    "internal_code": finding.internal_code,
                }
                for finding in findings
            ]
        ),
        "findings": [
            {
                "raw_text": finding.raw_text,
                "matched_text": finding.matched_text,
                "matched_project_nos": finding.matched_project_nos,
                "internal_code": finding.internal_code or "未归属",
                "layout_name": finding.layout_name,
                "entity_type": finding.entity_type,
                "entity_handle": finding.entity_handle,
                "block_path": finding.block_path,
                "field_context": finding.field_context,
                "context_kind": finding.context_kind,
                "confidence": finding.confidence,
                "position_x": finding.position_x,
                "position_y": finding.position_y,
                "context_excerpt": finding.raw_text[:120],
            }
            for finding in findings
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def write_report_xlsx(
    path: Path,
    *,
    source_filename: str,
    project_no: str,
    findings: list[AuditFinding],
    summary: dict[str, Any],
) -> None:
    workbook = Workbook()
    summary_sheet = cast(Worksheet, workbook.active)
    summary_sheet.title = "Summary"
    summary_sheet.append(["source_filename", source_filename])
    summary_sheet.append(["project_no", project_no])
    summary_sheet.append(["findings_count", summary["findings_count"]])
    summary_sheet.append(["affected_drawings_count", summary["affected_drawings_count"]])
    summary_sheet.append(["top_wrong_texts", ", ".join(summary["top_wrong_texts"])])
    summary_sheet.append(["top_internal_codes", ", ".join(summary["top_internal_codes"])])

    findings_sheet = workbook.create_sheet("Findings")
    findings_sheet.append(
        [
            "source_filename",
            "project_no",
            "internal_code",
            "layout_name",
            "entity_type",
            "entity_handle",
            "block_path",
            "field_context",
            "raw_text",
            "matched_text",
            "matched_project_nos",
            "confidence",
            "context_kind",
            "context_excerpt",
            "position_x",
            "position_y",
        ]
    )
    for finding in findings:
        findings_sheet.append(
            [
                source_filename,
                project_no,
                finding.internal_code or "未归属",
                finding.layout_name,
                finding.entity_type,
                finding.entity_handle,
                finding.block_path,
                finding.field_context,
                finding.raw_text,
                finding.matched_text,
                ", ".join(finding.matched_project_nos),
                finding.confidence,
                finding.context_kind,
                finding.raw_text[:120],
                finding.position_x,
                finding.position_y,
            ]
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    workbook.close()
