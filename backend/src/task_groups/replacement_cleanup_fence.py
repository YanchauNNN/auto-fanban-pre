from __future__ import annotations

import hashlib
import json
import os
import threading
import unicodedata
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..pipeline.cross_process_lock import exclusive_file_lock


class ReplacementCleanupReceiptError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReplacementCleanupFence:
    """Serialize and durably fence deletion of one predecessor group."""

    storage_dir: Path
    lock_timeout_seconds: float
    lock_poll_interval_seconds: float

    @staticmethod
    def normalize_replaced_group_id(value: object) -> str:
        normalized = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
        if not normalized:
            raise ValueError("replacement_cleanup_missing_replaced_group_id")
        return normalized

    @contextmanager
    def operation(self, replaced_group_id: object) -> Iterator[str]:
        normalized_id = self.normalize_replaced_group_id(replaced_group_id)
        digest = self._digest(normalized_id)
        lock_path = (
            self.storage_dir
            / "locks"
            / "replacement-cleanup-operations"
            / f"{digest}.lock"
        )
        with exclusive_file_lock(
            lock_path,
            timeout_seconds=self.lock_timeout_seconds,
            poll_interval_seconds=self.lock_poll_interval_seconds,
        ):
            yield normalized_id

    def has_deletion_receipt(self, normalized_replaced_group_id: str) -> bool:
        receipt_path = self._receipt_path(normalized_replaced_group_id)
        if not receipt_path.exists():
            return False
        try:
            payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise ReplacementCleanupReceiptError(
                f"replacement_cleanup_receipt_unreadable:{normalized_replaced_group_id}"
            ) from exc
        if not isinstance(payload, dict) or (
            payload.get("normalized_replaced_group_id") != normalized_replaced_group_id
        ):
            raise ReplacementCleanupReceiptError(
                f"replacement_cleanup_receipt_mismatch:{normalized_replaced_group_id}"
            )
        return True

    def record_deletion(self, normalized_replaced_group_id: str) -> None:
        receipt_path = self._receipt_path(normalized_replaced_group_id)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        digest_prefix = self._digest(normalized_replaced_group_id)[:8]
        tmp_path = receipt_path.parent / (
            f".{digest_prefix}.{os.getpid():x}.{threading.get_ident():x}."
            f"{uuid.uuid4().hex[:8]}.tmp"
        )
        try:
            tmp_path.write_text(
                json.dumps(
                    {
                        "normalized_replaced_group_id": normalized_replaced_group_id,
                        "deleted_at": datetime.now(UTC).isoformat(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            tmp_path.replace(receipt_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _receipt_path(self, normalized_replaced_group_id: str) -> Path:
        return (
            self.storage_dir
            / "rc"
            / f"{self._digest(normalized_replaced_group_id)[:32]}.json"
        )

    @staticmethod
    def _digest(normalized_replaced_group_id: str) -> str:
        return hashlib.sha256(normalized_replaced_group_id.encode("utf-8")).hexdigest()
