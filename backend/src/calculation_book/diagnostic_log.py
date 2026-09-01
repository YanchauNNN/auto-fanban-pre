from __future__ import annotations

import json
import math
import os
import re
import stat
import unicodedata
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any, BinaryIO, Literal, Self

LOG_SCHEMA_VERSION = "calculation-book-log-1"
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,199}$")
_LOG_FILENAME = re.compile(
    r"^calculation-book-[A-Za-z0-9][A-Za-z0-9_-]{0,199}\.log$"
)
_LOG_RECORD_KEYS = frozenset(
    {
        "schema_version",
        "timestamp_utc",
        "sequence",
        "event",
        "job_id",
        "correlation_id",
        "details",
    }
)
_AUTHORIZATION_VALUE = re.compile(
    r"(?i)authorization\s*[:=]\s*[^\r\n,;]+"
)
_BEARER_VALUE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
_NAMED_SECRET_VALUE = re.compile(
    r"(?i)(?:api[_-]?key|password|secret)\s*[:=]\s*[^\s,;]+"
)
_LONG_BASE64 = re.compile(
    r"(?<![A-Za-z0-9+/=])"
    r"(?=[A-Za-z0-9+/]{64,}={0,2}(?![A-Za-z0-9+/=]))"
    r"(?=[A-Za-z0-9+/=]*[+/=])"
    r"[A-Za-z0-9+/]{64,}={0,2}"
)
_REDACTED = "[REDACTED]"
_MAX_SANITIZE_DEPTH = 24
_MAX_COLLECTION_ITEMS = 20_000
_MAX_STRING_CHARS = 100_000
_MAX_TOTAL_NODES = 50_000
_MAX_TOTAL_CHARS = 500_000
_MIN_LOG_BYTES = 8_192
_TERMINAL_RESERVE_BYTES = 4_096
_MAX_DURATION_MS = 31_536_000_000
_MAX_TERMINAL_COUNT = 1_000_000
_TERMINAL_EVENTS = frozenset({"task_completed", "task_failed"})
_EVENT_DETAIL_KEYS: dict[str, frozenset[str]] = {
    "task_started": frozenset(
        {"archive_sha256", "archive_size_bytes", "source_filename", "params", "stage"}
    ),
    "archive_validated": frozenset(
        {"archive_sha256", "file_count", "image_count", "relative_paths"}
    ),
    "stage_started": frozenset({"stage"}),
    "stage_completed": frozenset({"stage", "duration_ms", "counts"}),
    "stage_failed": frozenset({"stage", "duration_ms", "error_code"}),
    "task_completed": frozenset(
        {"duration_ms", "figure_count", "warning_count", "output_filename"}
    ),
    "task_failed": frozenset({"stage", "duration_ms", "error_code"}),
    "image_grouped": frozenset(
        {
            "image_name",
            "relative_path",
            "member_kind",
            "member_id",
            "direction",
            "group",
        }
    ),
    "ocr_completed": frozenset(
        {
            "image_name",
            "member_kind",
            "member_id",
            "direction",
            "smx",
            "legend_values",
            "zero_smx",
        }
    ),
    "ocr_failed": frozenset(
        {"image_name", "member_kind", "member_id", "direction", "error_code"}
    ),
    "candidate_generated": frozenset(
        {"item_id", "smx", "target_area", "candidates", "elimination_codes"}
    ),
    "ai_call_started": frozenset(
        {
            "call_index",
            "batch_index",
            "item_ids",
            "repair_rounds",
            "candidate_counts",
            "excluded_candidate_ids",
            "input_summary_sha256",
        }
    ),
    "ai_call_completed": frozenset(
        {
            "call_index",
            "duration_ms",
            "model",
            "skill_id",
            "skill_version",
            "skill_sha256",
            "usage",
            "items",
        }
    ),
    "ai_call_failed": frozenset(
        {
            "call_index",
            "duration_ms",
            "error_kind",
            "error_code",
            "item_ids",
            "consecutive_base_failures",
        }
    ),
    "validation_completed": frozenset(
        {
            "item_id",
            "call_index",
            "status",
            "error_codes",
            "candidate_id",
            "better_candidate_ids",
        }
    ),
    "repair_scheduled": frozenset(
        {
            "item_id",
            "next_round",
            "new_excluded_candidate_ids",
            "excluded_candidate_ids",
            "remaining_count",
        }
    ),
    "item_finalized": frozenset(
        {
            "item_id",
            "member_kind",
            "member_id",
            "direction",
            "status",
            "source",
            "candidate_id",
            "spec",
            "actual_area",
            "smx",
            "target_area",
            "margin_ratio",
            "blank_reason_code",
            "image_name",
            "error_code",
        }
    ),
    "word_entry_written": frozenset(
        {
            "member_kind",
            "member_id",
            "direction",
            "spec",
            "actual_area",
            "smx",
            "image_name",
        }
    ),
}

