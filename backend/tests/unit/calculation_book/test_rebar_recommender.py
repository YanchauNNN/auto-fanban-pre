from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest

from src.ai.rebar_suggestion_task import (
    RebarSuggestionTaskError,
    RebarSuggestionTaskResult,
)
from src.calculation_book.ai_rebar_suggestion_schema import (
    PROTOCOL_VERSION,
    AiRebarSuggestionRequest,
    AiRebarSuggestionResponse,
    RebarSuggestionErrorCode,
)
from src.calculation_book.rebar_candidates import RebarCandidate
from src.calculation_book.rebar_recommender import (
    RebarRecommendationContractError,
    RebarSuggestionInput,
    recommend_rebar_suggestions,
)
from src.calculation_book.reinforcement_input import build_rebar_configuration


def _candidate(
    diameter: int,
    *,
    direction: str = "Y",
    priority_rank: int = 1,
    target_area: float = 1_100.0,
) -> RebarCandidate:
    configuration = build_rebar_configuration(
        layers=1,
        diameter=diameter,
        spacing_primary=400 if direction == "Z" else 200,
        spacing_secondary=400 if direction == "Z" else None,
        direction=direction,
    )
    profile = "grid" if direction == "Z" else "linear"
    spacing = "400x400" if direction == "Z" else "200"
    return RebarCandidate(
        candidate_id=f"{profile}-l1-d{diameter}-s{spacing}",
        profile=profile,
        direction=direction,
        layers=1,
        diameter=diameter,
        spacing_primary=400 if direction == "Z" else 200,
        spacing_secondary=400 if direction == "Z" else None,
        priority_rank=priority_rank,
        actual_area=configuration.actual_area,
        target_area=target_area,
        excess_area=configuration.actual_area - target_area,
        canonical_specification=configuration.canonical_specification,
        narrative_specification=configuration.narrative_specification,
    )


def _input(
    item_id: str = "N5001:Y",
    *,
    candidates: tuple[RebarCandidate, ...] | None = None,
    direction: str = "Y",
    smx: float = 1_000.0,
    target_area: float = 1_100.0,
) -> RebarSuggestionInput:
    member_id, _, _ = item_id.partition(":")
    return RebarSuggestionInput(
        item_id=item_id,
        member_kind="wall",
        member_id=member_id,
        direction=direction,
        smx=smx,
        target_area=target_area,
        candidates=candidates
        if candidates is not None
        else (_candidate(18, direction=direction, target_area=target_area),),
    )


def _response(
    request: AiRebarSuggestionRequest,
    choices: dict[str, str | None],
) -> AiRebarSuggestionResponse:
    items: list[dict[str, object]] = []
    for item in request.items:
        candidate_id = choices[item.item_id]
        if candidate_id is None:
            items.append(
                {
                    "item_id": item.item_id,
                    "status": "needs_review",
                    "reason": "当前候选无法确定",
                    "review_reasons": ["需要人工复核"],
                }
            )
        else:
            items.append(
                {
                    "item_id": item.item_id,
                    "status": "selected",
                    "selected_candidate_id": candidate_id,
                    "reason": "按优先级和最小超额选择",
                    "review_reasons": [],
                }
            )
    return AiRebarSuggestionResponse.model_validate(
        {"schema_version": PROTOCOL_VERSION, "items": items}
    )


Action = (
    Exception
    | dict[str, str | None]
    | Callable[[AiRebarSuggestionRequest], dict[str, str | None]]
)


class _ScriptedInvoker:
    def __init__(
        self,
        actions: list[Action],
        *,
        metadata_for_call: Callable[[int], tuple[str, str, str, str]] | None = None,
    ) -> None:
        self.actions = list(actions)
        self.requests: list[AiRebarSuggestionRequest] = []
        self.correlation_ids: list[str] = []
        self._metadata_for_call = metadata_for_call or (
            lambda _call: ("recommend-rebar-from-smx", "1.0.0", "sha-1", "local-model")
        )

    def suggest(
        self,
        request: AiRebarSuggestionRequest,
        *,
        correlation_id: str,
    ) -> RebarSuggestionTaskResult:
        self.requests.append(request)
        self.correlation_ids.append(correlation_id)
        action = self.actions.pop(0)
        if isinstance(action, Exception):
            raise action
        choices = action(request) if callable(action) else action
        skill_id, skill_version, skill_sha256, model = self._metadata_for_call(
            len(self.requests)
        )
        return RebarSuggestionTaskResult(
            response=_response(request, choices),
            correlation_id=correlation_id,
            task_id=request.task_id,
            skill_id=skill_id,
            skill_version=skill_version,
            skill_sha256=skill_sha256,
            model=model,
        )


