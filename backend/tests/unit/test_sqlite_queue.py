from __future__ import annotations

import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest


def _store_class() -> type[Any]:
    try:
        from src.pipeline.sqlite_queue import SQLiteQueueStore
    except ModuleNotFoundError as exc:
        pytest.fail(f"SQLiteQueueStore is not implemented: {exc}")
    return SQLiteQueueStore


def _store(tmp_path: Path) -> Any:
    store = _store_class()(tmp_path / "fanban_queue.sqlite3")
    store.initialize()
    return store


def _dt(minutes: int = 0) -> datetime:
    return datetime(2026, 7, 5, 8, 0, tzinfo=UTC) + timedelta(minutes=minutes)


def test_queue_initializes_required_tables(tmp_path: Path) -> None:
    store = _store(tmp_path)

    assert store.table_names() >= {
        "queue_items",
        "worker_heartbeats",
        "job_summaries",
        "activity_state",
    }


def test_connections_apply_configured_busy_timeout(tmp_path: Path) -> None:
    store = _store_class()(
        tmp_path / "fanban_queue.sqlite3",
        timeout_seconds=7.5,
        busy_timeout_ms=12345,
    )
    store.initialize()

    with store._connect() as conn:
        busy_timeout = int(conn.execute("PRAGMA busy_timeout").fetchone()[0])

    assert busy_timeout == 12345


def test_writer_waits_for_short_sqlite_lock(tmp_path: Path) -> None:
    store = _store_class()(
        tmp_path / "fanban_queue.sqlite3",
        timeout_seconds=2.0,
        busy_timeout_ms=2000,
    )
    store.initialize()

    blocker = sqlite3.connect(store.db_path, timeout=2.0)
    blocker.execute("PRAGMA busy_timeout = 2000")
    blocker.execute("BEGIN IMMEDIATE")

    result: dict[str, Any] = {}

    def _write_heartbeat() -> None:
        try:
            result["heartbeat"] = store.upsert_worker_heartbeat(worker_id="worker-a", now=_dt())
        except Exception as exc:  # pragma: no cover - asserted via result
            result["error"] = exc

    writer = threading.Thread(target=_write_heartbeat)
    writer.start()
    time.sleep(0.1)
    blocker.commit()
    blocker.close()
    writer.join(timeout=2)

    assert not writer.is_alive()
    assert "error" not in result
    assert result["heartbeat"]["worker_id"] == "worker-a"


def test_enqueue_is_idempotent_for_unfinished_item(tmp_path: Path) -> None:
    store = _store(tmp_path)

    first = store.enqueue("group", "group-1", priority=10, now=_dt())
    second = store.enqueue("group", "group-1", priority=1, now=_dt(1))

    assert second["id"] == first["id"]
    items = store.list_queue_items()
    assert len(items) == 1
    assert items[0]["priority"] == 10
    assert items[0]["status"] == "queued"


