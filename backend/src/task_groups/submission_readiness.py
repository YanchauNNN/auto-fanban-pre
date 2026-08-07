from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..models import JobStatus, TaskGroup
from ..pipeline.job_manager import JobManager
from ..workflow.models import WorkflowStatus


@dataclass(frozen=True, slots=True)
class TaskGroupSubmissionReadiness:
    error_codes: tuple[str, ...] = ()

    @property
    def is_ready(self) -> bool:
        return not self.error_codes

    @property
    def primary_error(self) -> str | None:
        return self.error_codes[0] if self.error_codes else None


class TaskGroupSubmissionReadinessPolicy:
    """Read-only readiness checks shared by submission and UI permissions."""

    def __init__(self, job_manager: JobManager) -> None:
        self.job_manager = job_manager

    def inspect(self, group: TaskGroup) -> TaskGroupSubmissionReadiness:
        errors: list[str] = []

        if group.workflow.status is not WorkflowStatus.DRAFT:
            errors.append("workflow_not_draft")
        if group.status is not JobStatus.SUCCEEDED:
            errors.append("task_group_not_succeeded")

        if not group.child_job_ids:
            errors.append("task_group_children_missing")
            return TaskGroupSubmissionReadiness(tuple(errors))

        children = []
        for child_job_id in group.child_job_ids:
            child = self.job_manager.get_job(child_job_id)
            if child is None:
                errors.append("task_group_child_not_found")
                continue
            children.append(child)
            if child.status is not JobStatus.SUCCEEDED:
                errors.append("task_group_child_not_succeeded")

        deliverable = next((child for child in children if child.task_role == "deliverable_main"), None)
        if deliverable is None:
            errors.append("deliverable_main_missing")
        elif deliverable.artifacts.package_zip is None:
            errors.append("deliverable_package_not_declared")
        elif not _is_file(deliverable.artifacts.package_zip):
            errors.append("deliverable_package_not_found")

        return TaskGroupSubmissionReadiness(tuple(dict.fromkeys(errors)))

    def ensure_ready(self, group: TaskGroup) -> TaskGroupSubmissionReadiness:
        result = self.inspect(group)
        if not result.is_ready:
            raise ValueError(result.primary_error)
        return result


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False
