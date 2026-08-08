from __future__ import annotations

import json
import os
import secrets
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from ..accounts.account_registry import AccountRegistry
from ..config import get_config
from ..models import AccountSnapshot

_SESSION_LOCKS_GUARD = threading.Lock()
_SESSION_LOCKS: dict[Path, threading.RLock] = {}


def _session_lock_for(path: Path) -> threading.RLock:
    normalized_path = path.resolve()
    with _SESSION_LOCKS_GUARD:
        lock = _SESSION_LOCKS.get(normalized_path)
        if lock is None:
            lock = threading.RLock()
            _SESSION_LOCKS[normalized_path] = lock
        return lock


class SessionRecord(BaseModel):
    token: str
    account_id: str
    created_at: datetime = Field(default_factory=datetime.now)
    last_seen_at: datetime = Field(default_factory=datetime.now)


class SessionService:
    """Persist sessions for the deployment's single API writer process.

    All service instances in that process share a path lock. Atomic replacement also
    keeps readers in other processes from observing partial JSON, but multiple writer
    processes would still require an inter-process transaction lock.
    """

    def __init__(self, registry: AccountRegistry) -> None:
        self.registry = registry
        self.config = get_config()
        self.path = self.config.management.session_store_path
        self._lock = _session_lock_for(self.path)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                self._save_sessions([])

    def create_session(self, account: AccountSnapshot | str) -> SessionRecord:
        account_id = account.account_id if isinstance(account, AccountSnapshot) else str(account)
        session = SessionRecord(token=secrets.token_urlsafe(32), account_id=account_id)
        with self._lock:
            sessions = [item for item in self._load_sessions() if item.account_id != account_id]
            sessions.append(session)
            self._save_sessions(sessions)
        return session

    def delete_session(self, authorization: str | None) -> None:
        token = self.extract_bearer_token(authorization) or str(authorization or "").strip()
        if not token:
            return
        with self._lock:
            sessions = [item for item in self._load_sessions() if item.token != token]
            self._save_sessions(sessions)

    def resolve_account(self, authorization: str | None) -> AccountSnapshot | None:
        token = self.extract_bearer_token(authorization)
        if not token:
            return None
        account_id: str | None = None
        with self._lock:
            sessions = self._load_sessions()
            for session in sessions:
                if session.token != token:
                    continue
                session.last_seen_at = datetime.now()
                self._save_sessions(sessions)
                account_id = session.account_id
                break
        if account_id is not None:
            account = self.registry.get_account(account_id)
            if account is not None:
                return account.to_snapshot()
        return None

    @staticmethod
    def extract_bearer_token(authorization: str | None) -> str | None:
        text = str(authorization or '').strip()
        prefix = 'Bearer '
        if text.startswith(prefix):
            return text[len(prefix):].strip() or None
        return None

    def _load_sessions(self) -> list[SessionRecord]:
        with self._lock:
            payload = json.loads(self.path.read_text(encoding='utf-8'))
            return [SessionRecord.model_validate(item) for item in payload.get('sessions', [])]

    def _save_sessions(self, sessions: list[SessionRecord]) -> None:
        with self._lock:
            payload = {'sessions': [session.model_dump(mode='json') for session in sessions]}
            serialized = json.dumps(payload, ensure_ascii=False, indent=2)
            descriptor, temporary_name = tempfile.mkstemp(
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
            )
            temporary_path = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(serialized)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_path, self.path)
            finally:
                temporary_path.unlink(missing_ok=True)