def test_claim_next_claims_one_queued_item_and_records_heartbeat(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.enqueue("job", "job-low", priority=1, now=_dt())
    store.enqueue("group", "group-high", priority=10, now=_dt())

    claimed = store.claim_next(worker_id="worker-a", now=_dt(2))

    assert claimed is not None
    assert claimed["item_type"] == "group"
    assert claimed["item_id"] == "group-high"
    assert claimed["status"] == "claimed"
    assert claimed["claimed_by"] == "worker-a"
    assert claimed["attempt_count"] == 1
    assert claimed["heartbeat_at"] == _dt(2).isoformat()

    queued = store.list_queue_items(status="queued")
    claimed_items = store.list_queue_items(status="claimed")
    assert [item["item_id"] for item in queued] == ["job-low"]
    assert [item["item_id"] for item in claimed_items] == ["group-high"]


def test_heartbeat_and_stale_claim_detection_use_worker_timestamps(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.enqueue("job", "job-1", priority=0, now=_dt())
    store.claim_next(worker_id="worker-a", now=_dt())

    store.heartbeat_claim("worker-a", "job", "job-1", now=_dt(5))

    assert store.find_stale_claims(timeout_seconds=120, now=_dt(6)) == []
    stale = store.find_stale_claims(timeout_seconds=120, now=_dt(8))
    assert len(stale) == 1
    assert stale[0]["item_id"] == "job-1"


def test_complete_closes_claim_and_allows_later_requeue(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.enqueue("job", "job-1", priority=0, now=_dt())
    store.claim_next(worker_id="worker-a", now=_dt(1))

    completed = store.complete("job", "job-1", status="done", now=_dt(2))
    requeued = store.enqueue("job", "job-1", priority=3, now=_dt(3))

    assert completed["status"] == "done"
    assert requeued["id"] != completed["id"]
    assert requeued["status"] == "queued"


def test_summary_index_lists_recent_items_without_scanning_job_json(tmp_path: Path) -> None:
    store = _store(tmp_path)

    store.upsert_summary(
        {
            "item_id": "job-1",
            "is_group": False,
            "status": "failed",
            "source_filename": "a.dwg",
            "stage": "EXPORT",
            "percent": 80,
            "message": "CAD export failed",
            "failure_reason": "cad_export_failed",
            "updated_at": _dt(2),
            "created_at": _dt(),
            "artifact_flags": {"package": False},
        }
    )
    store.upsert_summary(
        {
            "item_id": "group-1",
            "is_group": True,
            "status": "running",
            "source_filename": "batch",
            "stage": "GENERATE_DOCS",
            "percent": 35,
            "message": "generating docs",
            "updated_at": _dt(3),
            "created_at": _dt(1),
            "artifact_flags": {"docs": False},
        }
    )

    page = store.list_summaries(offset=0, limit=10)

    assert page["total"] == 2
    assert [item["item_id"] for item in page["items"]] == ["group-1", "job-1"]
    assert page["items"][0]["is_group"] is True
    assert page["items"][1]["artifact_flags"] == {"package": False}


def test_summary_index_can_sort_by_created_at_for_recent_job_view(tmp_path: Path) -> None:
    store = _store(tmp_path)

    store.upsert_summary(
        {
            "item_id": "old-touched",
            "is_group": False,
            "status": "succeeded",
            "source_filename": "old.dwg",
            "stage": "DONE",
            "percent": 100,
            "message": "done",
            "updated_at": _dt(10),
            "created_at": _dt(1),
            "artifact_flags": {},
        }
    )
    store.upsert_summary(
        {
            "item_id": "new-created",
            "is_group": False,
            "status": "queued",
            "source_filename": "new.dwg",
            "stage": "INIT",
            "percent": 0,
            "message": "queued",
            "updated_at": _dt(2),
            "created_at": _dt(5),
            "artifact_flags": {},
        }
    )

    page = store.list_summaries(offset=0, limit=10, sort_by="created_at")

    assert page["total"] == 2
    assert [item["item_id"] for item in page["items"]] == ["new-created", "old-touched"]


def test_summary_index_preserves_full_summary_payload(tmp_path: Path) -> None:
    store = _store(tmp_path)

    store.upsert_summary(
        {
            "item_id": "job-1",
            "job_id": "job-1",
            "is_group": False,
            "status": "queued",
            "source_filename": "a.dwg",
            "stage": "INIT",
            "percent": 0,
            "message": "",
            "updated_at": _dt(1),
            "created_at": _dt(),
            "artifact_flags": {"package": False},
            "artifacts": {"package_available": False},
            "font_preflight_summary": {"status": "ok"},
            "retry_available": False,
        }
    )

    [item] = store.list_summaries()["items"]
    assert item["job_id"] == "job-1"
    assert item["artifacts"] == {"package_available": False}
    assert item["font_preflight_summary"] == {"status": "ok"}
    assert item["retry_available"] is False


def test_activity_returns_lightweight_change_marker(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert_summary(
        {
            "item_id": "job-1",
            "is_group": False,
            "status": "succeeded",
            "source_filename": "done.dwg",
            "stage": "DONE",
            "percent": 100,
            "message": "done",
            "updated_at": _dt(1),
            "created_at": _dt(),
            "artifact_flags": {},
        }
    )
    store.upsert_summary(
        {
            "item_id": "job-2",
            "is_group": False,
            "status": "running",
            "source_filename": "active.dwg",
            "stage": "EXPORT",
            "percent": 50,
            "message": "running",
            "updated_at": _dt(5),
            "created_at": _dt(2),
            "artifact_flags": {},
        }
    )

    activity = store.activity()

    assert activity == {
        "total": 2,
        "active": 1,
        "last_changed_at": _dt(5).isoformat(),
    }
