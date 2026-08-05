from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from threading import Lock
from typing import Literal, NoReturn

import yaml

from ..calculation_book.ai_rebar_suggestion_schema import (
    AiRebarSuggestionRequest,
    AiRebarSuggestionResponse,
    InvalidAiRebarSuggestionPayload,
    parse_ai_rebar_suggestion_response,
)
from ..config.ai.ai_spec import AiSpec
from .chat_client import (
    ChatClientError,
    ChatClientProtocol,
    ChatClientTimeout,
    ChatGatewayError,
    ChatGatewayResponseError,
    ChatGatewayResponseTooLarge,
    build_chat_client,
)

_EXPECTED_SKILL_ID = "recommend-rebar-from-smx"
_FRONTMATTER = re.compile(
    r"\A---[ \t]*\r?\n(?P<body>.*?)\r?\n---(?:[ \t]*\r?\n|\Z)",
    re.DOTALL,
)
_MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\((?P<target>[^)\s]+)(?:\s+[^)]*)?\)")

RebarSuggestionTaskErrorKind = Literal["infrastructure", "model_call"]
RebarSuggestionTaskErrorCode = Literal[
    "skill_missing",
    "skill_path_invalid",
    "skill_too_large",
    "request_too_large",
    "model_timeout",
    "model_connection_failed",
    "model_authentication_failed",
    "model_gateway_failed",
    "model_response_too_large",
    "model_response_invalid",
]


