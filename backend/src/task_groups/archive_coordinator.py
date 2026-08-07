from __future__ import annotations

import os
import threading
import uuid
from copy import deepcopy
from datetime import UTC, datetime

from ..archive.models import ArchiveStatus
from ..archive.overwrite_service import ArchiveOverwriteService
from ..archive.service import ArchiveService
from ..models import JobStatus, TaskGroup
from ..pipeline.group_manager import TaskGroupVersionConflict
from ..workflow.models import WorkflowStatus
from ..workload.models import WorkloadSettlementStatus
from ..workload.settlement_service import WorkloadSettlementService
from .replacement_cleanup_fence import ReplacementCleanupFence
from .state_writer import SUMMARY_PUBLICATION_PENDING_KEY, TaskGroupStateWriter

TASK_GROUP_RECONCILIATION_ERROR_KEY = "task_group_reconciliation_error"
REPLACEMENT_CLEANUP_CLAIM_KEY = "replacement_cleanup_claim"


class TaskGroupArchiveCoordinator:
    """Coordinate archive, settlement, publication and replacement cleanup."""

    def __init__(
        self,
        *,
        archive_service: ArchiveService,
        workload_settlement_service: WorkloadSettlementService,
        state_writer: TaskGroupStateWriter,
        settlement_trigger: str,
        overwrite_service: ArchiveOverwriteService | None = None,
        cleanup_claim_ttl_seconds: float = 300.0,
        cleanup_owner_id: str | None = None,
    ) -> None:
        self.archive_service = archive_service
        self.workload_settlement_service = workload_settlement_service
        self.state_writer = state_writer
        self.settlement_trigger = settlement_trigger
        self.overwrite_service = overwrite_service
        self.cleanup_claim_ttl_seconds = cleanup_claim_ttl_seconds
        self.cleanup_owner_id = cleanup_owner_id
        self._cleanup_fence: ReplacementCleanupFence | None = None

    @property
    def cleanup_fence(self) -> ReplacementCleanupFence:
        if self._cleanup_fence is None:
            config = self.state_writer.group_manager.config
            self._cleanup_fence = ReplacementCleanupFence(
                storage_dir=config.storage_dir,
                lock_timeout_seconds=float(
                    config.management.task_group_lock_timeout_seconds
                ),
                lock_poll_interval_seconds=float(
                    config.management.task_group_lock_poll_interval_seconds
                ),
            )
        return self._cleanup_fence

    @cleanup_fence.setter
    def cleanup_fence(self, value: ReplacementCleanupFence) -> None:
        self._cleanup_fence = value

    def complete(self, group: TaskGroup) -> TaskGroup:
        if group.archive.status is not ArchiveStatus.SUCCEEDED:
            try:
                self.archive_service.archive_group(group)
            except Exception as exc:  # noqa: BLE001
                self.archive_service.mark_failed(group, str(exc))
                group.mark_failed(str(exc))
                self._record_error(group, stage="archive", error=exc)
                return self.state_writer.write(group)

        if self._should_settle(group) and (
            group.workload.settlement_status is not WorkloadSettlementStatus.SETTLED
        ):
            try:
                self.workload_settlement_service.settle(group)
            except Exception as exc:  # noqa: BLE001
                # The archive copy is already valid. Keep it valid and retry only
                # settlement instead of reporting a false archive-copy failure.
                group.mark_failed(str(exc))
                self._record_error(group, stage="settlement", error=exc)
                return self.state_writer.write(group)

        if group.status is not JobStatus.SUCCEEDED:
            group.mark_succeeded()
        self._clear_error(group, stages={"archive", "settlement"})

        # The successor must be durable and visible before any old records are
        # removed. A publisher failure therefore prevents cleanup entirely.
        self.state_writer.write(group)
        self.retry_pending_replacement_cleanup(group)
        return group

    def retry_pending_replacement_cleanup(
        self,
        group: TaskGroup,
        *,
        claim_owner: str | None = None,
    ) -> bool:
        if not group.replacement.replaced_record_pending_delete:
            return True
        if not self.is_replacement_cleanup_ready(group):
            return False
        try:
            ReplacementCleanupFence.normalize_replaced_group_id(
                group.replacement.replaced_group_id
            )
        except ValueError as exc:
            self._record_error(group, stage="replacement_cleanup", error=exc)
            self.state_writer.write(group)
            return False
        if self.overwrite_service is None:
            error = RuntimeError("replacement cleanup service is not configured")
            self._record_error(group, stage="replacement_cleanup", error=error)
            self.state_writer.write(group)
            return False

        owner = claim_owner or self.cleanup_owner_id or self._new_claim_owner()
        claim_token = self._try_claim_replacement_cleanup(group, owner=owner)
        if claim_token is None:
            return False

        try:
            with self.cleanup_fence.operation(
                group.replacement.replaced_group_id
            ) as normalized_replaced_group_id:
                return self._cleanup_replacement_under_operation_lock(
                    group,
                    owner=owner,
                    claim_token=claim_token,
                    normalized_replaced_group_id=normalized_replaced_group_id,
                )
        except TimeoutError:
            self._release_persisted_cleanup_claim(
                group.group_id,
                owner=owner,
                claim_token=claim_token,
            )
            return False

    def _try_claim_replacement_cleanup(self, group: TaskGroup, *, owner: str) -> str | None:
        claim = group.metadata.get(REPLACEMENT_CLEANUP_CLAIM_KEY)
        if self._claim_is_active(claim):
            # The owner identifies a worker process, not one invocation. An
            # active claim must therefore fence even a same-owner re-entry.
            return None
        had_claim = REPLACEMENT_CLEANUP_CLAIM_KEY in group.metadata
        previous_claim = deepcopy(claim)
        claim_token = uuid.uuid4().hex
        group.metadata[REPLACEMENT_CLEANUP_CLAIM_KEY] = {
            "owner": owner,
            "token": claim_token,
            "claimed_at": datetime.now(UTC).isoformat(),
        }
        try:
            self.state_writer.persist_without_publication(group)
        except TaskGroupVersionConflict:
            if had_claim:
                group.metadata[REPLACEMENT_CLEANUP_CLAIM_KEY] = previous_claim
            else:
                group.metadata.pop(REPLACEMENT_CLEANUP_CLAIM_KEY, None)
            return None
        except Exception:
            if had_claim:
                group.metadata[REPLACEMENT_CLEANUP_CLAIM_KEY] = previous_claim
            else:
                group.metadata.pop(REPLACEMENT_CLEANUP_CLAIM_KEY, None)
            raise
        return claim_token

    def _cleanup_replacement_under_operation_lock(
        self,
        group: TaskGroup,
        *,
        owner: str,
        claim_token: str,
        normalized_replaced_group_id: str,
    ) -> bool:
        current = self.state_writer.group_manager.reload_group(group.group_id)
        if current is None:
            return False
        if not self._claim_matches(current, owner=owner, claim_token=claim_token):
            self._sync_reconciliation_state(group, current)
            return False
        try:
            current_replaced_group_id = self.cleanup_fence.normalize_replaced_group_id(
                current.replacement.replaced_group_id
            )
        except ValueError as exc:
            self._release_cleanup_claim(
                current,
                owner=owner,
                claim_token=claim_token,
            )
            self._record_error(current, stage="replacement_cleanup", error=exc)
            self.state_writer.write(current)
            self._sync_reconciliation_state(group, current)
            return False
        if current_replaced_group_id != normalized_replaced_group_id:
            self._release_cleanup_claim(
                current,
                owner=owner,
                claim_token=claim_token,
            )
            self.state_writer.persist_without_publication(current)
            self._sync_reconciliation_state(group, current)
            return False
        if not current.replacement.replaced_record_pending_delete:
            self._release_cleanup_claim(
                current,
                owner=owner,
                claim_token=claim_token,
            )
            self.state_writer.persist_without_publication(current)
            self._sync_reconciliation_state(group, current)
            return True
        if not self.is_replacement_cleanup_ready(current):
            self._release_cleanup_claim(
                current,
                owner=owner,
                claim_token=claim_token,
            )
            self.state_writer.persist_without_publication(current)
            self._sync_reconciliation_state(group, current)
            return False

        try:
            deletion_completed = self.cleanup_fence.has_deletion_receipt(
                normalized_replaced_group_id
            )
            if not deletion_completed:
                self.overwrite_service.cleanup_replaced_group(current)
                self.cleanup_fence.record_deletion(normalized_replaced_group_id)
        except Exception as exc:  # noqa: BLE001
            # A partially deleted predecessor must not be republished. The
            # successor's durable pending marker is the retry driver. Reload
            # first so an expired-lease takeover claim is never cleared here.
            failed = self.state_writer.group_manager.reload_group(group.group_id)
            if failed is None:
                raise
            self._release_cleanup_claim(
                failed,
                owner=owner,
                claim_token=claim_token,
            )
            self._record_error(failed, stage="replacement_cleanup", error=exc)
            self.state_writer.write(failed)
            self._sync_reconciliation_state(group, failed)
            return False

        return self._complete_replacement_cleanup_state(
            group,
            owner=owner,
            claim_token=claim_token,
        )

    def _complete_replacement_cleanup_state(
        self,
        group: TaskGroup,
        *,
        owner: str,
        claim_token: str,
    ) -> bool:
        completed = self.state_writer.group_manager.reload_group(group.group_id)
        if completed is None:
            raise RuntimeError(f"replacement successor disappeared: {group.group_id}")
        completed.replacement.replaced_record_pending_delete = False
        self._release_cleanup_claim(
            completed,
            owner=owner,
            claim_token=claim_token,
        )
        self._clear_error(completed, stages={"replacement_cleanup"})
        self.state_writer.write(completed)
        self._sync_reconciliation_state(group, completed)
        return True

    def _release_persisted_cleanup_claim(
        self,
        group_id: str,
        *,
        owner: str,
        claim_token: str,
    ) -> None:
        current = self.state_writer.group_manager.reload_group(group_id)
        if current is None or not self._claim_matches(
            current,
            owner=owner,
            claim_token=claim_token,
        ):
            return
        self._release_cleanup_claim(
            current,
            owner=owner,
            claim_token=claim_token,
        )
        try:
            self.state_writer.persist_without_publication(current)
        except TaskGroupVersionConflict:
            return

    def _claim_is_active(self, claim: object) -> bool:
        if not isinstance(claim, dict):
            return False
        claimed_at_raw = claim.get("claimed_at")
        if not isinstance(claimed_at_raw, str):
            return False
        try:
            claimed_at = datetime.fromisoformat(claimed_at_raw)
        except ValueError:
            return False
        if claimed_at.tzinfo is None:
            claimed_at = claimed_at.replace(tzinfo=UTC)
        age_seconds = (datetime.now(UTC) - claimed_at.astimezone(UTC)).total_seconds()
        return age_seconds < self.cleanup_claim_ttl_seconds

    @staticmethod
    def _claim_matches(group: TaskGroup, *, owner: str, claim_token: str) -> bool:
        claim = group.metadata.get(REPLACEMENT_CLEANUP_CLAIM_KEY)
        return (
            isinstance(claim, dict)
            and claim.get("owner") == owner
            and claim.get("token") == claim_token
        )

    @classmethod
    def _release_cleanup_claim(
        cls,
        group: TaskGroup,
        *,
        owner: str,
        claim_token: str,
    ) -> None:
        if cls._claim_matches(group, owner=owner, claim_token=claim_token):
            group.metadata.pop(REPLACEMENT_CLEANUP_CLAIM_KEY, None)

    @staticmethod
    def _sync_reconciliation_state(target: TaskGroup, source: TaskGroup) -> None:
        target.state_version = source.state_version
        target.replacement = source.replacement.model_copy(deep=True)
        target.metadata = deepcopy(source.metadata)

    @staticmethod
    def _new_claim_owner() -> str:
        return f"{os.getpid()}-{threading.get_ident()}-{uuid.uuid4().hex}"

    @staticmethod
    def is_replacement_cleanup_ready(group: TaskGroup) -> bool:
        return (
            group.archive.status is ArchiveStatus.SUCCEEDED
            and group.workflow.status is WorkflowStatus.ARCHIVED
            and group.status is JobStatus.SUCCEEDED
            and group.workload.settlement_status is WorkloadSettlementStatus.SETTLED
            and not group.metadata.get(SUMMARY_PUBLICATION_PENDING_KEY)
        )

    def needs_archive_reconciliation(self, group: TaskGroup) -> bool:
        if group.archive.status is ArchiveStatus.FAILED:
            return True
        return (
            group.archive.status is ArchiveStatus.SUCCEEDED
            and group.workflow.status is WorkflowStatus.ARCHIVED
            and group.workload.settlement_status is not WorkloadSettlementStatus.SETTLED
        )

    def _should_settle(self, group: TaskGroup) -> bool:
        if self.settlement_trigger == "archive_success":
            return group.archive.status is ArchiveStatus.SUCCEEDED
        if self.settlement_trigger == "approval_terminal":
            return True
        raise ValueError(f"unsupported workload settlement trigger: {self.settlement_trigger}")

    @staticmethod
    def _record_error(group: TaskGroup, *, stage: str, error: Exception) -> None:
        group.metadata[TASK_GROUP_RECONCILIATION_ERROR_KEY] = {
            "stage": stage,
            "message": str(error),
        }

    @staticmethod
    def _clear_error(group: TaskGroup, *, stages: set[str]) -> None:
        error = group.metadata.get(TASK_GROUP_RECONCILIATION_ERROR_KEY)
        if isinstance(error, dict) and error.get("stage") in stages:
            group.metadata.pop(TASK_GROUP_RECONCILIATION_ERROR_KEY, None)
