from __future__ import annotations

from ..accounts.account_models import AccountRecord
from ..accounts.account_registry import AccountRegistry


class PasswordService:
    def __init__(self, registry: AccountRegistry) -> None:
        self.registry = registry

    def change_password(self, account_id: str, new_password: str) -> AccountRecord:
        if not str(new_password or '').strip():
            raise ValueError('new_password is required')
        return self.registry.set_password(account_id, new_password)
