from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .reinforcement_input import (
    InvalidReinforcementWorkbook,
    NormalizedReinforcementRow,
    NormalizedSlabReinforcementRow,
    ParsedRebarCell,
    ReinforcementRowIssue,
    ReinforcementSchedule,
    SlabReinforcementSchedule,
    build_reinforcement_schedule,
    normalize_slab_elevation,
    normalize_wall_id,
    parse_linear_rebar_cell,
    parse_rebar_cell,
)


class InvalidAiReinforcementPayload(ValueError):
    pass


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AiWallSourceCells(_StrictModel):
    wall: str | None = None
    X: str | None = None
    Y: str | None = None
    Z: str | None = None


class AiSlabSourceCells(_StrictModel):
    elevation: str | None = None
    top_x: str | None = None
    top_y: str | None = None
    middle_x: str | None = None
    middle_y: str | None = None
    bottom_x: str | None = None
    bottom_y: str | None = None
    z: str | None = None


WallBlankField = Literal["wall_id", "X", "Y", "Z"]
SlabBlankField = Literal[
    "elevation",
    "top_x",
    "top_y",
    "middle_x",
    "middle_y",
    "bottom_x",
    "bottom_y",
    "z",
]


class AiWallReinforcementRow(_StrictModel):
    kind: Literal["wall"]
    status: Literal["normalized", "needs_review"]
    wall_id: str | None
    X: str | None
    Y: str | None
    Z: str | None
    reason: str | None = None
    blank_fields: tuple[WallBlankField, ...] = ()
    source_sheet: str = Field(min_length=1)
    source_row: int = Field(ge=1)
    source_cells: AiWallSourceCells

    @model_validator(mode="after")
    def validate_status_fields(self) -> Self:
        required = ("wall_id", "X", "Y", "Z")
        if self.status == "normalized":
            missing = [name for name in required if _blank(getattr(self, name))]
            if missing:
                raise ValueError(
                    "normalized wall 缺少必填字段：" + ", ".join(missing)
                )
            if self.reason is not None or self.blank_fields:
                raise ValueError("normalized wall 不得包含 reason 或 blank_fields")
            missing_evidence = [
                name
                for name in ("wall", "X", "Y", "Z")
                if _blank(getattr(self.source_cells, name))
            ]
            if missing_evidence:
                raise ValueError(
                    "normalized wall 缺少来源证据：" + ", ".join(missing_evidence)
                )
            return self

        _validate_review_fields(
            reason=self.reason,
            blank_fields=self.blank_fields,
            values={name: getattr(self, name) for name in required},
            mandatory_fields=set(required),
        )
        populated_evidence = {
            "wall_id": self.source_cells.wall,
            "X": self.source_cells.X,
            "Y": self.source_cells.Y,
            "Z": self.source_cells.Z,
        }
        _validate_review_evidence(
            values={name: getattr(self, name) for name in required},
            evidence=populated_evidence,
            blank_fields=self.blank_fields,
        )
        return self


class AiSlabReinforcementRow(_StrictModel):
    kind: Literal["slab"]
    status: Literal["normalized", "needs_review"]
    elevation: str | None
    top_x: str | None
    top_y: str | None
    middle_x: str | None
    middle_y: str | None
    bottom_x: str | None
    bottom_y: str | None
    z: str | None
    reason: str | None = None
    blank_fields: tuple[SlabBlankField, ...] = ()
    source_sheet: str = Field(min_length=1)
    source_row: int = Field(ge=1)
    source_cells: AiSlabSourceCells

    @model_validator(mode="after")
    def validate_status_fields(self) -> Self:
        mandatory = (
            "elevation",
            "top_x",
            "top_y",
            "bottom_x",
            "bottom_y",
            "z",
        )
        all_fields = (
            "elevation",
            "top_x",
            "top_y",
            "middle_x",
            "middle_y",
            "bottom_x",
            "bottom_y",
            "z",
        )
        if self.status == "normalized":
            missing = [name for name in mandatory if _blank(getattr(self, name))]
            if missing:
                raise ValueError(
                    "normalized slab 缺少必填字段：" + ", ".join(missing)
                )
            if _blank(self.middle_x) != _blank(self.middle_y):
                raise ValueError("normalized slab 的 middle_x 和 middle_y 必须同时填写或同时为空")
            if self.reason is not None or self.blank_fields:
                raise ValueError("normalized slab 不得包含 reason 或 blank_fields")
            required_evidence = list(mandatory)
            if self.middle_x is not None:
                required_evidence.extend(("middle_x", "middle_y"))
            missing_evidence = [
                name
                for name in required_evidence
                if _blank(getattr(self.source_cells, name))
            ]
            if missing_evidence:
                raise ValueError(
                    "normalized slab 缺少来源证据：" + ", ".join(missing_evidence)
                )
            return self

        _validate_review_fields(
            reason=self.reason,
            blank_fields=self.blank_fields,
            values={name: getattr(self, name) for name in all_fields},
            mandatory_fields=set(mandatory),
        )
        if _blank(self.middle_x) != _blank(self.middle_y):
            missing_middle = "middle_x" if _blank(self.middle_x) else "middle_y"
            if missing_middle not in self.blank_fields:
                raise ValueError(f"未确定的 {missing_middle} 必须列入 blank_fields")
        _validate_review_evidence(
            values={name: getattr(self, name) for name in all_fields},
            evidence={
                name: getattr(self.source_cells, name)
                for name in all_fields
            },
            blank_fields=self.blank_fields,
        )
        return self


