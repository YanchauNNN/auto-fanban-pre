from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from ..doc_gen.derivation import DerivationEngine
from ..models import DocContext, GlobalDocParams, TaskGroup, normalize_global_doc_params
from ..pipeline.group_manager import GroupManager
from ..pipeline.job_manager import JobManager
from ..pipeline.shared_prep import SharedPrepService
from ..workflow.models import WorkflowStatus
from .admin_config_store import AdminConfigStore
from .identity import build_archive_identity
from .models import ArchiveState, ArchiveStatus
from .overwrite_service import ArchiveOverwriteService


class ArchiveService:
    def __init__(
        self,
        *,
        group_manager: GroupManager,
        job_manager: JobManager,
        shared_prep_service: SharedPrepService,
        admin_config_store: AdminConfigStore,
        overwrite_service: ArchiveOverwriteService | None = None,
    ) -> None:
        self.group_manager = group_manager
        self.job_manager = job_manager
        self.shared_prep_service = shared_prep_service
        self.admin_config_store = admin_config_store
        self.overwrite_service = overwrite_service
        self.derivation_engine = DerivationEngine()

    def archive_group(self, group: TaskGroup) -> TaskGroup:
        archive_root = self.admin_config_store.get_archive_root_path()
        if archive_root is None:
            raise ValueError("archive_root_path is not configured")
        if not group.child_job_ids:
            raise ValueError("group has no child jobs")

        shared_dir = group.shared_dir or self.group_manager.config.get_group_dir(group.group_id) / "shared"
        prep = self.shared_prep_service.load(shared_dir)
        primary_job = self.job_manager.get_job(group.child_job_ids[0])
        if primary_job is None:
            raise ValueError("primary child job not found")

        params = GlobalDocParams.model_validate(normalize_global_doc_params(primary_job.params))
        ctx = DocContext(params=params, frames=prep.frames, sheet_sets=prep.sheet_sets)
        derived = self.derivation_engine.compute(ctx)
        identity = build_archive_identity(
            params,
            album_internal_code=derived.album_internal_code,
            document_revision=derived.document_revision,
        )
        target_dir = identity.target_dir(archive_root)
        if self.overwrite_service is not None:
            self.overwrite_service.clear_target_directory(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        copied_files = []
        for child_job_id in group.child_job_ids:
            job = self.job_manager.get_job(child_job_id)
            if job is None:
                continue
            for artifact in (
                job.artifacts.package_zip,
                job.artifacts.ied_xlsx,
            ):
                if artifact and Path(artifact).exists():
                    copied = shutil.copy2(artifact, target_dir / Path(artifact).name)
                    copied_files.append(Path(copied))
        if prep.source_input_dwg.exists():
            copied = shutil.copy2(prep.source_input_dwg, target_dir / prep.source_input_dwg.name)
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
        if self.overwrite_service is not None:
            self.overwrite_service.cleanup_replaced_group(group)
        self.group_manager.update_group(group)
        return group

    def mark_failed(self, group: TaskGroup, error: str) -> TaskGroup:
        group.archive.status = ArchiveStatus.FAILED
        group.archive.last_error = error
        group.archive.retry_count += 1
        group.workflow.status = WorkflowStatus.ARCHIVE_FAILED
        group.workflow.archive_status = "failed"
        self.group_manager.update_group(group)
        return group
