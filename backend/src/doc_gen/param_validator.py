"""
文档参数校验器 - 在模块6入口校验 required/required_when/format。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from ..config import get_config, load_spec
from ..models import DocContext, GlobalDocParams, normalize_global_doc_params
from .upgrade_marking import UpgradeSheetCodeParseError, parse_upgrade_sheet_codes

_COND_RE = re.compile(
    r"""^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(==|!=)\s*['"]([^'"]*)['"]\s*$""",
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NAME_ID_RE = re.compile(r"^[^@\s]+@[A-Za-z0-9_-]+$")


class DocParamValidator:
    """按参数规范校验模块6入口参数。"""

    def __init__(self, spec_path: str | None = None):
        self.spec = load_spec(spec_path) if spec_path else load_spec()

    def validate(self, ctx: DocContext) -> list[str]:
        """返回校验错误列表（为空表示通过）。"""
        errors: list[str] = []
        params = ctx.params.model_dump()
        field_rules = self._flatten_param_rules()

        for field_name, rule in field_rules.items():
            if self._should_skip_ied_field(field_name, params):
                continue

            value = params.get(field_name)
            if self._is_required(rule, params) and self._is_empty(value):
                errors.append(f"文档参数缺失: {field_name}")
                continue

            fmt = rule.get("format")
            if fmt and not self._is_empty(value) and not self._validate_format(str(value), str(fmt)):
                errors.append(f"文档参数格式错误: {field_name} (要求: {fmt})")

        return errors

    def validate_frontend_params(self, raw_params: dict[str, Any]) -> dict[str, list[str]]:
        """按 YAML 中 `source: frontend` 规则校验前端提交参数。"""
        errors: dict[str, list[str]] = {}
        normalized = self._normalize_frontend_values(raw_params)
        field_rules = self._flatten_param_rules(source="frontend")

        for field_name, rule in field_rules.items():
            if self._should_skip_ied_field(field_name, normalized):
                continue

            value = normalized.get(field_name)
            if self._is_required(rule, normalized) and self._is_empty(value):
                errors.setdefault(field_name, []).append("required")
                continue

            fmt = rule.get("format")
            if (
                field_name == "upgrade_sheet_codes"
                and not self._coerce_bool(normalized.get("is_upgrade"))
            ):
                continue

            if fmt and not self._is_empty(value) and not self._validate_format(str(value), str(fmt)):
                errors.setdefault(field_name, []).append(f"format:{fmt}")

        return errors

    def validate_replace_frontend_params(self, raw_params: dict[str, Any]) -> dict[str, list[str]]:
        errors: dict[str, list[str]] = {}
        source_project_no = str(raw_params.get("source_project_no") or "").strip()
        target_project_no = str(raw_params.get("target_project_no") or "").strip()
        run_deliverable = self._coerce_bool(raw_params.get("run_deliverable"))

        if not source_project_no:
            errors.setdefault("source_project_no", []).append("required_for_replace")
        if not target_project_no:
            errors.setdefault("target_project_no", []).append("required_for_replace")
        elif source_project_no and source_project_no == target_project_no:
            errors.setdefault("target_project_no", []).append("must_differ_from_source_project_no")
        self._validate_factory_index_variants(
            raw_params,
            errors,
            source_project_no=source_project_no,
            target_project_no=target_project_no,
        )

        if not run_deliverable:
            return errors

        deliverable_params = raw_params.get("deliverable_params")
        if not isinstance(deliverable_params, dict):
            errors.setdefault("deliverable_params", []).append("invalid_deliverable_params")
            return errors

        nested_errors = self.validate_frontend_params(deliverable_params)
        if nested_errors:
            errors.setdefault("deliverable_params", []).append("invalid_deliverable_params")
        return errors

    def _validate_factory_index_variants(
        self,
        raw_params: dict[str, Any],
        errors: dict[str, list[str]],
        *,
        source_project_no: str,
        target_project_no: str,
    ) -> None:
        factory_config = get_config().factory_index_maps
        source_rules = factory_config.source_variant_rules.get(source_project_no)
        if source_rules:
            source_variant = self._first_normalized_variant(
                raw_params,
                factory_config.source_variant_param_names,
            )
            if not source_variant:
                errors.setdefault("source_island_no", []).append("required_for_source_project")
            elif source_variant not in source_rules:
                errors.setdefault("source_island_no", []).append("unsupported_source_island_no")

        target_templates = factory_config.island_templates.get(target_project_no)
        if target_templates:
            target_names = list(factory_config.target_variant_param_names)
            for legacy_name in factory_config.variant_param_names:
                if legacy_name not in target_names:
                    target_names.append(legacy_name)
            target_variant = self._first_normalized_variant(raw_params, target_names)
            if not target_variant:
                errors.setdefault("target_island_no", []).append("required_for_target_project")
            elif target_variant not in target_templates:
                errors.setdefault("target_island_no", []).append("unsupported_target_island_no")

    @staticmethod
    def _first_normalized_variant(raw_params: dict[str, Any], names: list[str]) -> str | None:
        for name in names:
            value = raw_params.get(name)
            text = str(value or "").strip()
            if not text:
                continue
            match = re.search(r"[1-9]", text)
            if match:
                return match.group(0)
        return None

    def _flatten_param_rules(self, source: str | None = None) -> dict[str, dict[str, Any]]:
        params_cfg = self.spec.doc_generation.get("params", {})
        flat: dict[str, dict[str, Any]] = {}

        for section in params_cfg.values():
            if not isinstance(section, dict):
                continue
            for field_name, rule in section.items():
                if isinstance(rule, dict):
                    if source is not None and rule.get("source") != source:
                        continue
                    flat[field_name] = rule

        return flat

    def _normalize_frontend_values(self, raw_params: dict[str, Any]) -> dict[str, Any]:
        if "project_no" not in raw_params or self._is_empty(raw_params.get("project_no")):
            return dict(raw_params)

        normalized_params = normalize_global_doc_params(raw_params)

        try:
            params = GlobalDocParams(**normalized_params)
        except Exception:
            return dict(normalized_params)

        return params.model_dump()

    def _is_required(self, rule: dict[str, Any], values: dict[str, Any]) -> bool:
        if bool(rule.get("required")):
            return True

        condition = rule.get("required_when")
        if not condition:
            return False

        return self._eval_condition(str(condition), values)

    def _eval_condition(self, expr: str, values: dict[str, Any]) -> bool:
        m = _COND_RE.match(expr)
        if not m:
            return False

        field_name, op, expected = m.groups()
        actual = values.get(field_name)
        actual_text = "" if actual is None else str(actual)

        if op == "==":
            return actual_text == expected
        if op == "!=":
            return actual_text != expected
        return False

    @staticmethod
    def _is_empty(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip() == ""
        return False

    def _should_skip_ied_field(self, field_name: str, values: dict[str, Any]) -> bool:
        if not field_name.startswith("ied_"):
            return False
        return not self._coerce_bool(values.get("include_ied_plan", True))

    def _validate_format(self, value: str, fmt: str) -> bool:
        if fmt == "YYYY-MM-DD":
            if not _DATE_RE.match(value):
                return False
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                return False
            return True

        if fmt == "姓名@ID":
            return _NAME_ID_RE.match(value) is not None

        if fmt == "upgrade-sheet-codes":
            try:
                parse_upgrade_sheet_codes(value)
            except UpgradeSheetCodeParseError:
                return False
            return True

        return True

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        text = str(value or "").strip().lower()
        return text in {"1", "true", "yes", "on"}