DiagnosticLogErrorCode = Literal[
    "log_create_failed",
    "log_write_failed",
    "log_flush_failed",
    "log_size_limit_exceeded",
    "log_corrupted",
]


class DiagnosticLogError(RuntimeError):
    """Raised when a calculation-book audit log cannot be written safely."""

    def __init__(self, code: DiagnosticLogErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class DiagnosticLogLimitExceeded(DiagnosticLogError):
    """Raised before a JSONL record would exceed the configured byte limit."""

    def __init__(self) -> None:
        super().__init__(
            "log_size_limit_exceeded",
            "diagnostic log exceeded its configured byte limit",
        )


class CalculationBookDiagnosticLog:
    def __init__(
        self,
        *,
        path: Path,
        stream: BinaryIO,
        job_id: str,
        correlation_id: str,
        max_bytes: int,
    ) -> None:
        self.path = path
        self.job_id = job_id
        self.correlation_id = correlation_id
        self.max_bytes = max_bytes
        self._terminal_reserve = _TERMINAL_RESERVE_BYTES
        self._stream = stream
        self._bytes_written = 0
        self._sequence = 0
        self._closed = False
        self._lock = Lock()

    @classmethod
    def create(
        cls,
        path: Path,
        *,
        job_id: str,
        correlation_id: str,
        max_bytes: int,
    ) -> Self:
        safe_job_id = _validated_identifier(job_id, label="job_id")
        safe_correlation_id = _validated_identifier(
            correlation_id,
            label="correlation_id",
        )
        if (
            isinstance(max_bytes, bool)
            or not isinstance(max_bytes, int)
            or max_bytes < _MIN_LOG_BYTES
        ):
            raise ValueError(f"max_bytes must be at least {_MIN_LOG_BYTES}")

        target = Path(path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise DiagnosticLogError(
                "log_create_failed",
                "diagnostic log directory could not be created",
            ) from None
        try:
            stream = _open_exclusive_stream(target)
        except FileExistsError:
            raise
        except Exception:
            raise DiagnosticLogError(
                "log_create_failed",
                "diagnostic log could not be created",
            ) from None
        return cls(
            path=target,
            stream=stream,
            job_id=safe_job_id,
            correlation_id=safe_correlation_id,
            max_bytes=max_bytes,
        )

    @classmethod
    def create_for_job(
        cls,
        *,
        log_dir: Path,
        job_id: str,
        correlation_id: str,
        max_bytes: int,
        retention_days: int,
    ) -> Self:
        safe_job_id = _validated_identifier(job_id, label="job_id")
        if (
            isinstance(retention_days, bool)
            or not isinstance(retention_days, int)
            or retention_days <= 0
        ):
            raise ValueError("retention_days must be a positive integer")
        resolved_logs_dir = _prepare_log_directory(log_dir)
        filename = calculation_book_log_filename(safe_job_id)
        _cleanup_expired_logs(
            resolved_logs_dir,
            current_filename=filename,
            retention_days=retention_days,
        )
        target = resolved_logs_dir / filename
        log = cls.create(
            target,
            job_id=safe_job_id,
            correlation_id=correlation_id,
            max_bytes=max_bytes,
        )
        final_path_failed = False
        try:
            final_path = _final_open_path(log._stream, target)
        except Exception:
            final_path_failed = True
            final_path = None
        if (
            final_path_failed
            or final_path is None
            or final_path.parent != resolved_logs_dir
            or final_path.name != filename
        ):
            try:
                _delete_open_file(log._stream, final_path or target)
            except Exception:
                pass
            finally:
                log._invalidate()
            raise DiagnosticLogError(
                "log_create_failed",
                "diagnostic log open path failed containment verification",
            ) from None
        log.path = final_path
        return log

    @property
    def bytes_written(self) -> int:
        return self._bytes_written

    @property
    def closed(self) -> bool:
        return self._closed

    def write(self, event: str, /, **details: Any) -> None:
        safe_event = _validated_event(event)
        _validate_event_details(safe_event, details)
        with self._lock:
            if self._closed:
                raise DiagnosticLogError(
                    "log_write_failed",
                    "diagnostic log is closed",
                )
            serialization_failed = False
            try:
                safe_details = _sanitize_value(details)
                record = {
                    "schema_version": LOG_SCHEMA_VERSION,
                    "timestamp_utc": datetime.now(UTC).isoformat(
                        timespec="milliseconds"
                    ),
                    "sequence": self._sequence + 1,
                    "event": safe_event,
                    "job_id": self.job_id,
                    "correlation_id": self.correlation_id,
                    "details": safe_details,
                }
                payload = (
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    + b"\n"
                )
            except Exception:
                serialization_failed = True
                payload = b""
            if serialization_failed:
                raise DiagnosticLogError(
                    "log_write_failed",
                    "diagnostic log event is not safely serializable",
                )
            byte_limit = self.max_bytes
            if safe_event not in _TERMINAL_EVENTS:
                byte_limit -= self._terminal_reserve
            if self._bytes_written + len(payload) > byte_limit:
                raise DiagnosticLogLimitExceeded
            io_failed = False
            try:
                written = self._stream.write(payload)
                self._stream.flush()
                os.fsync(self._stream.fileno())
            except Exception:
                io_failed = True
                written = None
            if io_failed:
                if not self._rollback_partial_write():
                    self._invalidate()
                    raise DiagnosticLogError(
                        "log_corrupted",
                        "diagnostic log integrity could not be recovered",
                    )
                raise DiagnosticLogError(
                    "log_write_failed",
                    "diagnostic log write failed",
                )
            if (
                isinstance(written, bool)
                or not isinstance(written, int)
                or written != len(payload)
            ):
                if not self._rollback_partial_write():
                    self._invalidate()
                    raise DiagnosticLogError(
                        "log_corrupted",
                        "diagnostic log integrity could not be recovered",
                    )
                raise DiagnosticLogError(
                    "log_write_failed",
                    "diagnostic log write was incomplete",
                )
            self._bytes_written += len(payload)
            self._sequence += 1

    def _rollback_partial_write(self) -> bool:
        try:
            self._stream.seek(self._bytes_written)
            self._stream.truncate()
            self._stream.flush()
            os.fsync(self._stream.fileno())
        except Exception:
            return False
        return True

    def _invalidate(self) -> None:
        with suppress(Exception):
            self._stream.close()
        self._closed = True

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            close_failed = False
            try:
                self._stream.flush()
                os.fsync(self._stream.fileno())
            except Exception:
                close_failed = True
            try:
                self._stream.close()
            except Exception:
                close_failed = True
            finally:
                self._closed = True
            if close_failed:
                raise DiagnosticLogError(
                    "log_flush_failed",
                    "diagnostic log close failed",
                )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _open_exclusive_stream(target: Path) -> BinaryIO:
    if os.name != "nt":
        descriptor = os.open(
            target,
            os.O_CREAT | os.O_EXCL | os.O_APPEND | os.O_WRONLY,
            0o600,
        )
        try:
            return os.fdopen(descriptor, "wb")
        except Exception:
            os.close(descriptor)
            raise

    import ctypes
    import msvcrt
    from ctypes import wintypes

    create_file = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(target),
        0x40000000 | 0x00010000,  # GENERIC_WRITE | DELETE
        0x00000001 | 0x00000004,  # FILE_SHARE_READ | FILE_SHARE_DELETE
        None,
        1,  # CREATE_NEW
        0x00000080,  # FILE_ATTRIBUTE_NORMAL
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        error_code = ctypes.get_last_error()
        if error_code in {80, 183}:  # ERROR_FILE_EXISTS / ERROR_ALREADY_EXISTS
            raise FileExistsError(str(target))
        raise OSError(error_code, "exclusive diagnostic log creation failed")

    flags = os.O_APPEND | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        descriptor = msvcrt.open_osfhandle(handle, flags)
    except Exception:
        ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(handle)
        raise
    try:
        return os.fdopen(descriptor, "wb")
    except Exception:
        os.close(descriptor)
        raise


def calculation_book_log_filename(job_id: str) -> str:
    """Return the only permitted audit-log filename for a task."""

    safe_job_id = _validated_identifier(job_id, label="job_id")
    return f"calculation-book-{safe_job_id}.log"


def calculation_book_log_matches_terminal_state(
    path: Path,
    *,
    job_id: str,
    expected_event: Literal["task_completed", "task_failed"],
    max_bytes: int,
) -> bool:
    """Validate a bounded JSONL log and its terminal event for API exposure."""

    try:
        safe_job_id = _validated_identifier(job_id, label="job_id")
    except ValueError:
        return False
    if (
        expected_event not in _TERMINAL_EVENTS
        or isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or max_bytes <= 0
    ):
        return False
    payload = _read_bounded_regular_file(Path(path), max_bytes=max_bytes)
    if payload is None or not payload.endswith(b"\n"):
        return False
    lines = payload.splitlines()
    if not lines:
        return False
    events: list[str] = []
    for sequence, line in enumerate(lines, start=1):
        event = _validated_persisted_record(
            line,
            job_id=safe_job_id,
            sequence=sequence,
        )
        if event is None:
            return False
        events.append(event)
    if any(event in _TERMINAL_EVENTS for event in events[:-1]):
        return False
    return events[-1] == expected_event


def _read_bounded_regular_file(path: Path, *, max_bytes: int) -> bytes | None:
    try:
        initial_stat = path.lstat()
        is_junction = getattr(path, "is_junction", lambda: False)
        if (
            not stat.S_ISREG(initial_stat.st_mode)
            or path.is_symlink()
            or is_junction()
            or initial_stat.st_size <= 0
            or initial_stat.st_size > max_bytes
        ):
            return None
        with path.open("rb") as stream:
            opened_stat = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or _file_identity(opened_stat) != _file_identity(initial_stat)
            ):
                return None
            payload = stream.read(max_bytes + 1)
            final_open_stat = os.fstat(stream.fileno())
        final_path_stat = path.lstat()
    except (OSError, RuntimeError):
        return None
    if (
        len(payload) > max_bytes
        or len(payload) != initial_stat.st_size
        or _file_identity(final_open_stat) != _file_identity(initial_stat)
        or _file_identity(final_path_stat) != _file_identity(initial_stat)
        or final_open_stat.st_size != initial_stat.st_size
        or final_path_stat.st_size != initial_stat.st_size
    ):
        return None
    return payload


def _file_identity(file_stat: os.stat_result) -> tuple[int, int]:
    return file_stat.st_dev, file_stat.st_ino


def _validated_persisted_record(
    payload: bytes,
    *,
    job_id: str,
    sequence: int,
) -> str | None:
    try:
        record = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict) or set(record) != _LOG_RECORD_KEYS:
        return None
    if record.get("schema_version") != LOG_SCHEMA_VERSION:
        return None
    persisted_sequence = record.get("sequence")
    if (
        isinstance(persisted_sequence, bool)
        or persisted_sequence != sequence
    ):
        return None
    if record.get("job_id") != job_id:
        return None
    try:
        _validated_identifier(
            record.get("correlation_id"),
            label="correlation_id",
        )
        event = _validated_event(record.get("event"))
    except (TypeError, ValueError):
        return None
    details = record.get("details")
    if not isinstance(details, dict):
        return None
    try:
        _validate_event_details(event, details)
    except (DiagnosticLogError, TypeError, ValueError):
        return None
    timestamp = record.get("timestamp_utc")
    if not isinstance(timestamp, str):
        return None
    try:
        parsed_timestamp = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if (
        parsed_timestamp.tzinfo is None
        or parsed_timestamp.utcoffset() != UTC.utcoffset(parsed_timestamp)
    ):
        return None
    return event


