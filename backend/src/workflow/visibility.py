from __future__ import annotations

from ..models import AccountSnapshot, TaskGroup


class WorkflowVisibility:
    def can_view(self, group: TaskGroup, account: AccountSnapshot) -> bool:
        if account.role == '管理员':
            return True
        if group.owner_snapshot and group.owner_snapshot.creator_account == account.account_id:
            return True
        return any(node.assignee_account == account.account_id for node in group.workflow.nodes)
