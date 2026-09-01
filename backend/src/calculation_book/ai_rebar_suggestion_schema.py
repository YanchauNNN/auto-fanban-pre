from __future__ import annotations

import json
import math
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from .rebar_candidates import RebarCandidate
from .reinforcement_input import RebarConfiguration, build_rebar_configuration

PROTOCOL_VERSION = "smx-rebar-1"
MAX_REASON_LENGTH = 500
MAX_REVIEW_REASON_LENGTH = 300
MAX_REVIEW_REASON_COUNT = 20
MAX_REVIEW_REASONS_TOTAL_LENGTH = 2_000


def _json_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("必须使用 JSON 数值，不能使用字符串或布尔值")
    return float(value)


def _json_integer(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("必须使用 JSON 整数，不能使用字符串、布尔值或小数")
    return value


def _bounded_text(value: Any, *, label: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} 必须是字符串")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError(f"{label} 不得包含控制字符")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} 去除首尾空白后不得为空")
    if len(normalized) > max_length:
        raise ValueError(f"{label} 不得超过 {max_length} 个字符")
    return normalized


def _reason_text(value: Any) -> str:
    return _bounded_text(value, label="reason", max_length=MAX_REASON_LENGTH)


def _review_reason_text(value: Any) -> str:
    return _bounded_text(
        value,
        label="review_reason",
        max_length=MAX_REVIEW_REASON_LENGTH,
    )


JsonNumber = Annotated[float, BeforeValidator(_json_number)]
JsonInteger = Annotated[int, BeforeValidator(_json_integer)]
ReasonText = Annotated[str, BeforeValidator(_reason_text)]
ReviewReasonText = Annotated[str, BeforeValidator(_review_reason_text)]


class RebarSuggestionErrorCode(StrEnum):
    MARGIN_BELOW_10_PERCENT = "MARGIN_BELOW_10_PERCENT"
    PRIORITY_SKIPPED = "PRIORITY_SKIPPED"
    NOT_MINIMUM_EXCESS = "NOT_MINIMUM_EXCESS"
    INVALID_CANDIDATE = "INVALID_CANDIDATE"
    FORMULA_MISMATCH = "FORMULA_MISMATCH"
    SCHEMA_INVALID = "SCHEMA_INVALID"