def _task_error(kind: str, code: str) -> RebarSuggestionTaskError:
    return RebarSuggestionTaskError(kind, code, "sanitized model call failure")


def _run(
    items: tuple[RebarSuggestionInput, ...],
    invoker: _ScriptedInvoker,
    *,
    batch_size: int = 20,
    max_failures: int = 3,
    audit=None,
):
    return recommend_rebar_suggestions(
        task_id="job-123",
        correlation_id="corr-123",
        items=items,
        invoker=invoker,
        batch_size=batch_size,
        max_consecutive_base_failures=max_failures,
        audit=audit,
    )


def test_first_valid_selection_passes_in_one_call() -> None:
    candidate = _candidate(18)
    invoker = _ScriptedInvoker([{"N5001:Y": candidate.candidate_id}])

    result = _run((_input(candidates=(candidate,)),), invoker)

    assert [entry.candidate for entry in result.selected] == [candidate]
    assert result.warnings == ()
    assert result.call_count == 1
    assert result.repair_round_count == 0
    assert result.skill_id == "recommend-rebar-from-smx"
    assert result.skill_version == "1.0.0"
    assert result.skill_sha256 == "sha-1"
    assert result.model == "local-model"


def test_business_failure_excludes_candidate_and_sends_targeted_repair() -> None:
    insufficient = _candidate(16)
    valid = _candidate(18)
    invoker = _ScriptedInvoker(
        [
            {"N5001:Y": insufficient.candidate_id},
            {"N5001:Y": valid.candidate_id},
        ]
    )

    result = _run((_input(candidates=(insufficient, valid)),), invoker)

    assert result.selected[0].candidate is valid
    assert result.call_count == 2
    assert result.repair_round_count == 1
    repair_item = invoker.requests[1].items[0]
    assert [candidate.candidate_id for candidate in repair_item.candidates] == [
        valid.candidate_id
    ]
    assert repair_item.repair_context is not None
    assert repair_item.repair_context.round == 1
    assert repair_item.repair_context.excluded_candidate_ids == (
        insufficient.candidate_id,
    )
    assert [error.code for error in repair_item.repair_context.errors] == [
        RebarSuggestionErrorCode.MARGIN_BELOW_10_PERCENT
    ]


@pytest.mark.parametrize(
    "wrong_candidates",
    [
        (
            _candidate(20, priority_rank=1),
            _candidate(18, priority_rank=2),
            RebarSuggestionErrorCode.PRIORITY_SKIPPED,
        ),
        (
            _candidate(18),
            _candidate(20),
            RebarSuggestionErrorCode.NOT_MINIMUM_EXCESS,
        ),
    ],
)
def test_priority_and_excess_failures_return_targeted_codes(
    wrong_candidates: tuple[RebarCandidate, RebarCandidate, RebarSuggestionErrorCode],
) -> None:
    better, selected, expected_code = wrong_candidates
    invoker = _ScriptedInvoker(
        [
            {"N5001:Y": selected.candidate_id},
            {"N5001:Y": better.candidate_id},
        ]
    )

    result = _run((_input(candidates=(better, selected)),), invoker)

    assert result.selected[0].candidate is better
    repair = invoker.requests[1].items[0].repair_context
    assert repair is not None
    assert repair.errors[0].code is expected_code


def test_rejected_candidates_shrink_monotonically_until_unique_choice() -> None:
    best, middle, worst = _candidate(18), _candidate(20), _candidate(25)
    invoker = _ScriptedInvoker(
        [
            {"N5001:Y": worst.candidate_id},
            {"N5001:Y": middle.candidate_id},
            {"N5001:Y": best.candidate_id},
        ]
    )

    result = _run((_input(candidates=(best, middle, worst)),), invoker)

    assert result.selected[0].candidate is best
    assert [
        [candidate.candidate_id for candidate in request.items[0].candidates]
        for request in invoker.requests
    ] == [
        [best.candidate_id, middle.candidate_id, worst.candidate_id],
        [best.candidate_id, middle.candidate_id],
        [best.candidate_id],
    ]
    assert result.call_count == 3
    assert result.repair_round_count == 2


