from __future__ import annotations

import json
from pathlib import Path

from src.deploy.probe_report import ProbeReporter


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def test_reporter_redacts_nested_credentials_and_large_base64(tmp_path: Path) -> None:
    reporter = ProbeReporter(
        tmp_path / "result",
        session_id="probe-1",
        probe_name="account-workload",
    )

    reporter.event(
        "login",
        "PASS",
        context={
            "Authorization": "Bearer secret-token",
            "nested": {
                "password": "plain-password",
                "cookie": "session=secret-cookie",
                "safe": "kept",
            },
            "body": "data:image/png;base64," + ("A" * 5000),
        },
    )
    summary = reporter.finish()

    raw = summary.events_path.read_text("utf-8")
    assert "secret-token" not in raw
    assert "plain-password" not in raw
    assert "secret-cookie" not in raw
    assert "A" * 1000 not in raw
    event = _read_jsonl(summary.events_path)[0]
    context = event["context"]
    assert context["Authorization"] == "[REDACTED]"
    assert context["nested"]["safe"] == "kept"
    assert context["body"] == "[REDACTED_BASE64]"


def test_reporter_fails_when_required_check_is_missing_or_skipped(tmp_path: Path) -> None:
    reporter = ProbeReporter(
        tmp_path / "result",
        session_id="probe-2",
        probe_name="calculation-book",
        required_checks=("api", "worker", "archive_runtime"),
    )

    reporter.event("api", "PASS")
    reporter.event("worker", "SKIPPED")
    summary = reporter.finish()

    assert summary.status == "FAIL"
    payload = json.loads(summary.summary_path.read_text("utf-8"))
    assert payload["missing_required_checks"] == ["archive_runtime"]
    assert payload["skipped_required_checks"] == ["worker"]


def test_reporter_writes_monotonic_events_and_atomic_terminal_summary(
    tmp_path: Path,
) -> None:
    result_dir = tmp_path / "result"
    reporter = ProbeReporter(
        result_dir,
        session_id="probe-3",
        probe_name="office",
        required_checks=("word", "excel"),
    )

    reporter.event("word", "PASS", elapsed_ms=120)
    reporter.event("excel", "PASS", elapsed_ms=80)
    summary = reporter.finish()

    events = _read_jsonl(summary.events_path)
    assert [event["sequence"] for event in events] == [1, 2]
    assert summary.status == "PASS"
    assert summary.summary_path.name == "summary.json"
    assert not list(result_dir.glob("*.tmp"))
    payload = json.loads(summary.summary_path.read_text("utf-8"))
    assert payload["terminal"] is True
    assert payload["event_count"] == 2


def test_reporter_propagates_explicit_failure(tmp_path: Path) -> None:
    reporter = ProbeReporter(
        tmp_path / "result",
        session_id="probe-4",
        probe_name="office",
        required_checks=("word",),
    )
    reporter.event("word", "FAIL", error_code="office_worker_timeout")

    summary = reporter.finish()

    assert summary.status == "FAIL"