def _prepare_log_directory(log_dir: Path) -> Path:
    candidate = Path(log_dir)
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        candidate_stat = candidate.lstat()
        is_junction = getattr(candidate, "is_junction", lambda: False)
        if (
            not stat.S_ISDIR(candidate_stat.st_mode)
            or candidate.is_symlink()
            or is_junction()
        ):
            raise OSError("unsafe diagnostic log root")
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        raise DiagnosticLogError(
            "log_create_failed",
            "diagnostic log directory could not be created",
        ) from None
    return resolved


def _cleanup_expired_logs(
    log_dir: Path,
    *,
    current_filename: str,
    retention_days: int,
) -> None:
    cutoff = datetime.now(UTC).timestamp() - retention_days * 86_400
    try:
        candidates = tuple(log_dir.iterdir())
    except (OSError, RuntimeError):
        return
    for candidate in candidates:
        if (
            candidate.name == current_filename
            or _LOG_FILENAME.fullmatch(candidate.name) is None
        ):
            continue
        try:
            if candidate.is_symlink():
                continue
            first_stat = candidate.lstat()
            if not stat.S_ISREG(first_stat.st_mode) or first_stat.st_mtime >= cutoff:
                continue
            resolved = candidate.resolve(strict=True)
            if resolved.parent != log_dir or resolved.name != candidate.name:
                continue
            second_stat = candidate.lstat()
            if (
                candidate.is_symlink()
                or not stat.S_ISREG(second_stat.st_mode)
                or (first_stat.st_dev, first_stat.st_ino)
                != (second_stat.st_dev, second_stat.st_ino)
            ):
                continue
            candidate.unlink()
        except (OSError, RuntimeError):
            # Retention is best-effort. Failure to remove one historical log
            # must not prevent the current task from creating its audit trail.
            continue


