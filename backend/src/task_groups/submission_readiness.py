from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import MechanismSpec, load_mechanism_spec
from ..config.mechanism_spec import TaskGroupSubmissionConditionConfig
from ..models import Job, JobStatus, TaskGroup
from ..pipeline.group_manager import GroupManager
from ..pipeline.job_manager import JobManager
from ..pipeline.shared_prep import SharedPrepService
from ..workflow.models import WorkflowStatus
from .job_submission_source import SOURCE_JOB_KEY, is_job_submission, job_source_files, read_job_submission


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

    def __init__(
        self,
        *,
        group_manager: GroupManager,
        job_manager: JobManager,
        shared_prep_service: SharedPrepService,
        mechanism_spec: MechanismSpec | None = None,
    ) -> None:
        self.group_manager = group_manager
        self.job_manager = job_manager
        self.shared_prep_service = shared_prep_service
        self.config = (mechanism_spec or load_mechanism_spec()).task_group_submission

    def inspect(self, group: TaskGroup) -> TaskGroupSubmissionReadiness:
        errors: list[str] = []

        if group.workflow.status is not WorkflowStatus.DRAFT:
            errors.append("workflow_not_draft")
        if group.status is not JobStatus.SUCCEEDED:
            errors.append("task_group_not_succeeded")
        if errors:
            return TaskGroupSubmissionReadiness(tuple(errors))

        if not group.child_job_ids:
            errors.append("task_group_children_missing")
            return TaskGroupSubmissionReadiness(tuple(errors))

        children = []
        for child_job_id in group.child_job_ids:
            child = self.job_manager.reload_job(child_job_id)
            if child is None:
                errors.append("task_group_child_not_found")
                continue
            children.append(child)
            if child.status is not JobStatus.SUCCEEDED:
                errors.append("task_group_child_not_succeeded")

        if is_job_submission(group):
            source = next((child for child in children if child.job_id == group.metadata[SOURCE_JOB_KEY]), None)
            if source is None or len(children) != 1:
                errors.append("workload_source_invalid")
            else:
                try:
                    read_job_submission(source)
                    job_source_files(source)
                except ValueError as exc:
                    errors.append(str(exc))
        else:
            errors.extend(self._inspect_shared_prep(group))

        for role_requirement in self.config.required_task_roles:
            matching_children = [
                item for item in children if item.task_role == role_requirement.task_role
            ]
            if not matching_children:
                errors.append(role_requirement.missing_role_error)
                continue
            if len(matching_children) > 1:
                errors.append(role_requirement.duplicate_role_error)
                continue
            child = matching_children[0]
            for artifact_requirement in role_requirement.artifacts:
                if not _artifact_is_required(child, artifact_requirement.required_when):
                    continue
                artifact = getattr(child.artifacts, artifact_requirement.field)
                if artifact is None:
                    errors.append(artifact_requirement.not_declared_error)
                elif not _is_file(artifact):
                    errors.append(artifact_requirement.not_found_error)

        return TaskGroupSubmissionReadiness(tuple(dict.fromkeys(errors)))

    def ensure_ready(self, group: TaskGroup) -> TaskGroupSubmissionReadiness:
        result = self.inspect(group)
        if not result.is_ready:
            raise ValueError(result.primary_error)
        return result

    def _inspect_shared_prep(self, group: TaskGroup) -> list[str]:
        config = self.config.shared_prep
        shared_dir = (
            group.shared_dir
            or self.group_manager.config.get_group_dir(group.group_id) / "shared"
        ).resolve()
        try:
            prep = self.shared_prep_service.load(shared_dir)
        except (OSError, TypeError, ValueError):
            return [config.invalid_error]

        source_path = prep.source_input_dwg
        if not source_path.is_absolute():
            source_path = shared_dir / source_path
        try:
            source_path = source_path.resolve()
        except OSError:
            return [config.source_missing_error]
        try:
            source_path.relative_to(shared_dir)
        except ValueError:
            return [config.source_outside_error]
        if not _is_file(source_path):
            return [config.source_missing_error]
        return []


def _artifact_is_required(
    child: Job,
    condition: TaskGroupSubmissionConditionConfig | None,
) -> bool:
    if condition is None:
        return True
    source = child.params if condition.source == "params" else child.options
    raw_value = source.get(condition.field, condition.default)
    return _coerce_bool(raw_value) == condition.equals


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False