AiReinforcementRow = Annotated[
    AiWallReinforcementRow | AiSlabReinforcementRow,
    Field(discriminator="kind"),
]


class AiReinforcementPayload(_StrictModel):
    schema_version: Literal["1"]
    source_row_count: int = Field(ge=1)
    rows: tuple[AiReinforcementRow, ...] = Field(min_length=1)


@dataclass(frozen=True)
class ReinforcementNormalizationWarning:
    code: str
    scope: str
    identity: str | None
    direction: str | None
    source_sheet: str
    source_row: int
    source_cells: dict[str, str]
    original_values: dict[str, str]
    reason: str
    blank_fields: tuple[str, ...]


@dataclass(frozen=True)
class ValidatedAiReinforcement:
    wall_schedule: ReinforcementSchedule
    slab_schedule: SlabReinforcementSchedule | None
    warnings: tuple[ReinforcementNormalizationWarning, ...]
    source_row_count: int


@dataclass(frozen=True)
class _SourceEvidence:
    cells: dict[str, str]
    originals: dict[str, str]


_ADDRESS_PATTERN = re.compile(r"^[A-Za-z]+(?P<row>[1-9]\d*)$")


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _validate_review_fields(
    *,
    reason: str | None,
    blank_fields: Sequence[str],
    values: Mapping[str, object],
    mandatory_fields: set[str],
) -> None:
    if _blank(reason):
        raise ValueError("needs_review 必须填写 reason")
    if not blank_fields:
        raise ValueError("needs_review 必须填写 blank_fields")
    if len(set(blank_fields)) != len(blank_fields):
        raise ValueError("blank_fields 不得重复")
    for name in blank_fields:
        if not _blank(values[name]):
            raise ValueError(f"blank_fields 中的 {name} 必须保持 None")
    omitted_mandatory = {
        name for name in mandatory_fields if _blank(values[name])
    }
    unreported = omitted_mandatory.difference(blank_fields)
    if unreported:
        raise ValueError(
            "未确定的必填字段必须列入 blank_fields："
            + ", ".join(sorted(unreported))
        )


def _validate_review_evidence(
    *,
    values: Mapping[str, object],
    evidence: Mapping[str, str | None],
    blank_fields: Sequence[str],
) -> None:
    if not any(not _blank(address) for address in evidence.values()):
        raise ValueError("needs_review 至少需要一个来源证据地址")
    missing = [
        name
        for name, value in values.items()
        if not _blank(value) and _blank(evidence[name])
    ]
    if missing:
        raise ValueError("已填写字段缺少来源证据：" + ", ".join(missing))
    missing_blank_evidence = [
        name for name in blank_fields if _blank(evidence[name])
    ]
    if missing_blank_evidence:
        raise ValueError(
            "blank_fields 缺少来源证据：" + ", ".join(missing_blank_evidence)
        )


