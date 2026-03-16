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
        self._project_identifier_whitelist_patterns = [
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
        if self._is_whitelisted_project_identifier(text, token):
            return False

        if context_kind.startswith("titleblock_"):
            if self.matching_policy.allow_embedded_match_in_titleblock:
                return self._contains_token(token, text)
            return self._is_strong_boundary_match(token, text)

        return self._contains_token(token, text)

    def _is_whitelisted_project_identifier(self, text: str, token: str) -> bool:
        if not token.isdigit():
            return False
        return any(pattern.fullmatch(text) for pattern in self._project_identifier_whitelist_patterns)

    @staticmethod
    def _is_strong_boundary_match(token: str, text: str) -> bool:
        pattern = re.compile(rf"(?<![A-Z0-9]){re.escape(token)}(?![A-Z0-9])")
        return bool(pattern.search(text))

    @staticmethod
    def _contains_token(token: str, text: str) -> bool:
        if token not in text:
            return False
        if not token.isalpha():
            return True

        start = 0
        token_length = len(token)
        while True:
            index = text.find(token, start)
            if index < 0:
                return False

            left_char = text[index - 1] if index > 0 else ""
            right_index = index + token_length
            right_char = text[right_index] if right_index < len(text) else ""
            if not (left_char.isalpha() or right_char.isalpha()):
                return True

            start = index + 1

    @staticmethod
    def _confidence_for(context_kind: str, text: str, token: str) -> str:
        if context_kind.startswith("titleblock_") or context_kind == "code_like" or text == token:
            return "high"
        return "medium"
