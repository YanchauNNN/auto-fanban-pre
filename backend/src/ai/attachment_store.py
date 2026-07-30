from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .chat_store import AiChatStore
from .owner_identity import normalize_owner_key


@dataclass(frozen=True)
class AiAttachment:
    attachment_id: str
    conversation_id: str
    message_id: str | None
    owner_key: str
    original_name: str
    stored_name: str
    media_type: str
    kind: str
    size_bytes: int
    sha256: str
    status: str
    extracted_text: str
    metadata: dict[str, Any]
    error_code: str | None
    created_at: str


class AiAttachmentConversationNotFound(ValueError):
    pass


class AiAttachmentStore:
    def __init__(self, chat_store: AiChatStore) -> None:
        self.chat_store = chat_store
        self.storage_root = chat_store.attachment_root
        self.storage_root.mkdir(parents=True, exist_ok=True)

    def create_attachment(
        self,
        *,
        owner_key: str,
        conversation_id: str,
        original_name: str,
        media_type: str,
        content: bytes,
    ) -> AiAttachment:
        normalized_owner = normalize_owner_key(owner_key)
        attachment_id = str(uuid.uuid4())
        safe_original_name = _safe_original_name(original_name)
        suffix = Path(safe_original_name).suffix.lower()
        owner_digest = hashlib.sha256(normalized_owner.encode("utf-8")).hexdigest()[:32]
        stored_name = Path(
            owner_digest,
            conversation_id,
            attachment_id,
            f"original{suffix}",
        ).as_posix()
        destination = self._resolve_stored_name(stored_name)
        destination.parent.mkdir(parents=True, exist_ok=False)
        temporary = destination.with_name(f".{destination.name}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)

            now = _now()
            with self.chat_store._connect() as connection, connection:
                conversation = connection.execute(
                    """
                    SELECT conversation_id
                    FROM ai_conversations
                    WHERE conversation_id = ?
                      AND owner_key = ?
                      AND archived = 0
                    """,
                    (conversation_id, normalized_owner),
                ).fetchone()
                if conversation is None:
                    raise AiAttachmentConversationNotFound(conversation_id)
                connection.execute(
                    """
                    INSERT INTO ai_attachments (
                        attachment_id, conversation_id, message_id, owner_key,
                        original_name, stored_name, media_type, kind, size_bytes,
                        sha256, status, extracted_text, metadata_json, error_code,
                        created_at
                    )
                    VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, 'uploaded', '', '{}', NULL, ?)
                    """,
                    (
                        attachment_id,
                        conversation_id,
                        normalized_owner,
                        safe_original_name,
                        stored_name,
                        media_type.strip() or "application/octet-stream",
                        _kind_for_suffix(suffix),
                        len(content),
                        hashlib.sha256(content).hexdigest(),
                        now,
                    ),
                )
        except Exception:
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            self._remove_empty_parents(destination.parent)
            raise

        created = self.get_attachment(
            owner_key=normalized_owner,
            conversation_id=conversation_id,
            attachment_id=attachment_id,
        )
        if created is None:
            raise RuntimeError("attachment disappeared after insert")
        return created

    def list_attachments(
        self,
        *,
        owner_key: str,
        conversation_id: str,
    ) -> list[AiAttachment]:
        normalized_owner = normalize_owner_key(owner_key)
        with self.chat_store._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM ai_attachments
                WHERE conversation_id = ?
                  AND owner_key = ?
                ORDER BY created_at ASC, attachment_id ASC
                """,
                (conversation_id, normalized_owner),
            ).fetchall()
        return [_attachment_from_row(row) for row in rows]

    def get_attachment(
        self,
        *,
        owner_key: str,
        conversation_id: str,
        attachment_id: str,
    ) -> AiAttachment | None:
        normalized_owner = normalize_owner_key(owner_key)
        with self.chat_store._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM ai_attachments
                WHERE attachment_id = ?
                  AND conversation_id = ?
                  AND owner_key = ?
                """,
                (attachment_id, conversation_id, normalized_owner),
            ).fetchone()
        return _attachment_from_row(row) if row is not None else None

    def list_message_attachments(
        self,
        *,
        owner_key: str,
        conversation_id: str,
        message_id: str,
    ) -> list[AiAttachment]:
        normalized_owner = normalize_owner_key(owner_key)
        with self.chat_store._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM ai_attachments
                WHERE message_id = ?
                  AND conversation_id = ?
                  AND owner_key = ?
                ORDER BY created_at ASC, attachment_id ASC
                """,
                (message_id, conversation_id, normalized_owner),
            ).fetchall()
        return [_attachment_from_row(row) for row in rows]

    def bind_to_message(
        self,
        *,
        owner_key: str,
        conversation_id: str,
        attachment_id: str,
        message_id: str,
    ) -> AiAttachment | None:
        normalized_owner = normalize_owner_key(owner_key)
        with self.chat_store._connect() as connection, connection:
            cursor = connection.execute(
                """
                UPDATE ai_attachments
                SET message_id = ?
                WHERE attachment_id = ?
                  AND conversation_id = ?
                  AND owner_key = ?
                  AND EXISTS (
                      SELECT 1
                      FROM ai_messages
                      WHERE message_id = ?
                        AND conversation_id = ?
                  )
                """,
                (
                    message_id,
                    attachment_id,
                    conversation_id,
                    normalized_owner,
                    message_id,
                    conversation_id,
                ),
            )
            if cursor.rowcount <= 0:
                return None
        return self.get_attachment(
            owner_key=normalized_owner,
            conversation_id=conversation_id,
            attachment_id=attachment_id,
        )

    def update_parse_result(
        self,
        *,
        owner_key: str,
        conversation_id: str,
        attachment_id: str,
        kind: str,
        extracted_text: str,
        media_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AiAttachment | None:
        return self._update_result(
            owner_key=owner_key,
            conversation_id=conversation_id,
            attachment_id=attachment_id,
            kind=kind,
            status="ready",
            extracted_text=extracted_text,
            media_type=media_type,
            metadata=metadata or {},
            error_code=None,
        )

    def mark_failed(
        self,
        *,
        owner_key: str,
        conversation_id: str,
        attachment_id: str,
        error_code: str,
        metadata: dict[str, Any] | None = None,
    ) -> AiAttachment | None:
        return self._update_result(
            owner_key=owner_key,
            conversation_id=conversation_id,
            attachment_id=attachment_id,
            kind="unknown",
            status="failed",
            extracted_text="",
            media_type=None,
            metadata=metadata or {},
            error_code=error_code,
        )

    def delete_attachment(
        self,
        *,
        owner_key: str,
        conversation_id: str,
        attachment_id: str,
    ) -> bool:
        normalized_owner = normalize_owner_key(owner_key)
        with self.chat_store._connect() as connection:
            row = connection.execute(
                """
                SELECT stored_name
                FROM ai_attachments
                WHERE attachment_id = ?
                  AND conversation_id = ?
                  AND owner_key = ?
                """,
                (attachment_id, conversation_id, normalized_owner),
            ).fetchone()
            if row is None:
                return False
            with connection:
                connection.execute(
                    "DELETE FROM ai_attachments WHERE attachment_id = ?",
                    (attachment_id,),
                )
        self.chat_store.remove_attachment_files([str(row["stored_name"])])
        return True

    def purge_expired_unbound(
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
        with self.chat_store._connect() as connection:
            rows = connection.execute(
                """
                SELECT attachment_id, stored_name
                FROM ai_attachments
                WHERE message_id IS NULL
                  AND created_at < ?
                """,
                (cutoff,),
            ).fetchall()
            if not rows:
                return 0
            with connection:
                connection.executemany(
                    "DELETE FROM ai_attachments WHERE attachment_id = ?",
                    [(str(row["attachment_id"]),) for row in rows],
                )
        self.chat_store.remove_attachment_files(
            [str(row["stored_name"]) for row in rows]
        )
        return len(rows)

    def resolve_path(self, attachment: AiAttachment) -> Path:
        return self._resolve_stored_name(attachment.stored_name)

    def read_bytes(self, attachment: AiAttachment) -> bytes:
        return self.resolve_path(attachment).read_bytes()

    def _update_result(
        self,
        *,
        owner_key: str,
        conversation_id: str,
        attachment_id: str,
        kind: str,
        status: str,
        extracted_text: str,
        media_type: str | None,
        metadata: dict[str, Any],
        error_code: str | None,
    ) -> AiAttachment | None:
        normalized_owner = normalize_owner_key(owner_key)
        metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        with self.chat_store._connect() as connection, connection:
            cursor = connection.execute(
                """
                UPDATE ai_attachments
                SET kind = ?, status = ?, extracted_text = ?, media_type = COALESCE(?, media_type),
                    metadata_json = ?, error_code = ?
                WHERE attachment_id = ?
                  AND conversation_id = ?
                  AND owner_key = ?
                """,
                (
                    kind,
                    status,
                    extracted_text,
                    media_type,
                    metadata_json,
                    error_code,
                    attachment_id,
                    conversation_id,
                    normalized_owner,
                ),
            )
            if cursor.rowcount <= 0:
                return None
        return self.get_attachment(
            owner_key=normalized_owner,
            conversation_id=conversation_id,
            attachment_id=attachment_id,
        )

    def _resolve_stored_name(self, stored_name: str) -> Path:
        root = self.storage_root.resolve()
        candidate = (root / stored_name).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("attachment path escapes storage root") from exc
        return candidate

    def _remove_empty_parents(self, directory: Path) -> None:
        root = self.storage_root.resolve()
        current = directory.resolve()
        while current != root:
            try:
                current.relative_to(root)
                current.rmdir()
            except (OSError, ValueError):
                break
            current = current.parent


def _safe_original_name(value: str) -> str:
    normalized = str(value).replace("\x00", "").strip()
    return Path(normalized).name or "attachment"


def _kind_for_suffix(suffix: str) -> str:
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return "image"
    if suffix in {".dwg", ".dxf"}:
        return "drawing"
    if suffix in {".pdf", ".txt", ".md", ".docx", ".xlsx"}:
        return "document"
    return "unknown"


def _attachment_from_row(row) -> AiAttachment:
    return AiAttachment(
        attachment_id=str(row["attachment_id"]),
        conversation_id=str(row["conversation_id"]),
        message_id=row["message_id"],
        owner_key=str(row["owner_key"]),
        original_name=str(row["original_name"]),
        stored_name=str(row["stored_name"]),
        media_type=str(row["media_type"]),
        kind=str(row["kind"]),
        size_bytes=int(row["size_bytes"]),
        sha256=str(row["sha256"]),
        status=str(row["status"]),
        extracted_text=str(row["extracted_text"] or ""),
        metadata=_loads_metadata(str(row["metadata_json"])),
        error_code=row["error_code"],
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
