from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ScanTextItem:
    raw_text: str
    entity_type: str
    field_context: str | None = None
    internal_code: str | None = None
    layout_name: str | None = None
    entity_handle: str | None = None
    block_path: str | None = None
    position_x: float | None = None
    position_y: float | None = None


@dataclass(slots=True)
class AuditFinding:
    raw_text: str
    matched_text: str
    matched_project_nos: list[str]
    context_kind: str
    confidence: str
    entity_type: str
    field_context: str | None = None
    internal_code: str | None = None
    layout_name: str | None = None
    entity_handle: str | None = None
    block_path: str | None = None
    position_x: float | None = None
    position_y: float | None = None


@dataclass(slots=True)
class AuditLexicon:
    project_options: list[str]
    allowed_texts: dict[str, set[str]]
    foreign_texts: dict[str, set[str]]
    token_projects: dict[str, set[str]] = field(default_factory=dict)
