from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AiConversation:
    conversation_id: str
    owner_key: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    account_id: str | None = None


@dataclass(frozen=True)
class AiChatMessage:
    message_id: str
    conversation_id: str
    role: str
    content: str
    created_at: str
    model_profile: str | None = None
    metadata: dict[str, Any] | None = None


class AiChatStore:
    def __init__(
        self,
        db_path: Path | str,
        *,
        timeout_seconds: float = 30.0,
        busy_timeout_ms: int = 30000,
    ) -> None:
        self.db_path = Path(db_path)
        self.timeout_seconds = timeout_seconds
        self.busy_timeout_ms = busy_timeout_ms

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;

                CREATE TABLE IF NOT EXISTS ai_conversations (
                    conversation_id TEXT PRIMARY KEY,
                    owner_key TEXT NOT NULL,
                    account_id TEXT,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS ix_ai_conversations_owner_updated
                ON ai_conversations(owner_key, archived, updated_at DESC);

                CREATE INDEX IF NOT EXISTS ix_ai_conversations_updated_at
                ON ai_conversations(updated_at);

                CREATE TABLE IF NOT EXISTS ai_messages (
                    message_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    model_profile TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES ai_conversations(conversation_id)
                );

                CREATE INDEX IF NOT EXISTS ix_ai_messages_conversation_created
                ON ai_messages(conversation_id, created_at ASC);
                """
            )

    def create_conversation(
        self,
        *,
        owner_key: str,
        title: str,
        account_id: str | None = None,
    ) -> AiConversation:
        now = _now()
        conversation_id = str(uuid.uuid4())
        with self._connect() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO ai_conversations (
                        conversation_id, owner_key, account_id, title,
                        created_at, updated_at, message_count, archived
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 0, 0)
                    """,
                    (conversation_id, owner_key, account_id, title.strip() or "新会话", now, now),
                )
            row = conn.execute(
                "SELECT * FROM ai_conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("conversation disappeared after insert")
        return _conversation_from_row(row)

    def list_conversations(self, owner_key: str) -> list[AiConversation]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM ai_conversations
                WHERE owner_key = ?
                  AND archived = 0
                ORDER BY updated_at DESC, conversation_id DESC
                """,
                (owner_key,),
            ).fetchall()
        return [_conversation_from_row(row) for row in rows]

    def get_conversation(self, conversation_id: str, owner_key: str) -> AiConversation | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM ai_conversations
                WHERE conversation_id = ?
                  AND owner_key = ?
                  AND archived = 0
                """,
                (conversation_id, owner_key),
            ).fetchone()
        return _conversation_from_row(row) if row is not None else None

    def rename_conversation(
        self,
        conversation_id: str,
        *,
        owner_key: str,
        title: str,
    ) -> AiConversation | None:
        normalized_title = title.strip() or "新会话"
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT conversation_id
                FROM ai_conversations
                WHERE conversation_id = ?
                  AND owner_key = ?
                  AND archived = 0
                """,
                (conversation_id, owner_key),
            ).fetchone()
            if existing is None:
                return None
            with conn:
                conn.execute(
                    """
                    UPDATE ai_conversations
                    SET title = ?,
                        updated_at = ?
                    WHERE conversation_id = ?
                    """,
                    (normalized_title, _now(), conversation_id),
                )
            row = conn.execute(
                "SELECT * FROM ai_conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return _conversation_from_row(row) if row is not None else None

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        model_profile: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AiChatMessage:
        now = _now()
        message_id = str(uuid.uuid4())
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO ai_messages (
                        message_id, conversation_id, role, content,
                        model_profile, metadata_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (message_id, conversation_id, role, content, model_profile, metadata_json, now),
                )
                conn.execute(
                    """
                    UPDATE ai_conversations
                    SET updated_at = ?,
                        message_count = message_count + 1
                    WHERE conversation_id = ?
                    """,
                    (now, conversation_id),
                )
            row = conn.execute(
                "SELECT * FROM ai_messages WHERE message_id = ?",
                (message_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("message disappeared after insert")
        return _message_from_row(row)

    def list_messages(self, conversation_id: str, *, limit: int | None = None) -> list[AiChatMessage]:
        params: tuple[Any, ...]
        sql = """
            SELECT *
            FROM ai_messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC
        """
        params = (conversation_id,)
        if limit is not None and limit > 0:
            sql = """
                SELECT *
                FROM (
                    SELECT *
                    FROM ai_messages
                    WHERE conversation_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                )
                ORDER BY created_at ASC
            """
            params = (conversation_id, int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_message_from_row(row) for row in rows]

    def update_message_metadata(
        self,
        message_id: str,
        metadata: dict[str, Any],
    ) -> AiChatMessage | None:
        metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            with conn:
                cursor = conn.execute(
                    "UPDATE ai_messages SET metadata_json = ? WHERE message_id = ?",
                    (metadata_json, message_id),
                )
            if cursor.rowcount <= 0:
                return None
            row = conn.execute(
                "SELECT * FROM ai_messages WHERE message_id = ?",
                (message_id,),
            ).fetchone()
        return _message_from_row(row) if row is not None else None

    def complete_exchange(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        user_metadata: dict[str, Any],
        assistant_content: str,
        assistant_model_profile: str | None,
        assistant_metadata: dict[str, Any],
    ) -> tuple[AiChatMessage, AiChatMessage]:
        now = _now()
        assistant_message_id = str(uuid.uuid4())
        user_metadata_json = json.dumps(user_metadata, ensure_ascii=False, sort_keys=True)
        assistant_metadata_json = json.dumps(
            assistant_metadata,
            ensure_ascii=False,
            sort_keys=True,
        )
        with self._connect() as conn, conn:
            user_cursor = conn.execute(
                """
                UPDATE ai_messages
                SET metadata_json = ?
                WHERE message_id = ?
                  AND conversation_id = ?
                  AND role = 'user'
                """,
                (user_metadata_json, user_message_id, conversation_id),
            )
            if user_cursor.rowcount <= 0:
                raise RuntimeError("user message disappeared before exchange completion")
            conn.execute(
                """
                INSERT INTO ai_messages (
                    message_id, conversation_id, role, content,
                    model_profile, metadata_json, created_at
                )
                VALUES (?, ?, 'assistant', ?, ?, ?, ?)
                """,
                (
                    assistant_message_id,
                    conversation_id,
                    assistant_content,
                    assistant_model_profile,
                    assistant_metadata_json,
                    now,
                ),
            )
            conversation_cursor = conn.execute(
                """
                UPDATE ai_conversations
                SET updated_at = ?,
                    message_count = message_count + 1
                WHERE conversation_id = ?
                """,
                (now, conversation_id),
            )
            if conversation_cursor.rowcount <= 0:
                raise RuntimeError("conversation disappeared before exchange completion")

        with self._connect() as conn:
            user_row = conn.execute(
                "SELECT * FROM ai_messages WHERE message_id = ?",
                (user_message_id,),
            ).fetchone()
            assistant_row = conn.execute(
                "SELECT * FROM ai_messages WHERE message_id = ?",
                (assistant_message_id,),
            ).fetchone()
        if user_row is None or assistant_row is None:
            raise RuntimeError("chat exchange disappeared after commit")
        return _message_from_row(user_row), _message_from_row(assistant_row)

    def clear_conversation(self, conversation_id: str, owner_key: str) -> bool:
        with self._connect() as conn:
            conversation = conn.execute(
                """
                SELECT conversation_id
                FROM ai_conversations
                WHERE conversation_id = ?
                  AND owner_key = ?
                  AND archived = 0
                """,
                (conversation_id, owner_key),
            ).fetchone()
            if conversation is None:
                return False
            with conn:
                conn.execute("DELETE FROM ai_messages WHERE conversation_id = ?", (conversation_id,))
                conn.execute(
                    """
                    UPDATE ai_conversations
                    SET message_count = 0,
                        updated_at = ?
                    WHERE conversation_id = ?
                    """,
                    (_now(), conversation_id),
                )
        return True

    def purge_expired(
        self,
        *,
        retention_days: int,
        now: datetime | None = None,
    ) -> int:
        if retention_days <= 0:
            return 0
        current_time = now or datetime.now(UTC)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=UTC)
        cutoff = (current_time.astimezone(UTC) - timedelta(days=retention_days)).isoformat()
        with self._connect() as conn, conn:
            conn.execute(
                """
                    DELETE FROM ai_messages
                    WHERE conversation_id IN (
                        SELECT conversation_id
                        FROM ai_conversations
                        WHERE updated_at < ?
                    )
                    """,
                (cutoff,),
            )
            cursor = conn.execute(
                "DELETE FROM ai_conversations WHERE updated_at < ?",
                (cutoff,),
            )
        return max(int(cursor.rowcount), 0)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=self.timeout_seconds)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        try:
            yield conn
        finally:
            conn.close()


def _conversation_from_row(row: sqlite3.Row) -> AiConversation:
    return AiConversation(
        conversation_id=str(row["conversation_id"]),
        owner_key=str(row["owner_key"]),
        account_id=row["account_id"],
        title=str(row["title"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        message_count=int(row["message_count"]),
    )


def _message_from_row(row: sqlite3.Row) -> AiChatMessage:
    return AiChatMessage(
        message_id=str(row["message_id"]),
        conversation_id=str(row["conversation_id"]),
        role=str(row["role"]),
        content=str(row["content"]),
        model_profile=row["model_profile"],
        metadata=_loads_metadata(str(row["metadata_json"])),
        created_at=str(row["created_at"]),
    )


def _loads_metadata(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _now() -> str:
    return datetime.now(UTC).isoformat()
