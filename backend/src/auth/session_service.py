from __future__ import annotations

import json
import secrets
from datetime import datetime

from pydantic import BaseModel, Field

from ..accounts.account_registry import AccountRegistry
from ..config import get_config
from ..models import AccountSnapshot


class SessionRecord(BaseModel):
    token: str
    account_id: str
    created_at: datetime = Field(default_factory=datetime.now)
    last_seen_at: datetime = Field(default_factory=datetime.now)


class SessionService:
    def __init__(self, registry: AccountRegistry) -> None:
        self.registry = registry
        self.config = get_config()
        self.path = self.config.management.session_store_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text('{"sessions": []}', encoding='utf-8')

    def create_session(self, account: AccountSnapshot | str) -> SessionRecord:
        account_id = account.account_id if isinstance(account, AccountSnapshot) else str(account)
        session = SessionRecord(token=secrets.token_urlsafe(32), account_id=account_id)
        sessions = [item for item in self._load_sessions() if item.account_id != account_id]
        sessions.append(session)
        self._save_sessions(sessions)
        return session

    def delete_session(self, authorization: str | None) -> None:
        token = self.extract_bearer_token(authorization) or str(authorization or "").strip()
        if not token:
            return
        sessions = [item for item in self._load_sessions() if item.token != token]
        self._save_sessions(sessions)

    def resolve_account(self, authorization: str | None) -> AccountSnapshot | None:
        token = self.extract_bearer_token(authorization)
        if not token:
            return None
        sessions = self._load_sessions()
        for session in sessions:
            if session.token != token:
                continue
            session.last_seen_at = datetime.now()
            self._save_sessions(sessions)
            account = self.registry.get_account(session.account_id)
            if account is None:
                return None
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
        payload = json.loads(self.path.read_text(encoding='utf-8'))
        return [SessionRecord.model_validate(item) for item in payload.get('sessions', [])]

    def _save_sessions(self, sessions: list[SessionRecord]) -> None:
        payload = {'sessions': [session.model_dump(mode='json') for session in sessions]}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
