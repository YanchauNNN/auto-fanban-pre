from __future__ import annotations

from ..models import TaskGroup
from .calculator import WorkloadCalculator
from .models import WorkloadContributorEntry, WorkloadSettlementStatus


class WorkloadSettlementService:
    def __init__(self, calculator: WorkloadCalculator | None = None) -> None:
        self.calculator = calculator or WorkloadCalculator()

    def settle(self, group: TaskGroup) -> TaskGroup:
        summary = self.calculator.refresh_final(group.workload)
        summary.contributor_entries = []
        if group.owner_snapshot is not None and group.archive.completed_at is not None:
            summary.contributor_entries.append(
                WorkloadContributorEntry(
                    role_key='initiator',
                    account_id=group.owner_snapshot.creator_account,
                    display_name=group.owner_snapshot.creator_name,
                    workload_a1=summary.final_workload_a1,
                    settled_at=group.archive.completed_at,
                )
            )
        for node in group.workflow.nodes:
            if node.approved_at is None:
                continue
            summary.contributor_entries.append(
                WorkloadContributorEntry(
                    role_key=node.node_key,
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
