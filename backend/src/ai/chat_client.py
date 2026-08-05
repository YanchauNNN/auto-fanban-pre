from __future__ import annotations

import json
import re
from contextlib import suppress
from dataclasses import dataclass, field
from http.client import HTTPException
from typing import Any, Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..config.ai.ai_spec import AiSpec


class ChatClientError(RuntimeError):
    """Base error for model gateway failures."""


class ChatClientTimeout(ChatClientError):
    """Raised when the model gateway times out."""


class ChatGatewayError(ChatClientError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ChatGatewayResponseError(ChatGatewayError):
    """Raised when a gateway response is unsafe or malformed."""


class ChatGatewayResponseTooLarge(ChatGatewayResponseError):
    """Raised before parsing when a gateway response exceeds its byte limit."""


class _RejectRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


_NO_REDIRECT_OPENER = build_opener(_RejectRedirectHandler())
_DEFAULT_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


def urlopen(request: Request, *, timeout: float) -> Any:
    return _NO_REDIRECT_OPENER.open(request, timeout=timeout)


@dataclass(repr=False)
class ChatClientConfig:
    base_url: str
    api_key: str | None
    authorization_scheme: str
    model: str
    timeout_seconds: int
    temperature: float
    max_output_tokens: int
    max_retries: int = 1
    retry_backoff_ms: int = 800
    max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES

    def __repr__(self) -> str:
        return (
            "ChatClientConfig("
            f"base_url={self.base_url!r}, "
            f"authorization_scheme={self.authorization_scheme!r}, "
            f"model={self.model!r}, "
            f"timeout_seconds={self.timeout_seconds!r}, "
            f"temperature={self.temperature!r}, "
            f"max_output_tokens={self.max_output_tokens!r}, "
            f"max_retries={self.max_retries!r}, "
            f"max_response_bytes={self.max_response_bytes!r})"
        )


@dataclass
class ChatToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]
    arguments_raw: str


@dataclass
class ChatCompletionResult:
    content: str
    usage: dict[str, Any] = field(default_factory=dict)
    raw_model: str | None = None
    tool_calls: list[ChatToolCall] = field(default_factory=list)


class ChatClientProtocol(Protocol):
    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatCompletionResult: ...


class OpenAICompatibleChatClient:
    def __init__(self, config: ChatClientConfig) -> None:
        self.config = config

    def __repr__(self) -> str:
        return f"OpenAICompatibleChatClient(base_url={self.config.base_url!r}, model={self.config.model!r})"

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatCompletionResult:
        payload = {
            "model": self.config.model,
            "stream": False,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_output_tokens,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        payload_serialization_failed = False
        try:
            encoded_payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError, UnicodeError, RecursionError):
            payload_serialization_failed = True
            encoded_payload = b""
        if payload_serialization_failed:
            raise ChatGatewayError("model gateway request payload is invalid")
        request_build_failed = False
        try:
            request = Request(
                self._chat_completions_url(),
                data=encoded_payload,
                headers=self._headers(),
                method="POST",
            )
        except ChatGatewayError:
            raise
        except ValueError:
            request_build_failed = True
            request = None
        if request_build_failed:
            raise ChatGatewayError("model gateway request configuration is invalid")
        assert request is not None

        attempts = max(int(self.config.max_retries), 0) + 1
        last_error: ChatClientError | None = None
        for attempt in range(attempts):
            should_raise = False
            try:
                with urlopen(request, timeout=float(self.config.timeout_seconds)) as response:
                    response_body = _read_bounded_response(
                        response,
                        max_bytes=self.config.max_response_bytes,
                    )
                    response_parse_failed = False
                    try:
                        response_payload = json.loads(response_body.decode("utf-8"))
                    except (UnicodeError, ValueError, RecursionError):
                        response_parse_failed = True
                    if response_parse_failed:
                        response_body = b""
                        raise ChatGatewayResponseError(
                            "model gateway returned invalid JSON"
                        )
                return _parse_completion_response(response_payload)
            except TimeoutError:
                last_error = ChatClientTimeout("model gateway timed out")
                should_raise = attempt >= attempts - 1
            except HTTPError as exc:
                with suppress(Exception):
                    exc.close()
                last_error = ChatGatewayError(
                    f"model gateway returned HTTP {exc.code}",
                    status_code=exc.code,
                )
                should_raise = (
                    not _is_retryable_status(exc.code) or attempt >= attempts - 1
                )
            except HTTPException:
                last_error = ChatGatewayError(
                    "model gateway returned an invalid HTTP response"
                )
                should_raise = attempt >= attempts - 1
            except ValueError:
                last_error = ChatGatewayError(
                    "model gateway request configuration is invalid"
                )
                should_raise = True
            except URLError:
                last_error = ChatGatewayError("model gateway request failed")
                should_raise = attempt >= attempts - 1
            if should_raise:
                assert last_error is not None
                raise last_error

        if last_error is not None:
            raise last_error
        raise ChatGatewayError("model gateway request failed")

    def _chat_completions_url(self) -> str:
        return f"{self.config.base_url.rstrip('/')}/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            scheme = self.config.authorization_scheme.strip().lower()
            if scheme == "bearer":
                authorization = f"Bearer {self.config.api_key}"
            elif scheme and scheme != "none":
                authorization = (
                    f"{self.config.authorization_scheme} {self.config.api_key}"
                )
            else:
                authorization = self.config.api_key
            if not _is_safe_authorization_header(authorization):
                raise ChatGatewayError(
                    "model gateway authorization configuration is invalid"
                )
            headers["Authorization"] = authorization
        return headers


