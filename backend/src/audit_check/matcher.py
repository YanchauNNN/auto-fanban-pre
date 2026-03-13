from __future__ import annotations

import re

from .lexicon import normalize_text
from .models import AuditFinding, AuditLexicon, ScanTextItem

_DATE_PATTERNS = (
    re.compile(r"^\d{4}[-/.]\d{1,2}([-/.:]\d{1,2})+$"),
    re.compile(r"^\d{4}年\d{1,2}月(\d{1,2}日?)?$"),
)
_DIMENSION_RE = re.compile(r"^\d+(?:\s*[X×*]\s*\d+)+$")
_INTERNAL_CODE_RE = re.compile(r"^\d{4}[A-Z0-9]+(?:-[A-Z0-9]+){1,2}$")
_EXTERNAL_CODE_RE = re.compile(r"^[A-Z0-9]{19}$")
_GENERIC_IDENTIFIER_RE = re.compile(r"^[A-Z0-9-]{6,}$")


class AuditMatchEngine:
    def __init__(self, lexicon: AuditLexicon) -> None:
        self.lexicon = lexicon

    def evaluate(self, *, project_no: str, items: list[ScanTextItem]) -> list[AuditFinding]:
        foreign_tokens = sorted(self.lexicon.foreign_texts.get(project_no, set()), key=len, reverse=True)
        findings: list[AuditFinding] = []

        for item in items:
            normalized_text = normalize_text(item.raw_text)
            if not normalized_text:
                continue

            context_kind = self._classify_context(item.field_context, normalized_text)
            if context_kind in {"date_like", "dimension_like"}:
                continue

            matched_tokens: set[str] = set()
            for token in foreign_tokens:
                if token in matched_tokens:
                    continue
                if self._matches_token(token=token, text=normalized_text, context_kind=context_kind):
                    matched_tokens.add(token)
                    findings.append(
                        AuditFinding(
                            raw_text=item.raw_text,
                            matched_text=token,
                            matched_project_nos=sorted(self.lexicon.token_projects.get(token, set())),
                            context_kind=context_kind,
                            confidence=self._confidence_for(context_kind, normalized_text, token),
                            entity_type=item.entity_type,
                            field_context=item.field_context,
                            internal_code=item.internal_code,
                            layout_name=item.layout_name,
                            entity_handle=item.entity_handle,
                            block_path=item.block_path,
                            position_x=item.position_x,
                            position_y=item.position_y,
                        )
                    )

        return findings

    @staticmethod
    def _classify_context(field_context: str | None, normalized_text: str) -> str:
        if field_context:
            return field_context
        if any(pattern.fullmatch(normalized_text) for pattern in _DATE_PATTERNS):
            return "date_like"
        if _DIMENSION_RE.fullmatch(normalized_text):
            return "dimension_like"
        if _INTERNAL_CODE_RE.fullmatch(normalized_text) or _EXTERNAL_CODE_RE.fullmatch(normalized_text):
            return "code_like"
        if _GENERIC_IDENTIFIER_RE.fullmatch(normalized_text):
            return "generic_identifier_like"
        return "plain_text"

    def _matches_token(self, *, token: str, text: str, context_kind: str) -> bool:
        if context_kind.startswith("titleblock_") or context_kind == "code_like":
            return token in text

        if context_kind == "generic_identifier_like":
            return len(token) > 4 and token in text and not token.isdigit()

        if self._is_strong_boundary_match(token, text):
            return True

        return len(token) > 4 and token in text and ("-" in token or any(ord(ch) > 127 for ch in token))

    @staticmethod
    def _is_strong_boundary_match(token: str, text: str) -> bool:
        pattern = re.compile(rf"(?<![A-Z0-9]){re.escape(token)}(?![A-Z0-9])")
        return bool(pattern.search(text))

    @staticmethod
    def _confidence_for(context_kind: str, text: str, token: str) -> str:
        if context_kind.startswith("titleblock_") or context_kind == "code_like" or text == token:
            return "high"
        return "medium"
