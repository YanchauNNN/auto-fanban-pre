from __future__ import annotations

import json
import math
from dataclasses import replace

import pytest
from pydantic import ValidationError

from src.calculation_book import ai_rebar_suggestion_schema as suggestion_schema
from src.calculation_book.ai_rebar_suggestion_schema import (
    PROTOCOL_VERSION,
    AiRebarRepairContext,
    AiRebarRepairError,
    AiRebarSuggestionCandidate,
    AiRebarSuggestionRequest,
    AiRebarSuggestionRequestItem,
    InvalidAiRebarSuggestionPayload,
    RebarSuggestionErrorCode,
    parse_ai_rebar_suggestion_response,
    validate_ai_rebar_suggestion_response,
)
from src.calculation_book.rebar_candidates import RebarCandidate
from src.calculation_book.reinforcement_input import build_rebar_configuration


def _candidate(
    candidate_id: str,
    *,
    diameter: int,
    priority_rank: int = 1,
    target_area: float = 1_100.0,
    actual_area: float | None = None,
) -> RebarCandidate:
    configuration = build_rebar_configuration(
        layers=1,
        diameter=diameter,
        spacing_primary=200,
        spacing_secondary=None,
        direction="Y",
    )
    exact_area = configuration.actual_area if actual_area is None else actual_area
    return RebarCandidate(
        candidate_id=candidate_id,
        profile="linear",
        direction="Y",
        layers=1,
        diameter=diameter,
        spacing_primary=200,
        spacing_secondary=None,
        priority_rank=priority_rank,
        actual_area=exact_area,
        target_area=target_area,
        excess_area=exact_area - target_area,
        canonical_specification=configuration.canonical_specification,
        narrative_specification=configuration.narrative_specification,
    )


def _request_item(
    *,
    item_id: str = "N5001:Y",
    candidates: tuple[RebarCandidate, ...] | None = None,
    repair_context: AiRebarRepairContext | None = None,
) -> AiRebarSuggestionRequestItem:
    source_candidates = (
        candidates
        if candidates is not None
        else (
            _candidate("linear-l1-d18-s200", diameter=18),
            _candidate("linear-l1-d20-s200", diameter=20),
        )
    )
    return AiRebarSuggestionRequestItem(
        item_id=item_id,
        member_kind="wall",
        member_id=item_id.split(":", maxsplit=1)[0],
        direction="Y",
        smx=1_000.0,
        target_area=1_100.0,
        candidates=tuple(
            AiRebarSuggestionCandidate.from_rebar_candidate(candidate)
            for candidate in source_candidates
        ),
        repair_context=repair_context,
    )


def _request(
    *,
    items: tuple[AiRebarSuggestionRequestItem, ...] | None = None,
) -> AiRebarSuggestionRequest:
    return AiRebarSuggestionRequest(
        schema_version=PROTOCOL_VERSION,
        task_id="job-123",
        items=items or (_request_item(),),
    )


def _response_text(
    *items: dict[str, object],
    schema_version: str = PROTOCOL_VERSION,
) -> str:
    return json.dumps(
        {"schema_version": schema_version, "items": list(items)},
        ensure_ascii=False,
    )


def _selected(
    *,
    item_id: str = "N5001:Y",
    candidate_id: str = "linear-l1-d18-s200",
) -> dict[str, object]:
    return {
        "item_id": item_id,
        "status": "selected",
        "selected_candidate_id": candidate_id,
        "reason": "选择满足规则的最优候选",
        "review_reasons": [],
    }


def _review(*, item_id: str = "N5001:Y") -> dict[str, object]:
    return {
        "item_id": item_id,
        "status": "needs_review",
        "reason": "现有信息不足",
        "review_reasons": ["无法确定候选"],
    }


