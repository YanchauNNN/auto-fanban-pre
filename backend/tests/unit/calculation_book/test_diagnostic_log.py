from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


def test_diagnostic_log_is_exclusive_jsonl_and_recursively_redacts_secrets(
    tmp_path: Path,
) -> None:
    from src.calculation_book.diagnostic_log import CalculationBookDiagnosticLog

    target = tmp_path / "calculation-book" / "logs" / "calculation-book-job-42.log"
    secret_values = {
        "api_key": "SECRET-API-KEY",
        "Authorization": "Bearer SECRET-AUTHORIZATION",
        "nested": {
            "system_prompt": "COMPLETE-SYSTEM-PROMPT",
            "image_base64": "U0VDUkVUX0lNQUdF",
        },
    }

    with CalculationBookDiagnosticLog.create(
        target,
        job_id="job-42",
        correlation_id="corr-42",
        max_bytes=100_000,
    ) as log:
        log.write(
            "task_started",
            archive_sha256="a" * 64,
            params=secret_values,
        )

    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["schema_version"] == "calculation-book-log-1"
    assert payload["timestamp_utc"].endswith("+00:00")
    assert payload["sequence"] == 1
    assert payload["event"] == "task_started"
    assert payload["job_id"] == "job-42"
    assert payload["correlation_id"] == "corr-42"
    assert payload["details"]["archive_sha256"] == "a" * 64
    assert payload["details"]["params"]["api_key"] == "[REDACTED]"
    serialized = target.read_text(encoding="utf-8")
    for forbidden in (
        "SECRET-API-KEY",
        "SECRET-AUTHORIZATION",
        "COMPLETE-SYSTEM-PROMPT",
        "U0VDUkVUX0lNQUdF",
    ):
        assert forbidden not in serialized

    with pytest.raises(FileExistsError):
        CalculationBookDiagnosticLog.create(
            target,
            job_id="job-42",
            correlation_id="corr-42",
            max_bytes=100_000,
        )


def test_diagnostic_log_enforces_byte_limit_without_partial_json(
    tmp_path: Path,
) -> None:
    from src.calculation_book.diagnostic_log import (
        CalculationBookDiagnosticLog,
        DiagnosticLogLimitExceeded,
    )

    target = tmp_path / "bounded.log"
    log = CalculationBookDiagnosticLog.create(
        target,
        job_id="job-bounded",
        correlation_id="corr-bounded",
        max_bytes=8_192,
    )
    log.write("task_started", stage="INIT")
    while True:
        before = log.bytes_written
        try:
            log.write("stage_started", stage="S" * 100)
        except DiagnosticLogLimitExceeded:
            break

    assert log.bytes_written == before
    log.write(
        "task_failed",
        stage="S" * 100,
        error_code="E" * 100,
    )
    log.close()
    payloads = [
        json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()
    ]
    assert [payload["event"] for payload in payloads] == [
        "task_started",
        *(["stage_started"] * (len(payloads) - 2)),
        "task_failed",
    ]
    assert target.stat().st_size <= 8_192


def test_terminal_reserve_accepts_the_maximum_completed_record(
    tmp_path: Path,
) -> None:
    from src.calculation_book.diagnostic_log import (
        CalculationBookDiagnosticLog,
        DiagnosticLogLimitExceeded,
    )

    target = tmp_path / "completed-reserve.log"
    log = CalculationBookDiagnosticLog.create(
        target,
        job_id="job-completed-reserve",
        correlation_id="corr-completed-reserve",
        max_bytes=8_192,
    )
    while True:
        try:
            log.write("stage_started", stage="S" * 100)
        except DiagnosticLogLimitExceeded:
            break

    log.write(
        "task_completed",
        duration_ms=31_536_000_000,
        figure_count=1_000_000,
        warning_count=1_000_000,
        output_filename="成" * 260,
    )
    log.close()

    payload = json.loads(target.read_text(encoding="utf-8").splitlines()[-1])
    assert payload["event"] == "task_completed"
    assert target.stat().st_size <= 8_192


def test_diagnostic_log_can_record_task_failed_after_a_stage_exception(
    tmp_path: Path,
) -> None:
    from src.calculation_book.diagnostic_log import CalculationBookDiagnosticLog

    target = tmp_path / "failure.log"
    with CalculationBookDiagnosticLog.create(
        target,
        job_id="job-failure",
        correlation_id="corr-failure",
        max_bytes=10_000,
    ) as log:
        try:
            raise RuntimeError("raw upstream failure")
        except RuntimeError:
            log.write(
                "task_failed",
                stage="AI_REBAR_SUGGESTION",
                error_code="model_gateway_failed",
            )

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["event"] == "task_failed"
    assert payload["details"] == {
        "error_code": "model_gateway_failed",
        "stage": "AI_REBAR_SUGGESTION",
    }


