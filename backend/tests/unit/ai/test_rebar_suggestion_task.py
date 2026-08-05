from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


class FakeClient:
    def __init__(
        self,
        content: str,
        *,
        error: Exception | None = None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        self.content = content
        self.error = error
        self.usage = usage or {}
        self.calls: list[dict[str, Any]] = []
        self.api_key = "unit-test-secret-api-key"

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> SimpleNamespace:
        self.calls.append({"messages": messages, "tools": tools})
        if self.error is not None:
            raise self.error
        return SimpleNamespace(content=self.content, usage=self.usage)

    def __repr__(self) -> str:
        return f"FakeClient(api_key={self.api_key!r})"


def _skill_root(tmp_path: Path) -> Path:
    root = tmp_path / "recommend-rebar-from-smx"
    references = root / "references"
    references.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(
        "---\n"
        "name: recommend-rebar-from-smx\n"
        "description: Use when selecting supplied SMX candidates.\n"
        "---\n"
        "# Bounded Skill\n"
        "Read [the schema](references/io-schema.md) and "
        "[the ranking rules](references/ranking-rules.md).\n",
        encoding="utf-8",
    )
    (references / "io-schema.md").write_text(
        "# IO schema\nReturn plain JSON only.\n",
        encoding="utf-8",
    )
    (references / "ranking-rules.md").write_text(
        "# Ranking rules\nChoose the minimum excess candidate.\n",
        encoding="utf-8",
    )
    return root


def _request():
    from src.calculation_book.ai_rebar_suggestion_schema import (
        AiRebarSuggestionRequest,
    )

    return AiRebarSuggestionRequest.model_validate(
        {
            "schema_version": "smx-rebar-1",
            "task_id": "task-42",
            "items": [
                {
                    "item_id": "N5001:Y",
                    "member_kind": "wall",
                    "member_id": "N5001",
                    "direction": "Y",
                    "smx": 100.0,
                    "target_area": 110.0,
                    "candidates": [
                        {
                            "candidate_id": "linear-l1-d16-s200",
                            "spec": "1D16@200",
                            "actual_area": 120.0,
                            "priority_rank": 1,
                            "excess_area": 10.0,
                        }
                    ],
                    "repair_context": None,
                }
            ],
        }
    )


def _response(*, reason: str = "最小超额候选") -> str:
    return json.dumps(
        {
            "schema_version": "smx-rebar-1",
            "items": [
                {
                    "item_id": "N5001:Y",
                    "status": "selected",
                    "selected_candidate_id": "linear-l1-d16-s200",
                    "reason": reason,
                    "review_reasons": [],
                }
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _task(
    tmp_path: Path,
    client: FakeClient,
    **limit_overrides: int,
):
    from src.ai.rebar_suggestion_task import (
        RebarSuggestionTask,
        RebarSuggestionTaskLimits,
    )

    defaults = {
        "max_skill_bytes": 100_000,
        "max_reference_files": 4,
        "max_request_bytes": 100_000,
        "max_response_bytes": 100_000,
        "max_response_tokens": 1_000,
        "max_identifier_chars": 200,
    }
    defaults.update(limit_overrides)
    return RebarSuggestionTask(
        client=client,
        model="structured-model",
        skill_root=_skill_root(tmp_path),
        skill_version="1.2.3",
        limits=RebarSuggestionTaskLimits(**defaults),
    )


def test_calls_structured_model_once_with_only_bounded_skill_request_and_ids(
    tmp_path: Path,
) -> None:
    client = FakeClient(_response(), usage={"completion_tokens": 41})
    task = _task(tmp_path, client)

    result = task.suggest(_request(), correlation_id="corr-7")

    assert len(client.calls) == 1
    assert client.calls[0]["tools"] is None
    assert len(client.calls[0]["messages"]) == 2
    system_message, user_message = client.calls[0]["messages"]
    assert system_message["role"] == "system"
    assert user_message["role"] == "user"

    system_payload = json.loads(system_message["content"])
    user_payload = json.loads(user_message["content"])
    assert set(system_payload) == {"skill_bundle"}
    assert set(user_payload) == {"correlation_id", "task_id", "request"}
    assert user_payload["correlation_id"] == "corr-7"
    assert user_payload["task_id"] == "task-42"
    assert user_payload["request"]["schema_version"] == "smx-rebar-1"

    bundle = system_payload["skill_bundle"]
    assert set(bundle) == {"skill_id", "skill_version", "content_sha256", "content"}
    assert bundle["skill_id"] == "recommend-rebar-from-smx"
    assert bundle["skill_version"] == "1.2.3"
    assert "## SKILL.md" in bundle["content"]
    assert "## references/io-schema.md" in bundle["content"]
    assert "## references/ranking-rules.md" in bundle["content"]
    assert bundle["content_sha256"] == hashlib.sha256(bundle["content"].encode("utf-8")).hexdigest()

    assert result.response.items[0].selected_candidate_id == "linear-l1-d16-s200"
    assert result.correlation_id == "corr-7"
    assert result.task_id == "task-42"
    assert result.skill_id == bundle["skill_id"]
    assert result.skill_version == bundle["skill_version"]
    assert result.skill_sha256 == bundle["content_sha256"]
    assert result.model == "structured-model"
    assert result.usage == {"completion_tokens": 41}


def test_freezes_first_successfully_loaded_skill_bundle_for_repair_rounds(
    tmp_path: Path,
) -> None:
    root = _skill_root(tmp_path)
    client = FakeClient(_response())
    task = _task_from_root(root, client)

    first = task.suggest(_request(), correlation_id="corr-first")
    first_system = client.calls[0]["messages"][0]["content"]
    (root / "SKILL.md").write_text(
        "---\nname: replaced-after-first-load\n---\nCHANGED SECRET",
        encoding="utf-8",
    )
    (root / "references" / "io-schema.md").unlink()

    second = task.suggest(_request(), correlation_id="corr-repair")
    second_system = client.calls[1]["messages"][0]["content"]

    assert second_system == first_system
    assert second.skill_id == first.skill_id
    assert second.skill_version == first.skill_version
    assert second.skill_sha256 == first.skill_sha256
    assert "CHANGED SECRET" not in second_system


def test_build_task_forces_structured_zero_temperature_and_no_internal_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.ai import rebar_suggestion_task as module

    captured: dict[str, Any] = {}
    fake_client = FakeClient(_response())
    fake_client.config = SimpleNamespace(model="profile-structured-model")

    def fake_build_chat_client(spec: Any, **kwargs: Any) -> FakeClient:
        captured["spec"] = spec
        captured["kwargs"] = kwargs
        return fake_client

    monkeypatch.setattr(module, "build_chat_client", fake_build_chat_client)
    spec = object()
    task = module.build_rebar_suggestion_task(
        spec,
        skill_root=_skill_root(tmp_path),
        skill_version="2.0.0",
        request_timeout_seconds=123,
        max_output_tokens=4_096,
    )

    assert captured == {
        "spec": spec,
        "kwargs": {
            "model_kind": "structured",
            "timeout_seconds": 123,
            "temperature": 0,
            "max_output_tokens": 4_096,
            "max_retries": 0,
            "max_response_bytes": task.limits.max_response_bytes,
        },
    }
    assert task.model == "profile-structured-model"
    assert task.limits.max_response_tokens == 4_096


@pytest.mark.parametrize(
    ("content", "expected_code"),
    [
        ("not JSON unit-test-secret-api-key", "model_response_invalid"),
        (f"```json\n{_response()}\n```", "model_response_invalid"),
        ('{"schema_version":"wrong","items":[]}', "model_response_invalid"),
        ('{"schema_version":"smx-rebar-1","items":[]}', "model_response_invalid"),
    ],
)
def test_rejects_invalid_or_fenced_model_output_as_sanitized_model_call_error(
    tmp_path: Path,
    content: str,
    expected_code: str,
) -> None:
    from src.ai.rebar_suggestion_task import RebarSuggestionTaskError

    client = FakeClient(content)
    task = _task(tmp_path, client)

    with pytest.raises(RebarSuggestionTaskError) as raised:
        task.suggest(_request(), correlation_id="corr-invalid")

    assert raised.value.kind == "model_call"
    assert raised.value.code == expected_code
    assert str(raised.value) == "structured rebar suggestion response is invalid"
    serialized = repr(raised.value)
    assert "unit-test-secret-api-key" not in serialized
    assert "Authorization" not in serialized
    assert "```" not in serialized
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (TimeoutError("unit-test-secret-api-key"), "model_timeout"),
        (
            ConnectionError("Authorization: Bearer unit-test-secret-api-key"),
            "model_connection_failed",
        ),
    ],
)
def test_wraps_native_transport_failures_without_sensitive_context(
    tmp_path: Path,
    error: Exception,
    expected_code: str,
) -> None:
    from src.ai.rebar_suggestion_task import RebarSuggestionTaskError

    client = FakeClient("", error=error)
    task = _task(tmp_path, client)

    with pytest.raises(RebarSuggestionTaskError) as raised:
        task.suggest(_request(), correlation_id="corr-network")

    assert raised.value.kind == "infrastructure"
    assert raised.value.code == expected_code
    assert "unit-test-secret-api-key" not in repr(raised.value)
    assert "Authorization" not in repr(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (401, "model_authentication_failed"),
        (403, "model_authentication_failed"),
        (503, "model_gateway_failed"),
    ],
)
def test_wraps_typed_chat_client_failures_as_sanitized_infrastructure_error(
    tmp_path: Path,
    status_code: int,
    expected_code: str,
) -> None:
    from src.ai.chat_client import ChatGatewayError
    from src.ai.rebar_suggestion_task import RebarSuggestionTaskError

    sensitive = (
        "Authorization: Bearer unit-test-secret-api-key " + "A" * 400 + " complete system prompt"
    )
    client = FakeClient("", error=ChatGatewayError(sensitive, status_code=status_code))
    task = _task(tmp_path, client)

    with pytest.raises(RebarSuggestionTaskError) as raised:
        task.suggest(_request(), correlation_id="corr-gateway")

    assert raised.value.kind == "infrastructure"
    assert raised.value.code == expected_code
    for forbidden in (
        "unit-test-secret-api-key",
        "Authorization",
        "A" * 100,
        "complete system prompt",
    ):
        assert forbidden not in repr(raised.value)


def test_rejects_response_byte_or_token_limit_before_schema_parse(tmp_path: Path) -> None:
    from src.ai.rebar_suggestion_task import RebarSuggestionTaskError

    oversized_body = FakeClient("not-json-" + "X" * 100)
    body_task = _task(tmp_path, oversized_body, max_response_bytes=20)
    with pytest.raises(RebarSuggestionTaskError) as body_error:
        body_task.suggest(_request(), correlation_id="corr-body")
    assert body_error.value.kind == "model_call"
    assert body_error.value.code == "model_response_too_large"

    oversized_tokens = FakeClient(_response(), usage={"completion_tokens": 11})
    token_task = _task(tmp_path, oversized_tokens, max_response_tokens=10)
    with pytest.raises(RebarSuggestionTaskError) as token_error:
        token_task.suggest(_request(), correlation_id="corr-tokens")
    assert token_error.value.kind == "model_call"
    assert token_error.value.code == "model_response_too_large"


def test_real_gateway_envelope_limit_maps_to_model_response_too_large(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.ai.rebar_suggestion_task import (
        RebarSuggestionTaskError,
        RebarSuggestionTaskLimits,
        build_rebar_suggestion_task,
    )
    from src.config.ai.ai_spec import AiSpec

    spec = AiSpec.model_validate(
        {
            "ai_layer": {
                "model_gateway": {
                    "base_url": "http://127.0.0.1:8001/v1",
                    "api_key_policy": "literal_for_test",
                    "api_key": "secret-key",
                    "authorization_scheme": "bearer",
                },
                "models": {
                    "chat": {"model": "chat-model"},
                    "structured": {"model": "structured-model"},
                },
                "chat": {"request_timeout_seconds": 10},
            }
        }
    )

    class OversizedResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, amount: int | None = None) -> bytes:
            body = b'{"choices":[]}' + b"SENSITIVE" * 100
            return body if amount is None else body[:amount]

    monkeypatch.setattr(
        "src.ai.chat_client.urlopen",
        lambda *_args, **_kwargs: OversizedResponse(),
    )
    limits = RebarSuggestionTaskLimits(
        max_skill_bytes=100_000,
        max_reference_files=4,
        max_request_bytes=100_000,
        max_response_bytes=64,
        max_response_tokens=1_000,
        max_identifier_chars=200,
    )
    task = build_rebar_suggestion_task(
        spec,
        skill_root=_skill_root(tmp_path),
        skill_version="1.0.0",
        request_timeout_seconds=10,
        max_output_tokens=1_000,
        limits=limits,
    )

    with pytest.raises(RebarSuggestionTaskError) as raised:
        task.suggest(_request(), correlation_id="corr-envelope")

    assert raised.value.kind == "model_call"
    assert raised.value.code == "model_response_too_large"
    assert "SENSITIVE" not in repr(raised.value)


def test_real_gateway_invalid_large_integer_is_a_sanitized_model_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.ai.chat_client import ChatClientConfig, OpenAICompatibleChatClient
    from src.ai.rebar_suggestion_task import (
        RebarSuggestionTask,
        RebarSuggestionTaskError,
        RebarSuggestionTaskLimits,
    )

    raw_body = (
        b'{"choices":[{"message":{"content":"{}"}}],"usage":{"completion_tokens":'
        + b"9" * 5_000
        + b"}}"
    )

    class InvalidIntegerResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, amount: int | None = None) -> bytes:
            return raw_body if amount is None else raw_body[:amount]

    monkeypatch.setattr(
        "src.ai.chat_client.urlopen",
        lambda *_args, **_kwargs: InvalidIntegerResponse(),
    )
    client = OpenAICompatibleChatClient(
        ChatClientConfig(
            base_url="http://127.0.0.1:8001/v1",
            api_key=None,
            authorization_scheme="none",
            model="structured-model",
            timeout_seconds=10,
            temperature=0,
            max_output_tokens=1_000,
            max_retries=0,
            max_response_bytes=100_000,
        )
    )
    task = RebarSuggestionTask(
        client=client,
        model="structured-model",
        skill_root=_skill_root(tmp_path),
        skill_version="1.0.0",
        limits=RebarSuggestionTaskLimits(max_response_bytes=100_000),
    )

    with pytest.raises(RebarSuggestionTaskError) as raised:
        task.suggest(_request(), correlation_id="corr-invalid-envelope")

    assert raised.value.kind == "model_call"
    assert raised.value.code == "model_response_invalid"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert "9999999999" not in repr(raised.value)