def validate_ai_reinforcement_payload(
    payload: AiReinforcementPayload,
    *,
    snapshot: dict[str, object],
    expected_source_row_count: int | None = None,
) -> ValidatedAiReinforcement:
    if payload.source_row_count != len(payload.rows):
        raise InvalidAiReinforcementPayload(
            "source_row_count 必须等于 rows 数量："
            f"{payload.source_row_count} != {len(payload.rows)}"
        )
    if (
        expected_source_row_count is not None
        and payload.source_row_count != expected_source_row_count
    ):
        raise InvalidAiReinforcementPayload(
            "source_row_count 与 expected_source_row_count 不一致："
            f"{payload.source_row_count} != {expected_source_row_count}"
        )
    if not any(isinstance(row, AiWallReinforcementRow) for row in payload.rows):
        raise InvalidAiReinforcementPayload("AI 配筋结果必须至少包含一条 wall 行")

    snapshot_index = _build_snapshot_index(snapshot)
    seen_source_rows: set[tuple[str, str, int]] = set()
    wall_rows: list[NormalizedReinforcementRow] = []
    wall_issues: list[ReinforcementRowIssue] = []
    slab_rows: list[NormalizedSlabReinforcementRow] = []
    warnings: list[ReinforcementNormalizationWarning] = []
    wall_contexts: dict[tuple[str, int], _SourceEvidence] = {}

    for row in payload.rows:
        source_identity = (row.kind, row.source_sheet, row.source_row)
        if source_identity in seen_source_rows:
            raise InvalidAiReinforcementPayload(
                f"{row.source_sheet} 第 {row.source_row} 行存在重复 {row.kind} 来源行"
            )
        seen_source_rows.add(source_identity)
        evidence = _resolve_evidence(row, snapshot_index)

        if isinstance(row, AiWallReinforcementRow):
            wall_contexts[(row.source_sheet, row.source_row)] = evidence
            if row.status == "needs_review":
                _validate_review_wall_rules(row, evidence)
                warning = _review_warning(row, evidence)
                warnings.append(warning)
                wall_id = normalize_wall_id(row.wall_id) if row.wall_id else None
                wall_issues.append(
                    ReinforcementRowIssue(
                        source_sheet=row.source_sheet,
                        source_row=row.source_row,
                        source_cells=evidence.cells,
                        original_values=evidence.originals,
                        original_wall_text=evidence.originals.get("wall", ""),
                        wall_id=wall_id,
                        error=cast(str, row.reason),
                    )
                )
                continue
            normalized_wall = _normalized_wall_row(row, evidence)
            wall_rows.append(normalized_wall)
            continue

        if row.status == "needs_review":
            _validate_review_slab_rules(row, evidence)
            warnings.append(_review_warning(row, evidence))
            continue
        slab_rows.append(_normalized_slab_row(row, evidence))

    wall_schedule = build_reinforcement_schedule(
        rows=tuple(wall_rows),
        issues=tuple(wall_issues),
        source_row_count=len(wall_rows) + len(wall_issues),
        normalization_triggered=True,
    )
    warnings.extend(_duplicate_wall_warnings(wall_schedule, wall_contexts))
    return ValidatedAiReinforcement(
        wall_schedule=wall_schedule,
        slab_schedule=(
            SlabReinforcementSchedule(rows=tuple(slab_rows))
            if slab_rows
            else None
        ),
        warnings=tuple(warnings),
        source_row_count=payload.source_row_count,
    )


def _build_snapshot_index(
    snapshot: dict[str, object],
) -> dict[tuple[str, str], Mapping[str, object]]:
    raw_cells = snapshot.get("cells")
    if not isinstance(raw_cells, list):
        raise InvalidAiReinforcementPayload("workbook snapshot 缺少 cells 列表")
    index: dict[tuple[str, str], Mapping[str, object]] = {}
    for position, raw_cell in enumerate(raw_cells, start=1):
        if not isinstance(raw_cell, Mapping):
            raise InvalidAiReinforcementPayload(
                f"workbook snapshot 的第 {position} 个 cell 结构无效"
            )
        sheet = raw_cell.get("sheet")
        address = raw_cell.get("address")
        source_row = raw_cell.get("row")
        if not isinstance(sheet, str) or not isinstance(address, str):
            raise InvalidAiReinforcementPayload(
                f"workbook snapshot 的第 {position} 个 cell 缺少 sheet/address"
            )
        match = _ADDRESS_PATTERN.fullmatch(address)
        if match is None or not isinstance(source_row, int):
            raise InvalidAiReinforcementPayload(
                f"workbook snapshot 的 {sheet}!{address} 行地址无效"
            )
        if int(match.group("row")) != source_row:
            raise InvalidAiReinforcementPayload(
                f"workbook snapshot 的 {sheet}!{address} 行号与 row={source_row} 不一致"
            )
        key = (sheet, address.upper())
        if key in index:
            raise InvalidAiReinforcementPayload(
                f"workbook snapshot 存在重复地址 {sheet}!{address}"
            )
        index[key] = raw_cell
    return index