@pytest.mark.parametrize(
    "job_id",
    ["../escape", "..", "bad/job", "bad\\job", "bad\r\njob"],
)
def test_diagnostic_log_rejects_unsafe_job_identifiers(
    tmp_path: Path,
    job_id: str,
) -> None:
    from src.calculation_book.diagnostic_log import CalculationBookDiagnosticLog

    with pytest.raises(ValueError):
        CalculationBookDiagnosticLog.create_for_job(
            work_dir=tmp_path,
            job_id=job_id,
            correlation_id="corr-safe",
            max_bytes=10_000,
        )


def test_create_for_job_uses_the_fixed_task_log_location(tmp_path: Path) -> None:
    from src.calculation_book.diagnostic_log import CalculationBookDiagnosticLog

    with CalculationBookDiagnosticLog.create_for_job(
        work_dir=tmp_path,
        job_id="job-safe_42",
        correlation_id="corr-safe",
        max_bytes=10_000,
    ) as log:
        assert log.path == (
            tmp_path
            / "calculation-book"
            / "logs"
            / "calculation-book-job-safe_42.log"
        )
        log.write("task_started")

    assert log.path.is_file()


def test_diagnostic_log_serializes_concurrent_writes_with_unique_sequences(
    tmp_path: Path,
) -> None:
    from src.calculation_book.diagnostic_log import CalculationBookDiagnosticLog

    target = tmp_path / "concurrent.log"
    with CalculationBookDiagnosticLog.create(
        target,
        job_id="job-concurrent",
        correlation_id="corr-concurrent",
        max_bytes=100_000,
    ) as log, ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda index: log.write(
                    "item_finalized",
                    item_id=f"N{index}:X",
                    status="blank",
                    source="ai",
                ),
                range(32),
            )
        )

    payloads = [
        json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()
    ]
    assert len(payloads) == 32
    assert sorted(payload["sequence"] for payload in payloads) == list(range(1, 33))


def test_diagnostic_log_rejects_writes_after_close(tmp_path: Path) -> None:
    from src.calculation_book.diagnostic_log import (
        CalculationBookDiagnosticLog,
        DiagnosticLogError,
    )

    log = CalculationBookDiagnosticLog.create(
        tmp_path / "closed.log",
        job_id="job-closed",
        correlation_id="corr-closed",
        max_bytes=10_000,
    )
    log.close()

    with pytest.raises(DiagnosticLogError) as raised:
        log.write("task_failed", error_code="too_late")

    assert raised.value.code == "log_write_failed"


def test_diagnostic_log_rejects_full_model_objects_in_event_details(
    tmp_path: Path,
) -> None:
    from src.calculation_book.diagnostic_log import (
        CalculationBookDiagnosticLog,
        DiagnosticLogError,
    )

    class UnsafeModelResponse:
        def model_dump(self, **_kwargs: object) -> dict[str, object]:
            return {
                "system_prompt": "COMPLETE-SYSTEM-PROMPT",
                "reason": "MODEL-REASON-SECRET",
            }

    target = tmp_path / "unsafe-model.log"
    with CalculationBookDiagnosticLog.create(
        target,
        job_id="job-unsafe-model",
        correlation_id="corr-unsafe-model",
        max_bytes=10_000,
    ) as log:
        with pytest.raises(DiagnosticLogError) as raised:
            log.write(
                "ai_call_completed",
                call_index=1,
                items=UnsafeModelResponse(),
            )

        assert raised.value.code == "log_write_failed"

    serialized = target.read_text(encoding="utf-8")
    assert serialized == ""
    assert "COMPLETE-SYSTEM-PROMPT" not in serialized
    assert "MODEL-REASON-SECRET" not in serialized


def test_diagnostic_log_close_failure_still_closes_the_stream(tmp_path: Path) -> None:
    from src.calculation_book.diagnostic_log import (
        CalculationBookDiagnosticLog,
        DiagnosticLogError,
    )

    class FlushFailingStream:
        closed = False

        def flush(self) -> None:
            raise OSError("sensitive flush failure")

        def fileno(self) -> int:
            return -1

        def close(self) -> None:
            self.closed = True

    stream = FlushFailingStream()
    log = CalculationBookDiagnosticLog(
        path=tmp_path / "flush-failure.log",
        stream=stream,  # type: ignore[arg-type]
        job_id="job-flush-failure",
        correlation_id="corr-flush-failure",
        max_bytes=10_000,
    )

    with pytest.raises(DiagnosticLogError) as raised:
        log.close()

    assert raised.value.code == "log_flush_failed"
    assert stream.closed is True
    assert log.closed is True
    log.close()


