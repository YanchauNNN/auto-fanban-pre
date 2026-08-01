from __future__ import annotations

import json
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..calculation_book.reinforcement_input import (
    ParsedRebarCell,
    ReinforcementSchedule,
    load_reinforcement_schedule,
)
from .context_skills import SkillContext

REINFORCEMENT_TABLE_SKILL_ID = "reinforcement_table_normalizer"
REINFORCEMENT_TABLE_SKILL_DIR = "reinforcement-table-normalizer"

_DEFAULT_TRIGGER_TERMS = (
    "配筋表",
    "墙体配筋",
    "配筋结果",
    "配筋规范",
    "规范化配筋",
    "水平筋",
    "竖向筋",
    "拉筋",
)
_FOLLOWUP_TERMS = (
    "继续",
    "这一行",
    "该墙",
    "这个墙",
    "重复",
    "实配面积",
    "为什么",
)
_REQUIRED_FILES = (
    Path("SKILL.md"),
    Path("references") / "normalization-rules.md",
)


@dataclass(frozen=True)
class ReinforcementTableSkillConfig:
    skill_id: str = REINFORCEMENT_TABLE_SKILL_ID
    auto_trigger: bool = True
    trigger_terms: tuple[str, ...] = _DEFAULT_TRIGGER_TERMS
    max_results: int = 10_000
    max_context_chars: int = 120_000
    history_followup_messages: int = 6


AttachmentReader = Callable[[Any], bytes]


class ReinforcementTableSkill:
    def __init__(
        self,
        *,
        root: Path,
        config: ReinforcementTableSkillConfig,
    ) -> None:
        self.root = root.resolve()
        self.config = config
        self.skill_id = config.skill_id

    @property
    def available(self) -> bool:
        return all((self.root / relative).is_file() for relative in _REQUIRED_FILES)

    def matches(
        self,
        content: str,
        history: Sequence[Any],
        attachments: Sequence[Any] = (),
    ) -> bool:
        if not self.config.auto_trigger:
            return False
        normalized = content.casefold()
        if any(term.casefold() in normalized for term in self.config.trigger_terms):
            return True
        attachment_names = " ".join(
            str(getattr(attachment, "original_name", ""))
            for attachment in attachments
        ).casefold()
        if "配筋" in attachment_names and ".xlsx" in attachment_names:
            return True
        return self._history_used_skill(history) and (
            not content.strip()
            or any(term.casefold() in normalized for term in _FOLLOWUP_TERMS)
        )

    def retrieve_if_applicable(
        self,
        content: str,
        history: Sequence[Any],
    ) -> SkillContext | None:
        if not self.matches(content, history):
            return None
        if not self.available:
            return self._unavailable_context()
        return SkillContext(
            skill_id=self.skill_id,
            content=(
                "墙体配筋表规范化 Skill 已触发，但本条消息没有可读取的 XLSX 附件。"
                "请上传原始配筋表；在确定性解析完成前不得猜测墙号、配筋规格或实配面积。"
            ),
            metadata={
                "available": True,
                "error": "xlsx_attachment_required",
                "evidence_count": 0,
                "requires_completion_review": False,
            },
        )

    def retrieve_from_attachments(
        self,
        content: str,
        history: Sequence[Any],
        attachments: Sequence[Any],
        attachment_reader: AttachmentReader,
    ) -> SkillContext | None:
        if not self.matches(content, history, attachments):
            return None
        if not self.available:
            return self._unavailable_context()

        xlsx_attachments = [
            attachment
            for attachment in attachments
            if Path(str(getattr(attachment, "original_name", ""))).suffix.casefold()
            == ".xlsx"
        ]
        if not xlsx_attachments:
            return self.retrieve_if_applicable(content, history)

        workbooks: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        with tempfile.TemporaryDirectory(prefix="fanban-reinforcement-") as temp_root:
            temp_dir = Path(temp_root)
            for index, attachment in enumerate(xlsx_attachments, start=1):
                source_name = str(
                    getattr(attachment, "original_name", f"attachment-{index}.xlsx")
                )
                if str(getattr(attachment, "status", "ready")).casefold() != "ready":
                    errors.append(
                        {
                            "source_name": source_name,
                            "error": "附件尚未完成解析，未读取任何配筋值",
                        }
                    )
                    continue
                try:
                    payload = attachment_reader(attachment)
                    workbook_path = temp_dir / f"reinforcement-{index}.xlsx"
                    workbook_path.write_bytes(payload)
                    schedule = load_reinforcement_schedule(workbook_path)
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "source_name": source_name,
                            "error": str(exc),
                        }
                    )
                    continue
                workbooks.append(_schedule_payload(source_name, schedule))

        requires_completion_review = any(
            workbook["requires_completion_review"] for workbook in workbooks
        )
        evidence_count = sum(len(workbook["rows"]) for workbook in workbooks)
        source_row_count = sum(
            int(workbook["source_row_count"])
            for workbook in workbooks
        )
        payload = {
            "skill": "墙体配筋表规范化",
            "policy": {
                "deterministic_parser_only": True,
                "guessing_forbidden": True,
                "exact_formula": (
                    "XY: layers*pi*(diameter/2)^2*(1000/spacing); "
                    "Z: XY result*(1000/secondary_spacing)"
                ),
                "rounding_only_for_presentation": True,
                "parenthetical_value_is_actual": True,
                "local_ambiguities_leave_fields_blank": True,
                "local_ambiguities_do_not_block_task": True,
            },
            "workbooks": workbooks,
            "errors": errors,
        }
        rendered, context_format, context_error = _render_payload(
            payload,
            max_context_chars=self.config.max_context_chars,
        )
        return SkillContext(
            skill_id=self.skill_id,
            content=rendered,
            metadata={
                "available": True,
                "evidence_count": evidence_count,
                "source_row_count": source_row_count,
                "workbook_count": len(workbooks),
                "requires_completion_review": requires_completion_review,
                "errors": errors,
                "context_format": context_format,
                "context_error": context_error,
            },
        )

    def _history_used_skill(self, history: Sequence[Any]) -> bool:
        for message in list(history)[-max(self.config.history_followup_messages, 0) :]:
            metadata = getattr(message, "metadata", None) or {}
            if self.skill_id in metadata.get("auto_skill_ids", []):
                return True
        return False

    def _unavailable_context(self) -> SkillContext:
        return SkillContext(
            skill_id=self.skill_id,
            content=(
                "墙体配筋表规范化 Skill 已触发，但本地规则包不完整。"
                "不得猜测墙号、配筋规格或实配面积；请先恢复 SKILL.md 和规则文件。"
            ),
            metadata={
                "available": False,
                "error": "skill_payload_incomplete",
                "evidence_count": 0,
                "requires_completion_review": False,
            },
        )


