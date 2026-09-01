from __future__ import annotations

from ..models import TaskGroup
from .display_name import build_task_group_display_fields


class TaskGroupSerializers:
    @staticmethod
    def summarize(
        group: TaskGroup,
        *,
        can_view_detail: bool,
        can_submit: bool,
        can_approve: bool,
        is_related_to_current_user: bool,
    ) -> dict[str, object]:
        effective_workload = float(group.workload.final_workload_a1 or group.workload.initial_workload_a1 or 0.0)
        owner = group.owner_snapshot.model_dump(mode="json") if group.owner_snapshot else None
        display_fields = build_task_group_display_fields(group)
        return {
            "group_id": group.group_id,
            **display_fields,
            "batch_id": group.batch_id,
            "project_no": group.project_no,
            "status": group.status.value,
            "created_at": group.created_at.isoformat(),
            "source_filenames": list(group.source_filenames),
            "owner_snapshot": owner,
            "creator_name": group.owner_snapshot.creator_name if group.owner_snapshot else None,
            "creator_account": group.owner_snapshot.creator_account if group.owner_snapshot else None,
            "creator_office": group.owner_snapshot.creator_office if group.owner_snapshot else None,
            "workflow_status": group.workflow.status.value,
            "current_node_key": group.workflow.current_node_key,
            "archive_status": group.archive.status.value,
            "workload": group.workload.model_dump(mode="json"),
            "effective_workload": round(effective_workload, 2),
            "can_view_detail": can_view_detail,
            "can_submit": can_submit,
            "can_approve": can_approve,
            "is_related_to_current_user": is_related_to_current_user,
        }

    @staticmethod
    def detail(
        group: TaskGroup,
        *,
        can_view_detail: bool,
        can_submit: bool,
        can_approve: bool,
        is_related_to_current_user: bool,
        submit_blockers: tuple[str, ...] = (),
    ) -> dict[str, object]:
        payload = TaskGroupSerializers.summarize(
            group,
            can_view_detail=can_view_detail,
            can_submit=can_submit,
            can_approve=can_approve,
            is_related_to_current_user=is_related_to_current_user,
        )
        payload.update(
            {
                "child_job_ids": list(group.child_job_ids),
                "personnel_snapshot": group.personnel_snapshot.model_dump(mode="json"),
                "workflow": group.workflow.model_dump(mode="json"),
                "archive": group.archive.model_dump(mode="json"),
                "replacement": group.replacement.model_dump(mode="json"),
                "legacy_visibility": group.legacy_visibility.model_dump(mode="json"),
                "submit_blockers": list(submit_blockers),
            }
        )
        return payload
