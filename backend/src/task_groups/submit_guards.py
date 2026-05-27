from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..archive.admin_config_store import AdminConfigStore
from ..archive.identity import build_archive_identity
from ..archive.overwrite_service import ArchiveOverwriteService
from ..config import BusinessSpec, load_spec
from ..doc_gen.derivation import DerivationEngine
from ..models import DocContext, GlobalDocParams, TaskGroup, normalize_global_doc_params
from ..pipeline.group_manager import GroupManager
from ..pipeline.job_manager import JobManager
from ..pipeline.shared_prep import SharedPrepService
from ..workflow.models import WorkflowStatus


@dataclass(frozen=True, slots=True)
class TaskGroupAlbumIdentity:
    engineering_no: str
    subitem_no: str
    album_internal_code: str
    revision: str
    archive_target: Path | None


@dataclass(frozen=True, slots=True)
class TaskGroupSubmitConflicts:
    identity: TaskGroupAlbumIdentity
    archive_target_exists: bool
    archived_group_id: str | None
    in_progress_group_id: str | None


class TaskGroupSubmitGuards:
    _ACTIVE_WORKFLOW_STATUSES = {
        WorkflowStatus.SUBMITTED,
        WorkflowStatus.IN_REVIEW,
        WorkflowStatus.THREE_REVIEW_APPROVED,
        WorkflowStatus.ARCHIVING,
        WorkflowStatus.ARCHIVE_FAILED,
    }

    def __init__(
        self,
        *,
        group_manager: GroupManager,
        job_manager: JobManager,
        shared_prep_service: SharedPrepService,
        admin_config_store: AdminConfigStore,
        overwrite_service: ArchiveOverwriteService,
        spec: BusinessSpec | None = None,
    ) -> None:
        self.group_manager = group_manager
        self.job_manager = job_manager
        self.shared_prep_service = shared_prep_service
        self.admin_config_store = admin_config_store
        self.overwrite_service = overwrite_service
        self.spec = spec or load_spec()
        self.archive_cfg = dict(self.spec.get_management_features().get("archive") or {})
        self.derivation_engine = DerivationEngine()

    def ensure_submit_allowed(
        self,
        group: TaskGroup,
        *,
        overwrite_archive_existing: bool,
        cancel_existing_in_progress: bool,
    ) -> None:
        conflicts = self.inspect(group)
        duplicate_policy_parts: list[str] = []

        if conflicts.in_progress_group_id:
            if not cancel_existing_in_progress:
                raise ValueError("duplicate_in_progress_exists")
            self.overwrite_service.delete_group_records_by_id(conflicts.in_progress_group_id)
            duplicate_policy_parts.append("cancel_existing_in_progress")

        if conflicts.archive_target_exists:
            if not overwrite_archive_existing:
                raise ValueError("archive_target_exists")
            duplicate_policy_parts.append("overwrite_archive_existing")
            group.replacement.album_internal_code = conflicts.identity.album_internal_code
            group.replacement.revision = conflicts.identity.revision
            group.replacement.replaced_group_id = conflicts.archived_group_id
            group.replacement.replaced_record_pending_delete = conflicts.archived_group_id is not None
            group.archive.overwrite_mode = str(self.archive_cfg.get("overwrite_mode") or "").strip() or None
            group.workflow.overwrite_archive_target = (
                str(conflicts.identity.archive_target) if conflicts.identity.archive_target is not None else None
            )

        group.workflow.duplicate_policy = "+".join(duplicate_policy_parts) if duplicate_policy_parts else None

    def inspect(self, group: TaskGroup) -> TaskGroupSubmitConflicts:
        identity = self._build_identity(group)
        archived_group_id: str | None = None
        in_progress_group_id: str | None = None

        for other in self.group_manager.load_all_groups():
            if other.group_id == group.group_id:
                continue
            try:
                other_identity = self._build_identity(other)
            except Exception:  # noqa: BLE001
                continue
            if other_identity != identity:
                continue
            if other.workflow.status == WorkflowStatus.ARCHIVED or str(other.archive.status.value) == "succeeded":
                archived_group_id = archived_group_id or other.group_id
                continue
            if other.workflow.status in self._ACTIVE_WORKFLOW_STATUSES:
                in_progress_group_id = in_progress_group_id or other.group_id

        archive_target_exists = bool(identity.archive_target and identity.archive_target.exists())
        return TaskGroupSubmitConflicts(
            identity=identity,
            archive_target_exists=archive_target_exists,
            archived_group_id=archived_group_id,
            in_progress_group_id=in_progress_group_id,
        )

    def _build_identity(self, group: TaskGroup) -> TaskGroupAlbumIdentity:
        if not group.child_job_ids:
            raise ValueError("group has no child jobs")
        primary_job = self.job_manager.get_job(group.child_job_ids[0])
        if primary_job is None:
            raise ValueError("primary child job not found")

        shared_dir = group.shared_dir or self.group_manager.config.get_group_dir(group.group_id) / "shared"
        prep = self.shared_prep_service.load(shared_dir)
        params = GlobalDocParams.model_validate(normalize_global_doc_params(primary_job.params))
        ctx = DocContext(params=params, frames=prep.frames, sheet_sets=prep.sheet_sets)
        derived = self.derivation_engine.compute(ctx)

        identity = build_archive_identity(
            params,
            album_internal_code=derived.album_internal_code,
            document_revision=derived.document_revision,
            spec=self.spec,
        )

        archive_root = self.admin_config_store.get_archive_root_path()
        archive_target = identity.target_dir(archive_root) if archive_root is not None else None
        return TaskGroupAlbumIdentity(
            engineering_no=identity.engineering_no,
            subitem_no=identity.subitem_no,
            album_internal_code=identity.album_internal_code,
            revision=identity.revision,
            archive_target=archive_target.resolve() if archive_target is not None else None,
        )