def _schedule_payload(
    source_name: str,
    schedule: ReinforcementSchedule,
) -> dict[str, Any]:
    normalized_rows = [
        {
            "status": "normalized",
            "wall_id": row.wall_id,
            "source_sheet": row.source_sheet,
            "source_row": row.source_row,
            "source_cells": row.source_cells,
            "directions": {
                "X": _cell_payload(row.x),
                "Y": _cell_payload(row.y),
                "Z": _cell_payload(row.z),
            },
        }
        for row in schedule.rows
    ]
    issue_rows = [
        {
            "status": "needs_review",
            "source_sheet": issue.source_sheet,
            "source_row": issue.source_row,
            "source_cells": issue.source_cells,
            "original_values": issue.original_values,
            "original_wall_text": issue.original_wall_text,
            "wall_id": issue.wall_id,
            "error": issue.error,
        }
        for issue in schedule.issues
    ]
    output_rows = sorted(
        [*normalized_rows, *issue_rows],
        key=lambda row: (
            str(row["source_sheet"]).casefold(),
            int(row["source_row"]),
        ),
    )
    return {
        "source_name": source_name,
        "source_row_count": schedule.source_row_count,
        "normalized_row_count": schedule.normalized_row_count,
        "issue_row_count": schedule.issue_row_count,
        "unique_wall_count": schedule.unique_wall_count,
        "normalization_triggered": schedule.normalization_triggered,
        "duplicate_wall_ids": list(schedule.duplicate_wall_ids),
        "requires_completion_review": schedule.requires_manual_confirmation,
        "issues": [
            {key: value for key, value in row.items() if key != "status"}
            for row in issue_rows
        ],
        "rows": [
            {key: value for key, value in row.items() if key != "status"}
            for row in normalized_rows
        ],
        "output_rows": output_rows,
    }


def _cell_payload(cell: ParsedRebarCell) -> dict[str, Any]:
    selected = cell.selected
    return {
        "original_text": cell.original_text,
        "normalized_text": cell.normalized_text,
        "canonical_specification": selected.canonical_specification,
        "narrative_specification": selected.narrative_specification,
        "actual_area": selected.actual_area,
        "selected_parenthetical": selected.is_parenthetical,
        "selected": _configuration_payload(selected),
        "candidates": [
            _configuration_payload(candidate) for candidate in cell.candidates
        ],
    }


def _configuration_payload(configuration: Any) -> dict[str, Any]:
    return {
        "layers": configuration.layers,
        "diameter": configuration.diameter,
        "spacing_primary": configuration.spacing_primary,
        "spacing_secondary": configuration.spacing_secondary,
        "canonical_specification": configuration.canonical_specification,
        "narrative_specification": configuration.narrative_specification,
        "actual_area": configuration.actual_area,
        "is_parenthetical": configuration.is_parenthetical,
    }