def build_chat_client(
    spec: AiSpec,
    *,
    model_kind: Literal["chat", "structured"] = "chat",
    timeout_seconds: int | None = None,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
    max_retries: int | None = None,
    max_response_bytes: int | None = None,
) -> OpenAICompatibleChatClient:
    """Build a gateway client without exposing gateway credentials."""

    if model_kind not in {"chat", "structured"}:
        raise ValueError(f"unsupported model_kind: {model_kind!r}")
    gateway = spec.resolve_gateway()
    models = spec.resolve_models()
    chat = spec.ai_layer.chat
    model = models.chat.model if model_kind == "chat" else models.structured.model
    resolved_max_output_tokens = (
        models.chat.max_output_tokens if max_output_tokens is None else max_output_tokens
    )
    if max_response_bytes is not None:
        resolved_max_response_bytes = max_response_bytes
    elif max_output_tokens is not None or model_kind == "chat":
        resolved_max_response_bytes = max(
            64 * 1024,
            resolved_max_output_tokens * 16,
        )
    else:
        resolved_max_response_bytes = _DEFAULT_MAX_RESPONSE_BYTES
    return OpenAICompatibleChatClient(
        ChatClientConfig(
            base_url=gateway.base_url,
            api_key=gateway.api_key,
            authorization_scheme=gateway.authorization_scheme,
            model=model,
            timeout_seconds=(
                chat.request_timeout_seconds if timeout_seconds is None else timeout_seconds
            ),
            temperature=(models.chat.temperature if temperature is None else temperature),
            max_output_tokens=resolved_max_output_tokens,
            max_retries=0 if max_retries is None else max_retries,
            retry_backoff_ms=gateway.retry_backoff_ms,
            max_response_bytes=resolved_max_response_bytes,
        )
    )


def _parse_completion_response(payload: Any) -> ChatCompletionResult:
    if not isinstance(payload, dict):
        raise ChatGatewayResponseError("model gateway response must be an object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ChatGatewayResponseError("model gateway response did not include choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise ChatGatewayResponseError("model gateway response choice is invalid")
    message = first.get("message")
    content: Any = None
    tool_calls: list[ChatToolCall] = []
    if isinstance(message, dict):
        content = message.get("content")
        tool_calls = _parse_tool_calls(message.get("tool_calls"))
    if content is None and isinstance(first.get("delta"), dict):
        content = first["delta"].get("content")
        tool_calls = _parse_tool_calls(first["delta"].get("tool_calls"))
    if content is None and tool_calls:
        content = ""
    if not isinstance(content, str):
        raise ChatGatewayResponseError("model gateway response did not include assistant content")
    usage = payload.get("usage")
    return ChatCompletionResult(
        content=_strip_think_blocks(content),
        usage=usage if isinstance(usage, dict) else {},
        raw_model=payload.get("model") if isinstance(payload.get("model"), str) else None,
        tool_calls=tool_calls,
    )


def _parse_tool_calls(value: Any) -> list[ChatToolCall]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ChatGatewayResponseError("model gateway returned invalid tool calls")
    parsed: list[ChatToolCall] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or not isinstance(item.get("function"), dict):
            raise ChatGatewayResponseError("model gateway returned an invalid tool call")
        function = item["function"]
        name = function.get("name")
        arguments_raw = function.get("arguments", "{}")
        if not isinstance(name, str) or not name.strip() or not isinstance(arguments_raw, str):
            raise ChatGatewayResponseError("model gateway returned an invalid tool function")
        arguments_parse_failed = False
        try:
            arguments = json.loads(arguments_raw or "{}")
        except (ValueError, RecursionError):
            arguments_parse_failed = True
            arguments = None
        if arguments_parse_failed:
            arguments_raw = ""
            function = {}
            item = {}
            value = None
            raise ChatGatewayResponseError(
                "model gateway returned invalid tool arguments"
            )
        if not isinstance(arguments, dict):
            raise ChatGatewayResponseError("model gateway tool arguments must be an object")
        call_id = item.get("id")
        parsed.append(
            ChatToolCall(
                call_id=call_id if isinstance(call_id, str) and call_id else f"tool-call-{index}",
                name=name.strip(),
                arguments=arguments,
                arguments_raw=arguments_raw,
            ),
        )
    return parsed


def _read_bounded_response(response: Any, *, max_bytes: int) -> bytes:
    if max_bytes <= 0:
        raise ChatGatewayResponseError("model gateway response size limit is invalid")
    try:
        body = response.read(max_bytes + 1)
    except TypeError:
        raise ChatGatewayResponseError(
            "model gateway response does not support bounded reads"
        ) from None
    if not isinstance(body, (bytes, bytearray)):
        body = b""
        raise ChatGatewayResponseError("model gateway response body is invalid")
    if len(body) > max_bytes:
        body = b""
        raise ChatGatewayResponseTooLarge(
            "model gateway response exceeded size limit"
        )
    return bytes(body)


def _is_retryable_status(status_code: int) -> bool:
    return status_code in {408, 429, 500, 502, 503, 504}


def _is_safe_authorization_header(value: str) -> bool:
    try:
        encoded = value.encode("latin-1")
    except UnicodeError:
        return False
    return len(encoded) <= 8_192 and all(32 <= byte <= 126 for byte in encoded)


def _strip_think_blocks(content: str) -> str:
    cleaned = re.sub(r"<think\b[^>]*>.*?</think>", "", content, flags=re.IGNORECASE | re.DOTALL)
    return cleaned.strip()