def _delete_open_file(stream: BinaryIO, final_path: Path) -> bool:
    try:
        if os.name != "nt":
            final_path.unlink(missing_ok=True)
            return True

        import ctypes
        import msvcrt
        from ctypes import wintypes

        class FileDispositionInfo(ctypes.Structure):
            _fields_ = (("delete_file", ctypes.c_ubyte),)

        set_file_info = ctypes.WinDLL(
            "kernel32",
            use_last_error=True,
        ).SetFileInformationByHandle
        set_file_info.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        )
        set_file_info.restype = wintypes.BOOL
        disposition = FileDispositionInfo(1)
        handle = msvcrt.get_osfhandle(stream.fileno())
        if set_file_info(
            handle,
            4,  # FileDispositionInfo
            ctypes.byref(disposition),
            ctypes.sizeof(disposition),
        ):
            return True
        final_path.unlink(missing_ok=True)
    except Exception:
        return False
    return True


def _final_open_path(stream: BinaryIO, fallback: Path) -> Path:
    if os.name != "nt":
        return fallback.resolve(strict=True)

    import ctypes
    import msvcrt
    from ctypes import wintypes

    get_final_path = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
    get_final_path.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    get_final_path.restype = wintypes.DWORD
    handle = msvcrt.get_osfhandle(stream.fileno())
    buffer = ctypes.create_unicode_buffer(32_768)
    length = get_final_path(handle, buffer, len(buffer), 0)
    if length == 0 or length >= len(buffer):
        raise OSError("could not resolve final diagnostic log handle path")
    raw_path = buffer.value
    if raw_path.startswith("\\\\?\\UNC\\"):
        raw_path = "\\\\" + raw_path[8:]
    elif raw_path.startswith("\\\\?\\"):
        raw_path = raw_path[4:]
    return Path(raw_path).resolve(strict=True)