def _render_payload(
    payload: dict[str, Any],
    *,
    max_context_chars: int,
) -> tuple[str, str, str | None]:
    full = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(full) <= max_context_chars:
        return full, "expanded_rows_v1", None

    compact = {
        "skill": payload["skill"],
        "encoding": "compact_rows_v1",
        "policy": payload["policy"],
        "row_schema": [
            "source_sheet",
            "source_row",
            "wall_cell",
            "x_cell",
            "y_cell",
            "z_cell",
            "wall_id",
            "X",
            "Y",
            "Z",
        ],
        "direction_schema": [
            "original_text_if_different",
            "canonical_specification",
            "narrative_specification",
            "actual_area_exact",
            "selected_parenthetical",
            "additional_candidates",
        ],
        "candidate_schema": [
            "layers",
            "diameter",
            "spacing_primary",
            "spacing_secondary",
            "canonical_specification",
            "narrative_specification",
            "actual_area_exact",
            "is_parenthetical",
        ],
        "issue_schema": [
            "source_sheet",
            "source_row",
            "wall_cell",
            "x_cell",
            "y_cell",
            "z_cell",
            "original_values",
            "original_wall_text",
            "wall_id",
            "error",
        ],
        "output_row_schema": [
            "status",
            "source_sheet",
            "source_row",
            "wall_id",
            "error",
        ],
        "workbooks": [
            _compact_workbook_payload(workbook)
            for workbook in payload["workbooks"]
        ],
        "errors": payload["errors"],
    }
    compact_rendered = json.dumps(
        compact,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(compact_rendered) <= max_context_chars:
        return compact_rendered, "compact_rows_v1", None

    overflow = {
        "skill": payload["skill"],
        "policy": payload["policy"],
        "workbooks": [
            {
                "source_name": workbook["source_name"],
                "source_row_count": workbook["source_row_count"],
                "normalized_row_count": workbook["normalized_row_count"],
                "issue_row_count": workbook["issue_row_count"],
                "unique_wall_count": workbook["unique_wall_count"],
                "normalization_triggered": workbook[
                    "normalization_triggered"
                ],
                "duplicate_wall_ids": workbook["duplicate_wall_ids"],
                "requires_completion_review": workbook[
                    "requires_completion_review"
                ],
            }
            for workbook in payload["workbooks"]
        ],
        "errors": payload["errors"],
        "context_error": (
            "所有行均已由确定性解析器读取，但完整结果超过单次 AI 上下文上限。"
            "不得截断后猜测；请拆分工作簿后重试。"
        ),
    }
    return (
        json.dumps(overflow, ensure_ascii=False, separators=(",", ":")),
        "summary_only",
        "context_limit_exceeded",
    )


def _compact_workbook_payload(workbook: dict[str, Any]) -> dict[str, Any]:
    records: list[list[Any]] = []
    for row in workbook["rows"]:
        source_cells = row["source_cells"]
        directions = [
            _compact_direction_payload(row["directions"][direction])
            for direction in ("X", "Y", "Z")
        ]
        records.append(
            [
                row["source_sheet"],
                row["source_row"],
                source_cells["wall"],
                source_cells["X"],
                source_cells["Y"],
                source_cells["Z"],
                row["wall_id"],
                *directions,
            ]
        )
    return {
        "source_name": workbook["source_name"],
        "source_row_count": workbook["source_row_count"],
        "normalized_row_count": workbook["normalized_row_count"],
        "issue_row_count": workbook["issue_row_count"],
        "unique_wall_count": workbook["unique_wall_count"],
        "normalization_triggered": workbook["normalization_triggered"],
        "duplicate_wall_ids": workbook["duplicate_wall_ids"],
        "requires_completion_review": workbook[
            "requires_completion_review"
        ],
        "row_records": records,
        "issue_records": [
            [
                issue["source_sheet"],
                issue["source_row"],
                issue["source_cells"]["wall"],
                issue["source_cells"]["X"],
                issue["source_cells"]["Y"],
                issue["source_cells"]["Z"],
                issue["original_values"],
                issue["original_wall_text"],
                issue["wall_id"],
                issue["error"],
            ]
            for issue in workbook["issues"]
        ],
        "output_row_records": [
            [
                row["status"],
                row["source_sheet"],
                row["source_row"],
                row.get("wall_id"),
                row.get("error"),
            ]
            for row in workbook["output_rows"]
        ],
    }


def _compact_direction_payload(direction: dict[str, Any]) -> list[Any]:
    canonical = direction["canonical_specification"]
    candidates = direction["candidates"]
    additional_candidates = (
        []
        if len(candidates) == 1
        else [
            [
                candidate["layers"],
                candidate["diameter"],
                candidate["spacing_primary"],
                candidate["spacing_secondary"],
                candidate["canonical_specification"],
                candidate["narrative_specification"],
                candidate["actual_area"],
                candidate["is_parenthetical"],
            ]
            for candidate in candidates
        ]
    )
    return [
        (
            None
            if direction["original_text"] == canonical
            else direction["original_text"]
        ),
        canonical,
        direction["narrative_specification"],
        direction["actual_area"],
        direction["selected_parenthetical"],
        additional_candidates,
    ]
