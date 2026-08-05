from __future__ import annotations

import json
from http.client import BadStatusLine
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import pytest


def _spec(tmp_path: Path):
    from src.config.ai.ai_spec import AiSpec

    spec = AiSpec.model_validate(
        {
            "ai_layer": {
                "model_gateway": {
                    "base_url": "http://127.0.0.1:8001/v1",
                    "api_key_policy": "literal_for_test",
                    "api_key": "factory-secret-api-key",
                    "authorization_scheme": "bearer",
                    "retry_backoff_ms": 321,
                },
                "models": {
                    "chat": {
                        "model": "chat-model",
                        "temperature": 0.2,
                        "max_output_tokens": 2048,
                    },
                    "structured": {"model": "structured-model"},
                },
                "chat": {"request_timeout_seconds": 23},
            }
        }
    )
    spec.source_path = tmp_path / "参数规范_AI.yaml"
    return spec


def test_build_chat_client_keeps_default_chat_runtime_behavior(tmp_path: Path) -> None:
    from src.ai.chat_client import build_chat_client

    client = build_chat_client(_spec(tmp_path))

    assert client.config.model == "chat-model"
    assert client.config.timeout_seconds == 23
    assert client.config.temperature == 0.2
    assert client.config.max_output_tokens == 2048
    assert client.config.max_retries == 0
    assert client.config.retry_backoff_ms == 321


def test_build_chat_client_selects_structured_model_and_task_overrides(tmp_path: Path) -> None:
    from src.ai.chat_client import build_chat_client

    client = build_chat_client(
        _spec(tmp_path),
        model_kind="structured",
        timeout_seconds=120,
        temperature=0,
        max_output_tokens=32_768,
        max_retries=2,
        max_response_bytes=123_456,
    )

    assert client.config.model == "structured-model"
    assert client.config.timeout_seconds == 120
    assert client.config.temperature == 0
    assert client.config.max_output_tokens == 32_768
    assert client.config.max_retries == 2
    assert client.config.max_response_bytes == 123_456


def test_structured_default_response_limit_is_not_derived_from_chat_tokens(
    tmp_path: Path,
) -> None:
    from src.ai.chat_client import build_chat_client

    client = build_chat_client(_spec(tmp_path), model_kind="structured")

    assert client.config.model == "structured-model"
    assert client.config.max_response_bytes == 4 * 1024 * 1024


def test_router_reexports_shared_chat_client_factory() -> None:
    from API.app.routers import ai as ai_router

    from src.ai.chat_client import build_chat_client

    assert ai_router.build_chat_client is build_chat_client


def test_build_chat_client_rejects_unknown_model_kind(tmp_path: Path) -> None:
    from src.ai.chat_client import build_chat_client

    with pytest.raises(ValueError, match="model_kind"):
        build_chat_client(_spec(tmp_path), model_kind="embedding")  # type: ignore[arg-type]


def test_client_repr_and_gateway_error_redact_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.ai.chat_client import (
        ChatClientConfig,
        ChatGatewayError,
        OpenAICompatibleChatClient,
    )

    secret = "gateway-secret-api-key"
    client = OpenAICompatibleChatClient(
        ChatClientConfig(
            base_url="http://127.0.0.1:8001/v1",
            api_key=secret,
            authorization_scheme="bearer",
            model="structured-model",
            timeout_seconds=120,
            temperature=0,
            max_output_tokens=32_768,
            max_retries=0,
        )
    )

    def fake_urlopen(*_args, **_kwargs):
        raise HTTPError(
            "http://127.0.0.1:8001/v1/chat/completions",
            500,
            "failed",
            {},
            BytesIO(f'{{"error":"request rejected for {secret}"}}'.encode()),
        )

    monkeypatch.setattr("src.ai.chat_client.urlopen", fake_urlopen)

    with pytest.raises(ChatGatewayError) as exc_info:
        client.complete([{"role": "user", "content": "normalize"}])

    assert secret not in repr(client.config)
    assert secret not in repr(client)
    assert secret not in str(exc_info.value)


