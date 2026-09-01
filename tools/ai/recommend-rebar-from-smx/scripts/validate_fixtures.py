from __future__ import annotations

import argparse
import copy
import json
import math
import unicodedata
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "smx-rebar-1"
MAX_REASON_LENGTH = 500
MAX_REVIEW_REASON_LENGTH = 300
MAX_REVIEW_REASON_COUNT = 20
MAX_REVIEW_REASONS_TOTAL_LENGTH = 2_000
ERROR_CODES = {
    "MARGIN_BELOW_10_PERCENT",
    "PRIORITY_SKIPPED",
    "NOT_MINIMUM_EXCESS",
    "INVALID_CANDIDATE",
    "FORMULA_MISMATCH",
    "SCHEMA_INVALID",
}


class ProtocolError(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ProtocolError(f"non-finite JSON constant is forbidden: {value}")


def parse_json_text(raw_text: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw_text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise ProtocolError("invalid JSON text") from exc
    if not isinstance(value, dict):
        raise ProtocolError("top-level JSON value must be an object")
    return value


def load_json(path: Path) -> dict[str, Any]:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProtocolError(f"cannot read JSON file: {path}") from exc
    return parse_json_text(raw_text)


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ProtocolError(
            f"{label} fields differ: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _text(value: Any, *, label: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ProtocolError(f"{label} must be a string")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ProtocolError(f"{label} contains a control character")
    normalized = value.strip()
    if not normalized:
        raise ProtocolError(f"{label} must not be blank")
    if len(normalized) > max_length:
        raise ProtocolError(f"{label} exceeds {max_length} characters")
    return normalized


def _number(value: Any, *, label: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError(f"{label} must be a JSON number")
    try:
        normalized = float(value)
    except OverflowError as exc:
        raise ProtocolError(f"{label} must be finite") from exc
    if not math.isfinite(normalized):
        raise ProtocolError(f"{label} must be finite")
    if minimum is not None and normalized < minimum:
        raise ProtocolError(f"{label} must be at least {minimum}")
    return normalized


def _positive_integer(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProtocolError(f"{label} must be a positive JSON integer")
    return value


def _repair_exclusions(context: Any, *, label: str) -> set[str]:
    if context is None:
        return set()
    if not isinstance(context, dict):
        raise ProtocolError(f"{label} must be an object or null")
    _exact_keys(context, {"round", "excluded_candidate_ids", "errors"}, label)
    _positive_integer(context["round"], label=f"{label}.round")
    excluded = context["excluded_candidate_ids"]
    if not isinstance(excluded, list):
        raise ProtocolError(f"{label}.excluded_candidate_ids must be an array")
    normalized_exclusions = [
        _text(value, label=f"{label}.excluded_candidate_id", max_length=200)
        for value in excluded
    ]
    if len(set(normalized_exclusions)) != len(normalized_exclusions):
        raise ProtocolError(f"{label} contains duplicate excluded candidate IDs")
    errors = context["errors"]
    if not isinstance(errors, list) or not errors:
        raise ProtocolError(f"{label}.errors must be a non-empty array")
    for index, error in enumerate(errors):
        error_label = f"{label}.errors[{index}]"
        if not isinstance(error, dict):
            raise ProtocolError(f"{error_label} must be an object")
        if set(error) not in (
            {"code", "message"},
            {"code", "candidate_id", "message"},
        ):
            raise ProtocolError(f"{error_label} has invalid fields")
        if error.get("code") not in ERROR_CODES:
            raise ProtocolError(f"{error_label}.code is unsupported")
        _text(error.get("message"), label=f"{error_label}.message", max_length=500)
        candidate_id = error.get("candidate_id")
        if candidate_id is not None:
            _text(candidate_id, label=f"{error_label}.candidate_id", max_length=200)
    return set(normalized_exclusions)


def _validate_request_item(item: Any, *, index: int) -> tuple[str, list[dict[str, Any]]]:
    label = f"request.items[{index}]"
    if not isinstance(item, dict):
        raise ProtocolError(f"{label} must be an object")
    _exact_keys(
        item,
        {
            "item_id",
            "member_kind",
            "member_id",
            "direction",
            "smx",
            "target_area",
            "candidates",
            "repair_context",
        },
        label,
    )
    item_id = _text(item["item_id"], label=f"{label}.item_id", max_length=200)
    _text(item["member_id"], label=f"{label}.member_id", max_length=200)
    if item["member_kind"] not in {"wall", "slab"}:
        raise ProtocolError(f"{label}.member_kind is unsupported")
    if item["direction"] not in {"X", "Y", "Z"}:
        raise ProtocolError(f"{label}.direction is unsupported")
    smx = _number(item["smx"], label=f"{label}.smx", minimum=0)
    target = _number(
        item["target_area"],
        label=f"{label}.target_area",
        minimum=0,
    )
    if target + 1e-9 < smx * 1.10:
        raise ProtocolError(f"{label}.target_area is below 110% of SMX")
    excluded = _repair_exclusions(item["repair_context"], label=f"{label}.repair_context")
    candidates = item["candidates"]
    if not isinstance(candidates, list):
        raise ProtocolError(f"{label}.candidates must be an array")
    seen: set[str] = set()
    for candidate_index, candidate in enumerate(candidates):
        candidate_label = f"{label}.candidates[{candidate_index}]"
        if not isinstance(candidate, dict):
            raise ProtocolError(f"{candidate_label} must be an object")
        _exact_keys(
            candidate,
            {"candidate_id", "spec", "actual_area", "priority_rank", "excess_area"},
            candidate_label,
        )
        candidate_id = _text(
            candidate["candidate_id"],
            label=f"{candidate_label}.candidate_id",
            max_length=200,
        )
        _text(candidate["spec"], label=f"{candidate_label}.spec", max_length=200)
        if candidate_id in seen:
            raise ProtocolError(f"{label} contains duplicate candidate_id")
        seen.add(candidate_id)
        if candidate_id in excluded:
            raise ProtocolError(f"{label} reintroduces an excluded candidate")
        actual = _number(
            candidate["actual_area"],
            label=f"{candidate_label}.actual_area",
            minimum=0,
        )
        _positive_integer(
            candidate["priority_rank"],
            label=f"{candidate_label}.priority_rank",
        )
        excess = _number(
            candidate["excess_area"],
            label=f"{candidate_label}.excess_area",
        )
        if not math.isclose(
            excess,
            actual - target,
            rel_tol=1e-12,
            abs_tol=1e-9,
        ):
            raise ProtocolError(f"{candidate_label}.excess_area is inconsistent")
    return item_id, candidates


def _request_items(request: dict[str, Any]) -> dict[str, dict[str, Any]]:
    _exact_keys(request, {"schema_version", "task_id", "items"}, "request")
    if request["schema_version"] != PROTOCOL_VERSION:
        raise ProtocolError(f"request schema_version must be {PROTOCOL_VERSION}")
    _text(request["task_id"], label="request.task_id", max_length=200)
    items = request["items"]
    if not isinstance(items, list) or not items:
        raise ProtocolError("request.items must be a non-empty array")
    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        item_id, _ = _validate_request_item(item, index=index)
        if item_id in result:
            raise ProtocolError(f"duplicate request item_id: {item_id}")
        result[item_id] = item
    return result


def expected_candidate(item: dict[str, Any]) -> str | None:
    candidates = item["candidates"]
    target = float(item["target_area"])
    eligible = [
        (
            int(candidate["priority_rank"]),
            float(candidate["excess_area"]),
            str(candidate["candidate_id"]),
        )
        for candidate in candidates
        if float(candidate["actual_area"]) >= target
    ]
    return min(eligible)[2] if eligible else None


def _validate_reason(value: Any, *, label: str) -> str:
    return _text(value, label=label, max_length=MAX_REASON_LENGTH)


def _validate_review_reasons(value: Any, *, label: str) -> None:
    if not isinstance(value, list) or not value:
        raise ProtocolError(f"{label} must be a non-empty array")
    if len(value) > MAX_REVIEW_REASON_COUNT:
        raise ProtocolError(f"{label} has too many entries")
    normalized = [
        _text(reason, label=f"{label}[{index}]", max_length=MAX_REVIEW_REASON_LENGTH)
        for index, reason in enumerate(value)
    ]
    if sum(len(reason) for reason in normalized) > MAX_REVIEW_REASONS_TOTAL_LENGTH:
        raise ProtocolError(f"{label} exceeds the total length limit")


def validate(request: dict[str, Any], response: dict[str, Any]) -> None:
    request_by_id = _request_items(request)
    _exact_keys(response, {"schema_version", "items"}, "response")
    if response["schema_version"] != PROTOCOL_VERSION:
        raise ProtocolError(f"response schema_version must be {PROTOCOL_VERSION}")
    response_items = response["items"]
    if not isinstance(response_items, list):
        raise ProtocolError("response.items must be an array")
    response_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(response_items):
        if not isinstance(item, dict):
            raise ProtocolError(f"response.items[{index}] must be an object")
        item_id = _text(
            item.get("item_id"),
            label=f"response.items[{index}].item_id",
            max_length=200,
        )
        if item_id in response_by_id:
            raise ProtocolError(f"duplicate response item_id: {item_id}")
        response_by_id[item_id] = item
    if set(request_by_id) != set(response_by_id):
        raise ProtocolError("request and response item_id sets differ")

    for item_id, request_item in request_by_id.items():
        response_item = response_by_id[item_id]
        expected = expected_candidate(request_item)
        status = response_item.get("status")
        if status == "selected":
            _exact_keys(
                response_item,
                {"item_id", "status", "selected_candidate_id", "reason", "review_reasons"},
                item_id,
            )
            if expected is None:
                raise ProtocolError(f"{item_id} must be needs_review")
            selected_candidate_id = _text(
                response_item["selected_candidate_id"],
                label=f"{item_id}.selected_candidate_id",
                max_length=200,
            )
            if selected_candidate_id != expected:
                raise ProtocolError(f"{item_id} selected the wrong candidate")
            _validate_reason(response_item["reason"], label=f"{item_id}.reason")
            if response_item["review_reasons"] != []:
                raise ProtocolError(f"{item_id} selected review_reasons must be empty")
        elif status == "needs_review":
            _exact_keys(
                response_item,
                {"item_id", "status", "reason", "review_reasons"},
                item_id,
            )
            if expected is not None:
                raise ProtocolError(f"{item_id} has an eligible candidate")
            _validate_reason(response_item["reason"], label=f"{item_id}.reason")
            _validate_review_reasons(
                response_item["review_reasons"],
                label=f"{item_id}.review_reasons",
            )
        else:
            raise ProtocolError(f"{item_id} has unsupported status")


def _candidate(candidate_id: str, rank: int, actual: float, target: float) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "spec": candidate_id,
        "actual_area": actual,
        "priority_rank": rank,
        "excess_area": actual - target,
    }


def _item(
    item_id: str,
    candidates: list[dict[str, Any]],
    *,
    target: float = 1100.0,
    excluded: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "member_kind": "wall",
        "member_id": item_id.split(":", 1)[0],
        "direction": item_id.split(":", 1)[1],
        "smx": 0.0 if target == 0 else 1000.0,
        "target_area": target,
        "candidates": candidates,
        "repair_context": (
            None
            if excluded is None
            else {
                "round": 1,
                "excluded_candidate_ids": excluded,
                "errors": [
                    {
                        "code": "INVALID_CANDIDATE",
                        "candidate_id": excluded[0],
                        "message": "retry",
                    }
                ],
            }
        ),
    }


def _selected(item_id: str, candidate_id: str) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "status": "selected",
        "selected_candidate_id": candidate_id,
        "reason": "best eligible candidate",
        "review_reasons": [],
    }


def _review(item_id: str) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "status": "needs_review",
        "reason": "no eligible candidate",
        "review_reasons": ["candidate list is empty or insufficient"],
    }


def _expect_error(request: dict[str, Any], response: dict[str, Any]) -> None:
    try:
        validate(request, response)
    except ProtocolError:
        return
    raise AssertionError("invalid fixture unexpectedly passed")


def run_fixtures() -> None:
    target = 1100.0
    items = [
        _item(
            "N1:X",
            [
                _candidate("rank1", 1, 1200, target),
                _candidate("rank2-closer", 2, 1110, target),
            ],
        ),
        _item(
            "N2:Y",
            [
                _candidate("waste", 1, 1200, target),
                _candidate("minimum", 1, 1120, target),
            ],
        ),
        _item(
            "N3:Z",
            [_candidate("grid-l1-d14-s200x400", 1, 1200, target)],
        ),
        _item(
            "N4:Z",
            [_candidate("grid-l1-d14-s400x400", 1, 961.625, 0)],
            target=0,
        ),
        _item(
            "N5:X",
            [_candidate("remaining", 1, 1150, target)],
            excluded=["excluded"],
        ),
        _item("N6:X", []),
    ]
    request = {
        "schema_version": PROTOCOL_VERSION,
        "task_id": "fixtures",
        "items": items,
    }
    valid = {
        "schema_version": PROTOCOL_VERSION,
        "items": [
            _selected("N1:X", "rank1"),
            _selected("N2:Y", "minimum"),
            _selected("N3:Z", "grid-l1-d14-s200x400"),
            _selected("N4:Z", "grid-l1-d14-s400x400"),
            _selected("N5:X", "remaining"),
            _review("N6:X"),
        ],
    }
    validate(request, valid)
    for item_id, wrong_id in (
        ("N1:X", "rank2-closer"),
        ("N2:Y", "waste"),
        ("N5:X", "excluded"),
    ):
        invalid = copy.deepcopy(valid)
        next(
            item for item in invalid["items"] if item["item_id"] == item_id
        )["selected_candidate_id"] = wrong_id
        _expect_error(request, invalid)

    invalid_request = copy.deepcopy(request)
    invalid_request["items"][0]["candidates"][0]["excess_area"] = math.nan
    _expect_error(invalid_request, valid)
    invalid_request = copy.deepcopy(request)
    invalid_request["items"][0]["candidates"][0]["excess_area"] += 1
    _expect_error(invalid_request, valid)
    invalid_response = copy.deepcopy(valid)
    invalid_response["items"][0]["reason"] = "line one\nline two"
    _expect_error(request, invalid_response)
    invalid_response = copy.deepcopy(valid)
    invalid_response["items"][0]["reason"] = "x" * (MAX_REASON_LENGTH + 1)
    _expect_error(request, invalid_response)
    invalid_response = copy.deepcopy(valid)
    invalid_response["items"][-1]["review_reasons"] = [
        "x" for _ in range(MAX_REVIEW_REASON_COUNT + 1)
    ]
    _expect_error(request, invalid_response)
    try:
        parse_json_text('{"value": NaN}')
    except ProtocolError:
        pass
    else:
        raise AssertionError("NaN JSON constant unexpectedly passed")
    try:
        parse_json_text('{"value": 1, "value": 2}')
    except ProtocolError:
        pass
    else:
        raise AssertionError("duplicate JSON key unexpectedly passed")
    print("fixtures: ok")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path)
    parser.add_argument("--response", type=Path)
    args = parser.parse_args()
    if (args.request is None) != (args.response is None):
        parser.error("--request and --response must be supplied together")
    if args.request is None:
        run_fixtures()
    else:
        validate(load_json(args.request), load_json(args.response))
        print("response: valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
