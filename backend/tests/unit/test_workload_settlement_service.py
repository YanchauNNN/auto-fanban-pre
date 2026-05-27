from __future__ import annotations

from datetime import datetime

import yaml

from src.models import TaskGroup, TaskOwnerSnapshot
from src.workflow.models import WorkflowNodeState, WorkflowNodeStatus
from src.workload.models import WorkloadSummary
from src.workload.settlement_service import WorkloadSettlementService


def test_workload_settlement_reads_contributor_policy_from_mechanism_yaml(tmp_path, monkeypatch) -> None:
    mechanism_spec = tmp_path / "documents" / "参数规范-3.yaml"
    mechanism_spec.parent.mkdir(parents=True, exist_ok=True)
    mechanism_spec.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "backend_mechanism": {
                    "workload_settlement": {
                        "include_initiator": False,
                        "include_approved_nodes": True,
                        "node_role_key_source": "node_label",
                    },
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FANBAN_MECHANISM_SPEC_PATH", str(mechanism_spec))
    approved_at = datetime(2026, 5, 26, 10, 0, 0)
    group = TaskGroup(group_id="group-1", project_no="2016")
    group.owner_snapshot = TaskOwnerSnapshot(
        creator_account="creator",
        creator_name="创建人",
        creator_role="设计人员",
        creator_office="结构一室",
    )
    group.archive.completed_at = datetime(2026, 5, 26, 11, 0, 0)
    group.workflow.nodes = [
        WorkflowNodeState(
            node_key="one_review",
            node_label="一审",
            assignee_account="checker",
            assignee_name="校核人",
            status=WorkflowNodeStatus.APPROVED,
            approved_at=approved_at,
        )
    ]
    group.workload = WorkloadSummary(initial_workload_a1=2.0, final_workload_a1=2.0)

    WorkloadSettlementService().settle(group)

    assert [entry.role_key for entry in group.workload.contributor_entries] == ["一审"]