def test_request_and_response_surrogates_are_sanitized_before_utf8_encoding(
    tmp_path: Path,
) -> None:
    from src.ai.rebar_suggestion_task import RebarSuggestionTaskError

    request = _request()
    unsafe_item = request.items[0].model_copy(
        update={"member_id": "\ud800SENSITIVE-REQUEST-U0VDUkVU"}
    )
    unsafe_request = request.model_copy(update={"items": (unsafe_item,)})
    request_client = FakeClient(_response())
    request_task = _task(tmp_path, request_client)

    with pytest.raises(RebarSuggestionTaskError) as request_error:
        request_task.suggest(unsafe_request, correlation_id="corr-surrogate-request")

    assert request_error.value.code == "request_too_large"
    assert request_error.value.__cause__ is None
    assert request_error.value.__context__ is None
    assert "SENSITIVE-REQUEST" not in repr(request_error.value)
    assert request_client.calls == []

    response_client = FakeClient("\ud800SENSITIVE-RESPONSE-U0VDUkVU")
    response_task = _task(tmp_path, response_client)

    with pytest.raises(RebarSuggestionTaskError) as response_error:
        response_task.suggest(_request(), correlation_id="corr-surrogate-response")

    assert response_error.value.code == "model_response_invalid"
    assert response_error.value.__cause__ is None
    assert response_error.value.__context__ is None
    assert "SENSITIVE-RESPONSE" not in repr(response_error.value)


