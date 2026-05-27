from __future__ import annotations

from ..config import MechanismSpec, load_mechanism_spec
from ..models import TaskGroup
from .calculator import WorkloadCalculator
from .models import WorkloadContributorEntry, WorkloadSettlementStatus


class WorkloadSettlementService:
    def __init__(
        self,
        calculator: WorkloadCalculator | None = None,
        mechanism_spec: MechanismSpec | None = None,
    ) -> None:
        self.calculator = calculator or WorkloadCalculator()
        self.mechanism_spec = mechanism_spec or load_mechanism_spec()

    def settle(self, group: TaskGroup) -> TaskGroup:
        summary = self.calculator.refresh_final(group.workload)
        policy = self.mechanism_spec.workload_settlement
        summary.contributor_entries = []
        if (
            policy.include_initiator
            and group.owner_snapshot is not None
            and group.archive.completed_at is not None
        ):
            summary.contributor_entries.append(
                WorkloadContributorEntry(
                    role_key=policy.initiator_role_key,
                    account_id=group.owner_snapshot.creator_account,
                    display_name=group.owner_snapshot.creator_name,
                    workload_a1=summary.final_workload_a1,
                    settled_at=group.archive.completed_at,
                )
            )
        if not policy.include_approved_nodes:
            summary.settlement_status = WorkloadSettlementStatus.SETTLED
            summary.settled_at = group.archive.completed_at
            group.workload = summary
            return group
        for node in group.workflow.nodes:
            if node.approved_at is None:
                continue
            summary.contributor_entries.append(
                WorkloadContributorEntry(
                    role_key=_node_role_key(node, policy.node_role_key_source),
                    account_id=node.acted_by_account or node.assignee_account,
                    display_name=node.acted_by_name or node.assignee_name,
                    workload_a1=summary.final_workload_a1,
                    settled_at=node.approved_at,
                )
            )
        summary.settlement_status = WorkloadSettlementStatus.SETTLED
        summary.settled_at = group.archive.completed_at
        group.workload = summary
        return group


def _node_role_key(node, source: str) -> str:
    if source == "node_label":
        return node.node_label or node.node_key
    return node.node_key