def _validated_identifier(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    normalized = value.strip()
    if not _SAFE_IDENTIFIER.fullmatch(normalized) or normalized in {".", ".."}:
        raise ValueError(f"{label} is invalid")
    return normalized


def _validated_event(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("event must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > 100:
        raise ValueError("event is invalid")
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ValueError("event is invalid")
    return normalized


def _validate_event_details(event: str, details: Mapping[str, Any]) -> None:
    allowed = _EVENT_DETAIL_KEYS.get(event)
    if allowed is None:
        raise ValueError(f"unsupported diagnostic log event: {event}")
    if not set(details).issubset(allowed):
        raise DiagnosticLogError(
            "log_write_failed",
            "diagnostic log event contains unsupported detail fields",
        )
    if event == "task_failed":
        _validate_bounded_detail(details, "stage", max_chars=100)
        _validate_bounded_detail(details, "error_code", max_chars=100)
        _validate_nonnegative_number(
            details,
            "duration_ms",
            max_value=_MAX_DURATION_MS,
        )
    elif event == "task_completed":
        _validate_bounded_detail(details, "output_filename", max_chars=260)
        _validate_nonnegative_number(
            details,
            "duration_ms",
            max_value=_MAX_DURATION_MS,
        )
        _validate_nonnegative_number(
            details,
            "figure_count",
            integer=True,
            max_value=_MAX_TERMINAL_COUNT,
        )
        _validate_nonnegative_number(
            details,
            "warning_count",
            integer=True,
            max_value=_MAX_TERMINAL_COUNT,
        )


def _validate_bounded_detail(
    details: Mapping[str, Any],
    key: str,
    *,
    max_chars: int,
) -> None:
    value = details.get(key)
    if value is None:
        return
    if not isinstance(value, str) or len(value) > max_chars:
        raise DiagnosticLogError(
            "log_write_failed",
            "diagnostic log terminal detail is invalid",
        )


def _validate_nonnegative_number(
    details: Mapping[str, Any],
    key: str,
    *,
    integer: bool = False,
    max_value: int | float,
) -> None:
    value = details.get(key)
    if value is None:
        return
    expected = int if integer else (int, float)
    if (
        isinstance(value, bool)
        or not isinstance(value, expected)
        or value < 0
        or value > max_value
        or (isinstance(value, float) and not math.isfinite(value))
    ):
        raise DiagnosticLogError(
            "log_write_failed",
            "diagnostic log terminal numeric detail is invalid",
        )


def _sensitive_key(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", value.casefold())
    if normalized in {"prompttokens", "completiontokens", "totaltokens"}:
        return False
    return (
        normalized in {
            "apikey",
            "authorization",
            "password",
            "secret",
            "systemprompt",
            "rawprompt",
            "accesstoken",
            "refreshtoken",
        }
        or "base64" in normalized
        or "apikey" in normalized
        or "authorization" in normalized
        or "cookie" in normalized
        or "headers" in normalized
        or "rawresponse" in normalized
        or "modelresponse" in normalized
        or normalized in {"prompt", "messages"}
        or normalized.endswith("prompt")
        or normalized.endswith("token")
        or normalized.endswith("secret")
        or normalized in {"reason", "reviewreasons"}
    )


def _sanitize_text(value: str) -> str:
    if len(value) > _MAX_STRING_CHARS:
        raise ValueError("diagnostic log string is too large")
    sanitized = _AUTHORIZATION_VALUE.sub("Authorization: [REDACTED]", value)
    sanitized = _BEARER_VALUE.sub("Bearer [REDACTED]", sanitized)
    sanitized = _NAMED_SECRET_VALUE.sub(_REDACTED, sanitized)
    return _LONG_BASE64.sub("[REDACTED_BASE64]", sanitized)


@dataclass
class _SanitizeBudget:
    nodes: int = 0
    characters: int = 0

    def account(self, *, characters: int = 0) -> None:
        self.nodes += 1
        self.characters += characters
        if self.nodes > _MAX_TOTAL_NODES or self.characters > _MAX_TOTAL_CHARS:
            raise ValueError("diagnostic log event exceeds its sanitation budget")


def _sanitize_value(
    value: Any,
    *,
    depth: int = 0,
    budget: _SanitizeBudget | None = None,
) -> Any:
    if budget is None:
        budget = _SanitizeBudget()
    budget.account()
    if depth > _MAX_SANITIZE_DEPTH:
        return "[TRUNCATED_DEPTH]"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite number")
        return value
    if isinstance(value, str):
        budget.account(characters=len(value))
        return _sanitize_text(value)
    if isinstance(value, Path):
        path_text = str(value)
        budget.account(characters=len(path_text))
        return _sanitize_text(path_text)
    if isinstance(value, Enum):
        return _sanitize_value(value.value, depth=depth + 1, budget=budget)
    if isinstance(value, Mapping):
        if len(value) > _MAX_COLLECTION_ITEMS:
            raise ValueError("mapping is too large")
        result: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str):
                raise TypeError("diagnostic log keys must be strings")
            if len(raw_key) > 500:
                raise ValueError("diagnostic log key is too large")
            budget.account(characters=len(raw_key))
            key = _sanitize_text(raw_key)
            result[key] = (
                _REDACTED
                if _sensitive_key(raw_key)
                else _sanitize_value(raw_value, depth=depth + 1, budget=budget)
            )
        return result
    if isinstance(value, Sequence) and not isinstance(
        value,
        (bytes, bytearray, memoryview),
    ):
        if len(value) > _MAX_COLLECTION_ITEMS:
            raise ValueError("sequence is too large")
        return [
            _sanitize_value(item, depth=depth + 1, budget=budget) for item in value
        ]
    raise TypeError("unsupported diagnostic log value")