def test_selected_items_are_not_resent_while_failed_items_are_repaired() -> None:
    best_a = _candidate(18)
    best_b, wrong_b = _candidate(18), _candidate(20)
    item_a = _input("N5001:Y", candidates=(best_a,))
    item_b = _input("N5002:Y", candidates=(best_b, wrong_b))
    invoker = _ScriptedInvoker(
        [
            {
                item_a.item_id: best_a.candidate_id,
                item_b.item_id: wrong_b.candidate_id,
            },
            {item_b.item_id: best_b.candidate_id},
        ]
    )

    result = _run((item_a, item_b), invoker)

    assert [entry.item_id for entry in result.selected] == [
        item_a.item_id,
        item_b.item_id,
    ]
    assert [item.item_id for item in invoker.requests[1].items] == [item_b.item_id]


def test_invalid_candidate_is_not_excluded_and_stops_after_three_failures() -> None:
    only = _candidate(18)
    invoker = _ScriptedInvoker(
        [{"N5001:Y": "invented"}, {"N5001:Y": "invented"}, {"N5001:Y": "invented"}]
    )

    result = _run((_input(candidates=(only,)),), invoker)

    assert result.selected == ()
    assert result.call_count == 3
    assert result.repair_round_count == 0
    assert result.warnings[0].code == "AI_BASE_FAILURE_LIMIT"
    assert all(
        [candidate.candidate_id for candidate in request.items[0].candidates]
        == [only.candidate_id]
        for request in invoker.requests
    )
    second_repair = invoker.requests[1].items[0].repair_context
    assert second_repair is not None
    assert second_repair.excluded_candidate_ids == ()
    assert second_repair.errors[0].code is RebarSuggestionErrorCode.INVALID_CANDIDATE


def test_schema_invalid_needs_review_keeps_candidates_and_uses_base_limit() -> None:
    candidate = _candidate(18)
    invoker = _ScriptedInvoker(
        [{"N5001:Y": None}, {"N5001:Y": None}, {"N5001:Y": None}]
    )

    result = _run((_input(candidates=(candidate,)),), invoker)

    assert result.call_count == 3
    assert result.repair_round_count == 0
    assert result.warnings[0].code == "AI_BASE_FAILURE_LIMIT"
    assert all(
        [entry.candidate_id for entry in request.items[0].candidates]
        == [candidate.candidate_id]
        for request in invoker.requests
    )
    repair = invoker.requests[1].items[0].repair_context
    assert repair is not None
    assert repair.excluded_candidate_ids == ()
    assert repair.errors[0].code is RebarSuggestionErrorCode.SCHEMA_INVALID


def test_needs_review_with_no_eligible_candidate_blanks_immediately() -> None:
    insufficient = _candidate(16)
    invoker = _ScriptedInvoker([{"N5001:Y": None}])

    result = _run((_input(candidates=(insufficient,)),), invoker)

    assert result.selected == ()
    assert result.call_count == 1
    assert result.warnings[0].code == "AI_NEEDS_REVIEW"


def test_last_business_invalid_candidate_blanks_without_an_empty_ai_call() -> None:
    insufficient = _candidate(16)
    invoker = _ScriptedInvoker([{"N5001:Y": insufficient.candidate_id}])

    result = _run((_input(candidates=(insufficient,)),), invoker)

    assert result.call_count == 1
    assert result.selected == ()
    assert result.warnings[0].code == "NO_ELIGIBLE_CANDIDATE"
    assert len(invoker.requests) == 1


def test_reselecting_an_excluded_candidate_stops_within_the_finite_call_bound() -> None:
    best, rejected = _candidate(18), _candidate(20)
    invoker = _ScriptedInvoker(
        [
            {"N5001:Y": rejected.candidate_id},
            {"N5001:Y": rejected.candidate_id},
            {"N5001:Y": rejected.candidate_id},
            {"N5001:Y": rejected.candidate_id},
        ]
    )

    result = _run((_input(candidates=(best, rejected)),), invoker)

    assert result.selected == ()
    assert result.warnings[0].code == "AI_BASE_FAILURE_LIMIT"
    assert result.repair_round_count == 1
    assert result.call_count == 4
    assert result.call_count <= 2 * 3
    assert all(
        [candidate.candidate_id for candidate in request.items[0].candidates]
        == [best.candidate_id]
        for request in invoker.requests[1:]
    )


def test_model_failures_are_per_item_and_do_not_block_later_batches() -> None:
    first = _input("N5001:Y")
    second = _input("N5002:Y")
    invoker = _ScriptedInvoker(
        [
            _task_error("infrastructure", "model_timeout"),
            {second.item_id: second.candidates[0].candidate_id},
            _task_error("infrastructure", "model_timeout"),
            _task_error("infrastructure", "model_timeout"),
        ]
    )

    result = _run((first, second), invoker, batch_size=1)

    assert [entry.item_id for entry in result.selected] == [second.item_id]
    assert result.warnings[0].item_id == first.item_id
    assert result.warnings[0].code == "AI_BASE_FAILURE_LIMIT"
    assert result.call_count == 4


