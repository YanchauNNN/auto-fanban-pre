from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

UNFINISHED_QUEUE_STATUSES = ("queued", "claimed")
ACTIVE_SUMMARY_STATUSES = {"queued", "running", "claimed", "processing", "pending"}
DEFAULT_SQLITE_TIMEOUT_SECONDS = 30.0
DEFAULT_SQLITE_BUSY_TIMEOUT_MS = 30000
WORKER_INTERRUPTED_ERROR = "worker_interrupted_before_completion"


class SQLiteQueueStore:
    """SQLite-backed control store for packaged runtime queue state."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        timeout_seconds: float = DEFAULT_SQLITE_TIMEOUT_SECONDS,
        busy_timeout_ms: int = DEFAULT_SQLITE_BUSY_TIMEOUT_MS,
    ) -> None:
        self.db_path = Path(db_path)
        self.timeout_seconds = float(timeout_seconds)
        self.busy_timeout_ms = int(busy_timeout_ms)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;

                CREATE TABLE IF NOT EXISTS queue_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_type TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    run_after TEXT,
                    claimed_by TEXT,
                    claimed_at TEXT,
                    heartbeat_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS uq_queue_items_unfinished
                ON queue_items(item_type, item_id)
                WHERE status IN ('queued', 'claimed');

                CREATE INDEX IF NOT EXISTS ix_queue_items_claim_order
                ON queue_items(status, priority DESC, id ASC);

                CREATE INDEX IF NOT EXISTS ix_queue_items_heartbeat
                ON queue_items(status, heartbeat_at);

                CREATE TABLE IF NOT EXISTS worker_heartbeats (
                    worker_id TEXT PRIMARY KEY,
                    pid INTEGER,
                    started_at TEXT,
                    last_seen_at TEXT NOT NULL,
                    state TEXT NOT NULL,
                    current_item_type TEXT,
                    current_item_id TEXT,
                    message TEXT
                );

                CREATE TABLE IF NOT EXISTS job_summaries (
                    item_id TEXT PRIMARY KEY,
                    is_group INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    batch_id TEXT,
                    group_id TEXT,
                    source_filename TEXT,
                    task_kind TEXT,
                    task_role TEXT,
                    stage TEXT,
                    percent INTEGER,
                    message TEXT,
                    failure_reason TEXT,
                    stage_context TEXT,
                    finished_at TEXT,
                    artifact_flags TEXT NOT NULL DEFAULT '{}',
                    findings_count INTEGER,
                    affected_drawings_count INTEGER,
                    summary_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS ix_job_summaries_updated
                ON job_summaries(updated_at DESC, item_id DESC);

                CREATE INDEX IF NOT EXISTS ix_job_summaries_status_updated
                ON job_summaries(status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS activity_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def table_names(self) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        return {str(row["name"]) for row in rows}

    def enqueue(
        self,
        item_type: str,
        item_id: str,
        *,
        priority: int = 0,
        run_after: datetime | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = _format_timestamp(_coerce_now(now))
        run_after_value = _format_timestamp(run_after) if run_after is not None else None
        with self._connect() as conn:
            try:
                with conn:
                    cursor = conn.execute(
                        """
                        INSERT INTO queue_items (
                            item_type, item_id, status, priority, run_after,
                            created_at, updated_at
                        )
                        VALUES (?, ?, 'queued', ?, ?, ?, ?)
                        """,
                        (item_type, item_id, priority, run_after_value, timestamp, timestamp),
                    )
                    row_id = int(cursor.lastrowid)
            except sqlite3.IntegrityError:
                existing = self._find_unfinished_queue_item(conn, item_type, item_id)
                if existing is None:
                    raise
                return existing

            row = self._get_queue_item(conn, row_id)
            if row is None:
                raise RuntimeError("queued item disappeared after insert")
            return row

    def claim_next(self, *, worker_id: str, now: datetime | None = None) -> dict[str, Any] | None:
        timestamp = _format_timestamp(_coerce_now(now))
        with self._connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    """
                    SELECT *
                    FROM queue_items
                    WHERE status = 'queued'
                      AND (run_after IS NULL OR run_after <= ?)
                    ORDER BY priority DESC, id ASC
                    LIMIT 1
                    """,
                    (timestamp,),
                ).fetchone()
                if row is None:
                    conn.commit()
                    return None

                conn.execute(
                    """
                    UPDATE queue_items
                    SET status = 'claimed',
                        claimed_by = ?,
                        claimed_at = ?,
                        heartbeat_at = ?,
                        attempt_count = attempt_count + 1,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (worker_id, timestamp, timestamp, timestamp, row["id"]),
                )
                claimed = self._get_queue_item(conn, int(row["id"]))
                conn.commit()
                return claimed
            except Exception:
                conn.rollback()
                raise

    def heartbeat_claim(
        self,
        worker_id: str,
        item_type: str,
        item_id: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        timestamp = _format_timestamp(_coerce_now(now))
        with self._connect() as conn:
            with conn:
                conn.execute(
                    """
                    UPDATE queue_items
                    SET heartbeat_at = ?, updated_at = ?
                    WHERE item_type = ?
                      AND item_id = ?
                      AND claimed_by = ?
                      AND status = 'claimed'
                    """,
                    (timestamp, timestamp, item_type, item_id, worker_id),
                )
            return self._find_unfinished_queue_item(conn, item_type, item_id)

    def find_stale_claims(
        self, *, timeout_seconds: int, now: datetime | None = None
    ) -> list[dict[str, Any]]:
        cutoff = _format_timestamp(_coerce_now(now) - timedelta(seconds=timeout_seconds))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM queue_items
                WHERE status = 'claimed'
                  AND heartbeat_at IS NOT NULL
                  AND heartbeat_at <= ?
                ORDER BY heartbeat_at ASC, id ASC
                """,
                (cutoff,),
            ).fetchall()
        return [_queue_row_to_dict(row) for row in rows]

    def recover_stale_claims(
        self,
        *,
        timeout_seconds: float,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Atomically fail expired claims without replaying non-idempotent work."""
        timestamp = _format_timestamp(_coerce_now(now))
        cutoff = _format_timestamp(
            _coerce_now(now) - timedelta(seconds=max(0.0, float(timeout_seconds)))
        )
        with self._connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                rows = conn.execute(
                    """
                    SELECT id
                    FROM queue_items
                    WHERE status = 'claimed'
                      AND COALESCE(heartbeat_at, claimed_at, updated_at) <= ?
                    ORDER BY COALESCE(heartbeat_at, claimed_at, updated_at) ASC, id ASC
                    """,
                    (cutoff,),
                ).fetchall()
                row_ids = [int(row["id"]) for row in rows]
                for row_id in row_ids:
                    conn.execute(
                        """
                        UPDATE queue_items
                        SET status = 'failed',
                            last_error = ?,
                            updated_at = ?
                        WHERE id = ?
                          AND status = 'claimed'
                          AND COALESCE(heartbeat_at, claimed_at, updated_at) <= ?
                        """,
                        (WORKER_INTERRUPTED_ERROR, timestamp, row_id, cutoff),
                    )
                recovered_rows = [
                    row
                    for row_id in row_ids
                    if (row := conn.execute(
                        "SELECT * FROM queue_items WHERE id = ? AND status = 'failed' "
                        "AND last_error = ?",
                        (row_id, WORKER_INTERRUPTED_ERROR),
                    ).fetchone())
                    is not None
                ]
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return [_queue_row_to_dict(row) for row in recovered_rows]

    def list_interrupted_claims(self) -> list[dict[str, Any]]:
        """Return interrupted claims that may still need JSON state reconciliation."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM queue_items
                WHERE status = 'failed'
                  AND last_error = ?
                  AND claimed_by IS NOT NULL
                ORDER BY id ASC
                """,
                (WORKER_INTERRUPTED_ERROR,),
            ).fetchall()
        return [_queue_row_to_dict(row) for row in rows]

    def acknowledge_interrupted_claim(
        self,
        *,
        queue_item_id: int,
        claimed_by: str,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Persistently acknowledge that interrupted JSON state was reconciled."""
        timestamp = _format_timestamp(_coerce_now(now))
        with self._connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.execute(
                    """
                    UPDATE queue_items
                    SET claimed_by = NULL,
                        updated_at = ?
                    WHERE id = ?
                      AND status = 'failed'
                      AND last_error = ?
                      AND claimed_by = ?
                    """,
                    (
                        timestamp,
                        int(queue_item_id),
                        WORKER_INTERRUPTED_ERROR,
                        claimed_by,
                    ),
                )
                if cursor.rowcount != 1:
                    conn.commit()
                    return None
                acknowledged = self._get_queue_item(conn, int(queue_item_id))
                conn.commit()
                return acknowledged
            except Exception:
                conn.rollback()
                raise

    def has_newer_queue_item(
        self,
        *,
        item_type: str,
        item_id: str,
        after_queue_item_id: int,
    ) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM queue_items
                WHERE item_type = ?
                  AND item_id = ?
                  AND id > ?
                LIMIT 1
                """,
                (item_type, item_id, int(after_queue_item_id)),
            ).fetchone()
        return row is not None

    def get_queue_item(self, queue_item_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            return self._get_queue_item(conn, int(queue_item_id))

    def complete_claim(
        self,
        *,
        queue_item_id: int,
        worker_id: str,
        status: str,
        last_error: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Complete only the exact claim owned by ``worker_id``.

        Returning ``None`` fences a late worker whose claim was already recovered.
        """
        timestamp = _format_timestamp(_coerce_now(now))
        with self._connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.execute(
                    """
                    UPDATE queue_items
                    SET status = ?,
                        last_error = ?,
                        updated_at = ?
                    WHERE id = ?
                      AND status = 'claimed'
                      AND claimed_by = ?
                    """,
                    (status, last_error, timestamp, int(queue_item_id), worker_id),
                )
                if cursor.rowcount != 1:
                    conn.commit()
                    return None
                completed = self._get_queue_item(conn, int(queue_item_id))
                conn.commit()
                return completed
            except Exception:
                conn.rollback()
                raise

    def complete(
        self,
        item_type: str,
        item_id: str,
        *,
        status: str,
        last_error: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = _format_timestamp(_coerce_now(now))
        with self._connect() as conn:
            existing = self._find_unfinished_queue_item(conn, item_type, item_id)
            if existing is None:
                raise KeyError(f"unfinished queue item not found: {item_type}:{item_id}")
            with conn:
                conn.execute(
                    """
                    UPDATE queue_items
                    SET status = ?,
                        last_error = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (status, last_error, timestamp, existing["id"]),
                )
            completed = self._get_queue_item(conn, int(existing["id"]))
            if completed is None:
                raise RuntimeError("queue item disappeared after completion")
            return completed

    def list_queue_items(self, *, status: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM queue_items"
        params: tuple[Any, ...] = ()
        if status is not None:
            sql += " WHERE status = ?"
            params = (status,)
        sql += " ORDER BY id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_queue_row_to_dict(row) for row in rows]

    def queue_depth(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM queue_items
                WHERE status IN ('queued', 'claimed')
                """
            ).fetchone()
        return int(row["count"])

    def upsert_worker_heartbeat(
        self,
        *,
        worker_id: str,
        pid: int | None = None,
        state: str = "idle",
        current_item_type: str | None = None,
        current_item_id: str | None = None,
        message: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = _format_timestamp(_coerce_now(now))
        with self._connect() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO worker_heartbeats (
                        worker_id, pid, started_at, last_seen_at, state,
                        current_item_type, current_item_id, message
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(worker_id) DO UPDATE SET
                        pid = excluded.pid,
                        last_seen_at = excluded.last_seen_at,
                        state = excluded.state,
                        current_item_type = excluded.current_item_type,
                        current_item_id = excluded.current_item_id,
                        message = excluded.message
                    """,
                    (
                        worker_id,
                        pid,
                        timestamp,
                        timestamp,
                        state,
                        current_item_type,
                        current_item_id,
                        message,
                    ),
                )
            row = conn.execute(
                "SELECT * FROM worker_heartbeats WHERE worker_id = ?", (worker_id,)
            ).fetchone()
        if row is None:
            raise RuntimeError("worker heartbeat disappeared after upsert")
        return dict(row)

    def worker_status(
        self, *, max_age_seconds: int = 90, now: datetime | None = None
    ) -> dict[str, Any]:
        cutoff = _format_timestamp(_coerce_now(now) - timedelta(seconds=max_age_seconds))
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count, MAX(last_seen_at) AS last_seen_at
                FROM worker_heartbeats
                WHERE last_seen_at >= ?
                """,
                (cutoff,),
            ).fetchone()
        count = int(row["count"])
        return {
            "alive": count > 0,
            "count": count,
            "last_seen_at": row["last_seen_at"],
        }

    def upsert_summary(self, summary: dict[str, Any]) -> dict[str, Any]:
        now_value = _format_timestamp(_coerce_now(None))
        created_at = _format_timestamp(summary.get("created_at") or summary.get("updated_at") or now_value)
        updated_at = _format_timestamp(summary.get("updated_at") or created_at)
        artifact_flags = _json_dumps(summary.get("artifact_flags") or {})
        summary_json = _json_dumps(_json_ready(summary))
        stage_context = summary.get("stage_context")
        if isinstance(stage_context, dict | list):
            stage_context = _json_dumps(stage_context)
        finished_at = summary.get("finished_at")
        finished_at_value = _format_timestamp(finished_at) if finished_at is not None else None

        values = {
            "item_id": summary["item_id"],
            "is_group": 1 if bool(summary.get("is_group")) else 0,
            "status": summary["status"],
            "created_at": created_at,
            "updated_at": updated_at,
            "batch_id": summary.get("batch_id"),
            "group_id": summary.get("group_id"),
            "source_filename": summary.get("source_filename"),
            "task_kind": summary.get("task_kind"),
            "task_role": summary.get("task_role"),
            "stage": summary.get("stage"),
            "percent": summary.get("percent"),
            "message": summary.get("message"),
            "failure_reason": summary.get("failure_reason"),
            "stage_context": stage_context,
            "finished_at": finished_at_value,
            "artifact_flags": artifact_flags,
            "findings_count": summary.get("findings_count"),
            "affected_drawings_count": summary.get("affected_drawings_count"),
            "summary_json": summary_json,
        }
        columns = tuple(values)
        placeholders = ", ".join("?" for _ in columns)
        update_assignments = ", ".join(
            f"{column} = excluded.{column}" for column in columns if column != "item_id"
        )

        with self._connect() as conn:
            with conn:
                conn.execute(
                    f"""
                    INSERT INTO job_summaries ({", ".join(columns)})
                    VALUES ({placeholders})
                    ON CONFLICT(item_id) DO UPDATE SET {update_assignments}
                    """,
                    tuple(values[column] for column in columns),
                )
            row = conn.execute(
                "SELECT * FROM job_summaries WHERE item_id = ?", (summary["item_id"],)
            ).fetchone()
        if row is None:
            raise RuntimeError("summary disappeared after upsert")
        return _summary_row_to_dict(row)

    def delete_summary(self, item_id: str) -> bool:
        with self._connect() as conn, conn:
            cursor = conn.execute(
                "DELETE FROM job_summaries WHERE item_id = ?",
                (item_id,),
            )
        return cursor.rowcount > 0

    def list_summaries(
        self,
        *,
        status: str | None = None,
        offset: int = 0,
        limit: int | None = 100,
        sort_by: str = "updated_at",
    ) -> dict[str, Any]:
        params: list[Any] = []
        where = ""
        if status is not None:
            where = " WHERE status = ?"
            params.append(status)
        sort_column = "created_at" if sort_by == "created_at" else "updated_at"

        with self._connect() as conn:
            total = int(
                conn.execute(f"SELECT COUNT(*) AS count FROM job_summaries{where}", params).fetchone()[
                    "count"
                ]
            )
            if limit is None:
                rows = conn.execute(
                    f"""
                    SELECT *
                    FROM job_summaries
                    {where}
                    ORDER BY {sort_column} DESC, item_id DESC
                    """,
                    params,
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT *
                    FROM job_summaries
                    {where}
                    ORDER BY {sort_column} DESC, item_id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (*params, limit, offset),
                ).fetchall()
        return {"total": total, "items": [_summary_row_to_dict(row) for row in rows]}

    def activity(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total, MAX(updated_at) AS last_changed_at FROM job_summaries"
            ).fetchone()
            active_rows = conn.execute(
                f"""
                SELECT COUNT(*) AS active
                FROM job_summaries
                WHERE status IN ({", ".join("?" for _ in ACTIVE_SUMMARY_STATUSES)})
                """,
                tuple(ACTIVE_SUMMARY_STATUSES),
            ).fetchone()
        return {
            "total": int(row["total"]),
            "active": int(active_rows["active"]),
            "last_changed_at": row["last_changed_at"],
        }

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=self.timeout_seconds)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        try:
            yield conn
        finally:
            conn.close()

    def _get_queue_item(self, conn: sqlite3.Connection, row_id: int) -> dict[str, Any] | None:
        row = conn.execute("SELECT * FROM queue_items WHERE id = ?", (row_id,)).fetchone()
        return _queue_row_to_dict(row) if row is not None else None

    def _find_unfinished_queue_item(
        self, conn: sqlite3.Connection, item_type: str, item_id: str
    ) -> dict[str, Any] | None:
        row = conn.execute(
            """
            SELECT *
            FROM queue_items
            WHERE item_type = ?
              AND item_id = ?
              AND status IN ('queued', 'claimed')
            ORDER BY id DESC
            LIMIT 1
            """,
            (item_type, item_id),
        ).fetchone()
        return _queue_row_to_dict(row) if row is not None else None


def _coerce_now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def _format_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _queue_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _summary_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    summary_json = item.pop("summary_json", "{}")
    item["is_group"] = bool(item["is_group"])
    item["artifact_flags"] = json.loads(item["artifact_flags"] or "{}")
    summary_payload = json.loads(summary_json or "{}")
    if isinstance(summary_payload, dict):
        item.update(summary_payload)
        item.setdefault("item_id", row["item_id"])
        if "is_group" in item:
            item["is_group"] = bool(item["is_group"])
    return item


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_ready(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    return value
