from __future__ import annotations

import hashlib
import json
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from time import perf_counter
from typing import Literal, Protocol

from ..ai.rebar_suggestion_task import (
    RebarSuggestionTaskError,
    RebarSuggestionTaskResult,
)
from .ai_rebar_suggestion_schema import (
    PROTOCOL_VERSION,
    AiRebarRepairContext,
    AiRebarRepairError,
    AiRebarSuggestionCandidate,
    AiRebarSuggestionRequest,
    AiRebarSuggestionRequestItem,
    AiRebarSuggestionResponse,
    RebarSuggestionErrorCode,
    RebarSuggestionValidationError,
    ValidatedRebarSelection,
    validate_ai_rebar_suggestion_response,
)
from .rebar_candidates import RebarCandidate
from .reinforcement_input import RebarConfiguration

MemberKind = Literal["wall", "slab"]
Direction = Literal["X", "Y", "Z"]
SelectionSource = Literal["ai", "fixed_rule"]
RebarSuggestionAudit = Callable[[str, dict[str, object]], None]
WarningCode = Literal[
    "NO_ELIGIBLE_CANDIDATE",
    "AI_NEEDS_REVIEW",
    "AI_BASE_FAILURE_LIMIT",
]

_BUSINESS_REPAIR_CODES = frozenset(
    {
        RebarSuggestionErrorCode.MARGIN_BELOW_10_PERCENT,
        RebarSuggestionErrorCode.PRIORITY_SKIPPED,
        RebarSuggestionErrorCode.NOT_MINIMUM_EXCESS,
    }
)
_BASE_PROTOCOL_CODES = frozenset(
    {
        RebarSuggestionErrorCode.INVALID_CANDIDATE,
        RebarSuggestionErrorCode.SCHEMA_INVALID,
    }
)


class RebarRecommendationContractError(RuntimeError):
    """Raised when backend-owned recommendation invariants are broken."""


@dataclass(frozen=True)
class RebarSuggestionInput:
    item_id: str
    member_kind: MemberKind
    member_id: str
    direction: Direction
    smx: float
    target_area: float
    candidates: tuple[RebarCandidate, ...]


@dataclass(frozen=True)
class SelectedRebarSuggestion:
    item_id: str
    member_kind: MemberKind
    member_id: str
    direction: Direction
    smx: float
    target_area: float
    candidate: RebarCandidate
    configuration: RebarConfiguration
    reason: str
    source: SelectionSource


@dataclass(frozen=True)
class RebarSuggestionWarning:
    item_id: str
    member_kind: MemberKind
    member_id: str
    direction: Direction
    code: WarningCode
    message: str
    detail_codes: tuple[str, ...] = ()
    review_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class RebarSuggestionResult:
    selected: tuple[SelectedRebarSuggestion, ...]
    warnings: tuple[RebarSuggestionWarning, ...]
    call_count: int
    repair_round_count: int
    skill_id: str | None
    skill_version: str | None
    skill_sha256: str | None
    model: str | None


class RebarSuggestionInvoker(Protocol):
    def suggest(
        self,
        request: AiRebarSuggestionRequest,
        *,
        correlation_id: str,
    ) -> RebarSuggestionTaskResult: ...


@dataclass
class _ItemState:
    source: RebarSuggestionInput
    excluded_candidate_ids: set[str] = field(default_factory=set)
    feedback_round: int = 0
    consecutive_base_failures: int = 0
    repair_context: AiRebarRepairContext | None = None
    selected: SelectedRebarSuggestion | None = None
    warning: RebarSuggestionWarning | None = None

    @property
    def active(self) -> bool:
        return self.selected is None and self.warning is None

    @property
    def remaining_candidates(self) -> tuple[RebarCandidate, ...]:
        return tuple(
            candidate
            for candidate in self.source.candidates
            if candidate.candidate_id not in self.excluded_candidate_ids
        )