def test_business_valid_response_resets_consecutive_base_failure_counter() -> None:
    best, wrong = _candidate(18), _candidate(20)
    invoker = _ScriptedInvoker(
        [
            _task_error("model_call", "model_response_invalid"),
            _task_error("model_call", "model_response_invalid"),
            {"N5001:Y": wrong.candidate_id},
            _task_error("model_call", "model_response_invalid"),
            _task_error("model_call", "model_response_invalid"),
            {"N5001:Y": best.candidate_id},
        ]
    )

    result = _run((_input(candidates=(best, wrong)),), invoker)

    assert result.warnings == ()
    assert result.selected[0].candidate is best
    assert result.call_count == 6


def test_empty_candidates_and_zero_z_fixed_candidate_do_not_call_ai() -> None:
    fixed = _candidate(14, direction="Z", target_area=0.0)
    invoker = _ScriptedInvoker([])

    result = _run(
        (
            _input("N5001:Y", candidates=()),
            _input(
                "N5002:Z",
                candidates=(fixed,),
                direction="Z",
                smx=0.0,
                target_area=0.0,
            ),
        ),
        invoker,
    )

    assert invoker.requests == []
    assert result.call_count == 0
    assert result.repair_round_count == 0
    assert result.selected[0].candidate is fixed
    assert result.selected[0].source == "fixed_rule"
    assert result.warnings[0].code == "NO_ELIGIBLE_CANDIDATE"
    assert result.skill_id is None
    assert result.skill_version is None
    assert result.skill_sha256 is None
    assert result.model is None


def test_formula_mismatch_fails_fast_as_backend_contract_error() -> None:
    candidate = _candidate(18)
    tampered = replace(
        candidate,
        actual_area=candidate.actual_area + 1,
        excess_area=candidate.excess_area + 1,
    )
    invoker = _ScriptedInvoker([{"N5001:Y": tampered.candidate_id}])

    with pytest.raises(RebarRecommendationContractError, match="FORMULA_MISMATCH"):
        _run((_input(candidates=(tampered,)),), invoker)

    assert len(invoker.requests) == 1


def test_metadata_must_remain_consistent_across_calls() -> None:
    best, wrong = _candidate(18), _candidate(20)
    invoker = _ScriptedInvoker(
        [
            {"N5001:Y": wrong.candidate_id},
            {"N5001:Y": best.candidate_id},
        ],
        metadata_for_call=lambda call: (
            "recommend-rebar-from-smx",
            "1.0.0",
            f"sha-{call}",
            "local-model",
        ),
    )

    with pytest.raises(RebarRecommendationContractError, match="metadata"):
        _run((_input(candidates=(best, wrong)),), invoker)


def test_batch_size_bounds_every_model_call() -> None:
    items = tuple(_input(f"N500{i}:Y") for i in range(1, 6))
    invoker = _ScriptedInvoker(
        [
            lambda request: {
                item.item_id: item.candidates[0].candidate_id
                for item in request.items
            }
            for _ in range(3)
        ]
    )

    result = _run(items, invoker, batch_size=2)

    assert len(result.selected) == 5
    assert [len(request.items) for request in invoker.requests] == [2, 2, 1]


def test_audit_reports_candidates_calls_validation_repair_and_final_state() -> None:
    best, wrong = _candidate(18), _candidate(20)
    invoker = _ScriptedInvoker(
        [
            {"N5001:Y": wrong.candidate_id},
            {"N5001:Y": best.candidate_id},
        ]
    )
    events: list[tuple[str, dict[str, object]]] = []

    result = _run(
        (_input(candidates=(best, wrong)),),
        invoker,
        audit=lambda event, payload: events.append((event, payload)),
    )

    assert result.selected[0].candidate is best
    event_names = [event for event, _payload in events]
    assert event_names == [
        "candidate_generated",
        "ai_call_started",
        "ai_call_completed",
        "validation_completed",
        "repair_scheduled",
        "ai_call_started",
        "ai_call_completed",
        "validation_completed",
        "item_finalized",
    ]
    first_call = events[1][1]
    assert first_call["item_ids"] == ["N5001:Y"]
    assert first_call["candidate_counts"] == {"N5001:Y": 2}
    repair = events[4][1]
    assert repair["new_excluded_candidate_ids"] == [wrong.candidate_id]
    final = events[-1][1]
    assert final["status"] == "selected"
    assert final["candidate_id"] == best.candidate_id
    assert "按优先级和最小超额选择" not in repr(events)
