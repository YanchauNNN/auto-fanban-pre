from __future__ import annotations

import re

from ..config import get_config
from .lexicon import normalize_text
from .models import AuditFinding, AuditLexicon, ScanTextItem


class AuditMatchEngine:
    def __init__(self, lexicon: AuditLexicon) -> None:
        self.lexicon = lexicon
        audit_cfg = get_config().audit_check
        self.matching_policy = audit_cfg.matching_policy
        self._date_patterns = [re.compile(pattern) for pattern in audit_cfg.context_rules.date_like]
        self._dimension_patterns = [
            re.compile(pattern) for pattern in audit_cfg.context_rules.dimension_like
        ]
        self._internal_code_patterns = [
            re.compile(pattern) for pattern in audit_cfg.context_rules.code_like_internal
        ]
        self._external_code_patterns = [
            re.compile(pattern) for pattern in audit_cfg.context_rules.code_like_external
        ]
        self._generic_identifier_re = re.compile(audit_cfg.generic_identifier_like.regex)
        self._generic_identifier_exempt_patterns = [
            re.compile(pattern)
            for pattern in audit_cfg.generic_identifier_like.exempt_embed_patterns
        ]

    def evaluate(self, *, project_no: str, items: list[ScanTextItem]) -> list[AuditFinding]:
        foreign_tokens = sorted(self.lexicon.foreign_texts.get(project_no, set()), key=len, reverse=True)
        findings: list[AuditFinding] = []

        for item in items:
            normalized_text = normalize_text(item.raw_text)
            if not normalized_text:
                continue

            context_kind = self._classify_context(item.field_context, normalized_text)
            if (
                context_kind == "date_like"
                and self.matching_policy.suppress_project_no_in_date_like
            ) or (
                context_kind == "dimension_like"
                and self.matching_policy.suppress_project_no_in_dimension_like
            ):
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

    def _classify_context(self, field_context: str | None, normalized_text: str) -> str:
        if field_context:
            return field_context
        if any(pattern.fullmatch(normalized_text) for pattern in self._date_patterns):
            return "date_like"
        if any(pattern.fullmatch(normalized_text) for pattern in self._dimension_patterns):
            return "dimension_like"
        if any(pattern.fullmatch(normalized_text) for pattern in self._internal_code_patterns) or any(
            pattern.fullmatch(normalized_text) for pattern in self._external_code_patterns
        ):
            return "code_like"
        if self._generic_identifier_re.fullmatch(normalized_text):
            return "generic_identifier_like"
        return "plain_text"

    def _matches_token(self, *, token: str, text: str, context_kind: str) -> bool:
        if context_kind.startswith("titleblock_"):
            if self.matching_policy.allow_embedded_match_in_titleblock:
                return token in text
            return self._is_strong_boundary_match(token, text)

        if context_kind == "code_like":
            return token in text

        if context_kind == "generic_identifier_like":
            if self._is_exempt_generic_identifier(text, token):
                return False
            return token in text

        if context_kind == "plain_text" and self._is_non_ascii_suffix_match(token, text):
            return True

        if self._is_strong_boundary_match(token, text):
            return True

        return len(token) > 4 and token in text and ("-" in token or any(ord(ch) > 127 for ch in token))

    def _is_exempt_generic_identifier(self, text: str, token: str) -> bool:
        if not token.isdigit():
            return False
        return any(pattern.fullmatch(text) for pattern in self._generic_identifier_exempt_patterns)

    @staticmethod
    def _is_strong_boundary_match(token: str, text: str) -> bool:
        pattern = re.compile(rf"(?<![A-Z0-9]){re.escape(token)}(?![A-Z0-9])")
        return bool(pattern.search(text))

    @staticmethod
    def _is_non_ascii_suffix_match(token: str, text: str) -> bool:
        if not (token.isdigit() and len(token) == 4):
            return False
        if not any(ord(ch) > 127 for ch in text):
            return False
        pattern = re.compile(rf"{re.escape(token)}(?=[^A-Z0-9])")
        return bool(pattern.search(text))

    @staticmethod
    def _confidence_for(context_kind: str, text: str, token: str) -> str:
        if context_kind.startswith("titleblock_") or context_kind == "code_like" or text == token:
            return "high"
        return "medium"