def recommend_rebar_suggestions(
    *,
    task_id: str,
    correlation_id: str,
    items: tuple[RebarSuggestionInput, ...],
    invoker: RebarSuggestionInvoker,
    batch_size: int,
    max_consecutive_base_failures: int,
    audit: RebarSuggestionAudit | None = None,
) -> RebarSuggestionResult:
    """Select exact candidates with per-item monotonic repair and bounded failures."""

    _validate_limit(batch_size, label="batch_size")
    _validate_limit(
        max_consecutive_base_failures,
        label="max_consecutive_base_failures",
    )
    states = _build_states(items)
    metadata: tuple[str, str, str, str] | None = None
    call_count = 0
    pending: deque[str] = deque()

    for state in states.values():
        _validate_input_contract(state.source, task_id=task_id)
        _emit(
            audit,
            "candidate_generated",
            item_id=state.source.item_id,
            smx=state.source.smx,
            target_area=state.source.target_area,
            candidates=[
                {
                    "candidate_id": candidate.candidate_id,
                    "priority_rank": candidate.priority_rank,
                    "actual_area": candidate.actual_area,
                    "excess_area": candidate.excess_area,
                }
                for candidate in state.source.candidates
            ],
            elimination_codes=[],
        )
        if not state.source.candidates:
            state.warning = _warning(
                state,
                code="NO_ELIGIBLE_CANDIDATE",
                message="后端未生成满足配筋规则的候选，当前方向已留空",
            )
            continue
        if _is_fixed_zero_z(state.source):
            state.selected = _select_fixed_candidate(state, task_id=task_id)
            continue
        pending.append(state.source.item_id)

    while pending:
        batch_ids = _take_active_batch(pending, states=states, batch_size=batch_size)
        if not batch_ids:
            continue
        batch_states = tuple(states[item_id] for item_id in batch_ids)
        request = AiRebarSuggestionRequest(
            schema_version=PROTOCOL_VERSION,
            task_id=task_id,
            items=tuple(_request_item(state) for state in batch_states),
        )
        call_count += 1
        _emit(
            audit,
            "ai_call_started",
            call_index=call_count,
            batch_index=call_count,
            item_ids=list(batch_ids),
            repair_rounds={
                state.source.item_id: state.feedback_round
                for state in batch_states
            },
            candidate_counts={
                state.source.item_id: len(state.remaining_candidates)
                for state in batch_states
            },
            excluded_candidate_ids={
                state.source.item_id: sorted(state.excluded_candidate_ids)
                for state in batch_states
            },
            input_summary_sha256=_request_summary_sha256(request),
        )
        started = perf_counter()

        try:
            invocation = invoker.suggest(request, correlation_id=correlation_id)
        except RebarSuggestionTaskError as exc:
            _emit(
                audit,
                "ai_call_failed",
                call_index=call_count,
                duration_ms=_duration_ms(started),
                error_kind=exc.kind,
                error_code=exc.code,
                item_ids=list(batch_ids),
                consecutive_base_failures={
                    state.source.item_id: state.consecutive_base_failures + 1
                    for state in batch_states
                },
            )
            for state in batch_states:
                _record_base_failure(
                    state,
                    detail_code=exc.code,
                    max_failures=max_consecutive_base_failures,
                )
                if state.active:
                    _emit_repair_scheduled(audit, state)
                    pending.append(state.source.item_id)
            continue

        _validate_invocation_identity(
            invocation,
            task_id=task_id,
            correlation_id=correlation_id,
        )
        invocation_metadata = (
            invocation.skill_id,
            invocation.skill_version,
            invocation.skill_sha256,
            invocation.model,
        )
        if metadata is None:
            metadata = invocation_metadata
        elif invocation_metadata != metadata:
            raise RebarRecommendationContractError(
                "AI recommendation metadata changed between model calls"
            )
        _emit(
            audit,
            "ai_call_completed",
            call_index=call_count,
            duration_ms=_duration_ms(started),
            model=invocation.model,
            skill_id=invocation.skill_id,
            skill_version=invocation.skill_version,
            skill_sha256=invocation.skill_sha256,
            usage=invocation.usage,
            items=[
                {
                    "item_id": item.item_id,
                    "status": item.status,
                    "candidate_id": getattr(item, "selected_candidate_id", None),
                }
                for item in invocation.response.items
            ],
        )

        validation = validate_ai_rebar_suggestion_response(
            invocation.response,
            request=request,
            server_candidates={
                state.source.item_id: state.source.candidates
                for state in batch_states
            },
        )
        formula_errors = tuple(
            error
            for error in validation.errors
            if error.code is RebarSuggestionErrorCode.FORMULA_MISMATCH
        )
        if formula_errors:
            first = formula_errors[0]
            raise RebarRecommendationContractError(
                "FORMULA_MISMATCH in backend candidate contract"
                + (f" for {first.item_id}" if first.item_id else "")
            )

        selected_by_id = {entry.item_id: entry for entry in validation.selected}
        review_by_id = {entry.item_id: entry for entry in validation.needs_review}
        errors_by_id = {
            error.item_id: error
            for error in validation.errors
            if error.item_id is not None
        }
        for state in batch_states:
            item_id = state.source.item_id
            outcomes = sum(
                item_id in outcome
                for outcome in (selected_by_id, review_by_id, errors_by_id)
            )
            if outcomes != 1:
                raise RebarRecommendationContractError(
                    f"validator returned {outcomes} outcomes for {item_id}"
                )
            if item_id in selected_by_id:
                selection = selected_by_id[item_id]
                _emit(
                    audit,
                    "validation_completed",
                    item_id=item_id,
                    call_index=call_count,
                    status="selected",
                    error_codes=[],
                    candidate_id=selection.candidate.candidate_id,
                    better_candidate_ids=[],
                )
                state.consecutive_base_failures = 0
                state.selected = _selected_output(
                    state,
                    selection,
                    source="ai",
                )
            elif item_id in review_by_id:
                _emit(
                    audit,
                    "validation_completed",
                    item_id=item_id,
                    call_index=call_count,
                    status="needs_review",
                    error_codes=[],
                    candidate_id=None,
                    better_candidate_ids=[],
                )
                state.consecutive_base_failures = 0
                review = review_by_id[item_id]
                state.warning = _warning(
                    state,
                    code="AI_NEEDS_REVIEW",
                    message="AI 未能从当前候选中形成确定建议，当前方向已留空",
                    review_reasons=review.review_reasons,
                )
            else:
                error = errors_by_id[item_id]
                _emit(
                    audit,
                    "validation_completed",
                    item_id=item_id,
                    call_index=call_count,
                    status="invalid",
                    error_codes=[error.code.value],
                    candidate_id=error.candidate_id,
                    better_candidate_ids=list(error.better_candidate_ids),
                )
                _apply_validation_error(
                    state,
                    error=error,
                    max_failures=max_consecutive_base_failures,
                )
                if state.active:
                    _emit_repair_scheduled(audit, state)
                    pending.append(item_id)

    selected = tuple(
        state.selected for state in states.values() if state.selected is not None
    )
    warnings = tuple(
        state.warning for state in states.values() if state.warning is not None
    )
    for state in states.values():
        _emit_item_finalized(audit, state)
    repair_round_count = max(
        (len(state.excluded_candidate_ids) for state in states.values()),
        default=0,
    )
    return RebarSuggestionResult(
        selected=selected,
        warnings=warnings,
        call_count=call_count,
        repair_round_count=repair_round_count,
        skill_id=metadata[0] if metadata is not None else None,
        skill_version=metadata[1] if metadata is not None else None,
        skill_sha256=metadata[2] if metadata is not None else None,
        model=metadata[3] if metadata is not None else None,
    )


