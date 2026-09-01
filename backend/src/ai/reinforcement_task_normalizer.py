from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..calculation_book.ai_reinforcement_schema import (
    AiReinforcementPayload,
    AiSlabReinforcementRow,
    AiWallReinforcementRow,
    InvalidAiReinforcementPayload,
    ValidatedAiReinforcement,
    validate_ai_reinforcement_payload,
)
from ..calculation_book.reinforcement_input import (
    InvalidReinforcementWorkbook,
    ReinforcementSchedule,
    SlabReinforcementSchedule,
    build_reinforcement_schedule,
    load_reinforcement_schedule,
    load_slab_reinforcement_schedule,
)
from ..calculation_book.reinforcement_workbook import build_workbook_snapshot
from .chat_client import ChatClientError, ChatClientProtocol, ChatCompletionResult

_SKILL_ID = "reinforcement_table_normalizer"
_ValidatedPayload = TypeVar("_ValidatedPayload")
NormalizationErrorCode = Literal[
    "skill_missing",
    "snapshot_too_large",
    "model_output_invalid",
    "model_schema_invalid",
    "model_gateway_failed",
]


class _DeterministicAuditSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_sheet: str = Field(min_length=1)
    source_row: int = Field(ge=1)


class _HybridAuditPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["hybrid-1"]
    source_row_count: int = Field(ge=1)
    patch_rows: tuple[AiWallReinforcementRow, ...] = ()
    review_sources: tuple[_DeterministicAuditSource, ...] = ()


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