def test_request_has_fixed_strict_protocol_and_complete_item_contract() -> None:
    request = _request()

    assert request.schema_version == "smx-rebar-1"
    assert request.model_dump(mode="json") == {
        "schema_version": "smx-rebar-1",
        "task_id": "job-123",
        "items": [
            {
                "item_id": "N5001:Y",
                "member_kind": "wall",
                "member_id": "N5001",
                "direction": "Y",
                "smx": 1000.0,
                "target_area": 1100.0,
                "candidates": [
                    {
                        "candidate_id": "linear-l1-d18-s200",
                        "spec": "1D18间距200",
                        "actual_area": math.pi * 9**2 * 5,
                        "priority_rank": 1,
                        "excess_area": math.pi * 9**2 * 5 - 1100,
                    },
                    {
                        "candidate_id": "linear-l1-d20-s200",
                        "spec": "1D20间距200",
                        "actual_area": math.pi * 10**2 * 5,
                        "priority_rank": 1,
                        "excess_area": math.pi * 10**2 * 5 - 1100,
                    },
                ],
                "repair_context": None,
            }
        ],
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AiRebarSuggestionRequest.model_validate(
            {**request.model_dump(), "unexpected": True}
        )
    with pytest.raises(ValidationError, match="schema_version"):
        AiRebarSuggestionRequest.model_validate(
            {**request.model_dump(), "schema_version": "future-version"}
        )


def test_request_rejects_duplicate_item_and_candidate_ids() -> None:
    item = _request_item()
    with pytest.raises(ValidationError, match="重复 item_id"):
        _request(items=(item, item))

    duplicate = item.candidates[0]
    with pytest.raises(ValidationError, match="重复 candidate_id"):
        AiRebarSuggestionRequestItem.model_validate(
            {**item.model_dump(), "candidates": [duplicate, duplicate]}
        )


def test_request_rejects_candidates_that_reappear_after_exclusion() -> None:
    context = AiRebarRepairContext(
        round=1,
        excluded_candidate_ids=("linear-l1-d18-s200",),
        errors=(
            AiRebarRepairError(
                code=RebarSuggestionErrorCode.NOT_MINIMUM_EXCESS,
                candidate_id="linear-l1-d18-s200",
                message="同级存在超额更小的候选",
            ),
        ),
    )
    with pytest.raises(ValidationError, match="已排除候选"):
        _request_item(repair_context=context)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("actual_area", "1272.3"),
        ("actual_area", True),
        ("excess_area", "172.3"),
        ("excess_area", False),
        ("priority_rank", "1"),
        ("priority_rank", True),
    ],
)
def test_candidate_numeric_protocol_rejects_strings_and_booleans(
    field_name: str,
    invalid_value: object,
) -> None:
    payload = AiRebarSuggestionCandidate.from_rebar_candidate(
        _candidate("linear-l1-d18-s200", diameter=18)
    ).model_dump()
    payload[field_name] = invalid_value

    with pytest.raises(ValidationError, match=field_name):
        AiRebarSuggestionCandidate.model_validate(payload)


@pytest.mark.parametrize(("field_name", "invalid_value"), [("smx", "1000"), ("smx", True)])
def test_request_numeric_protocol_rejects_fake_smx(
    field_name: str,
    invalid_value: object,
) -> None:
    payload = _request_item().model_dump()
    payload[field_name] = invalid_value

    with pytest.raises(ValidationError, match=field_name):
        AiRebarSuggestionRequestItem.model_validate(payload)


@pytest.mark.parametrize("invalid_value", ["1100", True])
def test_request_numeric_protocol_rejects_fake_target_area(
    invalid_value: object,
) -> None:
    item = _request_item()
    payload = item.model_dump()
    payload["smx"] = 0
    payload["target_area"] = invalid_value
    numeric_target = 1.0 if invalid_value is True else 1100.0
    payload["candidates"] = [
        {
            **candidate.model_dump(),
            "excess_area": candidate.actual_area - numeric_target,
        }
        for candidate in item.candidates
    ]

    with pytest.raises(ValidationError, match="target_area"):
        AiRebarSuggestionRequestItem.model_validate(payload)


@pytest.mark.parametrize("invalid_value", ["1", True, 1.5])
def test_repair_round_rejects_non_integer_or_boolean_values(
    invalid_value: object,
) -> None:
    with pytest.raises(ValidationError, match="round"):
        AiRebarRepairContext.model_validate(
            {
                "round": invalid_value,
                "excluded_candidate_ids": [],
                "errors": [
                    {
                        "code": "INVALID_CANDIDATE",
                        "candidate_id": "invalid",
                        "message": "候选无效",
                    }
                ],
            }
        )


