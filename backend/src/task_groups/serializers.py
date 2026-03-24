from __future__ import annotations

from ..models import TaskGroup


class TaskGroupSerializers:
    @staticmethod
    def summarize(group: TaskGroup) -> dict[str, object]:
        return {
            "group_id": group.group_id,
            "batch_id": group.batch_id,
            "project_no": group.project_no,
            "status": group.status.value,
            "created_at": group.created_at.isoformat(),
            "source_filenames": list(group.source_filenames),
            "owner_snapshot": group.owner_snapshot.model_dump(mode="json") if group.owner_snapshot else None,
            "workflow_status": group.workflow.status.value,
            "current_node_key": group.workflow.current_node_key,
            "archive_status": group.archive.status.value,
            "workload": group.workload.model_dump(mode="json"),
        }

    @staticmethod
    def detail(group: TaskGroup) -> dict[str, object]:
        payload = TaskGroupSerializers.summarize(group)
        payload.update(
            {
                "child_job_ids": list(group.child_job_ids),
                "personnel_snapshot": group.personnel_snapshot.model_dump(mode="json"),
                "workflow": group.workflow.model_dump(mode="json"),
                "archive": group.archive.model_dump(mode="json"),
                "replacement": group.replacement.model_dump(mode="json"),
                "legacy_visibility": group.legacy_visibility.model_dump(mode="json"),
            }
        )
        return payload