def _emit(
    audit: RebarSuggestionAudit | None,
    event: str,
    **payload: object,
) -> None:
    if audit is not None:
        audit(event, payload)


def _duration_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))


def _request_summary_sha256(request: AiRebarSuggestionRequest) -> str:
    payload = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _emit_repair_scheduled(
    audit: RebarSuggestionAudit | None,
    state: _ItemState,
) -> None:
    _emit(
        audit,
        "repair_scheduled",
        item_id=state.source.item_id,
        next_round=state.feedback_round + 1,
        new_excluded_candidate_ids=(
            [state.repair_context.errors[0].candidate_id]
            if state.repair_context is not None
            and state.repair_context.errors[0].candidate_id is not None
            else []
        ),
        excluded_candidate_ids=sorted(state.excluded_candidate_ids),
        remaining_count=len(state.remaining_candidates),
    )


def _emit_item_finalized(
    audit: RebarSuggestionAudit | None,
    state: _ItemState,
) -> None:
    selected = state.selected
    warning = state.warning
    _emit(
        audit,
        "item_finalized",
        item_id=state.source.item_id,
        member_kind=state.source.member_kind,
        member_id=state.source.member_id,
        direction=state.source.direction,
        status="selected" if selected is not None else "blank",
        source=selected.source if selected is not None else None,
        candidate_id=(
            selected.candidate.candidate_id if selected is not None else None
        ),
        spec=(
            selected.configuration.canonical_specification
            if selected is not None
            else None
        ),
        actual_area=(
            selected.configuration.actual_area if selected is not None else None
        ),
        smx=state.source.smx,
        target_area=state.source.target_area,
        margin_ratio=(
            0.0
            if state.source.smx == 0
            else (state.source.target_area / state.source.smx) - 1
        ),
        blank_reason_code=warning.code if warning is not None else None,
        image_name=None,
        error_code=(warning.detail_codes[0] if warning and warning.detail_codes else None),
    )