def test_numeric_protocol_still_accepts_json_numbers_and_array_to_tuple() -> None:
    item = _request_item()
    payload = item.model_dump(mode="json")
    payload["smx"] = 1000
    payload["target_area"] = 1100.0
    payload["repair_context"] = {
        "round": 1,
        "excluded_candidate_ids": [],
        "errors": [
            {
                "code": "INVALID_CANDIDATE",
                "candidate_id": "old-id",
                "message": "候选无效",
            }
        ],
    }

    parsed = AiRebarSuggestionRequestItem.model_validate(payload)

    assert parsed.smx == 1000.0
    assert parsed.target_area == 1100.0
    assert isinstance(parsed.candidates, tuple)
    assert parsed.repair_context is not None
    assert isinstance(parsed.repair_context.errors, tuple)


@pytest.mark.parametrize(
    "raw_text",
    [
        "```json\n{}\n```",
        "模型结果如下：\n{}",
        "{}\n额外说明",
        '{"schema_version":"smx-rebar-1","items":[],"items":[]}',
    ],
)
def test_parser_rejects_fenced_markdown_explanations_and_duplicate_keys(
    raw_text: str,
) -> None:
    with pytest.raises(InvalidAiRebarSuggestionPayload) as raised:
        parse_ai_rebar_suggestion_response(raw_text, request=_request())

    assert raised.value.code is RebarSuggestionErrorCode.SCHEMA_INVALID


@pytest.mark.parametrize(
    "payload",
    [
        _selected() | {"actual_area": 9999},
        _selected() | {"diameter": 40},
        _selected() | {"spec": "1D40间距100"},
        _selected() | {"new_specification": "2D40间距100"},
    ],
)
def test_selected_output_cannot_supply_calculations_or_new_specifications(
    payload: dict[str, object],
) -> None:
    with pytest.raises(InvalidAiRebarSuggestionPayload) as raised:
        parse_ai_rebar_suggestion_response(
            _response_text(payload),
            request=_request(),
        )

    assert raised.value.code is RebarSuggestionErrorCode.SCHEMA_INVALID


@pytest.mark.parametrize(
    "items",
    [
        (),
        (_selected(), _selected()),
        (_selected(item_id="N9999:Y"),),
        (_selected(), _selected(item_id="N9999:Y")),
    ],
)
def test_response_item_ids_must_exactly_match_request_once(
    items: tuple[dict[str, object], ...],
) -> None:
    with pytest.raises(InvalidAiRebarSuggestionPayload) as raised:
        parse_ai_rebar_suggestion_response(
            _response_text(*items),
            request=_request(),
        )

    assert raised.value.code is RebarSuggestionErrorCode.SCHEMA_INVALID


@pytest.mark.parametrize(
    "payload",
    [
        _selected() | {"status": "other"},
        {key: value for key, value in _selected().items() if key != "selected_candidate_id"},
        _selected() | {"review_reasons": ["不应存在"]},
        _review() | {"selected_candidate_id": "linear-l1-d18-s200"},
        _review() | {"review_reasons": []},
    ],
)
def test_only_selected_and_needs_review_have_valid_state_specific_fields(
    payload: dict[str, object],
) -> None:
    with pytest.raises(InvalidAiRebarSuggestionPayload) as raised:
        parse_ai_rebar_suggestion_response(
            _response_text(payload),
            request=_request(),
        )

    assert raised.value.code is RebarSuggestionErrorCode.SCHEMA_INVALID


def test_parser_accepts_plain_json_selected_and_needs_review() -> None:
    items = (_request_item(), _request_item(item_id="N5002:Y"))

    response = parse_ai_rebar_suggestion_response(
        _response_text(_selected(), _review(item_id="N5002:Y")),
        request=_request(items=items),
    )

    assert [item.status for item in response.items] == ["selected", "needs_review"]


def test_model_explanation_limits_are_explicit_and_stable() -> None:
    assert suggestion_schema.MAX_REASON_LENGTH == 500
    assert suggestion_schema.MAX_REVIEW_REASON_LENGTH == 300
    assert suggestion_schema.MAX_REVIEW_REASON_COUNT == 20
    assert suggestion_schema.MAX_REVIEW_REASONS_TOTAL_LENGTH == 2_000


