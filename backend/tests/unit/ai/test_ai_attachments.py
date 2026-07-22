from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _stores(tmp_path: Path):
    from src.ai.attachment_store import AiAttachmentStore
    from src.ai.chat_store import AiChatStore

    chat_store = AiChatStore(tmp_path / "chat" / "fanban_ai_chat.sqlite3")
    chat_store.initialize()
    attachment_store = AiAttachmentStore(chat_store)
    return chat_store, attachment_store


def test_attachment_store_creates_lists_and_hashes_owner_isolated_file(
    tmp_path: Path,
) -> None:
    chat_store, attachment_store = _stores(tmp_path)
    owner_key = "ip:10.0.0.8"
    conversation = chat_store.create_conversation(owner_key=owner_key, title="附件")
    content = b"attachment-marker"

    created = attachment_store.create_attachment(
        owner_key=owner_key,
        conversation_id=conversation.conversation_id,
        original_name="sensitive-plan.txt",
        media_type="text/plain",
        content=content,
    )

    stored_path = attachment_store.resolve_path(created)
    assert created.sha256 == hashlib.sha256(content).hexdigest()
    assert created.size_bytes == len(content)
    assert created.status == "uploaded"
    assert stored_path.read_bytes() == content
    assert "10.0.0.8" not in str(stored_path)
    assert "sensitive-plan" not in str(stored_path)
    assert attachment_store.get_attachment(
        owner_key=owner_key,
        conversation_id=conversation.conversation_id,
        attachment_id=created.attachment_id,
    ) == created
    assert attachment_store.list_attachments(
        owner_key=owner_key,
        conversation_id=conversation.conversation_id,
    ) == [created]


def test_attachment_store_denies_cross_owner_access_and_binding(tmp_path: Path) -> None:
    chat_store, attachment_store = _stores(tmp_path)
    owner_key = "ip:10.0.0.8"
    other_owner = "ip:10.0.0.9"
    conversation = chat_store.create_conversation(owner_key=owner_key, title="附件")
    message = chat_store.add_message(conversation.conversation_id, "user", "查看附件")
    created = attachment_store.create_attachment(
        owner_key=owner_key,
        conversation_id=conversation.conversation_id,
        original_name="plan.pdf",
        media_type="application/pdf",
        content=b"%PDF-test",
    )

    assert attachment_store.list_attachments(
        owner_key=other_owner,
        conversation_id=conversation.conversation_id,
    ) == []
    assert attachment_store.get_attachment(
        owner_key=other_owner,
        conversation_id=conversation.conversation_id,
        attachment_id=created.attachment_id,
    ) is None
    assert attachment_store.bind_to_message(
        owner_key=other_owner,
        conversation_id=conversation.conversation_id,
        attachment_id=created.attachment_id,
        message_id=message.message_id,
    ) is None
    assert attachment_store.delete_attachment(
        owner_key=other_owner,
        conversation_id=conversation.conversation_id,
        attachment_id=created.attachment_id,
    ) is False

    bound = attachment_store.bind_to_message(
        owner_key=owner_key,
        conversation_id=conversation.conversation_id,
        attachment_id=created.attachment_id,
        message_id=message.message_id,
    )
    assert bound is not None
    assert bound.message_id == message.message_id


def test_attachment_store_delete_removes_database_row_and_file(tmp_path: Path) -> None:
    chat_store, attachment_store = _stores(tmp_path)
    owner_key = "ip:10.0.0.8"
    conversation = chat_store.create_conversation(owner_key=owner_key, title="附件")
    created = attachment_store.create_attachment(
        owner_key=owner_key,
        conversation_id=conversation.conversation_id,
        original_name="plan.txt",
        media_type="text/plain",
        content=b"delete-me",
    )
    stored_path = attachment_store.resolve_path(created)

    assert attachment_store.delete_attachment(
        owner_key=owner_key,
        conversation_id=conversation.conversation_id,
        attachment_id=created.attachment_id,
    ) is True
    assert stored_path.exists() is False
    assert attachment_store.get_attachment(
        owner_key=owner_key,
        conversation_id=conversation.conversation_id,
        attachment_id=created.attachment_id,
    ) is None


def test_chat_store_clear_and_delete_remove_attachment_files(tmp_path: Path) -> None:
    chat_store, attachment_store = _stores(tmp_path)
    owner_key = "ip:10.0.0.8"
    cleared = chat_store.create_conversation(owner_key=owner_key, title="清空")
    cleared_attachment = attachment_store.create_attachment(
        owner_key=owner_key,
        conversation_id=cleared.conversation_id,
        original_name="clear.txt",
        media_type="text/plain",
        content=b"clear",
    )
    cleared_path = attachment_store.resolve_path(cleared_attachment)

    assert chat_store.clear_conversation(cleared.conversation_id, owner_key) is True
    assert cleared_path.exists() is False
    assert attachment_store.list_attachments(
        owner_key=owner_key,
        conversation_id=cleared.conversation_id,
    ) == []

    deleted = chat_store.create_conversation(owner_key=owner_key, title="删除")
    deleted_attachment = attachment_store.create_attachment(
        owner_key=owner_key,
        conversation_id=deleted.conversation_id,
        original_name="delete.txt",
        media_type="text/plain",
        content=b"delete",
    )
    deleted_path = attachment_store.resolve_path(deleted_attachment)

    assert chat_store.delete_conversation(deleted.conversation_id, owner_key) is True
    assert deleted_path.exists() is False


def test_attachment_retention_cleans_expired_files(tmp_path: Path) -> None:
    chat_store, attachment_store = _stores(tmp_path)
    owner_key = "ip:10.0.0.8"
    conversation = chat_store.create_conversation(owner_key=owner_key, title="过期")
    created = attachment_store.create_attachment(
        owner_key=owner_key,
        conversation_id=conversation.conversation_id,
        original_name="expired.txt",
        media_type="text/plain",
        content=b"expired",
    )
    stored_path = attachment_store.resolve_path(created)
    now = datetime(2026, 7, 22, tzinfo=UTC)
    expired_at = (now - timedelta(days=31)).isoformat()
    with sqlite3.connect(chat_store.db_path) as connection:
        connection.execute(
            "UPDATE ai_attachments SET created_at = ? WHERE attachment_id = ?",
            (expired_at, created.attachment_id),
        )

    assert attachment_store.purge_expired_unbound(retention_days=30, now=now) == 1
    assert stored_path.exists() is False

    conversation_attachment = attachment_store.create_attachment(
        owner_key=owner_key,
        conversation_id=conversation.conversation_id,
        original_name="conversation.txt",
        media_type="text/plain",
        content=b"conversation",
    )
    conversation_path = attachment_store.resolve_path(conversation_attachment)
    with sqlite3.connect(chat_store.db_path) as connection:
        connection.execute(
            "UPDATE ai_conversations SET updated_at = ? WHERE conversation_id = ?",
            (expired_at, conversation.conversation_id),
        )

    assert chat_store.purge_expired(retention_days=30, now=now) == 1
    assert conversation_path.exists() is False