@pytest.mark.parametrize("missing", ["SKILL.md", "references/io-schema.md"])
def test_missing_skill_file_fails_before_model_call(
    tmp_path: Path,
    missing: str,
) -> None:
    from src.ai.rebar_suggestion_task import (
        RebarSuggestionTask,
        RebarSuggestionTaskError,
        RebarSuggestionTaskLimits,
    )

    root = _skill_root(tmp_path)
    (root / Path(missing)).unlink()
    client = FakeClient(_response())
    task = RebarSuggestionTask(
        client=client,
        model="structured-model",
        skill_root=root,
        skill_version="1.0.0",
        limits=RebarSuggestionTaskLimits(),
    )

    with pytest.raises(RebarSuggestionTaskError) as raised:
        task.suggest(_request(), correlation_id="corr-missing")

    assert raised.value.kind == "infrastructure"
    assert raised.value.code == "skill_missing"
    assert client.calls == []


@pytest.mark.parametrize(
    "link_target",
    ["../outside.md", "references/nested/rules.md", "https://example.test/rules.md"],
)
def test_rejects_non_direct_or_escaping_skill_reference_before_model_call(
    tmp_path: Path,
    link_target: str,
) -> None:
    from src.ai.rebar_suggestion_task import (
        RebarSuggestionTaskError,
    )

    root = _skill_root(tmp_path)
    (tmp_path / "outside.md").write_text("outside-secret", encoding="utf-8")
    (root / "SKILL.md").write_text(
        f"---\nname: recommend-rebar-from-smx\n---\nRead [rules]({link_target}).\n",
        encoding="utf-8",
    )
    client = FakeClient(_response())
    task = _task_from_root(root, client)

    with pytest.raises(RebarSuggestionTaskError) as raised:
        task.suggest(_request(), correlation_id="corr-escape")

    assert raised.value.kind == "infrastructure"
    assert raised.value.code == "skill_path_invalid"
    assert "outside-secret" not in repr(raised.value)
    assert client.calls == []