def test_client_rejects_oversized_gateway_body_before_json_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.ai.chat_client import (
        ChatClientConfig,
        ChatGatewayResponseError,
        OpenAICompatibleChatClient,
    )

    secret_body = b'{"choices":[]}' + b"SENSITIVE-BASE64-A" * 20
    reads: list[int | None] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, amount: int | None = None) -> bytes:
            reads.append(amount)
            if amount is None:
                return secret_body
            return secret_body[:amount]

    monkeypatch.setattr(
        "src.ai.chat_client.urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )
    client = OpenAICompatibleChatClient(
        ChatClientConfig(
            base_url="http://127.0.0.1:8001/v1",
            api_key="secret-key",
            authorization_scheme="bearer",
            model="structured-model",
            timeout_seconds=10,
            temperature=0,
            max_output_tokens=10,
            max_retries=0,
            max_response_bytes=32,
        )
    )

    with pytest.raises(ChatGatewayResponseError) as raised:
        client.complete([{"role": "user", "content": "bounded"}])

    assert reads == [33]
    assert str(raised.value) == "model gateway response exceeded size limit"
    assert "SENSITIVE-BASE64" not in repr(raised.value)


def test_client_rejects_an_adapter_that_cannot_perform_a_bounded_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.ai.chat_client import (
        ChatClientConfig,
        ChatGatewayResponseError,
        OpenAICompatibleChatClient,
    )

    unbounded_reads: list[bool] = []

    class UnboundedOnlyResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            unbounded_reads.append(True)
            return b'{"choices":[]}' + b"SENSITIVE" * 1_000

    monkeypatch.setattr(
        "src.ai.chat_client.urlopen",
        lambda *_args, **_kwargs: UnboundedOnlyResponse(),
    )
    client = OpenAICompatibleChatClient(
        ChatClientConfig(
            base_url="http://127.0.0.1:8001/v1",
            api_key=None,
            authorization_scheme="none",
            model="structured-model",
            timeout_seconds=10,
            temperature=0,
            max_output_tokens=10,
            max_retries=0,
            max_response_bytes=32,
        )
    )

    with pytest.raises(ChatGatewayResponseError) as raised:
        client.complete([{"role": "user", "content": "bounded"}])

    assert str(raised.value) == "model gateway response does not support bounded reads"
    assert unbounded_reads == []


def test_invalid_gateway_json_does_not_retain_the_raw_response_in_an_exception_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.ai.chat_client import (
        ChatClientConfig,
        ChatGatewayResponseError,
        OpenAICompatibleChatClient,
    )

    secret_body = b"not-json-SENSITIVE-BASE64-U0VDUkVU"

    class InvalidJsonResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, amount: int | None = None) -> bytes:
            return secret_body if amount is None else secret_body[:amount]

    monkeypatch.setattr(
        "src.ai.chat_client.urlopen",
        lambda *_args, **_kwargs: InvalidJsonResponse(),
    )
    client = OpenAICompatibleChatClient(
        ChatClientConfig(
            base_url="http://127.0.0.1:8001/v1",
            api_key=None,
            authorization_scheme="none",
            model="structured-model",
            timeout_seconds=10,
            temperature=0,
            max_output_tokens=10,
            max_retries=0,
        )
    )

    with pytest.raises(ChatGatewayResponseError) as raised:
        client.complete([{"role": "user", "content": "bounded"}])

    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert "SENSITIVE-BASE64" not in repr(raised.value)


def test_invalid_large_integer_in_tool_arguments_is_a_sanitized_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.ai.chat_client import (
        ChatClientConfig,
        ChatGatewayResponseError,
        OpenAICompatibleChatClient,
    )

    arguments = '{"value":' + "9" * 5_000 + "}"
    body = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {
                                    "name": "unsafe",
                                    "arguments": arguments,
                                },
                            }
                        ],
                    }
                }
            ]
        }
    ).encode()

    class InvalidToolResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, amount: int | None = None) -> bytes:
            return body if amount is None else body[:amount]

    monkeypatch.setattr(
        "src.ai.chat_client.urlopen",
        lambda *_args, **_kwargs: InvalidToolResponse(),
    )
    client = OpenAICompatibleChatClient(
        ChatClientConfig(
            base_url="http://127.0.0.1:8001/v1",
            api_key=None,
            authorization_scheme="none",
            model="structured-model",
            timeout_seconds=10,
            temperature=0,
            max_output_tokens=10,
            max_retries=0,
        )
    )

    with pytest.raises(ChatGatewayResponseError) as raised:
        client.complete([{"role": "user", "content": "bounded"}])

    assert str(raised.value) == "model gateway returned invalid tool arguments"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert "9999999999" not in repr(raised.value)


