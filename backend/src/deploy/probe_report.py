from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROBE_REPORT_SCHEMA_VERSION = "fanban-business-probe@1"
_VALID_STATUSES = {"PASS", "FAIL", "SKIPPED"}
_DEFAULT_SENSITIVE_KEYS = (
    "password",
    "authorization",
    "token",
    "api_key",
    "apikey",
    "secret",
    "cookie",
)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[^\s,;]+")
_BASE64_PATTERN = re.compile(r"^[A-Za-z0-9+/=\r\n]+$")


@dataclass(frozen=True)
class ProbeSummary:
    status: str
    summary_path: Path
    events_path: Path


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class ProbeReporter:
    def __init__(
        self,
        result_dir: Path,
        *,
        session_id: str,
        probe_name: str,
        required_checks: Iterable[str] = (),
        sensitive_key_patterns: Iterable[str] = _DEFAULT_SENSITIVE_KEYS,
        max_event_context_bytes: int = 131_072,
    ) -> None:
        self.result_dir = Path(result_dir)
        self.result_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id
        self.probe_name = probe_name
        self.required_checks = tuple(dict.fromkeys(str(item) for item in required_checks))
        self.sensitive_key_patterns = tuple(
            item.casefold() for item in sensitive_key_patterns if str(item).strip()
        )
        self.max_event_context_bytes = max(1024, int(max_event_context_bytes))
        self.events_path = self.result_dir / "events.jsonl"
        self.summary_path = self.result_dir / "summary.json"
        self._sequence = 0
        self._statuses: dict[str, str] = {}

    def _is_sensitive_key(self, key: str) -> bool:
        folded = key.casefold()
        return any(pattern in folded for pattern in self.sensitive_key_patterns)

    def _redact(self, value: Any, *, key: str = "") -> Any:
        if key and self._is_sensitive_key(key):
            return "[REDACTED]"
        if isinstance(value, Mapping):
            return {
                str(child_key): self._redact(child_value, key=str(child_key))
                for child_key, child_value in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [self._redact(item) for item in value]
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, str):
            if value.startswith("data:") and ";base64," in value[:256]:
                return "[REDACTED_BASE64]"
            compact = "".join(value.split())
            if len(compact) >= 4096 and _BASE64_PATTERN.fullmatch(compact):
                return "[REDACTED_BASE64]"
            return _BEARER_PATTERN.sub("Bearer [REDACTED]", value)
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value)

    def _bounded_context(self, context: Mapping[str, Any] | None) -> dict[str, Any]:
        safe = self._redact(dict(context or {}))
        encoded = json.dumps(safe, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) <= self.max_event_context_bytes:
            return safe
        return {
            "truncated": True,
            "original_size_bytes": len(encoded),
        }

    def event(
        self,
        check: str,
        status: str,
        *,
        elapsed_ms: int | None = None,
        error_code: str = "",
        message: str = "",
        context: Mapping[str, Any] | None = None,
    ) -> None:
        normalized_status = str(status).upper()
        if normalized_status not in _VALID_STATUSES:
            raise ValueError(f"unsupported probe status: {status}")
        self._sequence += 1
        self._statuses[str(check)] = normalized_status
        payload = {
            "schema_version": PROBE_REPORT_SCHEMA_VERSION,
            "session_id": self.session_id,
            "probe_name": self.probe_name,
            "sequence": self._sequence,
            "timestamp": _utc_now(),
            "check": str(check),
            "status": normalized_status,
            "elapsed_ms": elapsed_ms,
            "error_code": str(error_code),
            "message": _BEARER_PATTERN.sub("Bearer [REDACTED]", str(message)),
            "context": self._bounded_context(context),
        }
        with self.events_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())

    def finish(self, status: str | None = None) -> ProbeSummary:
        requested_status = str(status).upper() if status is not None else "PASS"
        if requested_status not in _VALID_STATUSES:
            raise ValueError(f"unsupported terminal probe status: {status}")
        missing = [check for check in self.required_checks if check not in self._statuses]
        skipped = [
            check
            for check in self.required_checks
            if self._statuses.get(check) == "SKIPPED"
        ]
        has_failure = any(value == "FAIL" for value in self._statuses.values())
        terminal_status = (
            "FAIL"
            if requested_status == "FAIL" or has_failure or missing or skipped
            else requested_status
        )
        payload = {
            "schema_version": PROBE_REPORT_SCHEMA_VERSION,
            "session_id": self.session_id,
            "probe_name": self.probe_name,
            "generated_at": _utc_now(),
            "status": terminal_status,
            "terminal": True,
            "event_count": self._sequence,
            "checks": dict(self._statuses),
            "required_checks": list(self.required_checks),
            "missing_required_checks": missing,
            "skipped_required_checks": skipped,
            "events_path": str(self.events_path),
        }
        temp_path = self.summary_path.with_name(
            f".{self.summary_path.name}.{uuid.uuid4().hex[:8]}.tmp"
        )
        try:
            with temp_path.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self.summary_path)
        finally:
            temp_path.unlink(missing_ok=True)
        return ProbeSummary(
            status=terminal_status,
            summary_path=self.summary_path,
            events_path=self.events_path,
        )
