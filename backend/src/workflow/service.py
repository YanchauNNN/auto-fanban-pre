from __future__ import annotations

from datetime import datetime
import math

from ..config import BusinessSpec, load_mechanism_spec, load_spec
from ..models import AccountSnapshot, TaskGroup, TaskOwnerSnapshot
from .assignee_resolver import WorkflowAssigneeResolver
from .models import WorkflowNodeStatus, WorkflowState, WorkflowStatus


class WorkflowService:
    def __init__(self, resolver: WorkflowAssigneeResolver | None = None, spec: BusinessSpec | None = None) -> None:
        self.spec = spec or load_spec()
        self.workflow_cfg = dict(self.spec.get_management_features().get("workflow") or {})
        self.workflow_runtime_cfg = load_mechanism_spec().workflow_runtime
        self.resolver = resolver or WorkflowAssigneeResolver(self.spec)

    def start(self, group: TaskGroup, initiator: AccountSnapshot) -> TaskGroup:
        nodes = self.resolver.build_nodes(group.personnel_snapshot)
        existing_duplicate_policy = group.workflow.duplicate_policy
        existing_overwrite_target = group.workflow.overwrite_archive_target
        group.owner_snapshot = TaskOwnerSnapshot(
            creator_account=initiator.account_id,
            creator_name=initiator.display_name,
            creator_role=initiator.role,
            creator_office=initiator.office_name,
            created_by_scope=str((self.workflow_cfg.get('submit_rule') or {})['initiator_binding']),
            submitted_at=datetime.now(),
        )
        group.workflow = WorkflowState(
            status=WorkflowStatus.IN_REVIEW,
            initiated_at=datetime.now(),
            initiated_by_account=initiator.account_id,
            initiated_by_name=initiator.display_name,
            duplicate_policy=existing_duplicate_policy,
            overwrite_archive_target=existing_overwrite_target,
            current_node_key=nodes[0].node_key if nodes else None,
            nodes=nodes,
        )
        return group

    def approve(
        self,
        group: TaskGroup,
        acting_account: AccountSnapshot,
        factor: float,
        *,
        node_key: str | None = None,
    ) -> TaskGroup:
        current = self.current_node(group)
        if current is None:
            raise ValueError('no current workflow node')
        current_index = group.workflow.nodes.index(current)
        if node_key is not None and current.node_key != node_key:
            raise ValueError('node_key_mismatch')
        if current.assignee_account != acting_account.account_id:
            raise ValueError('only current assignee can approve')
        factor_cfg = dict(self.workflow_cfg.get('factor') or {})
        min_factor = float(factor_cfg['min'])
        max_factor = float(factor_cfg['max'])
        precision = int(factor_cfg['precision'])
        if not math.isfinite(factor) or factor < min_factor or factor > max_factor:
            raise ValueError('factor out of range')
        current.status = WorkflowNodeStatus.APPROVED
        current.factor = round(float(factor), precision)
        current.approved_at = datetime.now()
        current.acted_by_account = acting_account.account_id
        current.acted_by_name = acting_account.display_name
        next_node = self._next_pending_node(group, current_index)
        if next_node is None:
            group.workflow.current_node_key = None
            group.workflow.status = _workflow_status(self.workflow_runtime_cfg.approval_terminal_status)
            return group
        next_node.status = WorkflowNodeStatus.CURRENT
        group.workflow.current_node_key = next_node.node_key
        group.workflow.status = WorkflowStatus.IN_REVIEW
        return group

    def repair_current_node(self, group: TaskGroup, assignee: AccountSnapshot) -> TaskGroup:
        current = self.current_node(group)
        if current is None:
            raise ValueError('no current workflow node')
        current.assignee_account = assignee.account_id
        current.assignee_name = assignee.display_name
        return group

    @staticmethod
    def current_node(group: TaskGroup):
        for node in group.workflow.nodes:
            if node.status == WorkflowNodeStatus.CURRENT:
                return node
        return None

    @staticmethod
    def _next_pending_node(group: TaskGroup, current_index: int):
        for node in group.workflow.nodes[current_index + 1 :]:
            if node.status == WorkflowNodeStatus.PENDING:
                return node
        return None


def _workflow_status(value: str) -> WorkflowStatus:
    try:
        return WorkflowStatus(str(value))
    except ValueError:
        raise ValueError(f"invalid workflow terminal status: {value}") from None