class RebarSuggestionTaskError(RuntimeError):
    """Sanitized failure raised by one structured recommendation call."""

    def __init__(
        self,
        kind: RebarSuggestionTaskErrorKind,
        code: RebarSuggestionTaskErrorCode,
        message: str,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.code = code


@dataclass(frozen=True)
class RebarSuggestionTaskLimits:
    max_skill_bytes: int = 128 * 1024
    max_reference_files: int = 8
    max_request_bytes: int = 1024 * 1024
    max_response_bytes: int = 1024 * 1024
    max_response_tokens: int = 65_536
    max_identifier_chars: int = 200

    def __post_init__(self) -> None:
        for name, value in (
            ("max_skill_bytes", self.max_skill_bytes),
            ("max_reference_files", self.max_reference_files),
            ("max_request_bytes", self.max_request_bytes),
            ("max_response_bytes", self.max_response_bytes),
            ("max_response_tokens", self.max_response_tokens),
            ("max_identifier_chars", self.max_identifier_chars),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be greater than 0")


@dataclass(frozen=True)
class RebarSuggestionSkillBundle:
    skill_id: str
    skill_version: str
    content_sha256: str
    content: str = field(repr=False)


@dataclass(frozen=True)
class RebarSuggestionTaskResult:
    response: AiRebarSuggestionResponse = field(repr=False)
    correlation_id: str
    task_id: str
    skill_id: str
    skill_version: str
    skill_sha256: str
    model: str
    usage: dict[str, int] = field(default_factory=dict, repr=False)


class RebarSuggestionTask:
    def __init__(
        self,
        *,
        client: ChatClientProtocol,
        model: str,
        skill_root: Path,
        skill_version: str,
        limits: RebarSuggestionTaskLimits,
    ) -> None:
        self._client = client
        self.model = str(model)
        self.skill_root = Path(skill_root)
        self.skill_version = str(skill_version)
        self.limits = limits
        self._skill_bundle: RebarSuggestionSkillBundle | None = None
        self._skill_bundle_lock = Lock()

    def __repr__(self) -> str:
        return (
            "RebarSuggestionTask("
            f"model={self.model!r}, skill_root={self.skill_root!r}, "
            f"skill_version={self.skill_version!r}, limits={self.limits!r})"
        )

    def suggest(
        self,
        request: AiRebarSuggestionRequest,
        *,
        correlation_id: str,
    ) -> RebarSuggestionTaskResult:
        correlation_id = self._bounded_identifier(
            correlation_id,
            label="correlation_id",
        )
        task_id = self._bounded_identifier(request.task_id, label="task_id")
        bundle = self._load_skill_bundle()
        messages = self._messages(
            bundle=bundle,
            request=request,
            correlation_id=correlation_id,
            task_id=task_id,
        )
        completion = self._complete(messages)
        content = completion.content
        if not isinstance(content, str):
            self._raise_invalid_response()
        response_encoding_failed = False
        try:
            response_bytes = content.encode("utf-8")
        except UnicodeError:
            response_encoding_failed = True
            response_bytes = b""
        if response_encoding_failed:
            completion = None
            content = ""
            self._raise_invalid_response()
        completion_tokens = _completion_token_count(completion.usage)
        if len(response_bytes) > self.limits.max_response_bytes or (
            completion_tokens is not None and completion_tokens > self.limits.max_response_tokens
        ):
            raise RebarSuggestionTaskError(
                "model_call",
                "model_response_too_large",
                "structured rebar suggestion response exceeded its safe limit",
            )

        response_error = False
        try:
            response = parse_ai_rebar_suggestion_response(content, request=request)
        except (InvalidAiRebarSuggestionPayload, ValueError, RecursionError):
            response_error = True
        if response_error:
            completion = None
            content = ""
            self._raise_invalid_response()

        usage = _safe_usage(completion.usage)
        return RebarSuggestionTaskResult(
            response=response,
            correlation_id=correlation_id,
            task_id=task_id,
            skill_id=bundle.skill_id,
            skill_version=bundle.skill_version,
            skill_sha256=bundle.content_sha256,
            model=self.model,
            usage=usage,
        )

    def _complete(self, messages: list[dict[str, str]]):
        failure: RebarSuggestionTaskError | None = None
        try:
            return self._client.complete(messages)
        except (ChatClientTimeout, TimeoutError):
            failure = RebarSuggestionTaskError(
                "infrastructure",
                "model_timeout",
                "structured rebar suggestion model timed out",
            )
        except ChatGatewayResponseTooLarge:
            failure = RebarSuggestionTaskError(
                "model_call",
                "model_response_too_large",
                "structured rebar suggestion response exceeded its safe limit",
            )
        except ChatGatewayResponseError:
            failure = RebarSuggestionTaskError(
                "model_call",
                "model_response_invalid",
                "structured rebar suggestion response is invalid",
            )
        except ChatGatewayError as exc:
            code: RebarSuggestionTaskErrorCode = (
                "model_authentication_failed"
                if exc.status_code in {401, 403}
                else "model_gateway_failed"
            )
            failure = RebarSuggestionTaskError(
                "infrastructure",
                code,
                "structured rebar suggestion gateway request failed",
            )
        except ChatClientError:
            failure = RebarSuggestionTaskError(
                "infrastructure",
                "model_gateway_failed",
                "structured rebar suggestion gateway request failed",
            )
        except (ConnectionError, OSError):
            failure = RebarSuggestionTaskError(
                "infrastructure",
                "model_connection_failed",
                "structured rebar suggestion model connection failed",
            )
        assert failure is not None
        raise failure

    def _load_skill_bundle(self) -> RebarSuggestionSkillBundle:
        if self._skill_bundle is not None:
            return self._skill_bundle
        with self._skill_bundle_lock:
            if self._skill_bundle is None:
                self._skill_bundle = self._read_skill_bundle()
            return self._skill_bundle

    def _read_skill_bundle(self) -> RebarSuggestionSkillBundle:
        try:
            root = self.skill_root.resolve(strict=True)
        except (OSError, RuntimeError):
            raise RebarSuggestionTaskError(
                "infrastructure",
                "skill_missing",
                "rebar suggestion Skill bundle is unavailable",
            ) from None
        if not root.is_dir():
            raise RebarSuggestionTaskError(
                "infrastructure",
                "skill_missing",
                "rebar suggestion Skill bundle is unavailable",
            )
        try:
            root_snapshot = _stat_identity(root.stat())
        except OSError:
            raise RebarSuggestionTaskError(
                "infrastructure",
                "skill_missing",
                "rebar suggestion Skill bundle is unavailable",
            ) from None

        skill_bytes = self._read_bounded_file(
            root,
            Path("SKILL.md"),
            remaining=self.limits.max_skill_bytes,
        )
        skill_text = self._decode_skill_text(skill_bytes)
        skill_id = self._skill_id(skill_text)
        references = self._direct_references(skill_text)
        if len(references) > self.limits.max_reference_files:
            raise RebarSuggestionTaskError(
                "infrastructure",
                "skill_too_large",
                "rebar suggestion Skill bundle exceeds its safe limit",
            )

        parts: list[tuple[str, str]] = [("SKILL.md", skill_text)]
        consumed = len(skill_bytes)
        for relative in references:
            payload = self._read_bounded_file(
                root,
                Path(*relative.parts),
                remaining=self.limits.max_skill_bytes - consumed,
            )
            consumed += len(payload)
            parts.append((relative.as_posix(), self._decode_skill_text(payload)))
        self._assert_root_unchanged(root, root_snapshot)

        content = "\n\n".join(f"## {name}\n{text}" for name, text in parts)
        if len(content.encode("utf-8")) > self.limits.max_skill_bytes:
            raise RebarSuggestionTaskError(
                "infrastructure",
                "skill_too_large",
                "rebar suggestion Skill bundle exceeds its safe limit",
            )
        return RebarSuggestionSkillBundle(
            skill_id=skill_id,
            skill_version=self._bounded_identifier(
                self.skill_version,
                label="skill_version",
            ),
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            content=content,
        )

    def _read_bounded_file(
        self,
        root: Path,
        relative: Path,
        *,
        remaining: int,
    ) -> bytes:
        if remaining <= 0:
            raise RebarSuggestionTaskError(
                "infrastructure",
                "skill_too_large",
                "rebar suggestion Skill bundle exceeds its safe limit",
            )
        candidate = root / relative
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            raise RebarSuggestionTaskError(
                "infrastructure",
                "skill_missing",
                "rebar suggestion Skill bundle is unavailable",
            ) from None
        if not resolved.is_relative_to(root):
            raise RebarSuggestionTaskError(
                "infrastructure",
                "skill_path_invalid",
                "rebar suggestion Skill bundle path is invalid",
            )
        if not resolved.is_file():
            raise RebarSuggestionTaskError(
                "infrastructure",
                "skill_missing",
                "rebar suggestion Skill bundle is unavailable",
            )
        try:
            path_snapshot = _stat_state(resolved.stat())
        except OSError:
            raise RebarSuggestionTaskError(
                "infrastructure",
                "skill_missing",
                "rebar suggestion Skill bundle is unavailable",
            ) from None
        try:
            with resolved.open("rb") as stream:
                opened_before = _stat_state(os.fstat(stream.fileno()))
                if opened_before != path_snapshot:
                    self._raise_skill_path_changed()
                payload = stream.read(remaining + 1)
                opened_after = _stat_state(os.fstat(stream.fileno()))
                if opened_after != opened_before:
                    self._raise_skill_path_changed()
        except RebarSuggestionTaskError:
            raise
        except OSError:
            raise RebarSuggestionTaskError(
                "infrastructure",
                "skill_missing",
                "rebar suggestion Skill bundle is unavailable",
            ) from None
        try:
            resolved_after = candidate.resolve(strict=True)
            path_after = _stat_state(resolved_after.stat())
        except (OSError, RuntimeError):
            self._raise_skill_path_changed()
        if (
            resolved_after != resolved
            or not resolved_after.is_relative_to(root)
            or path_after != opened_after
        ):
            self._raise_skill_path_changed()
        if len(payload) > remaining:
            raise RebarSuggestionTaskError(
                "infrastructure",
                "skill_too_large",
                "rebar suggestion Skill bundle exceeds its safe limit",
            )
        return payload

    def _assert_root_unchanged(
        self,
        root: Path,
        expected_snapshot: tuple[int, int],
    ) -> None:
        try:
            resolved_after = self.skill_root.resolve(strict=True)
            snapshot_after = _stat_identity(resolved_after.stat())
        except (OSError, RuntimeError):
            self._raise_skill_path_changed()
        if resolved_after != root or snapshot_after != expected_snapshot:
            self._raise_skill_path_changed()

    @staticmethod
    def _raise_skill_path_changed() -> NoReturn:
        raise RebarSuggestionTaskError(
            "infrastructure",
            "skill_path_invalid",
            "rebar suggestion Skill bundle changed during loading",
        )

    @staticmethod
    def _decode_skill_text(payload: bytes) -> str:
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            raise RebarSuggestionTaskError(
                "infrastructure",
                "skill_path_invalid",
                "rebar suggestion Skill bundle is invalid",
            ) from None

    @staticmethod
    def _skill_id(skill_text: str) -> str:
        match = _FRONTMATTER.match(skill_text)
        if match is None:
            raise RebarSuggestionTaskError(
                "infrastructure",
                "skill_path_invalid",
                "rebar suggestion Skill metadata is invalid",
            )
        try:
            metadata = yaml.safe_load(match.group("body"))
        except (yaml.YAMLError, RecursionError, ValueError):
            metadata = None
        if not isinstance(metadata, dict) or metadata.get("name") != _EXPECTED_SKILL_ID:
            raise RebarSuggestionTaskError(
                "infrastructure",
                "skill_path_invalid",
                "rebar suggestion Skill metadata is invalid",
            )
        return _EXPECTED_SKILL_ID

    @staticmethod
    def _direct_references(skill_text: str) -> tuple[PurePosixPath, ...]:
        references: list[PurePosixPath] = []
        seen: set[str] = set()
        for match in _MARKDOWN_LINK.finditer(skill_text):
            target = match.group("target")
            if not target.startswith("references/"):
                if "://" in target or target.startswith(("/", "\\", "..")):
                    raise RebarSuggestionTaskError(
                        "infrastructure",
                        "skill_path_invalid",
                        "rebar suggestion Skill reference path is invalid",
                    )
                continue
            if "\\" in target or "?" in target or "#" in target:
                raise RebarSuggestionTaskError(
                    "infrastructure",
                    "skill_path_invalid",
                    "rebar suggestion Skill reference path is invalid",
                )
            relative = PurePosixPath(target)
            if (
                relative.is_absolute()
                or len(relative.parts) != 2
                or relative.parts[0] != "references"
                or relative.parts[1] in {"", ".", ".."}
            ):
                raise RebarSuggestionTaskError(
                    "infrastructure",
                    "skill_path_invalid",
                    "rebar suggestion Skill reference path is invalid",
                )
            normalized = relative.as_posix()
            if normalized not in seen:
                seen.add(normalized)
                references.append(relative)
        return tuple(references)

    def _bounded_identifier(self, value: str, *, label: str) -> str:
        if not isinstance(value, str):
            raise RebarSuggestionTaskError(
                "infrastructure",
                "request_too_large",
                "structured rebar suggestion identifiers are invalid",
            )
        normalized = value.strip()
        if (
            not normalized
            or len(normalized) > self.limits.max_identifier_chars
            or any(unicodedata.category(character).startswith("C") for character in normalized)
        ):
            raise RebarSuggestionTaskError(
                "infrastructure",
                "request_too_large",
                f"structured rebar suggestion {label} is invalid",
            )
        return normalized

    def _messages(
        self,
        *,
        bundle: RebarSuggestionSkillBundle,
        request: AiRebarSuggestionRequest,
        correlation_id: str,
        task_id: str,
    ) -> list[dict[str, str]]:
        system_content = _compact_json(
            {
                "skill_bundle": {
                    "skill_id": bundle.skill_id,
                    "skill_version": bundle.skill_version,
                    "content_sha256": bundle.content_sha256,
                    "content": bundle.content,
                }
            }
        )
        user_content = _compact_json(
            {
                "correlation_id": correlation_id,
                "task_id": task_id,
                "request": request.model_dump(mode="json"),
            }
        )
        request_encoding_failed = False
        try:
            user_content_size = len(user_content.encode("utf-8"))
        except UnicodeError:
            request_encoding_failed = True
            user_content_size = 0
        if request_encoding_failed:
            user_content = ""
            raise RebarSuggestionTaskError(
                "infrastructure",
                "request_too_large",
                "structured rebar suggestion request is invalid",
            )
        if user_content_size > self.limits.max_request_bytes:
            raise RebarSuggestionTaskError(
                "infrastructure",
                "request_too_large",
                "structured rebar suggestion request exceeds its safe limit",
            )
        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

    @staticmethod
    def _raise_invalid_response() -> None:
        raise RebarSuggestionTaskError(
            "model_call",
            "model_response_invalid",
            "structured rebar suggestion response is invalid",
        )


def build_rebar_suggestion_task(
    spec: AiSpec,
    *,
    skill_root: Path,
    skill_version: str,
    request_timeout_seconds: int,
    max_output_tokens: int,
    limits: RebarSuggestionTaskLimits | None = None,
) -> RebarSuggestionTask:
    resolved_limits = limits or RebarSuggestionTaskLimits(
        max_response_bytes=max(64 * 1024, max_output_tokens * 16),
        max_response_tokens=max_output_tokens,
    )
    client = build_chat_client(
        spec,
        model_kind="structured",
        timeout_seconds=request_timeout_seconds,
        temperature=0,
        max_output_tokens=max_output_tokens,
        max_retries=0,
        max_response_bytes=resolved_limits.max_response_bytes,
    )
    return RebarSuggestionTask(
        client=client,
        model=client.config.model,
        skill_root=skill_root,
        skill_version=skill_version,
        limits=resolved_limits,
    )


def _compact_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _completion_token_count(usage: object) -> int | None:
    if not isinstance(usage, dict):
        return None
    value = usage.get("completion_tokens")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _safe_usage(usage: object) -> dict[str, int]:
    if not isinstance(usage, dict):
        return {}
    result: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            result[key] = value
    return result


def _stat_identity(value: os.stat_result) -> tuple[int, int]:
    return (value.st_dev, value.st_ino)


def _stat_state(value: os.stat_result) -> tuple[int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
    )
