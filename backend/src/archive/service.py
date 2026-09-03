from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from ..config import load_mechanism_spec
from ..doc_gen.derivation import DerivationEngine
from ..models import DocContext, GlobalDocParams, Job, TaskGroup, normalize_global_doc_params
from ..pipeline.group_manager import GroupManager
from ..pipeline.job_manager import JobManager
from ..pipeline.shared_prep import SharedPrepService
from ..workflow.models import WorkflowStatus
from .admin_config_store import AdminConfigStore
from .identity import build_archive_identity
from .models import ArchiveState, ArchiveStatus
from ..task_groups.job_submission_source import is_job_submission, job_source_files, read_job_submission
from ..task_groups.submission_readiness import _artifact_is_required, _is_file


class ArchiveService:
    def __init__(
        self,
        *,
        group_manager: GroupManager,
        job_manager: JobManager,
        shared_prep_service: SharedPrepService,
        admin_config_store: AdminConfigStore,
    ) -> None:
        self.group_manager = group_manager
        self.job_manager = job_manager
        self.shared_prep_service = shared_prep_service
        self.admin_config_store = admin_config_store
        self.derivation_engine = DerivationEngine()
        self.submission_config = load_mechanism_spec().task_group_submission

    def archive_group(self, group: TaskGroup) -> TaskGroup:
        archive_root = self.admin_config_store.get_archive_root_path()
        if archive_root is None:
            raise ValueError("archive_root_path is not configured")
        if not group.child_job_ids:
            raise ValueError("group has no child jobs")

        children = []
        for job_id in group.child_job_ids:
            child = self.job_manager.reload_job(job_id)
            if child is None:
                raise ValueError(f"task_group_child_not_found:job={job_id}")
            children.append(child)
        artifacts = self._checked_artifacts(children)
        shared_dir = group.shared_dir or self.group_manager.config.get_group_dir(group.group_id) / "shared"
        primary_job = children[0]

        if is_job_submission(group):
            _, identity = read_job_submission(primary_job)
            sources = job_source_files(primary_job)
        else:
            prep = self.shared_prep_service.load(shared_dir)
            params = GlobalDocParams.model_validate(normalize_global_doc_params(primary_job.params))
            ctx = DocContext(params=params, frames=prep.frames, sheet_sets=prep.sheet_sets)
            derived = self.derivation_engine.compute(ctx)
            identity = build_archive_identity(
                params,
                album_internal_code=derived.album_internal_code,
                document_revision=derived.document_revision,
            )
            sources = [prep.source_input_dwg] if prep.source_input_dwg.exists() else []
        target_dir = identity.target_dir(archive_root)
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        target_dir.mkdir(parents=True, exist_ok=True)

        copied_files = []
        for artifact in artifacts:
            # Do not silently skip a file removed after preflight. copy2 must
            # fail so the coordinator leaves workload unsettled and retryable.
            copied = shutil.copy2(artifact, target_dir / artifact.name)
            copied_files.append(Path(copied))
        for source in sources:
            copied = shutil.copy2(source, target_dir / source.name)
            copied_files.append(Path(copied))

        group.archive = ArchiveState(
            archive_root_path=str(archive_root),
            target_dir=target_dir,
            status=ArchiveStatus.SUCCEEDED,
            completed_at=group.archive.completed_at or datetime.now(),
            last_error=None,
            retry_count=group.archive.retry_count,
            archived_files=[str(path) for path in copied_files],
        )
        group.workflow.status = WorkflowStatus.ARCHIVED
        group.workflow.archive_status = "succeeded"
        return group

    def _checked_artifacts(self, children: list[Job]) -> list[Path]:
        """Recheck submission artifact rules before touching an archive target."""
        required_paths: set[Path] = set()
        for requirement in self.submission_config.required_task_roles:
            matching = [child for child in children if child.task_role == requirement.task_role]
            if not matching:
                raise ValueError(f"{requirement.missing_role_error}:role={requirement.task_role}")
            if len(matching) != 1:
                raise ValueError(f"{requirement.duplicate_role_error}:role={requirement.task_role}")
            child = matching[0]
            for artifact_rule in requirement.artifacts:
                if not _artifact_is_required(child, artifact_rule.required_when):
                    continue
                artifact = getattr(child.artifacts, artifact_rule.field)
                context = f"job={child.job_id}:artifact={artifact_rule.field}"
                if artifact is None:
                    raise ValueError(f"{artifact_rule.not_declared_error}:{context}")
                if not _is_file(artifact):
                    raise ValueError(f"{artifact_rule.not_found_error}:{context}:path={artifact}")
                required_paths.add(artifact)
        return [
            artifact
            for child in children
            for artifact in (child.artifacts.package_zip, child.artifacts.ied_xlsx)
            if artifact is not None and (artifact in required_paths or _is_file(artifact))
        ]

    def mark_failed(self, group: TaskGroup, error: str) -> TaskGroup:
        group.archive.status = ArchiveStatus.FAILED
        group.archive.last_error = error
        group.archive.retry_count += 1
        group.workflow.status = WorkflowStatus.ARCHIVE_FAILED
        group.workflow.archive_status = "failed"
        return group
