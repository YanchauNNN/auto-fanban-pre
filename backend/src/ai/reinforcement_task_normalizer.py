from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from ..calculation_book.ai_reinforcement_schema import (
    AiReinforcementPayload,
    AiSlabReinforcementRow,
    InvalidAiReinforcementPayload,
    ValidatedAiReinforcement,
    validate_ai_reinforcement_payload,
)
from ..calculation_book.reinforcement_workbook import build_workbook_snapshot
from .chat_client import ChatClientProtocol

_SKILL_ID = "reinforcement_table_normalizer"
_FENCED_JSON = re.compile(r"\A```json[ \t]*\r?\n(?P<body>.*)\r?\n```[ \t]*\Z", re.DOTALL)
NormalizationErrorCode = Literal[
    "skill_missing",
    "snapshot_too_large",
    "model_output_invalid",
    "model_schema_invalid",
]


@dataclass(frozen=True)
class ReinforcementTaskNormalizerLimits:
    max_non_empty_cells: int = 10_000
    max_snapshot_chars: int = 500_000
    max_skill_chars: int = 100_000

    def __post_init__(self) -> None:
        for name, value in (
            ("max_non_empty_cells", self.max_non_empty_cells),
            ("max_snapshot_chars", self.max_snapshot_chars),
            ("max_skill_chars", self.max_skill_chars),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be greater than 0")


class ReinforcementTaskNormalizationError(RuntimeError):
    def __init__(self, code: NormalizationErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class ReinforcementTaskNormalizer:
    def __init__(
        self,
        *,
        client: ChatClientProtocol,
        skill_root: Path,
        limits: ReinforcementTaskNormalizerLimits,
    ) -> None:
        self._client = client
        self.skill_root = Path(skill_root)
        self.limits = limits

    def __repr__(self) -> str:
        return (
            "ReinforcementTaskNormalizer("
            f"skill_root={self.skill_root!r}, limits={self.limits!r})"
        )

    def normalize(
        self,
        workbook_path: Path,
        *,
        include_slab: bool,
        expected_source_row_count: int | None = None,
    ) -> ValidatedAiReinforcement:
        skill_text = self._load_skill_bundle()
        snapshot_json, snapshot = self._build_snapshot_json(Path(workbook_path))
        messages = self._messages(
            skill_text=skill_text,
            snapshot_json=snapshot_json,
            include_slab=include_slab,
            expected_source_row_count=expected_source_row_count,
        )
        completion = self._client.complete(messages)
        raw_payload = self._decode_model_output(completion.content)
        try:
            payload = AiReinforcementPayload.model_validate(raw_payload)
        except ValidationError as exc:
            raise ReinforcementTaskNormalizationError(
                "model_schema_invalid",
                "model output does not match reinforcement schema v1",
            ) from exc

        if not include_slab and any(
            isinstance(row, AiSlabReinforcementRow) for row in payload.rows
        ):
            raise ReinforcementTaskNormalizationError(
                "model_schema_invalid",
                "model output contains slab rows while slab normalization is disabled",
            )
        try:
            return validate_ai_reinforcement_payload(
                payload,
                snapshot=snapshot,
                expected_source_row_count=expected_source_row_count,
            )
        except InvalidAiReinforcementPayload as exc:
            raise ReinforcementTaskNormalizationError(
                "model_schema_invalid",
                "model output failed reinforcement evidence or row-conservation validation",
            ) from exc

    def _load_skill_bundle(self) -> str:
        root = self.skill_root.resolve()
        paths = (
            root / "SKILL.md",
            root / "references" / "normalization-rules.md",
        )
        remaining = self.limits.max_skill_chars
        parts: list[str] = []
        for path in paths:
            resolved = path.resolve()
            if not resolved.is_relative_to(root) or not resolved.is_file():
                raise ReinforcementTaskNormalizationError(
                    "skill_missing",
                    "reinforcement normalization Skill bundle is unavailable",
                )
            try:
                with resolved.open(encoding="utf-8") as stream:
                    content = stream.read(remaining + 1)
            except (OSError, UnicodeError) as exc:
                raise ReinforcementTaskNormalizationError(
                    "skill_missing",
                    "reinforcement normalization Skill bundle is unreadable",
                ) from exc
            if len(content) > remaining:
                raise ReinforcementTaskNormalizationError(
                    "skill_missing",
                    "reinforcement normalization Skill bundle exceeds its size limit",
                )
            remaining -= len(content)
            parts.append(f"## {resolved.relative_to(root).as_posix()}\n{content}")
        return "\n\n".join(parts)

    def _build_snapshot_json(
        self,
        workbook_path: Path,
    ) -> tuple[str, dict[str, object]]:
        try:
            snapshot = build_workbook_snapshot(
                workbook_path,
                max_non_empty_cells=self.limits.max_non_empty_cells,
            )
        except ValueError as exc:
            if "limit" not in str(exc) and "max_non_empty_cells" not in str(exc):
                raise
            raise ReinforcementTaskNormalizationError(
                "snapshot_too_large",
                "workbook snapshot exceeds its safe cell limit",
            ) from exc
        snapshot_json = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(snapshot_json) > self.limits.max_snapshot_chars:
            raise ReinforcementTaskNormalizationError(
                "snapshot_too_large",
                "workbook snapshot exceeds its safe character limit",
            )
        return snapshot_json, snapshot

    @staticmethod
    def _messages(
        *,
        skill_text: str,
        snapshot_json: str,
        include_slab: bool,
        expected_source_row_count: int | None,
    ) -> list[dict[str, str]]:
        system = (
            f"执行 skill_id={_SKILL_ID}。只返回 schema v1 的单个 JSON 对象；"
            "不得返回/计算实际配筋面积（actual_area），不得输出文件或生成 Excel。"
            "未知值必须使用 status=needs_review，未确定字段保持 null，并填写 blank_fields 和 reason。"
            "必须保留 source_sheet/source_row/source_cells 证据和物理来源行守恒；"
            "不得跨 wall/slab kind 复制来源行凑数。完整 Skill 如下：\n\n"
            f"{skill_text}"
        )
        include_slab_text = "true" if include_slab else "false"
        row_count_constraint = (
            "expected_source_row_count 未提供；请按 snapshot 识别物理来源行，"
            "不得杜撰固定源行数。"
            if expected_source_row_count is None
            else (
                "schema 的 source_row_count 与 rows 数量都必须等于 "
                f"{expected_source_row_count}。"
            )
        )
        user = (
            f"include_slab={include_slab_text}。同时识别 wall 与 slab；"
            "include_slab=false 时不得杜撰 slab。"
            f"{row_count_constraint}"
            "只依据以下安全 workbook snapshot 返回 JSON，不解释、不加额外代码块：\n"
            f"{snapshot_json}"
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    @staticmethod
    def _decode_model_output(content: str) -> dict[str, object]:
        candidate = content.strip()
        fenced = _FENCED_JSON.fullmatch(candidate)
        if fenced is not None:
            candidate = fenced.group("body")
        try:
            decoded = json.loads(candidate)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ReinforcementTaskNormalizationError(
                "model_output_invalid",
                "model output is not plain JSON or one complete json code fence",
            ) from exc
        if not isinstance(decoded, dict):
            raise ReinforcementTaskNormalizationError(
                "model_output_invalid",
                "model output must be one JSON object",
            )
        return decoded