def test_authentication_error_does_not_echo_gateway_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.ai.chat_client import (
        ChatClientConfig,
        ChatGatewayError,
        OpenAICompatibleChatClient,
    )

    secret = "gateway-secret-api-key"
    system_prompt = "COMPLETE-SYSTEM-PROMPT-SHOULD-NOT-LEAK"

    upstream = HTTPError(
        "http://127.0.0.1:8001/v1/chat/completions",
        401,
        "unauthorized",
        {"Authorization": f"Bearer {secret}"},
        BytesIO(
            (
                f'{{"error":"Authorization: Bearer {secret}; '
                f'{system_prompt}; U0VDUkVUX0JBU0U2NA=="}}'
            ).encode()
        )
    )

    def fake_urlopen(*_args, **_kwargs):
        raise upstream

    monkeypatch.setattr("src.ai.chat_client.urlopen", fake_urlopen)
    client = OpenAICompatibleChatClient(
        ChatClientConfig(
            base_url="http://127.0.0.1:8001/v1",
            api_key=secret,
            authorization_scheme="bearer",
            model="structured-model",
            timeout_seconds=10,
            temperature=0,
            max_output_tokens=100,
            max_retries=0,
        )
    )

    with pytest.raises(ChatGatewayError) as raised:
        client.complete([{"role": "system", "content": system_prompt}])

    assert raised.value.status_code == 401
    assert str(raised.value) == "model gateway returned HTTP 401"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert upstream.fp is None or upstream.fp.closed
    for forbidden in (secret, "Authorization", system_prompt, "U0VDUkVUX0JBU0U2NA"):
        assert forbidden not in repr(raised.value)


def test_malformed_http_status_line_is_sanitized_without_exception_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.ai.chat_client import (
        ChatClientConfig,
        ChatGatewayError,
        OpenAICompatibleChatClient,
    )

    sensitive = "Authorization: Bearer secret-key COMPLETE-PROMPT U0VDUkVU"
    monkeypatch.setattr(
        "src.ai.chat_client.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(BadStatusLine(sensitive)),
    )
    client = OpenAICompatibleChatClient(
        ChatClientConfig(
            base_url="http://127.0.0.1:8001/v1",
            api_key="secret-key",
            authorization_scheme="bearer",
            model="structured-model",
            timeout_seconds=10,
            temperature=0,
            max_output_tokens=10,
            max_retries=0,
        )
    )

    with pytest.raises(ChatGatewayError) as raised:
        client.complete([{"role": "user", "content": "bounded"}])

    assert str(raised.value) == "model gateway returned an invalid HTTP response"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    for forbidden in ("secret-key", "Authorization", "COMPLETE-PROMPT", "U0VDUkVU"):
        assert forbidden not in repr(raised.value)


def test_request_with_an_isolated_surrogate_is_rejected_without_leaking_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.ai.chat_client import (
        ChatClientConfig,
        ChatGatewayError,
        OpenAICompatibleChatClient,
    )

    calls: list[bool] = []
    monkeypatch.setattr(
        "src.ai.chat_client.urlopen",
        lambda *_args, **_kwargs: calls.append(True),
    )
    client = OpenAICompatibleChatClient(
        ChatClientConfig(
            base_url="http://127.0.0.1:8001/v1",
            api_key=None,
            authorization_scheme="none",
            model="structured-model",
            timeout_seconds=10,
            temperature=0,
            max_output_tokens=10,
            max_retries=0,
        )
    )
    sensitive = "\ud800COMPLETE-PROMPT-U0VDUkVU"

    with pytest.raises(ChatGatewayError) as raised:
        client.complete([{"role": "user", "content": sensitive}])

    assert str(raised.value) == "model gateway request payload is invalid"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert "COMPLETE-PROMPT" not in repr(raised.value)
    assert calls == []


def test_authorization_header_control_characters_are_rejected_without_key_leakage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.ai.chat_client import (
        ChatClientConfig,
        ChatGatewayError,
        OpenAICompatibleChatClient,
    )

    secret = "secret-key\r\nAuthorization: Bearer echoed-secret"
    calls: list[bool] = []

    def unsafe_urlopen(*_args: object, **_kwargs: object):
        calls.append(True)
        raise ValueError(f"Invalid header value: Bearer {secret}")

    monkeypatch.setattr("src.ai.chat_client.urlopen", unsafe_urlopen)
    client = OpenAICompatibleChatClient(
        ChatClientConfig(
            base_url="http://127.0.0.1:8001/v1",
            api_key=secret,
            authorization_scheme="bearer",
            model="structured-model",
            timeout_seconds=10,
            temperature=0,
            max_output_tokens=10,
            max_retries=0,
        )
    )

    with pytest.raises(ChatGatewayError) as raised:
        client.complete([{"role": "user", "content": "bounded"}])

    assert str(raised.value) == "model gateway authorization configuration is invalid"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert "secret-key" not in repr(raised.value)
    assert "Authorization" not in repr(raised.value)
    assert calls == []
