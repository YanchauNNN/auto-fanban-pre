from __future__ import annotations

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
    )

    assert client.config.model == "structured-model"
    assert client.config.timeout_seconds == 120
    assert client.config.temperature == 0
    assert client.config.max_output_tokens == 32_768
    assert client.config.max_retries == 2


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