def test_model_explanations_are_stripped_before_use() -> None:
    selected = _selected()
    selected["reason"] = "  合格候选  "
    review = _review(item_id="N5002:Y")
    review["reason"] = "  需要复核  "
    review["review_reasons"] = ["  信息不足  "]

    response = parse_ai_rebar_suggestion_response(
        _response_text(selected, review),
        request=_request(items=(_request_item(), _request_item(item_id="N5002:Y"))),
    )

    assert response.items[0].reason == "合格候选"
    assert response.items[1].reason == "需要复核"
    assert response.items[1].review_reasons == ("信息不足",)


@pytest.mark.parametrize(
    "payload",
    [
        _selected() | {"reason": "   "},
        _selected() | {"reason": "合法\n伪造下一段"},
        _selected() | {"reason": "合法\u202e伪装"},
        _selected() | {"reason": "x" * 501},
        _review() | {"review_reasons": ["\t"]},
        _review() | {"review_reasons": ["合法\u0000伪装"]},
        _review() | {"review_reasons": ["x" * 301]},
        _review() | {"review_reasons": [f"原因{i}" for i in range(21)]},
        _review() | {"review_reasons": ["x" * 260 for _ in range(8)]},
    ],
)
def test_model_explanations_reject_blank_oversized_or_control_text(
    payload: dict[str, object],
) -> None:
    with pytest.raises(InvalidAiRebarSuggestionPayload) as raised:
        parse_ai_rebar_suggestion_response(
            _response_text(payload),
            request=_request(),
        )

    assert raised.value.code is RebarSuggestionErrorCode.SCHEMA_INVALID


def test_validation_resolves_candidate_id_to_server_candidate_and_exact_formula() -> None:
    request = _request()
    candidates = {
        "N5001:Y": (
            _candidate("linear-l1-d18-s200", diameter=18),
            _candidate("linear-l1-d20-s200", diameter=20),
        )
    }

    result = validate_ai_rebar_suggestion_response(
        _response_text(_selected()),
        request=request,
        server_candidates=candidates,
    )

    assert result.errors == ()
    assert result.needs_review == ()
    assert len(result.selected) == 1
    selected = result.selected[0]
    assert selected.item_id == "N5001:Y"
    assert selected.candidate is candidates["N5001:Y"][0]
    assert selected.configuration.actual_area == pytest.approx(
        build_rebar_configuration(
            layers=1,
            diameter=18,
            spacing_primary=200,
            spacing_secondary=None,
            direction="Y",
        ).actual_area
    )


def test_validation_accepts_a_response_already_parsed_by_the_model_client() -> None:
    candidate = _candidate("linear-l1-d18-s200", diameter=18)
    request = _request(items=(_request_item(candidates=(candidate,)),))
    parsed = parse_ai_rebar_suggestion_response(
        _response_text(_selected()),
        request=request,
    )

    result = validate_ai_rebar_suggestion_response(
        parsed,
        request=request,
        server_candidates={"N5001:Y": (candidate,)},
    )

    assert result.errors == ()
    assert result.selected[0].candidate is candidate


def test_request_accepts_an_empty_candidate_set_for_deterministic_review() -> None:
    item = _request_item(candidates=())

    assert item.candidates == ()


def test_request_rejects_a_missing_candidates_field() -> None:
    payload = _request_item(candidates=()).model_dump(mode="json")
    del payload["candidates"]

    with pytest.raises(ValidationError):
        AiRebarSuggestionRequestItem.model_validate(payload)


def test_validation_preserves_needs_review_when_no_candidate_exists() -> None:
    request = _request(items=(_request_item(candidates=()),))

    result = validate_ai_rebar_suggestion_response(
        _response_text(_review()),
        request=request,
        server_candidates={"N5001:Y": ()},
    )

    assert result.selected == ()
    assert result.errors == ()
    assert result.needs_review[0].review_reasons == ("无法确定候选",)


def test_validation_rejects_needs_review_when_an_eligible_candidate_exists() -> None:
    candidate = _candidate("linear-l1-d18-s200", diameter=18)

    result = validate_ai_rebar_suggestion_response(
        _response_text(_review()),
        request=_request(items=(_request_item(candidates=(candidate,)),)),
        server_candidates={"N5001:Y": (candidate,)},
    )

    assert result.selected == ()
    assert result.needs_review == ()
    assert [error.code for error in result.errors] == [
        RebarSuggestionErrorCode.SCHEMA_INVALID
    ]


