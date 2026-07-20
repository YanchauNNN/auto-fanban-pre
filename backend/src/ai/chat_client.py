from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class ChatClientError(RuntimeError):
    """Base error for model gateway failures."""


class ChatClientTimeout(ChatClientError):
    """Raised when the model gateway times out."""


class ChatGatewayError(ChatClientError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class _RejectRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


_NO_REDIRECT_OPENER = build_opener(_RejectRedirectHandler())


def urlopen(request: Request, *, timeout: float):
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

    def __repr__(self) -> str:
        return (
            "ChatClientConfig("
            f"base_url={self.base_url!r}, "
            f"authorization_scheme={self.authorization_scheme!r}, "
            f"model={self.model!r}, "
            f"timeout_seconds={self.timeout_seconds!r}, "
            f"temperature={self.temperature!r}, "
            f"max_output_tokens={self.max_output_tokens!r}, "
            f"max_retries={self.max_retries!r})"
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
        request = Request(
            self._chat_completions_url(),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )

        attempts = max(int(self.config.max_retries), 0) + 1
        last_error: ChatClientError | None = None
        for attempt in range(attempts):
            try:
                with urlopen(request, timeout=float(self.config.timeout_seconds)) as response:
                    response_payload = json.loads(response.read().decode("utf-8"))
                return _parse_completion_response(response_payload)
            except TimeoutError as exc:
                last_error = ChatClientTimeout("model gateway timed out")
                if attempt >= attempts - 1:
                    raise last_error from exc
            except HTTPError as exc:
                body = _read_error_body(exc)
                last_error = ChatGatewayError(
                    f"model gateway returned HTTP {exc.code}: {body}",
                    status_code=exc.code,
                )
                if not _is_retryable_status(exc.code) or attempt >= attempts - 1:
                    raise last_error from exc
            except URLError as exc:
                last_error = ChatGatewayError(f"model gateway request failed: {exc.reason}")
                if attempt >= attempts - 1:
                    raise last_error from exc
            except json.JSONDecodeError as exc:
                raise ChatGatewayError("model gateway returned invalid JSON") from exc

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
                headers["Authorization"] = f"Bearer {self.config.api_key}"
            elif scheme and scheme != "none":
                headers["Authorization"] = f"{self.config.authorization_scheme} {self.config.api_key}"
            else:
                headers["Authorization"] = self.config.api_key
        return headers


def _parse_completion_response(payload: dict[str, Any]) -> ChatCompletionResult:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ChatGatewayError("model gateway response did not include choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise ChatGatewayError("model gateway response choice is invalid")
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
        raise ChatGatewayError("model gateway response did not include assistant content")
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
        raise ChatGatewayError("model gateway returned invalid tool calls")
    parsed: list[ChatToolCall] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or not isinstance(item.get("function"), dict):
            raise ChatGatewayError("model gateway returned an invalid tool call")
        function = item["function"]
        name = function.get("name")
        arguments_raw = function.get("arguments", "{}")
        if not isinstance(name, str) or not name.strip() or not isinstance(arguments_raw, str):
            raise ChatGatewayError("model gateway returned an invalid tool function")
        try:
            arguments = json.loads(arguments_raw or "{}")
        except json.JSONDecodeError as exc:
            raise ChatGatewayError("model gateway returned invalid tool arguments") from exc
        if not isinstance(arguments, dict):
            raise ChatGatewayError("model gateway tool arguments must be an object")
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


def _read_error_body(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace").strip()
    except Exception:
        body = ""
    return body[:500]


def _is_retryable_status(status_code: int) -> bool:
    return status_code in {408, 429, 500, 502, 503, 504}


def _strip_think_blocks(content: str) -> str:
    cleaned = re.sub(r"<think\b[^>]*>.*?</think>", "", content, flags=re.IGNORECASE | re.DOTALL)
    return cleaned.strip()
