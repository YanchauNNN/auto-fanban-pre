from __future__ import annotations

from ..config import BusinessSpec, load_spec
from ..models import PersonnelSnapshot
from .models import WorkflowNodeState, WorkflowNodeStatus


class WorkflowAssigneeResolver:
    def __init__(self, spec: BusinessSpec | None = None) -> None:
        self.spec = spec or load_spec()
        self.workflow_cfg = dict(self.spec.get_management_features().get("workflow") or {})

    def build_nodes(self, personnel_snapshot: PersonnelSnapshot) -> list[WorkflowNodeState]:
        nodes: list[WorkflowNodeState] = []
        for index, node_cfg in enumerate(self.workflow_cfg.get('nodes') or []):
            assignee_field = str(node_cfg.get('assignee_source') or '')
            personnel = personnel_snapshot.members.get(assignee_field)
            nodes.append(
                WorkflowNodeState(
                    node_key=str(node_cfg.get('key') or ''),
                    node_label=str(node_cfg.get('label') or ''),
                    assignee_account=personnel.matched_account if personnel else None,
                    assignee_name=personnel.matched_name if personnel else None,
                    status=WorkflowNodeStatus.CURRENT if index == 0 else WorkflowNodeStatus.PENDING,
                    factor=float((self.workflow_cfg.get('factor') or {}).get('default') or 1.0),
                )
            )
        return nodes