@pytest.mark.parametrize(
    ("candidate_id", "repair_context"),
    [
        ("not-in-request", None),
        (
            "linear-l1-d18-s200",
            AiRebarRepairContext(
                round=1,
                excluded_candidate_ids=("linear-l1-d18-s200",),
                errors=(
                    AiRebarRepairError(
                        code=RebarSuggestionErrorCode.INVALID_CANDIDATE,
                        candidate_id="linear-l1-d18-s200",
                        message="候选已排除",
                    ),
                ),
            ),
        ),
    ],
)
def test_validation_returns_invalid_candidate_for_unknown_or_excluded_id(
    candidate_id: str,
    repair_context: AiRebarRepairContext | None,
) -> None:
    server_candidate = _candidate("linear-l1-d20-s200", diameter=20)
    if repair_context is None:
        item = _request_item(candidates=(server_candidate,))
    else:
        # An excluded ID must not be in the current request candidate list.
        item = _request_item(
            candidates=(server_candidate,),
            repair_context=repair_context,
        )

    result = validate_ai_rebar_suggestion_response(
        _response_text(_selected(candidate_id=candidate_id)),
        request=_request(items=(item,)),
        server_candidates={"N5001:Y": (server_candidate,)},
    )

    assert [error.code for error in result.errors] == [
        RebarSuggestionErrorCode.INVALID_CANDIDATE
    ]


def test_validation_returns_margin_below_ten_percent() -> None:
    insufficient = _candidate(
        "linear-l1-d16-s200",
        diameter=16,
        actual_area=1_099.999999,
    )
    request = _request(items=(_request_item(candidates=(insufficient,)),))

    result = validate_ai_rebar_suggestion_response(
        _response_text(_selected(candidate_id=insufficient.candidate_id)),
        request=request,
        server_candidates={"N5001:Y": (insufficient,)},
    )

    assert result.errors[0].code is RebarSuggestionErrorCode.FORMULA_MISMATCH

    exact_but_insufficient = replace(
        _candidate("linear-l1-d16-s200", diameter=16),
        target_area=1_100.0,
        excess_area=math.pi * 8**2 * 5 - 1_100.0,
    )
    result = validate_ai_rebar_suggestion_response(
        _response_text(_selected(candidate_id=exact_but_insufficient.candidate_id)),
        request=_request(items=(_request_item(candidates=(exact_but_insufficient,)),)),
        server_candidates={"N5001:Y": (exact_but_insufficient,)},
    )
    assert result.errors[0].code is RebarSuggestionErrorCode.MARGIN_BELOW_10_PERCENT


def test_validation_returns_priority_skipped_before_excess_check() -> None:
    high_priority = _candidate(
        "linear-l1-d20-s200",
        diameter=20,
        priority_rank=1,
    )
    selected = _candidate(
        "linear-l1-d18-s200",
        diameter=18,
        priority_rank=2,
    )
    candidates = (high_priority, selected)

    result = validate_ai_rebar_suggestion_response(
        _response_text(_selected(candidate_id=selected.candidate_id)),
        request=_request(items=(_request_item(candidates=candidates),)),
        server_candidates={"N5001:Y": candidates},
    )

    assert [error.code for error in result.errors] == [
        RebarSuggestionErrorCode.PRIORITY_SKIPPED
    ]


def test_validation_uses_unrounded_same_tier_excess() -> None:
    target = 1_100.0
    better = _candidate("linear-l1-d18-s200", diameter=18, target_area=target)
    worse = _candidate("linear-l1-d20-s200", diameter=20, target_area=target)
    assert better.excess_area < worse.excess_area
    candidates = (worse, better)

    result = validate_ai_rebar_suggestion_response(
        _response_text(_selected(candidate_id=worse.candidate_id)),
        request=_request(items=(_request_item(candidates=candidates),)),
        server_candidates={"N5001:Y": candidates},
    )

    assert [error.code for error in result.errors] == [
        RebarSuggestionErrorCode.NOT_MINIMUM_EXCESS
    ]
    assert result.errors[0].better_candidate_ids == (better.candidate_id,)