def _validate_limit(value: int, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")


def _build_states(
    items: tuple[RebarSuggestionInput, ...],
) -> dict[str, _ItemState]:
    states: dict[str, _ItemState] = {}
    for item in items:
        if item.item_id in states:
            raise RebarRecommendationContractError(
                f"duplicate recommendation item_id: {item.item_id}"
            )
        states[item.item_id] = _ItemState(source=item)
    return states


def _validate_input_contract(item: RebarSuggestionInput, *, task_id: str) -> None:
    try:
        AiRebarSuggestionRequest(
            schema_version=PROTOCOL_VERSION,
            task_id=task_id,
            items=(
                AiRebarSuggestionRequestItem(
                    item_id=item.item_id,
                    member_kind=item.member_kind,
                    member_id=item.member_id,
                    direction=item.direction,
                    smx=item.smx,
                    target_area=item.target_area,
                    candidates=tuple(
                        AiRebarSuggestionCandidate.from_rebar_candidate(candidate)
                        for candidate in item.candidates
                    ),
                    repair_context=None,
                ),
            ),
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise RebarRecommendationContractError(
            f"invalid backend recommendation input for {item.item_id}"
        ) from exc


def _is_fixed_zero_z(item: RebarSuggestionInput) -> bool:
    return item.direction == "Z" and item.smx == 0


def _select_fixed_candidate(
    state: _ItemState,
    *,
    task_id: str,
) -> SelectedRebarSuggestion:
    if len(state.source.candidates) != 1:
        raise RebarRecommendationContractError(
            f"zero-SMX Z item {state.source.item_id} must have exactly one fixed candidate"
        )
    request = AiRebarSuggestionRequest(
        schema_version=PROTOCOL_VERSION,
        task_id=task_id,
        items=(_request_item(state),),
    )
    candidate = state.source.candidates[0]
    response = AiRebarSuggestionResponse.model_validate(
        {
            "schema_version": PROTOCOL_VERSION,
            "items": [
                {
                    "item_id": state.source.item_id,
                    "status": "selected",
                    "selected_candidate_id": candidate.candidate_id,
                    "reason": "Z 向 SMX 为 0，采用后端固定构造钢筋候选",
                    "review_reasons": [],
                }
            ],
        }
    )
    validation = validate_ai_rebar_suggestion_response(
        response,
        request=request,
        server_candidates={state.source.item_id: state.source.candidates},
    )
    if validation.errors or len(validation.selected) != 1:
        code = validation.errors[0].code if validation.errors else "UNKNOWN"
        raise RebarRecommendationContractError(
            f"fixed zero-SMX Z candidate failed backend validation: {code}"
        )
    return _selected_output(state, validation.selected[0], source="fixed_rule")


def _take_active_batch(
    pending: deque[str],
    *,
    states: dict[str, _ItemState],
    batch_size: int,
) -> tuple[str, ...]:
    result: list[str] = []
    while pending and len(result) < batch_size:
        item_id = pending.popleft()
        if states[item_id].active:
            result.append(item_id)
    return tuple(result)


def _request_item(state: _ItemState) -> AiRebarSuggestionRequestItem:
    source = state.source
    return AiRebarSuggestionRequestItem(
        item_id=source.item_id,
        member_kind=source.member_kind,
        member_id=source.member_id,
        direction=source.direction,
        smx=source.smx,
        target_area=source.target_area,
        candidates=tuple(
            AiRebarSuggestionCandidate.from_rebar_candidate(candidate)
            for candidate in state.remaining_candidates
        ),
        repair_context=state.repair_context,
    )


def _validate_invocation_identity(
    invocation: RebarSuggestionTaskResult,
    *,
    task_id: str,
    correlation_id: str,
) -> None:
    if not isinstance(invocation.response, AiRebarSuggestionResponse):
        raise RebarRecommendationContractError(
            "AI recommendation invoker returned an invalid response object"
        )
    if invocation.task_id != task_id or invocation.correlation_id != correlation_id:
        raise RebarRecommendationContractError(
            "AI recommendation invoker returned mismatched request identity"
        )


def _record_base_failure(
    state: _ItemState,
    *,
    detail_code: str,
    max_failures: int,
) -> None:
    state.consecutive_base_failures += 1
    if state.consecutive_base_failures >= max_failures:
        state.warning = _warning(
            state,
            code="AI_BASE_FAILURE_LIMIT",
            message="AI 连续基础调用或协议失败达到上限，当前方向已留空",
            detail_codes=(detail_code,),
        )


def _apply_validation_error(
    state: _ItemState,
    *,
    error: RebarSuggestionValidationError,
    max_failures: int,
) -> None:
    if error.code in _BUSINESS_REPAIR_CODES:
        state.consecutive_base_failures = 0
        candidate_id = error.candidate_id
        remaining_ids = {
            candidate.candidate_id for candidate in state.remaining_candidates
        }
        if candidate_id is None or candidate_id not in remaining_ids:
            raise RebarRecommendationContractError(
                f"business repair error lacks a current candidate for {state.source.item_id}"
            )
        state.excluded_candidate_ids.add(candidate_id)
        _set_repair_context(state, error=error, include_candidate_id=True)
        if not state.remaining_candidates:
            state.warning = _warning(
                state,
                code="NO_ELIGIBLE_CANDIDATE",
                message="所有候选均未通过后端精确校验，当前方向已留空",
                detail_codes=(error.code.value,),
            )
        return
    if error.code in _BASE_PROTOCOL_CODES:
        _set_repair_context(state, error=error, include_candidate_id=False)
        _record_base_failure(
            state,
            detail_code=error.code.value,
            max_failures=max_failures,
        )
        return
    raise RebarRecommendationContractError(
        f"unsupported validator error code: {error.code}"
    )


def _set_repair_context(
    state: _ItemState,
    *,
    error: RebarSuggestionValidationError,
    include_candidate_id: bool,
) -> None:
    state.feedback_round += 1
    message = error.message
    if error.better_candidate_ids:
        message += "；更优候选为 " + ", ".join(error.better_candidate_ids)
    state.repair_context = AiRebarRepairContext(
        round=state.feedback_round,
        excluded_candidate_ids=tuple(
            candidate.candidate_id
            for candidate in state.source.candidates
            if candidate.candidate_id in state.excluded_candidate_ids
        ),
        errors=(
            AiRebarRepairError(
                code=error.code,
                candidate_id=error.candidate_id if include_candidate_id else None,
                message=message,
            ),
        ),
    )


def _selected_output(
    state: _ItemState,
    selection: ValidatedRebarSelection,
    *,
    source: SelectionSource,
) -> SelectedRebarSuggestion:
    item = state.source
    return SelectedRebarSuggestion(
        item_id=item.item_id,
        member_kind=item.member_kind,
        member_id=item.member_id,
        direction=item.direction,
        smx=item.smx,
        target_area=item.target_area,
        candidate=selection.candidate,
        configuration=selection.configuration,
        reason=selection.reason,
        source=source,
    )


def _warning(
    state: _ItemState,
    *,
    code: WarningCode,
    message: str,
    detail_codes: tuple[str, ...] = (),
    review_reasons: tuple[str, ...] = (),
) -> RebarSuggestionWarning:
    item = state.source
    return RebarSuggestionWarning(
        item_id=item.item_id,
        member_kind=item.member_kind,
        member_id=item.member_id,
        direction=item.direction,
        code=code,
        message=message,
        detail_codes=detail_codes,
        review_reasons=review_reasons,
    )