class InvalidAiRebarSuggestionPayload(ValueError):
    def __init__(
        self,
        message: str,
        *,
        item_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = RebarSuggestionErrorCode.SCHEMA_INVALID
        self.item_id = item_id


class _StrictModel(BaseModel):
    # JSON arrays naturally arrive as ``list`` objects; Pydantic may normalize
    # those to immutable tuples while the protocol remains strict about keys.
    model_config = ConfigDict(extra="forbid", frozen=True)


class AiRebarSuggestionCandidate(_StrictModel):
    candidate_id: str = Field(min_length=1)
    spec: str = Field(min_length=1)
    actual_area: JsonNumber = Field(ge=0)
    priority_rank: JsonInteger = Field(ge=1)
    excess_area: JsonNumber

    @model_validator(mode="after")
    def validate_finite_values(self) -> Self:
        if not math.isfinite(self.actual_area) or not math.isfinite(
            self.excess_area
        ):
            raise ValueError("候选面积必须是有限数值")
        return self

    @classmethod
    def from_rebar_candidate(
        cls,
        candidate: RebarCandidate,
    ) -> AiRebarSuggestionCandidate:
        return cls(
            candidate_id=candidate.candidate_id,
            spec=candidate.canonical_specification,
            actual_area=candidate.actual_area,
            priority_rank=candidate.priority_rank,
            excess_area=candidate.excess_area,
        )


class AiRebarRepairError(_StrictModel):
    code: RebarSuggestionErrorCode
    candidate_id: str | None = None
    message: str = Field(min_length=1)


class AiRebarRepairContext(_StrictModel):
    round: JsonInteger = Field(ge=1)
    excluded_candidate_ids: tuple[str, ...] = ()
    errors: tuple[AiRebarRepairError, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_exclusions(self) -> Self:
        if len(set(self.excluded_candidate_ids)) != len(
            self.excluded_candidate_ids
        ):
            raise ValueError("repair_context 包含重复的已排除候选")
        if any(not candidate_id.strip() for candidate_id in self.excluded_candidate_ids):
            raise ValueError("已排除 candidate_id 不得为空")
        return self


class AiRebarSuggestionRequestItem(_StrictModel):
    item_id: str = Field(min_length=1)
    member_kind: Literal["wall", "slab"]
    member_id: str = Field(min_length=1)
    direction: Literal["X", "Y", "Z"]
    smx: JsonNumber = Field(ge=0)
    target_area: JsonNumber = Field(ge=0)
    candidates: tuple[AiRebarSuggestionCandidate, ...]
    repair_context: AiRebarRepairContext | None

    @model_validator(mode="after")
    def validate_item_contract(self) -> Self:
        if not math.isfinite(self.smx) or not math.isfinite(self.target_area):
            raise ValueError("SMX 和目标面积必须是有限数值")
        minimum_target = self.smx * 1.10
        if self.target_area + 1e-9 < minimum_target:
            raise ValueError("target_area 不得低于 SMX 的 110%")

        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError(f"{self.item_id} 包含重复 candidate_id")
        for candidate in self.candidates:
            expected_excess = candidate.actual_area - self.target_area
            if not _same_number(candidate.excess_area, expected_excess):
                raise ValueError(
                    f"{self.item_id} 候选 {candidate.candidate_id} 的 excess_area 不守恒"
                )

        if self.repair_context is not None:
            excluded = set(self.repair_context.excluded_candidate_ids)
            repeated = sorted(excluded.intersection(candidate_ids))
            if repeated:
                raise ValueError(
                    f"{self.item_id} 的 candidates 重新包含已排除候选："
                    + ", ".join(repeated)
                )
        return self


class AiRebarSuggestionRequest(_StrictModel):
    schema_version: Literal["smx-rebar-1"]
    task_id: str = Field(min_length=1)
    items: tuple[AiRebarSuggestionRequestItem, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_item_ids(self) -> Self:
        item_ids = [item.item_id for item in self.items]
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("请求包含重复 item_id")
        return self


class AiSelectedRebarSuggestionResponseItem(_StrictModel):
    item_id: str = Field(min_length=1)
    status: Literal["selected"]
    selected_candidate_id: str = Field(min_length=1)
    reason: ReasonText
    review_reasons: tuple[ReviewReasonText, ...] = Field(
        max_length=MAX_REVIEW_REASON_COUNT
    )

    @model_validator(mode="after")
    def validate_no_review_reason(self) -> Self:
        if self.review_reasons:
            raise ValueError("selected 状态的 review_reasons 必须为空")
        return self


class AiNeedsReviewRebarSuggestionResponseItem(_StrictModel):
    item_id: str = Field(min_length=1)
    status: Literal["needs_review"]
    reason: ReasonText
    review_reasons: tuple[ReviewReasonText, ...] = Field(
        min_length=1,
        max_length=MAX_REVIEW_REASON_COUNT,
    )

    @model_validator(mode="after")
    def validate_review_reasons(self) -> Self:
        total_length = sum(len(reason) for reason in self.review_reasons)
        if total_length > MAX_REVIEW_REASONS_TOTAL_LENGTH:
            raise ValueError(
                "needs_review 的 review_reasons 总长度不得超过 "
                f"{MAX_REVIEW_REASONS_TOTAL_LENGTH} 个字符"
            )
        return self


AiRebarSuggestionResponseItem = Annotated[
    AiSelectedRebarSuggestionResponseItem
    | AiNeedsReviewRebarSuggestionResponseItem,
    Field(discriminator="status"),
]


class AiRebarSuggestionResponse(_StrictModel):
    schema_version: Literal["smx-rebar-1"]
    items: tuple[AiRebarSuggestionResponseItem, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_item_ids(self) -> Self:
        item_ids = [item.item_id for item in self.items]
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("模型响应包含重复 item_id")
        return self


@dataclass(frozen=True)
class ValidatedRebarSelection:
    item_id: str
    candidate: RebarCandidate
    configuration: RebarConfiguration
    reason: str


@dataclass(frozen=True)
class RebarSuggestionNeedsReview:
    item_id: str
    reason: str
    review_reasons: tuple[str, ...]


@dataclass(frozen=True)
class RebarSuggestionValidationError:
    code: RebarSuggestionErrorCode
    message: str
    item_id: str | None = None
    candidate_id: str | None = None
    better_candidate_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RebarSuggestionValidationResult:
    selected: tuple[ValidatedRebarSelection, ...]
    needs_review: tuple[RebarSuggestionNeedsReview, ...]
    errors: tuple[RebarSuggestionValidationError, ...]


class _DuplicateJsonKey(ValueError):
    pass


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(f"JSON 包含重复字段：{key}")
        result[key] = value
    return result


def parse_ai_rebar_suggestion_response(
    raw_text: str,
    *,
    request: AiRebarSuggestionRequest,
) -> AiRebarSuggestionResponse:
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise InvalidAiRebarSuggestionPayload("模型响应必须是非空 JSON 文本")
    stripped = raw_text.strip()
    if stripped.startswith("```") or "```" in stripped:
        raise InvalidAiRebarSuggestionPayload("模型响应不得使用 Markdown 代码块")
    try:
        payload = json.loads(stripped, object_pairs_hook=_strict_json_object)
        response = AiRebarSuggestionResponse.model_validate(payload)
    except (json.JSONDecodeError, _DuplicateJsonKey, ValueError) as exc:
        raise InvalidAiRebarSuggestionPayload(
            f"模型响应不符合 {PROTOCOL_VERSION} 协议"
        ) from exc

    _validate_item_conservation(response=response, request=request)
    return response


def validate_ai_rebar_suggestion_response(
    response_payload: str | AiRebarSuggestionResponse,
    *,
    request: AiRebarSuggestionRequest,
    server_candidates: Mapping[str, Sequence[RebarCandidate]],
) -> RebarSuggestionValidationResult:
    try:
        if isinstance(response_payload, str):
            response = parse_ai_rebar_suggestion_response(
                response_payload,
                request=request,
            )
        else:
            response = response_payload
            _validate_item_conservation(response=response, request=request)
    except InvalidAiRebarSuggestionPayload as exc:
        return RebarSuggestionValidationResult(
            selected=(),
            needs_review=(),
            errors=(
                RebarSuggestionValidationError(
                    code=RebarSuggestionErrorCode.SCHEMA_INVALID,
                    message=str(exc),
                    item_id=exc.item_id,
                ),
            ),
        )

    request_by_id = {item.item_id: item for item in request.items}
    selected: list[ValidatedRebarSelection] = []
    needs_review: list[RebarSuggestionNeedsReview] = []
    errors: list[RebarSuggestionValidationError] = []

    for response_item in response.items:
        request_item = request_by_id[response_item.item_id]
        if response_item.status == "needs_review":
            eligible_candidate_ids = tuple(
                candidate.candidate_id
                for candidate in request_item.candidates
                if candidate.actual_area >= request_item.target_area
            )
            if eligible_candidate_ids:
                errors.append(
                    RebarSuggestionValidationError(
                        code=RebarSuggestionErrorCode.SCHEMA_INVALID,
                        message=(
                            f"{response_item.item_id} 仍有合格候选，"
                            "不得返回 needs_review"
                        ),
                        item_id=response_item.item_id,
                        better_candidate_ids=eligible_candidate_ids,
                    )
                )
                continue
            needs_review.append(
                RebarSuggestionNeedsReview(
                    item_id=response_item.item_id,
                    reason=response_item.reason,
                    review_reasons=response_item.review_reasons,
                )
            )
            continue

        validation = _validate_selected_item(
            response_item=response_item,
            request_item=request_item,
            server_candidates=server_candidates.get(response_item.item_id, ()),
        )
        if isinstance(validation, RebarSuggestionValidationError):
            errors.append(validation)
        else:
            selected.append(validation)

    return RebarSuggestionValidationResult(
        selected=tuple(selected),
        needs_review=tuple(needs_review),
        errors=tuple(errors),
    )


def _validate_item_conservation(
    *,
    response: AiRebarSuggestionResponse,
    request: AiRebarSuggestionRequest,
) -> None:
    request_ids = {item.item_id for item in request.items}
    response_ids = {item.item_id for item in response.items}
    if response_ids == request_ids:
        return
    missing = sorted(request_ids - response_ids)
    extra = sorted(response_ids - request_ids)
    details: list[str] = []
    if missing:
        details.append("缺失 " + ", ".join(missing))
    if extra:
        details.append("额外 " + ", ".join(extra))
    raise InvalidAiRebarSuggestionPayload(
        "模型响应 item_id 不守恒：" + "；".join(details)
    )


def _validate_selected_item(
    *,
    response_item: AiSelectedRebarSuggestionResponseItem,
    request_item: AiRebarSuggestionRequestItem,
    server_candidates: Sequence[RebarCandidate],
) -> ValidatedRebarSelection | RebarSuggestionValidationError:
    candidate_id = response_item.selected_candidate_id
    request_candidates = {
        candidate.candidate_id: candidate for candidate in request_item.candidates
    }
    excluded = (
        set(request_item.repair_context.excluded_candidate_ids)
        if request_item.repair_context is not None
        else set()
    )
    try:
        server_candidate_ids = [
            candidate.candidate_id for candidate in server_candidates
        ]
        server_id_counts = Counter(server_candidate_ids)
        duplicate_server_ids = sorted(
            candidate_id
            for candidate_id, count in server_id_counts.items()
            if count > 1
        )
    except (AttributeError, TypeError):
        return _error(
            RebarSuggestionErrorCode.FORMULA_MISMATCH,
            request_item,
            candidate_id,
            "服务端候选表包含无法识别的 candidate_id",
        )
    if duplicate_server_ids:
        return _error(
            RebarSuggestionErrorCode.FORMULA_MISMATCH,
            request_item,
            candidate_id,
            "服务端候选表包含重复 candidate_id："
            + ", ".join(duplicate_server_ids),
        )
    server_by_id = dict(zip(server_candidate_ids, server_candidates, strict=True))
    if (
        candidate_id not in request_candidates
        or candidate_id in excluded
        or candidate_id not in server_by_id
    ):
        return _error(
            RebarSuggestionErrorCode.INVALID_CANDIDATE,
            request_item,
            candidate_id,
            "模型选择的候选不存在、未发送或已排除",
        )

    allowed_server: dict[str, tuple[RebarCandidate, RebarConfiguration]] = {}
    for allowed_id, request_candidate in request_candidates.items():
        server_candidate = server_by_id.get(allowed_id)
        if server_candidate is None:
            return _error(
                RebarSuggestionErrorCode.FORMULA_MISMATCH,
                request_item,
                allowed_id,
                "请求候选无法在服务端候选表中复核",
            )
        configuration = _rebuild_configuration(server_candidate)
        if configuration is None or not _candidate_derivation_matches(
            candidate=server_candidate,
            request_candidate=request_candidate,
            request_item=request_item,
            configuration=configuration,
        ):
            return _error(
                RebarSuggestionErrorCode.FORMULA_MISMATCH,
                request_item,
                allowed_id,
                "候选派生值与后端精确公式不一致",
            )
        allowed_server[allowed_id] = (server_candidate, configuration)

    candidate, configuration = allowed_server[candidate_id]
    if configuration.actual_area < request_item.target_area:
        return _error(
            RebarSuggestionErrorCode.MARGIN_BELOW_10_PERCENT,
            request_item,
            candidate_id,
            "候选实际配筋面积未达到 SMX 的 110% 目标面积",
        )

    qualifying = [
        (other, rebuilt)
        for other, rebuilt in allowed_server.values()
        if rebuilt.actual_area >= request_item.target_area
    ]
    highest_priority = min(other.priority_rank for other, _ in qualifying)
    if candidate.priority_rank != highest_priority:
        return _error(
            RebarSuggestionErrorCode.PRIORITY_SKIPPED,
            request_item,
            candidate_id,
            "模型跳过了仍有合格候选的更高优先级",
        )

    selected_excess = configuration.actual_area - request_item.target_area
    same_priority = [
        (other, rebuilt.actual_area - request_item.target_area)
        for other, rebuilt in qualifying
        if other.priority_rank == candidate.priority_rank
    ]
    minimum_excess = min(excess for _, excess in same_priority)
    if selected_excess > minimum_excess:
        better = tuple(
            sorted(
                other.candidate_id
                for other, excess in same_priority
                if excess < selected_excess
            )
        )
        return RebarSuggestionValidationError(
            code=RebarSuggestionErrorCode.NOT_MINIMUM_EXCESS,
            item_id=request_item.item_id,
            candidate_id=candidate_id,
            message="同一优先级内存在未舍入超额面积更小的候选",
            better_candidate_ids=better,
        )

    return ValidatedRebarSelection(
        item_id=request_item.item_id,
        candidate=candidate,
        configuration=configuration,
        reason=response_item.reason,
    )


def _rebuild_configuration(
    candidate: RebarCandidate,
) -> RebarConfiguration | None:
    try:
        return build_rebar_configuration(
            layers=candidate.layers,
            diameter=candidate.diameter,
            spacing_primary=candidate.spacing_primary,
            spacing_secondary=candidate.spacing_secondary,
            direction=candidate.direction,
        )
    except (AttributeError, OverflowError, TypeError, ValueError):
        return None


def _candidate_derivation_matches(
    *,
    candidate: RebarCandidate,
    request_candidate: AiRebarSuggestionCandidate,
    request_item: AiRebarSuggestionRequestItem,
    configuration: RebarConfiguration,
) -> bool:
    profile = "grid" if candidate.direction == "Z" else "linear"
    spacing = str(configuration.spacing_primary)
    if configuration.spacing_secondary is not None:
        spacing += f"x{configuration.spacing_secondary}"
    expected_id = (
        f"{profile}-l{configuration.layers}-d{configuration.diameter}-s{spacing}"
    )
    exact_excess = configuration.actual_area - request_item.target_area
    return all(
        (
            candidate.profile == profile,
            candidate.direction == request_item.direction,
            candidate.candidate_id == expected_id,
            candidate.canonical_specification
            == configuration.canonical_specification,
            candidate.narrative_specification
            == configuration.narrative_specification,
            _same_number(candidate.actual_area, configuration.actual_area),
            _same_number(candidate.target_area, request_item.target_area),
            _same_number(candidate.excess_area, exact_excess),
            request_candidate.spec == configuration.canonical_specification,
            request_candidate.priority_rank == candidate.priority_rank,
            _same_number(request_candidate.actual_area, configuration.actual_area),
            _same_number(request_candidate.excess_area, exact_excess),
        )
    )


def _same_number(left: float, right: float) -> bool:
    try:
        return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-9)
    except (ArithmeticError, TypeError, ValueError):
        return False


def _error(
    code: RebarSuggestionErrorCode,
    item: AiRebarSuggestionRequestItem,
    candidate_id: str,
    message: str,
) -> RebarSuggestionValidationError:
    return RebarSuggestionValidationError(
        code=code,
        item_id=item.item_id,
        candidate_id=candidate_id,
        message=message,
    )