def test_diagnostic_log_sanitizes_arbitrary_mapping_failures(
    tmp_path: Path,
) -> None:
    from src.calculation_book.diagnostic_log import (
        CalculationBookDiagnosticLog,
        DiagnosticLogError,
    )

    sensitive = "SECRET-MAPPING-FAILURE"

    class ExplodingMapping(Mapping[str, object]):
        def __getitem__(self, _key: str) -> object:
            raise RuntimeError(sensitive)

        def __iter__(self) -> Iterator[str]:
            raise RuntimeError(sensitive)

        def __len__(self) -> int:
            raise RuntimeError(sensitive)

    target = tmp_path / "exploding-mapping.log"
    with CalculationBookDiagnosticLog.create(
        target,
        job_id="job-exploding",
        correlation_id="corr-exploding",
        max_bytes=10_000,
    ) as log:
        with pytest.raises(DiagnosticLogError) as raised:
            log.write("task_started", params=ExplodingMapping())

        assert raised.value.code == "log_write_failed"
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None
        assert sensitive not in repr(raised.value)

    assert target.read_bytes() == b""


def test_unrecoverable_short_write_invalidates_and_closes_the_log(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.calculation_book.diagnostic_log import (
        CalculationBookDiagnosticLog,
        DiagnosticLogError,
    )

    class UnrecoverableStream:
        closed = False

        def write(self, payload: bytes) -> int:
            return max(1, len(payload) // 2)

        def flush(self) -> None:
            return None

        def fileno(self) -> int:
            return 42

        def seek(self, _offset: int) -> None:
            raise OSError("SECRET-ROLLBACK-FAILURE")

        def truncate(self) -> None:
            raise AssertionError("unreachable")

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr("src.calculation_book.diagnostic_log.os.fsync", lambda _fd: None)
    stream = UnrecoverableStream()
    log = CalculationBookDiagnosticLog(
        path=tmp_path / "unrecoverable.log",
        stream=stream,  # type: ignore[arg-type]
        job_id="job-unrecoverable",
        correlation_id="corr-unrecoverable",
        max_bytes=10_000,
    )

    with pytest.raises(DiagnosticLogError) as raised:
        log.write("task_started", stage="INIT")

    assert raised.value.code == "log_corrupted"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert "SECRET-ROLLBACK-FAILURE" not in repr(raised.value)
    assert stream.closed is True
    assert log.closed is True


def test_create_for_job_rejects_an_open_handle_outside_the_checked_parent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.calculation_book import diagnostic_log

    outside = tmp_path.parent / "outside-race" / "calculation-book-job-race.log"
    monkeypatch.setattr(
        diagnostic_log,
        "_final_open_path",
        lambda _stream, _fallback: outside,
    )

    with pytest.raises(diagnostic_log.DiagnosticLogError) as raised:
        diagnostic_log.CalculationBookDiagnosticLog.create_for_job(
            work_dir=tmp_path,
            job_id="job-race",
            correlation_id="corr-race",
            max_bytes=10_000,
        )

    assert raised.value.code == "log_create_failed"
    created = (
        tmp_path
        / "calculation-book"
        / "logs"
        / "calculation-book-job-race.log"
    )
    assert created.exists() is False


def test_create_for_job_closes_handle_and_redacts_delete_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.calculation_book import diagnostic_log

    sensitive = "SECRET-DELETE-FAILURE"
    outside = tmp_path.parent / "outside-race" / "calculation-book-job-delete.log"
    monkeypatch.setattr(
        diagnostic_log,
        "_final_open_path",
        lambda _stream, _fallback: outside,
    )
    monkeypatch.setattr(
        diagnostic_log,
        "_delete_open_file",
        lambda _stream, _path: (_ for _ in ()).throw(OSError(sensitive)),
    )

    with pytest.raises(diagnostic_log.DiagnosticLogError) as raised:
        diagnostic_log.CalculationBookDiagnosticLog.create_for_job(
            work_dir=tmp_path,
            job_id="job-delete",
            correlation_id="corr-delete",
            max_bytes=10_000,
        )

    assert raised.value.code == "log_create_failed"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert sensitive not in repr(raised.value)
    created = (
        tmp_path
        / "calculation-book"
        / "logs"
        / "calculation-book-job-delete.log"
    )
    created.write_text("handle-closed", encoding="utf-8")
    assert created.read_text(encoding="utf-8") == "handle-closed"