def _source_cell_map(
    source_cells: AiWallSourceCells | AiSlabSourceCells,
) -> dict[str, str]:
    dumped = source_cells.model_dump(exclude_none=True)
    return {
        name: value
        for name, value in dumped.items()
        if isinstance(value, str)
    }


def _resolve_evidence(
    row: AiWallReinforcementRow | AiSlabReinforcementRow,
    snapshot_index: Mapping[tuple[str, str], Mapping[str, object]],
) -> _SourceEvidence:
    source_cells = _source_cell_map(row.source_cells)
    originals: dict[str, str] = {}
    for field, address in source_cells.items():
        match = _ADDRESS_PATTERN.fullmatch(address)
        if match is None:
            raise InvalidAiReinforcementPayload(
                f"{row.source_sheet} 第 {row.source_row} 行来源地址 {address} 无效"
            )
        if int(match.group("row")) != row.source_row:
            raise InvalidAiReinforcementPayload(
                f"{row.source_sheet} 第 {row.source_row} 行来源地址 {address} 跨行"
            )
        snapshot_cell = snapshot_index.get((row.source_sheet, address.upper()))
        if snapshot_cell is None:
            raise InvalidAiReinforcementPayload(
                f"{row.source_sheet} 第 {row.source_row} 行来源地址 {address} 不存在"
            )
        originals[field] = _readable_value(snapshot_cell.get("value"))
    return _SourceEvidence(cells=source_cells, originals=originals)


def _normalized_wall_row(
    row: AiWallReinforcementRow,
    evidence: _SourceEvidence,
) -> NormalizedReinforcementRow:
    wall_id = normalize_wall_id(cast(str, row.wall_id))
    if wall_id is None:
        raise _field_error(row, evidence.cells["wall"], "无法识别墙号")
    parsed: dict[str, ParsedRebarCell] = {}
    for direction in ("X", "Y", "Z"):
        address = evidence.cells[direction]
        try:
            cell = parse_rebar_cell(
                cast(str, getattr(row, direction)),
                direction=direction,
            )
        except InvalidReinforcementWorkbook as exc:
            raise _field_error(row, address, str(exc)) from exc
        parsed[direction] = replace(
            cell,
            original_text=evidence.originals[direction],
        )
    return NormalizedReinforcementRow(
        wall_id=wall_id,
        x=parsed["X"],
        y=parsed["Y"],
        z=parsed["Z"],
        source_sheet=row.source_sheet,
        source_row=row.source_row,
        source_cells=evidence.cells,
    )


def _validate_review_wall_rules(
    row: AiWallReinforcementRow,
    evidence: _SourceEvidence,
) -> None:
    if row.wall_id is not None and normalize_wall_id(row.wall_id) is None:
        raise _field_error(row, evidence.cells["wall"], "无法识别墙号")
    for direction in ("X", "Y", "Z"):
        value = getattr(row, direction)
        if value is None:
            continue
        try:
            parse_rebar_cell(value, direction=direction)
        except InvalidReinforcementWorkbook as exc:
            raise _field_error(row, evidence.cells[direction], str(exc)) from exc


def _normalized_slab_row(
    row: AiSlabReinforcementRow,
    evidence: _SourceEvidence,
) -> NormalizedSlabReinforcementRow:
    try:
        elevation = normalize_slab_elevation(cast(str, row.elevation))
    except InvalidReinforcementWorkbook as exc:
        raise _field_error(row, evidence.cells["elevation"], str(exc)) from exc
    parsed: dict[str, ParsedRebarCell | None] = {}
    for field in (
        "top_x",
        "top_y",
        "middle_x",
        "middle_y",
        "bottom_x",
        "bottom_y",
        "z",
    ):
        value = getattr(row, field)
        if value is None:
            parsed[field] = None
            continue
        address = evidence.cells[field]
        try:
            cell = parse_linear_rebar_cell(value)
        except InvalidReinforcementWorkbook as exc:
            raise _field_error(row, address, str(exc)) from exc
        parsed[field] = replace(
            cell,
            original_text=evidence.originals[field],
        )
    return NormalizedSlabReinforcementRow(
        elevation=elevation,
        top_x=cast(ParsedRebarCell, parsed["top_x"]),
        top_y=cast(ParsedRebarCell, parsed["top_y"]),
        middle_x=parsed["middle_x"],
        middle_y=parsed["middle_y"],
        bottom_x=cast(ParsedRebarCell, parsed["bottom_x"]),
        bottom_y=cast(ParsedRebarCell, parsed["bottom_y"]),
        z=cast(ParsedRebarCell, parsed["z"]),
        source_sheet=row.source_sheet,
        source_row=row.source_row,
        source_cells=evidence.cells,
    )