def test_validation_returns_formula_mismatch_for_tampered_server_derivation() -> None:
    exact = _candidate("linear-l1-d18-s200", diameter=18)
    tampered = replace(
        exact,
        actual_area=exact.actual_area + 1,
        excess_area=exact.excess_area + 1,
    )

    result = validate_ai_rebar_suggestion_response(
        _response_text(_selected()),
        request=_request(items=(_request_item(candidates=(tampered,)),)),
        server_candidates={"N5001:Y": (tampered,)},
    )

    assert [error.code for error in result.errors] == [
        RebarSuggestionErrorCode.FORMULA_MISMATCH
    ]


def test_validation_rejects_duplicate_server_candidate_ids_before_lookup() -> None:
    exact = _candidate("linear-l1-d18-s200", diameter=18)
    duplicate_with_different_derivation = replace(exact, diameter=20)
    request = _request(items=(_request_item(candidates=(exact,)),))

    result = validate_ai_rebar_suggestion_response(
        _response_text(_selected()),
        request=request,
        server_candidates={
            "N5001:Y": (exact, duplicate_with_different_derivation)
        },
    )

    assert [error.code for error in result.errors] == [
        RebarSuggestionErrorCode.FORMULA_MISMATCH
    ]
    assert "重复" in result.errors[0].message


def test_validation_rejects_a_missing_nonselected_server_candidate() -> None:
    selected = _candidate("linear-l1-d18-s200", diameter=18)
    missing = _candidate("linear-l1-d20-s200", diameter=20)
    request = _request(items=(_request_item(candidates=(selected, missing)),))

    result = validate_ai_rebar_suggestion_response(
        _response_text(_selected()),
        request=request,
        server_candidates={"N5001:Y": (selected,)},
    )

    assert [error.code for error in result.errors] == [
        RebarSuggestionErrorCode.FORMULA_MISMATCH
    ]
    assert result.errors[0].candidate_id == missing.candidate_id


@pytest.mark.parametrize(
    "malformed",
    [
        replace(
            _candidate("linear-l1-d18-s200", diameter=18),
            direction=None,  # type: ignore[arg-type]
        ),
        replace(
            _candidate("linear-l1-d18-s200", diameter=18),
            diameter=10**1000,
        ),
    ],
)
def test_malformed_server_candidate_fields_become_formula_mismatch(
    malformed: RebarCandidate,
) -> None:
    request = _request(items=(_request_item(candidates=(malformed,)),))

    result = validate_ai_rebar_suggestion_response(
        _response_text(_selected()),
        request=request,
        server_candidates={"N5001:Y": (malformed,)},
    )

    assert [error.code for error in result.errors] == [
        RebarSuggestionErrorCode.FORMULA_MISMATCH
    ]


def test_malformed_server_derived_values_do_not_escape_validation() -> None:
    exact = _candidate("linear-l1-d18-s200", diameter=18)
    malformed = replace(exact, actual_area=None)  # type: ignore[arg-type]
    request = _request(items=(_request_item(candidates=(exact,)),))

    result = validate_ai_rebar_suggestion_response(
        _response_text(_selected()),
        request=request,
        server_candidates={"N5001:Y": (malformed,)},
    )

    assert [error.code for error in result.errors] == [
        RebarSuggestionErrorCode.FORMULA_MISMATCH
    ]


def test_validation_returns_schema_invalid_instead_of_raising() -> None:
    candidate = _candidate("linear-l1-d18-s200", diameter=18)

    result = validate_ai_rebar_suggestion_response(
        "```json\n{}\n```",
        request=_request(items=(_request_item(candidates=(candidate,)),)),
        server_candidates={"N5001:Y": (candidate,)},
    )

    assert result.selected == ()
    assert result.needs_review == ()
    assert len(result.errors) == 1
    assert result.errors[0].code is RebarSuggestionErrorCode.SCHEMA_INVALID


def test_all_six_stable_validation_codes_are_exhaustive() -> None:
    assert {code.value for code in RebarSuggestionErrorCode} == {
        "MARGIN_BELOW_10_PERCENT",
        "PRIORITY_SKIPPED",
        "NOT_MINIMUM_EXCESS",
        "INVALID_CANDIDATE",
        "FORMULA_MISMATCH",
        "SCHEMA_INVALID",
    }
