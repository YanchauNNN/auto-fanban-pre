from __future__ import annotations

from ..config import MechanismSpec, load_mechanism_spec
from ..models import AccountSnapshot, TaskGroup


class WorkflowVisibility:
    def __init__(self, mechanism_spec: MechanismSpec | None = None) -> None:
        self.mechanism_spec = mechanism_spec or load_mechanism_spec()
        self.admin_roles = set(self.mechanism_spec.permissions.workflow_admin_roles)

    def can_view(self, group: TaskGroup, account: AccountSnapshot) -> bool:
        if account.role in self.admin_roles:
            return True
        if group.owner_snapshot and group.owner_snapshot.creator_account == account.account_id:
            return True
        return any(node.assignee_account == account.account_id for node in group.workflow.nodes)
