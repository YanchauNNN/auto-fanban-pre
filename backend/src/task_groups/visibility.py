from __future__ import annotations

from ..config import BusinessSpec, load_spec
from ..models import AccountSnapshot, TaskGroup


class TaskGroupVisibility:
    def __init__(self, spec: BusinessSpec | None = None) -> None:
        self.spec = spec or load_spec()
        visibility_cfg = dict(self.spec.get_management_features().get("task_visibility") or {})
        self.role_scopes = {str(k): str(v) for k, v in dict(visibility_cfg.get("roles") or {}).items()}
        self.legacy_default_scope = str(visibility_cfg.get("legacy_default_scope") or "admin_only")

    def can_view(self, group: TaskGroup, account: AccountSnapshot) -> bool:
        role_scope = self.role_scopes.get(account.role, "self_only")
        if role_scope == "all":
            return True
        if group.owner_snapshot is None:
            legacy_scope = str(group.legacy_visibility.scope or self.legacy_default_scope)
            return legacy_scope == "all"
        if role_scope == "office_only":
            return account.office_name == group.owner_snapshot.creator_office
        return account.account_id == group.owner_snapshot.creator_account
