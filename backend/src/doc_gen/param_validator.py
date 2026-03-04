"""
文档参数校验器 - 在模块6入口校验 required/required_when/format。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from ..config import load_spec
from ..models import DocContext

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
            value = params.get(field_name)
            if self._is_required(rule, params) and self._is_empty(value):
                errors.append(f"文档参数缺失: {field_name}")
                continue

            fmt = rule.get("format")
            if fmt and not self._is_empty(value) and not self._validate_format(str(value), str(fmt)):
                errors.append(f"文档参数格式错误: {field_name} (要求: {fmt})")

        return errors

    def _flatten_param_rules(self) -> dict[str, dict[str, Any]]:
        params_cfg = self.spec.doc_generation.get("params", {})
        flat: dict[str, dict[str, Any]] = {}

        for section in params_cfg.values():
            if not isinstance(section, dict):
                continue
            for field_name, rule in section.items():
                if isinstance(rule, dict):
                    flat[field_name] = rule

        return flat

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

        return True