def _validate_review_slab_rules(
    row: AiSlabReinforcementRow,
    evidence: _SourceEvidence,
) -> None:
    if row.elevation is not None:
        try:
            normalize_slab_elevation(row.elevation)
        except InvalidReinforcementWorkbook as exc:
            raise _field_error(row, evidence.cells["elevation"], str(exc)) from exc
    for field in (
        "top_x",
        "top_y",
        "middle_x",
        "middle_y",
        "bottom_x",
        "bottom_y",
        "z",
    ):
        value = getattr(row, field)
        if value is None:
            continue
        try:
            parse_linear_rebar_cell(value)
        except InvalidReinforcementWorkbook as exc:
            raise _field_error(row, evidence.cells[field], str(exc)) from exc


def _field_error(
    row: AiWallReinforcementRow | AiSlabReinforcementRow,
    address: str,
    reason: str,
) -> InvalidAiReinforcementPayload:
    return InvalidAiReinforcementPayload(
        f"{row.source_sheet} 第 {row.source_row} 行 {address}：{reason}"
    )


def _review_warning(
    row: AiWallReinforcementRow | AiSlabReinforcementRow,
    evidence: _SourceEvidence,
) -> ReinforcementNormalizationWarning:
    blank_fields = tuple(row.blank_fields)
    direction = (
        blank_fields[0]
        if len(blank_fields) == 1
        and blank_fields[0] not in {"wall_id", "elevation"}
        else None
    )
    if isinstance(row, AiWallReinforcementRow):
        identity_value = normalize_wall_id(row.wall_id) if row.wall_id else None
    else:
        try:
            identity_value = (
                normalize_slab_elevation(row.elevation)
                if row.elevation is not None
                else None
            )
        except InvalidReinforcementWorkbook:
            identity_value = None
    return ReinforcementNormalizationWarning(
        code="needs_review",
        scope=row.kind,
        identity=identity_value,
        direction=direction,
        source_sheet=row.source_sheet,
        source_row=row.source_row,
        source_cells=evidence.cells,
        original_values=evidence.originals,
        reason=cast(str, row.reason),
        blank_fields=blank_fields,
    )


def _duplicate_wall_warnings(
    schedule: ReinforcementSchedule,
    contexts: Mapping[tuple[str, int], _SourceEvidence],
) -> list[ReinforcementNormalizationWarning]:
    warnings: list[ReinforcementNormalizationWarning] = []
    for wall_id in schedule.duplicate_wall_ids:
        duplicate_rows: list[NormalizedReinforcementRow | ReinforcementRowIssue] = [
            row for row in schedule.rows if row.wall_id == wall_id
        ]
        duplicate_rows.extend(
            issue for issue in schedule.issues if issue.wall_id == wall_id
        )
        first = duplicate_rows[0]
        evidence = contexts[(first.source_sheet, first.source_row)]
        warnings.append(
            ReinforcementNormalizationWarning(
                code="duplicate_wall_id",
                scope="wall",
                identity=wall_id,
                direction=None,
                source_sheet=first.source_sheet,
                source_row=first.source_row,
                source_cells=evidence.cells,
                original_values=evidence.originals,
                reason=f"墙号 {wall_id} 来自多个源行，需要人工确认",
                blank_fields=(),
            )
        )
    return warnings


def _readable_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (float, Decimal)):
        if isinstance(value, float) and not math.isfinite(value):
            return str(value).lower()
        return format(value, "g")
    if isinstance(value, Mapping):
        stable_mapping = {
            str(key): _stable_json_value(item)
            for key, item in value.items()
        }
        return json.dumps(
            stable_mapping,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return json.dumps(
            [_stable_json_value(item) for item in value],
            ensure_ascii=False,
            separators=(",", ":"),
        )
    value_type = type(value)
    return f"<{value_type.__module__}.{value_type.__qualname__}>"


def _stable_json_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, (float, Decimal)):
        return _readable_value(value)
    if isinstance(value, Mapping):
        return {
            str(key): _stable_json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_stable_json_value(item) for item in value]
    value_type = type(value)
    return f"<{value_type.__module__}.{value_type.__qualname__}>"
