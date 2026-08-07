from __future__ import annotations

from ..accounts.account_registry import AccountRegistry
from ..accounts.personnel_normalizer import PersonnelNormalizer
from ..archive.service import ArchiveService
from ..config import load_mechanism_spec, load_spec
from ..models import AccountSnapshot, TaskGroup
from ..pipeline.group_manager import GroupManager
from ..pipeline.job_manager import JobManager
from ..pipeline.shared_prep import SharedPrepService
from ..task_groups.serializers import TaskGroupSerializers
from ..task_groups.submission_readiness import TaskGroupSubmissionReadinessPolicy
from ..task_groups.submit_guards import TaskGroupSubmitGuards
from ..task_groups.visibility import TaskGroupVisibility
from ..workflow.input_validator import WorkflowInputValidator
from ..workflow.service import WorkflowService
from ..workflow.visibility import WorkflowVisibility
from ..workload.calculator import WorkloadCalculator
from ..workload.queries import WorkloadQueries
from ..workload.settlement_service import WorkloadSettlementService


class TaskGroupService:
    def __init__(
        self,
        *,
        group_manager: GroupManager,
        job_manager: JobManager,
        shared_prep_service: SharedPrepService,
        account_registry: AccountRegistry,
        personnel_normalizer: PersonnelNormalizer,
        workflow_validator: WorkflowInputValidator,
        workflow_service: WorkflowService,
        task_group_visibility: TaskGroupVisibility,
        workflow_visibility: WorkflowVisibility,
        serializers: TaskGroupSerializers,
        submission_readiness: TaskGroupSubmissionReadinessPolicy,
        submit_guards: TaskGroupSubmitGuards,
        workload_calculator: WorkloadCalculator,
        workload_settlement_service: WorkloadSettlementService,
        workload_queries: WorkloadQueries,
        archive_service: ArchiveService,
    ) -> None:
        self.group_manager = group_manager
        self.job_manager = job_manager
        self.shared_prep_service = shared_prep_service
        self.account_registry = account_registry
        self.personnel_normalizer = personnel_normalizer
        self.workflow_validator = workflow_validator
        self.workflow_service = workflow_service
        self.task_group_visibility = task_group_visibility
        self.workflow_visibility = workflow_visibility
        self.serializers = serializers
        self.submission_readiness = submission_readiness
        self.submit_guards = submit_guards
        self.workload_calculator = workload_calculator
        self.workload_settlement_service = workload_settlement_service
        self.workload_queries = workload_queries
        self.archive_service = archive_service

    def list_recent(self, account: AccountSnapshot, limit: int = 100) -> list[dict[str, object]]:
        groups = self.group_manager.list_groups(limit=limit)
        visible = [group for group in groups if self.task_group_visibility.can_view(group, account)]
        return [self._serialize_summary(group, account) for group in visible]

    def get_detail(self, group_id: str, account: AccountSnapshot) -> dict[str, object]:
        group = self._require_group(group_id)
        if not self.task_group_visibility.can_view(group, account):
            raise PermissionError("group not visible")
        return self._serialize_detail(group, account)

    def submit(
        self,
        group_id: str,
        initiator: AccountSnapshot,
        *,
        overwrite_archive_existing: bool = False,
        cancel_existing_in_progress: bool = False,
    ) -> dict[str, object]:
        group = self._require_group(group_id)
        if group.owner_snapshot and group.owner_snapshot.creator_account != initiator.account_id:
            raise ValueError("submitter_must_match_creator")
        self.submission_readiness.ensure_ready(group)
        self.submit_guards.ensure_submit_allowed(
            group,
            overwrite_archive_existing=overwrite_archive_existing,
            cancel_existing_in_progress=cancel_existing_in_progress,
        )
        group.personnel_snapshot = self._build_personnel_snapshot(group)
        errors = self.workflow_validator.validate_submit(group.personnel_snapshot)
        if errors:
            raise ValueError(";".join(errors))
        prep = self.shared_prep_service.load(group.shared_dir or self.group_manager.config.get_group_dir(group.group_id) / "shared")
        group.workload = self.workload_calculator.build_from_shared_prep(prep)
        group = self.workflow_service.start(group, initiator)
        group.mark_running("WORKFLOW_SUBMITTED")
        self.group_manager.update_group(group)
        return self._serialize_detail(group, initiator)

    def restart_submit(
        self,
        group_id: str,
        initiator: AccountSnapshot,
        *,
        overwrite_archive_existing: bool = False,
        cancel_existing_in_progress: bool = False,
    ) -> dict[str, object]:
        return self.submit(
            group_id,
            initiator,
            overwrite_archive_existing=overwrite_archive_existing,
            cancel_existing_in_progress=cancel_existing_in_progress,
        )

    def approve(
        self,
        group_id: str,
        acting_account: AccountSnapshot,
        factor: float,
        node_key: str | None = None,
    ) -> dict[str, object]:
        group = self._require_group(group_id)
        self.workflow_service.approve(group, acting_account, factor, node_key=node_key)
        self._apply_factors(group)
        mechanism_spec = load_mechanism_spec()
        workflow_runtime = mechanism_spec.workflow_runtime
        workload_cfg = dict(load_spec().get_management_features().get("workload") or {})
        settlement_trigger = str(workload_cfg["settlement_trigger"]).strip()
        if group.workflow.status.value == workflow_runtime.archive_trigger_status:
            try:
                self.archive_service.archive_group(group)
                if settlement_trigger == "archive_success":
                    if group.archive.status.value == "succeeded":
                        self.workload_settlement_service.settle(group)
                elif settlement_trigger == "approval_terminal":
                    self.workload_settlement_service.settle(group)
                group.mark_succeeded()
            except Exception as exc:  # noqa: BLE001
                self.archive_service.mark_failed(group, str(exc))
                group.mark_failed(str(exc))
        self.group_manager.update_group(group)
        return self._serialize_detail(group, acting_account)

    def repair_current_node(self, group_id: str, assignee_snapshot: AccountSnapshot) -> dict[str, object]:
        group = self._require_group(group_id)
        self.workflow_service.repair_current_node(group, assignee_snapshot)
        self.group_manager.update_group(group)
        return self._serialize_detail(group, assignee_snapshot)

    def rebind_account_references(self, old_account_id: str, new_account_snapshot: AccountSnapshot) -> None:
        for group in self.group_manager.load_all_groups():
            changed = False
            if group.owner_snapshot and group.owner_snapshot.creator_account == old_account_id:
                group.owner_snapshot.creator_account = new_account_snapshot.account_id
                group.owner_snapshot.creator_name = new_account_snapshot.display_name
                group.owner_snapshot.creator_role = new_account_snapshot.role
                group.owner_snapshot.creator_office = new_account_snapshot.office_name
                changed = True
            for personnel in group.personnel_snapshot.members.values():
                if personnel.matched_account == old_account_id:
                    personnel.matched_account = new_account_snapshot.account_id
                    personnel.matched_name = new_account_snapshot.display_name
                    personnel.normalized_value = f"{new_account_snapshot.display_name}@{new_account_snapshot.account_id}"
                    changed = True
            for node in group.workflow.nodes:
                if node.assignee_account == old_account_id:
                    node.assignee_account = new_account_snapshot.account_id
                    node.assignee_name = new_account_snapshot.display_name
                    changed = True
                if node.acted_by_account == old_account_id:
                    node.acted_by_account = new_account_snapshot.account_id
                    node.acted_by_name = new_account_snapshot.display_name
                    changed = True
            if changed:
                self.group_manager.update_group(group)

    def workflow_monitor(self, account: AccountSnapshot) -> list[dict[str, object]]:
        groups = self.group_manager.load_all_groups()
        visible = [group for group in groups if self.workflow_visibility.can_view(group, account)]
        return [self._serialize_summary(group, account) for group in visible]

    def pending_todo_count(self, account: AccountSnapshot) -> int:
        count = 0
        for group in self.group_manager.load_all_groups():
            current = self.workflow_service.current_node(group)
            if current is not None and current.assignee_account == account.account_id:
                count += 1
        return count

    def _build_personnel_snapshot(self, group: TaskGroup):
        primary_job = self.job_manager.get_job(group.child_job_ids[0]) if group.child_job_ids else None
        if primary_job is None:
            raise ValueError("group has no child jobs")
        workflow_cfg = dict(load_spec().get_management_features().get("workflow") or {})
        field_names: set[str] = {
            str(field_name)
            for field_name in (workflow_cfg.get("deduplication_rules") or {}).get("unique_role_fields") or []
            if str(field_name).strip()
        }
        for node_cfg in workflow_cfg.get("nodes") or []:
            source = str(node_cfg.get("assignee_source") or "").strip()
            if source:
                field_names.add(source)
        one_review_source = str((workflow_cfg.get("one_review") or {}).get("assignee_source") or "").strip()
        if one_review_source:
            field_names.add(one_review_source)
        for field_name in workflow_cfg.get("preserve_fields") or []:
            field_text = str(field_name).strip()
            if field_text:
                field_names.add(field_text)
        values = {field_name: primary_job.params.get(field_name) for field_name in sorted(field_names)}
        return self.personnel_normalizer.normalize_fields(values)

    def _apply_factors(self, group: TaskGroup) -> None:
        workflow_cfg = dict(load_spec().get_management_features().get("workflow") or {})
        factor_keys = {
            str(node_cfg.get("key") or ""): str(node_cfg.get("factor_key") or "")
            for node_cfg in workflow_cfg.get("nodes") or []
        }
        group.workload.node_factors = {}
        for node in group.workflow.nodes:
            if node.node_key:
                group.workload.node_factors[node.node_key] = node.factor
            factor_key = factor_keys.get(node.node_key)
            if factor_key and hasattr(group.workload, factor_key):
                setattr(group.workload, factor_key, node.factor)
        self.workload_calculator.refresh_final(group.workload)

    def _require_group(self, group_id: str) -> TaskGroup:
        group = self.group_manager.get_group(group_id)
        if group is None:
            raise ValueError("group not found")
        return group

    def _serialize_summary(self, group: TaskGroup, account: AccountSnapshot) -> dict[str, object]:
        permissions = self._permissions(group, account)
        return self.serializers.summarize(group, **permissions)

    def _serialize_detail(self, group: TaskGroup, account: AccountSnapshot) -> dict[str, object]:
        permissions = self._permissions(group, account)
        return self.serializers.detail(group, **permissions)

    def _permissions(self, group: TaskGroup, account: AccountSnapshot) -> dict[str, bool]:
        current_node = self.workflow_service.current_node(group)
        can_view_detail = self.task_group_visibility.can_view(group, account)
        can_submit = self.submission_readiness.inspect(group).is_ready and (
            group.owner_snapshot is None or group.owner_snapshot.creator_account == account.account_id
        )
        can_approve = current_node is not None and current_node.assignee_account == account.account_id
        is_related_to_current_user = bool(
            (group.owner_snapshot and group.owner_snapshot.creator_account == account.account_id)
            or any(node.assignee_account == account.account_id for node in group.workflow.nodes)
        )
        return {
            "can_view_detail": can_view_detail,
            "can_submit": can_submit,
            "can_approve": can_approve,
            "is_related_to_current_user": is_related_to_current_user,
        }