def test_deeply_nested_skill_frontmatter_is_a_sanitized_metadata_error(
    tmp_path: Path,
) -> None:
    from src.ai.rebar_suggestion_task import RebarSuggestionTaskError

    root = _skill_root(tmp_path)
    nested_value = "[" * 2_000 + "]" * 2_000
    (root / "SKILL.md").write_text(
        "---\n"
        "name: recommend-rebar-from-smx\n"
        f"description: {nested_value}\n"
        "---\n"
        "# Bounded Skill\n",
        encoding="utf-8",
    )
    client = FakeClient(_response())
    task = _task_from_root(root, client)

    with pytest.raises(RebarSuggestionTaskError) as raised:
        task.suggest(_request(), correlation_id="corr-deep-frontmatter")

    assert raised.value.kind == "infrastructure"
    assert raised.value.code == "skill_path_invalid"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert "[[[[[[" not in repr(raised.value)
    assert client.calls == []


def test_rejects_symlink_escape_when_supported(tmp_path: Path) -> None:
    from src.ai.rebar_suggestion_task import RebarSuggestionTaskError

    root = _skill_root(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("outside-secret", encoding="utf-8")
    link = root / "references" / "io-schema.md"
    link.unlink()
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable in this Windows test environment")
    client = FakeClient(_response())
    task = _task_from_root(root, client)

    with pytest.raises(RebarSuggestionTaskError) as raised:
        task.suggest(_request(), correlation_id="corr-link")

    assert raised.value.code == "skill_path_invalid"
    assert "outside-secret" not in repr(raised.value)
    assert client.calls == []


def test_rejects_a_skill_file_replaced_between_validation_and_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.ai.rebar_suggestion_task import RebarSuggestionTaskError

    root = _skill_root(tmp_path)
    target = root / "references" / "io-schema.md"
    replacement = root / "references" / "replacement.md"
    replacement.write_text("RACED OUTSIDE SECRET", encoding="utf-8")
    original_open = Path.open
    replaced = False

    def racing_open(path: Path, *args: Any, **kwargs: Any):
        nonlocal replaced
        if path == target.resolve() and not replaced:
            replaced = True
            os.replace(replacement, target)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", racing_open)
    client = FakeClient(_response())
    task = _task_from_root(root, client)

    with pytest.raises(RebarSuggestionTaskError) as raised:
        task.suggest(_request(), correlation_id="corr-race")

    assert raised.value.kind == "infrastructure"
    assert raised.value.code == "skill_path_invalid"
    assert "RACED OUTSIDE SECRET" not in repr(raised.value)
    assert client.calls == []


def test_rejects_skill_bundle_or_reference_count_over_limit(tmp_path: Path) -> None:
    from src.ai.rebar_suggestion_task import RebarSuggestionTaskError

    client = FakeClient(_response())
    byte_limited = _task(tmp_path, client, max_skill_bytes=20)
    with pytest.raises(RebarSuggestionTaskError) as byte_error:
        byte_limited.suggest(_request(), correlation_id="corr-skill-bytes")
    assert byte_error.value.code == "skill_too_large"
    assert client.calls == []

    client = FakeClient(_response())
    file_limited = _task(tmp_path, client, max_reference_files=1)
    with pytest.raises(RebarSuggestionTaskError) as file_error:
        file_limited.suggest(_request(), correlation_id="corr-skill-files")
    assert file_error.value.code == "skill_too_large"
    assert client.calls == []


def test_task_repr_and_errors_never_include_client_or_prompt_secrets(tmp_path: Path) -> None:
    from src.ai.rebar_suggestion_task import RebarSuggestionTaskError

    base64_blob = "U0VDUkVUX1NZU1RFTV9QUk9NUFQ=" * 10
    client = FakeClient(_response(reason=base64_blob))
    task = _task(tmp_path, client, max_response_bytes=10)

    with pytest.raises(RebarSuggestionTaskError) as raised:
        task.suggest(_request(), correlation_id="corr-redaction")

    serialized = f"{task!r} {raised.value!r}"
    assert client.api_key not in serialized
    assert "Authorization" not in serialized
    assert base64_blob not in serialized
    assert "# Bounded Skill" not in serialized


def test_success_result_repr_and_usage_do_not_echo_model_controlled_secrets(
    tmp_path: Path,
) -> None:
    base64_blob = "U0VDUkVUX1NZU1RFTV9QUk9NUFQ=" * 10
    client = FakeClient(
        _response(reason=base64_blob),
        usage={
            "prompt_tokens": 10,
            "completion_tokens": 3,
            "total_tokens": 13,
            "authorization": "Bearer result-secret-key",
            "system_prompt": base64_blob,
        },
    )
    task = _task(tmp_path, client)

    result = task.suggest(_request(), correlation_id="corr-safe-result")

    assert result.usage == {
        "prompt_tokens": 10,
        "completion_tokens": 3,
        "total_tokens": 13,
    }
    serialized = repr(result)
    assert "result-secret-key" not in serialized
    assert "authorization" not in serialized
    assert base64_blob not in serialized


def _task_from_root(root: Path, client: FakeClient):
    from src.ai.rebar_suggestion_task import (
        RebarSuggestionTask,
        RebarSuggestionTaskLimits,
    )

    return RebarSuggestionTask(
        client=client,
        model="structured-model",
        skill_root=root,
        skill_version="1.0.0",
        limits=RebarSuggestionTaskLimits(),
    )
