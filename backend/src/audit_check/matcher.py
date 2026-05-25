from __future__ import annotations

import re

from ..config import get_config
from .lexicon import normalize_text, normalize_text_without_spaces
from .models import AuditFinding, AuditLexicon, ScanTextItem

FORBIDDEN_DISCIPLINE_WORD = "工种"


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
        self._unit_consistency = audit_cfg.unit_consistency

    def evaluate(
        self,
        *,
        project_no: str,
        items: list[ScanTextItem],
        unit_no: str | None = None,
    ) -> list[AuditFinding]:
        foreign_tokens = sorted(self.lexicon.foreign_texts.get(project_no, set()), key=len, reverse=True)
        findings: list[AuditFinding] = []
        normalized_unit_no = str(unit_no or "").strip()
        normalized_items = [
            (item, normalize_text(item.raw_text))
            for item in items
        ]
        unit_code_pattern = self._compile_unit_code_pattern(project_no)
        observed_factory_codes = self._collect_observed_factory_codes(
            unit_code_pattern=unit_code_pattern,
            normalized_texts=[normalized_text for _, normalized_text in normalized_items],
        )

        for item, normalized_text in normalized_items:
            if not normalized_text:
                continue

            context_kind = self._classify_context(item.field_context, normalized_text)
            if FORBIDDEN_DISCIPLINE_WORD in normalized_text:
                findings.append(
                    AuditFinding(
                        raw_text=item.raw_text,
                        matched_text=FORBIDDEN_DISCIPLINE_WORD,
                        matched_project_nos=[],
                        context_kind="forbidden_term",
                        confidence="high",
                        entity_type=item.entity_type,
                        field_context=item.field_context,
                        internal_code=item.internal_code,
                        layout_name=item.layout_name,
                        entity_handle=item.entity_handle,
                        block_path=item.block_path,
                        position_x=item.position_x,
                        position_y=item.position_y,
                        text_bbox=item.text_bbox,
                    )
                )

            findings.extend(
                self._unit_consistency_findings(
                    project_no=project_no,
                    unit_no=normalized_unit_no,
                    item=item,
                    normalized_text=normalized_text,
                    unit_code_pattern=unit_code_pattern,
                    observed_factory_codes=observed_factory_codes,
                )
            )
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
                            text_bbox=item.text_bbox,
                        )
                    )

        return findings

    def _unit_consistency_findings(
        self,
        *,
        project_no: str,
        unit_no: str,
        item: ScanTextItem,
        normalized_text: str,
        unit_code_pattern: re.Pattern[str],
        observed_factory_codes: set[str],
    ) -> list[AuditFinding]:
        if not self._unit_consistency.enabled or not project_no or not unit_no:
            return []
        allowed_units = [
            str(value).strip()
            for value in self._unit_consistency.project_units.get(project_no, [])
        ]
        if unit_no not in allowed_units:
            return []

        findings: list[AuditFinding] = []
        seen: set[tuple[str, str]] = set()
        for pattern in [unit_code_pattern, re.compile(self._unit_consistency.explicit_unit_text_pattern)]:
            for match in pattern.finditer(normalized_text):
                self._append_unit_consistency_finding(
                    findings=findings,
                    seen=seen,
                    project_no=project_no,
                    selected_unit_no=unit_no,
                    item=item,
                    match=match,
                )

        short_pattern = re.compile(self._unit_consistency.short_factory_code_pattern)
        for match in short_pattern.finditer(normalized_text):
            factory_code = str(match.group("factory_code") or "").strip().upper()
            if (
                self._unit_consistency.short_factory_code_requires_observed_album_factory
                and factory_code not in observed_factory_codes
            ):
                continue
            self._append_unit_consistency_finding(
                findings=findings,
                seen=seen,
                project_no=project_no,
                selected_unit_no=unit_no,
                item=item,
                match=match,
            )
        return findings

    @staticmethod
    def _collect_observed_factory_codes(
        *,
        unit_code_pattern: re.Pattern[str],
        normalized_texts: list[str],
    ) -> set[str]:
        factory_codes: set[str] = set()
        for normalized_text in normalized_texts:
            for match in unit_code_pattern.finditer(normalized_text):
                factory_code = str(match.group("factory_code") or "").strip().upper()
                if factory_code:
                    factory_codes.add(factory_code)
        return factory_codes

    @staticmethod
    def _append_unit_consistency_finding(
        *,
        findings: list[AuditFinding],
        seen: set[tuple[str, str]],
        project_no: str,
        selected_unit_no: str,
        item: ScanTextItem,
        match: re.Match[str],
    ) -> None:
        matched_unit = str(match.group("unit_no") or "").strip()
        matched_text = match.group(0)
        key = (matched_text, matched_unit)
        if not matched_unit or matched_unit == selected_unit_no or key in seen:
            return
        seen.add(key)
        findings.append(
            AuditFinding(
                raw_text=item.raw_text,
                matched_text=matched_text,
                matched_project_nos=[project_no],
                context_kind="unit_consistency",
                confidence="high",
                entity_type=item.entity_type,
                field_context=item.field_context,
                internal_code=item.internal_code,
                layout_name=item.layout_name,
                entity_handle=item.entity_handle,
                block_path=item.block_path,
                position_x=item.position_x,
                position_y=item.position_y,
                text_bbox=item.text_bbox,
            )
        )

    def _compile_unit_code_pattern(self, project_no: str) -> re.Pattern[str]:
        pattern = self._unit_consistency.code_pattern.replace(
            "{project_no}",
            re.escape(str(project_no or "").strip()),
        )
        return re.compile(pattern)

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
        if AuditMatchEngine._contains_token_exact(token, text):
            return True

        if normalize_text_without_spaces(token) == token:
            return False

        return AuditMatchEngine._contains_token_exact(
            normalize_text_without_spaces(token),
            normalize_text_without_spaces(text),
        )

    @staticmethod
    def _contains_token_exact(token: str, text: str) -> bool:
        if token not in text:
            return False
        if not (token.isascii() and token.isalpha()):
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