@dataclass(frozen=True)
class _DeterministicBaseline:
    wall_schedule: ReinforcementSchedule
    slab_schedule: SlabReinforcementSchedule | None


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
        max_correction_attempts: int = 0,
    ) -> None:
        if max_correction_attempts < 0:
            raise ValueError("max_correction_attempts must not be negative")
        self._client = client
        self.skill_root = Path(skill_root)
        self.limits = limits
        self.max_correction_attempts = max_correction_attempts

    def __repr__(self) -> str:
        return (
            f"ReinforcementTaskNormalizer(skill_root={self.skill_root!r}, limits={self.limits!r})"
        )

    def normalize(
        self,
        workbook_path: Path,
        *,
        include_slab: bool,
        expected_source_row_count: int | None = None,
    ) -> ValidatedAiReinforcement:
        skill_text = self._load_skill_bundle()
        baseline = self._deterministic_baseline(
            Path(workbook_path),
            include_slab=include_slab,
            expected_source_row_count=expected_source_row_count,
        )
        if baseline is not None:
            assert expected_source_row_count is not None
            return self._audit_deterministic_baseline(
                baseline,
                workbook_path=Path(workbook_path),
                skill_text=skill_text,
                include_slab=include_slab,
                expected_source_row_count=expected_source_row_count,
            )
        snapshot_json, snapshot = self._build_snapshot_json(Path(workbook_path))
        messages = self._messages(
            skill_text=skill_text,
            snapshot_json=snapshot_json,
            include_slab=include_slab,
            expected_source_row_count=expected_source_row_count,
        )

        def validate_response(content: str) -> ValidatedAiReinforcement:
            last_error: ReinforcementTaskNormalizationError | None = None
            for raw_payload in self._decode_model_output(content):
                try:
                    payload = AiReinforcementPayload.model_validate(
                        self._sanitize_full_payload(raw_payload)
                    )
                    if not include_slab and any(
                        isinstance(row, AiSlabReinforcementRow) for row in payload.rows
                    ):
                        raise ReinforcementTaskNormalizationError(
                            "model_schema_invalid",
                            "model output contains slab rows while slab normalization is disabled",
                        )
                    return validate_ai_reinforcement_payload(
                        payload,
                        snapshot=snapshot,
                        expected_source_row_count=expected_source_row_count,
                    )
                except ValidationError:
                    last_error = ReinforcementTaskNormalizationError(
                        "model_schema_invalid",
                        "model output does not match reinforcement schema v1",
                    )
                except InvalidAiReinforcementPayload:
                    last_error = ReinforcementTaskNormalizationError(
                        "model_schema_invalid",
                        "model output failed reinforcement evidence or row-conservation validation",
                    )
                except ReinforcementTaskNormalizationError as exc:
                    last_error = exc
            assert last_error is not None
            raise last_error

        return self._complete_until_valid(messages, validate_response)

    @staticmethod
    def _deterministic_baseline(
        workbook_path: Path,
        *,
        include_slab: bool,
        expected_source_row_count: int | None,
    ) -> _DeterministicBaseline | None:
        if expected_source_row_count is None:
            return None
        try:
            wall_schedule = load_reinforcement_schedule(workbook_path)
            slab_schedule = (
                load_slab_reinforcement_schedule(
                    workbook_path,
                    required=False,
                )
                if include_slab
                else None
            )
        except InvalidReinforcementWorkbook:
            return None
        total_source_rows = wall_schedule.source_row_count + (
            len(slab_schedule.rows) if slab_schedule is not None else 0
        )
        if total_source_rows != expected_source_row_count:
            return None
        return _DeterministicBaseline(
            wall_schedule=wall_schedule,
            slab_schedule=slab_schedule,
        )

    def _audit_deterministic_baseline(
        self,
        baseline: _DeterministicBaseline,
        *,
        workbook_path: Path,
        skill_text: str,
        include_slab: bool,
        expected_source_row_count: int,
    ) -> ValidatedAiReinforcement:
        schedule = baseline.wall_schedule
        duplicate_ids = set(schedule.duplicate_wall_ids)
        duplicate_rows = [
            {
                "source_sheet": row.source_sheet,
                "source_row": row.source_row,
                "source_cells": row.source_cells,
                "wall_id": row.wall_id,
                "X": row.x.original_text,
                "Y": row.y.original_text,
                "Z": row.z.original_text,
            }
            for row in schedule.rows
            if row.wall_id in duplicate_ids
        ]
        issue_rows = [
            {
                "source_sheet": issue.source_sheet,
                "source_row": issue.source_row,
                "source_cells": issue.source_cells,
                "original_values": issue.original_values,
                "wall_id": issue.wall_id,
            }
            for issue in schedule.issues
        ]
        audit_json = json.dumps(
            {
                "source_row_count": expected_source_row_count,
                "wall_source_row_count": schedule.source_row_count,
                "normalized_row_count": len(schedule.rows),
                "issue_row_count": len(schedule.issues),
                "duplicate_wall_ids": list(schedule.duplicate_wall_ids),
                "duplicate_rows": duplicate_rows,
                "issues": issue_rows,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(audit_json) > self.limits.max_snapshot_chars:
            raise ReinforcementTaskNormalizationError(
                "snapshot_too_large",
                "deterministic reinforcement audit exceeds its safe character limit",
            )
        messages = self._audit_messages(
            skill_text=skill_text,
            audit_json=audit_json,
            include_slab=include_slab,
            expected_source_row_count=expected_source_row_count,
        )

        def validate_response(content: str) -> ValidatedAiReinforcement:
            last_error: ReinforcementTaskNormalizationError | None = None
            for raw_payload in self._decode_model_output(content):
                try:
                    audit = _HybridAuditPayload.model_validate(
                        self._sanitize_hybrid_payload(raw_payload)
                    )
                    return self._validate_hybrid_audit(
                        audit,
                        baseline=baseline,
                        workbook_path=workbook_path,
                        expected_source_row_count=expected_source_row_count,
                    )
                except ValidationError:
                    last_error = ReinforcementTaskNormalizationError(
                        "model_schema_invalid",
                        "model output does not match hybrid audit schema v1",
                    )
                except ReinforcementTaskNormalizationError as exc:
                    last_error = exc
            assert last_error is not None
            raise last_error

        return self._complete_until_valid(messages, validate_response)

    def _validate_hybrid_audit(
        self,
        audit: _HybridAuditPayload,
        *,
        baseline: _DeterministicBaseline,
        workbook_path: Path,
        expected_source_row_count: int,
    ) -> ValidatedAiReinforcement:
        schedule = baseline.wall_schedule
        duplicate_ids = set(schedule.duplicate_wall_ids)
        if audit.source_row_count != expected_source_row_count:
            raise ReinforcementTaskNormalizationError(
                "model_schema_invalid",
                "deterministic audit row conservation failed",
            )

        duplicate_sources = {
            (row.source_sheet, row.source_row)
            for row in schedule.rows
            if row.wall_id in duplicate_ids
        }
        reported_sources = {
            (source.source_sheet, source.source_row) for source in audit.review_sources
        }
        if len(reported_sources) != len(audit.review_sources) or not reported_sources.issubset(
            duplicate_sources
        ):
            raise ReinforcementTaskNormalizationError(
                "model_schema_invalid",
                "deterministic audit review sources are not duplicate-row evidence",
            )

        issue_sources = {(issue.source_sheet, issue.source_row) for issue in schedule.issues}
        patch_sources = {(row.source_sheet, row.source_row) for row in audit.patch_rows}
        if len(patch_sources) != len(audit.patch_rows) or patch_sources != issue_sources:
            raise ReinforcementTaskNormalizationError(
                "model_schema_invalid",
                "hybrid audit patches do not conserve deterministic issue rows",
            )

        patch_rows = ()
        patch_issues = ()
        patch_warnings = ()
        if audit.patch_rows:
            snapshot = build_workbook_snapshot(
                workbook_path,
                max_non_empty_cells=self.limits.max_non_empty_cells,
            )
            patch_payload = AiReinforcementPayload.model_validate(
                {
                    "schema_version": "1",
                    "source_row_count": len(audit.patch_rows),
                    "rows": [row.model_dump() for row in audit.patch_rows],
                }
            )
            try:
                validated_patch = validate_ai_reinforcement_payload(
                    patch_payload,
                    snapshot=snapshot,
                    expected_source_row_count=len(audit.patch_rows),
                )
            except InvalidAiReinforcementPayload as exc:
                raise ReinforcementTaskNormalizationError(
                    "model_schema_invalid",
                    "hybrid audit patch evidence validation failed",
                ) from exc
            patch_rows = validated_patch.wall_schedule.rows
            patch_issues = validated_patch.wall_schedule.issues
            patch_warnings = validated_patch.warnings

        merged_schedule = build_reinforcement_schedule(
            rows=(*schedule.rows, *patch_rows),
            issues=patch_issues,
            source_row_count=schedule.source_row_count,
            normalization_triggered=True,
        )
        return ValidatedAiReinforcement(
            wall_schedule=merged_schedule,
            slab_schedule=baseline.slab_schedule,
            warnings=patch_warnings,
            source_row_count=expected_source_row_count,
        )

    def _complete_until_valid(
        self,
        messages: list[dict[str, str]],
        validator: Callable[[str], _ValidatedPayload],
    ) -> _ValidatedPayload:
        current_messages = messages
        last_error: ReinforcementTaskNormalizationError | None = None
        for attempt in range(self.max_correction_attempts + 1):
            completion = self._complete(current_messages)
            try:
                return validator(completion.content)
            except ReinforcementTaskNormalizationError as exc:
                if exc.code not in {"model_output_invalid", "model_schema_invalid"}:
                    raise
                last_error = exc
                if attempt >= self.max_correction_attempts:
                    break
                current_messages = [
                    *messages,
                    {
                        "role": "user",
                        "content": (
                            "上一次响应未通过结构或证据校验。只返回一个紧凑 JSON 对象；"
                            "不要解释、不要使用 Markdown 代码块、不要增加 schema 以外字段。"
                            "必须保持源行数量和来源单元格证据守恒。"
                        ),
                    },
                ]
        assert last_error is not None
        raise last_error from None

    @staticmethod
    def _audit_messages(
        *,
        skill_text: str,
        audit_json: str,
        include_slab: bool,
        expected_source_row_count: int,
    ) -> list[dict[str, str]]:
        system = (
            f"执行 skill_id={_SKILL_ID} 的 deterministic-audit 模式。"
            "后端确定性解析器已将已确定墙体行作为基线，issues 只允许 patch；"
            "不得重复输出已确定的 rows，也不得回显已确定行的配筋字段；"
            "patch_rows 仅可返回 issue 行的规范字段，仍禁止返回 actual_area。"
            "只返回无换行紧凑 JSON："
            '{"schema_version":"hybrid-1","source_row_count":N,'
            '"patch_rows":[],"review_sources":[]}。'
            "patch_rows 必须与 issues 的物理来源行一一守恒，"
            "格式与 wall schema v1 行完全一致；"
            'review_sources 每项只能包含 {"source_sheet":"表名","source_row":行号}，'
            "严禁增加 wall_id、source_cells 或说明字段；"
            "review_sources 只能列出 duplicate_wall_ids 对应的来源行；"
            "没有额外复核行时必须返回空数组。完整 Skill 如下：\n\n"
            f"{skill_text}"
        )
        user = (
            f"include_slab={'true' if include_slab else 'false'}。"
            f"source_row_count 必须等于 {expected_source_row_count}。"
            "只审计以下 issue/duplicate 证据，禁止回显其他已确定行：\n"
            f"{audit_json}"
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def _complete(self, messages: list[dict[str, str]]) -> ChatCompletionResult:
        try:
            return self._client.complete(messages)
        except ChatClientError:
            pass
        raise ReinforcementTaskNormalizationError(
            "model_gateway_failed",
            "reinforcement model gateway request failed",
        )

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
            "必须返回无缩进、无换行的紧凑 JSON，不得输出不必要空白；"
            "严禁解释文字、Markdown 代码块和 schema 之外的字段；"
            "不得返回/计算实际配筋面积（actual_area），不得输出文件或生成 Excel。"
            "未知值必须使用 status=needs_review，未确定字段保持 null，并填写 blank_fields 和 reason。"
            "必须保留 source_sheet/source_row/source_cells 证据和物理来源行守恒；"
            "不得跨 wall/slab kind 复制来源行凑数。完整 Skill 如下：\n\n"
            f"{skill_text}"
        )
        include_slab_text = "true" if include_slab else "false"
        row_count_constraint = (
            "expected_source_row_count 未提供；请按 snapshot 识别物理来源行，不得杜撰固定源行数。"
            if expected_source_row_count is None
            else (
                f"schema 的 source_row_count 与 rows 数量都必须等于 {expected_source_row_count}。"
            )
        )
        scope_instruction = (
            "同时识别 wall 与 slab。" if include_slab else "仅识别 wall，忽略 slab；不得杜撰 slab。"
        )
        user = (
            f"include_slab={include_slab_text}。{scope_instruction}"
            f"{row_count_constraint}"
            "只依据以下安全 workbook snapshot 返回 JSON，不解释、不加额外代码块：\n"
            f"{snapshot_json}"
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    @staticmethod
    def _decode_model_output(content: str) -> tuple[dict[str, object], ...]:
        if not isinstance(content, str):
            raise ReinforcementTaskNormalizationError(
                "model_output_invalid",
                "model output does not contain a JSON object",
            )
        decoder = json.JSONDecoder()
        candidates: list[dict[str, object]] = []
        for index, char in enumerate(content):
            if char != "{":
                continue
            try:
                decoded, _ = decoder.raw_decode(content, index)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, dict) and decoded not in candidates:
                candidates.append(decoded)
        if not candidates:
            raise ReinforcementTaskNormalizationError(
                "model_output_invalid",
                "model output does not contain a JSON object",
            )
        return tuple(candidates)

    @staticmethod
    def _sanitize_full_payload(payload: dict[str, object]) -> dict[str, object]:
        return {
            key: value
            for key, value in payload.items()
            if key in {"schema_version", "source_row_count", "rows"}
        } | {
            "rows": [
                ReinforcementTaskNormalizer._sanitize_row(row)
                for row in payload.get("rows", [])
                if isinstance(row, dict)
            ]
        }

    @staticmethod
    def _sanitize_hybrid_payload(payload: dict[str, object]) -> dict[str, object]:
        patch_rows = payload.get("patch_rows", [])
        review_sources = payload.get("review_sources", [])
        return {
            "schema_version": payload.get("schema_version"),
            "source_row_count": payload.get("source_row_count"),
            "patch_rows": [
                ReinforcementTaskNormalizer._sanitize_row(row)
                for row in patch_rows
                if isinstance(row, dict)
            ]
            if isinstance(patch_rows, list)
            else patch_rows,
            "review_sources": [
                {
                    key: value
                    for key, value in source.items()
                    if key in {"source_sheet", "source_row"}
                }
                for source in review_sources
                if isinstance(source, dict)
            ]
            if isinstance(review_sources, list)
            else review_sources,
        }

    @staticmethod
    def _sanitize_row(row: dict[str, object]) -> dict[str, object]:
        kind = row.get("kind")
        if kind == "wall":
            allowed = set(AiWallReinforcementRow.model_fields)
            cell_fields = {"wall", "X", "Y", "Z"}
        elif kind == "slab":
            allowed = set(AiSlabReinforcementRow.model_fields)
            cell_fields = {
                "elevation",
                "top_x",
                "top_y",
                "middle_x",
                "middle_y",
                "bottom_x",
                "bottom_y",
                "z",
            }
        else:
            return {key: value for key, value in row.items() if key == "kind"}
        sanitized = {key: value for key, value in row.items() if key in allowed}
        source_cells = sanitized.get("source_cells")
        if isinstance(source_cells, dict):
            sanitized["source_cells"] = {
                key: value for key, value in source_cells.items() if key in cell_fields
            }
        return sanitized
