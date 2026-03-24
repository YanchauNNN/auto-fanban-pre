from __future__ import annotations

from ..models import AccountSnapshot, TaskGroup


class TaskGroupVisibility:
    def can_view(self, group: TaskGroup, account: AccountSnapshot) -> bool:
        if account.role == "管理员":
            return True
        if group.owner_snapshot is None:
            return group.legacy_visibility.scope != "admin_only"
        if account.role == "所领导":
            return True
        if account.role == "室主任":
            return account.office_name == group.owner_snapshot.creator_office
        return account.account_id == group.owner_snapshot.creator_account
