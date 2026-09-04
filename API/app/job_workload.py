"""Explicit workload submission from ordinary job detail; GET is strictly read-only."""
from __future__ import annotations

import hashlib
import logging
from contextlib import contextmanager

from fastapi import HTTPException
from src.config import load_mechanism_spec, load_spec
from src.models import JobStatus, TaskGroup, TaskOwnerSnapshot
from src.pipeline.cross_process_lock import exclusive_file_lock
from src.task_groups.job_submission_source import (
    SOURCE_JOB_KEY,
    job_source_files,
    read_job_submission,
)
from src.task_groups.visibility import TaskGroupVisibility

logger = logging.getLogger(__name__)

MESSAGES = {
    "workload_unsupported": "该任务类型尚未定义工作量计量规则，暂不参与填报。",
    "workload_execution_active": "出图执行器正在完成收尾，请稍后再提交工作量。",
    "submitter_must_match_creator": "仅任务创建人可以提交工作量；无历史归属的任务须由管理员处理。",
    "task_group_not_succeeded": "任务尚未生成成功，请完成出图后再提交。",
    "workflow_not_draft": "工作量流程已经启动，请在工作量模块查看进度。",
    "deliverable_package_not_declared": "任务未登记交付压缩包，请检查出图结果。",
    "deliverable_package_not_found": "交付压缩包已不存在，请重新生成任务。",
    "deliverable_ied_not_declared": "任务要求的 IED 表未登记，请检查出图结果。",
    "deliverable_ied_not_found": "任务要求的 IED 表已不存在。",
    "workload_snapshot_missing": "缺少出图时记录的工作量基数，无法安全填报，请重新生成。",
    "workload_snapshot_invalid": "工作量基数无效，必须是有效的正数。",
    "workload_manifest_invalid": "出图追溯记录缺失或图册编号不一致，无法确定归档对象。",
    "workload_revision_missing": "缺少可核验的图纸版次记录，无法安全归档，请重新生成出图任务。",
    "workload_archive_identity_invalid": "图册归档编码无效，请检查原任务参数。",
    "workload_source_missing": "原始上传文件缺失，无法完成后续归档。",
    "workload_source_outside": "原始文件不在该任务目录内，请由管理员检查任务数据。",
}


class JobWorkloadSubmission:
    def __init__(self, runtime, management):
        self.runtime = runtime
        self.management = management
        self.service = management.task_group_service
        self.workflow_cfg = load_spec().get_management_features()["workflow"]
        self.nodes = self.workflow_cfg["nodes"]
        self.allowed_fields = {str(node["assignee_source"]) for node in self.nodes}

    def _resolve(self, item_id, account):
        if not item_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in item_id):
            raise HTTPException(404, "任务不存在")
        job = self.runtime.job_manager.reload_job(item_id)
        group = self.runtime.group_manager.reload_group(job.group_id if job and job.group_id else item_id)
        if group:
            if not (TaskGroupVisibility().can_view(group, account) or self.service.workflow_visibility.can_view(group, account)):
                raise HTTPException(403, "无权查看该任务的工作量信息")
            children = [self.runtime.job_manager.reload_job(key) for key in group.child_job_ids]
            job = next((child for child in children if child and child.task_role == "deliverable_main"), None)
            job = job or next((child for child in children if child), None)
        elif job:
            if not TaskGroupVisibility().can_view_job(job, account):
                raise HTTPException(403, "无权查看该任务")
        else:
            raise HTTPException(404, "任务不存在")
        return job, group

    def _is_creator(self, job, group, account):
        owner = group.owner_snapshot if group else job.owner_snapshot if job else None
        if owner:
            return owner.creator_account == account.account_id
        return account.role in load_mechanism_spec().permissions.workflow_admin_roles

    def preview(self, item_id, account):
        job, group = self._resolve(item_id, account)
        supported = bool(job and job.job_type.value in load_mechanism_spec().task_group_submission.standalone_job_types and not job.options.get("split_only"))
        errors = []
        workload = None
        if not supported:
            errors.append("workload_unsupported")
        elif group:
            errors.extend(self.service.submission_readiness.inspect(group).error_codes)
            workload = group.workload.initial_workload_a1 or None
            if not errors and not workload:
                prep = self.runtime.shared_prep_service.load(group.shared_dir)
                workload = self.management.workload_calculator.build_from_shared_prep(prep).initial_workload_a1
        else:
            if job.status != JobStatus.SUCCEEDED:
                errors.append("task_group_not_succeeded")
            try:
                summary, _ = read_job_submission(job)
                workload = summary.initial_workload_a1
                job_source_files(job)
            except ValueError as exc:
                errors.append(str(exc))
            for requirement in load_mechanism_spec().task_group_submission.required_task_roles:
                for artifact in requirement.artifacts:
                    if artifact.required_when:
                        condition = artifact.required_when
                        values = job.params if condition.source == "params" else job.options
                        raw = values.get(condition.field, condition.default)
                        enabled = raw is True or str(raw).lower() in {"true", "1", "yes", "on"}
                        if enabled != condition.equals:
                            continue
                    path = getattr(job.artifacts, artifact.field)
                    if path is None:
                        errors.append(artifact.not_declared_error)
                    elif not path.is_file():
                        errors.append(artifact.not_found_error)
        if supported and not self._is_creator(job, group, account):
            errors.append("submitter_must_match_creator")
        if supported:
            controls = [("job", job.job_id)]
            if group:
                controls.append(("group", group.group_id))
            for item_type, key in controls:
                control = self.runtime.queue_store.execution_control(item_type, key)
                if control and control["state"] == "running":
                    errors.append("workload_execution_active")
                    break
        fields = []
        for node in self.nodes:
            key = str(node["assignee_source"])
            saved = group.personnel_snapshot.members.get(key) if group else None
            value = saved.normalized_value if saved else (job.params.get(key) if job else "")
            fields.append({"key": key, "label": str(node["label"]) + "人员", "value": value or "", "required": True})
        detail = self.service._serialize_detail(group, account) if group else None
        return {
            "supported": supported, "can_submit": supported and not errors,
            "blockers": [{"code": code, "message": MESSAGES.get(code, f"提交条件未满足：{code}")} for code in dict.fromkeys(errors)],
            "group_id": group.group_id if group else None,
            "workflow_status": group.workflow.status.value if group else "draft",
            "initial_workload_a1": workload, "personnel_fields": fields, "group": detail,
        }

    def _validate_personnel(self, job, account, overrides):
        errors = {}
        if set(overrides) - self.allowed_fields:
            raise HTTPException(422, {"message": "含有不允许修改的人员字段", "field_errors": dict.fromkeys(set(overrides) - self.allowed_fields, "不允许修改该字段")})
        effective = {key: str(job.params.get(key) or "") for key in self.allowed_fields}
        effective.update(overrides)
        snapshot = self.management.personnel_normalizer.normalize_fields(effective)
        for node in self.nodes:
            key = str(node["assignee_source"])
            member = snapshot.members.get(key)
            if not member or member.status != "matched" or not member.matched_account:
                errors[key] = f"请选择有效的{node['label']}人员（姓名@账号），且账号须存在。"
        for error in self.management.workflow_validator.validate_for_initiator(snapshot, account):
            if error.startswith("workflow_role_duplicate:"):
                for key in error.split(":")[1:]:
                    if key in self.allowed_fields:
                        errors[key] = "审批人员不能与其他审批节点或当前提交人重复。"
            else:
                key = error.split(":")[0]
                errors.setdefault(key, "人员信息无效，请检查姓名和账号。")
        if errors:
            raise HTTPException(422, {"message": "请修正审批人员后重新提交。", "field_errors": errors})
        return effective

    @contextmanager
    def _lock(self, key):
        config = self.runtime.config
        digest = hashlib.sha256(key.encode()).hexdigest()
        with exclusive_file_lock(config.storage_dir / "locks" / "workload-submit" / f"{digest}.lock", timeout_seconds=config.management.task_group_lock_timeout_seconds, poll_interval_seconds=config.management.task_group_lock_poll_interval_seconds):
            yield

    def submit(self, item_id, account, *, personnel, overwrite_archive_existing=False, cancel_existing_in_progress=False):
        job, group = self._resolve(item_id, account)
        lock_key = str(group.metadata.get(SOURCE_JOB_KEY) or group.group_id) if group else item_id
        with self._lock(lock_key):
            job, group = self._resolve(item_id, account)
            if not self._is_creator(job, group, account):
                raise HTTPException(403, MESSAGES["submitter_must_match_creator"])
            preview = self.preview(item_id, account)
            if not preview["can_submit"]:
                raise HTTPException(422, {"message": "；".join(item["message"] for item in preview["blockers"]), "field_errors": {}})
            effective = self._validate_personnel(job, account, personnel)
            if group is None:
                summary, identity = read_job_submission(job)
                group_id = "group-workload-" + hashlib.sha256(job.job_id.encode()).hexdigest()[:32]
                group = self.runtime.group_manager.reload_group(group_id)
                if group is None:
                    group = TaskGroup(group_id=group_id, batch_id=job.batch_id, project_no=job.project_no,
                                      source_filenames=[job.source_filename or job.input_files[0].name],
                                      run_audit_check=False, shared_run_id=group_id, child_job_ids=[job.job_id])
                    group.owner_snapshot = job.owner_snapshot or TaskOwnerSnapshot(creator_account=account.account_id, creator_name=account.display_name, creator_role=account.role, creator_office=account.office_name)
                    group.metadata.update({SOURCE_JOB_KEY: job.job_id, "album_internal_code": identity.album_internal_code})
                    group.workload = summary
                    group.mark_succeeded()
                    self.runtime.group_manager.update_group(group)
                elif group.metadata.get(SOURCE_JOB_KEY) != job.job_id:
                    raise HTTPException(409, "任务关联冲突，请联系管理员")
                job.group_id = group.group_id
                job.task_role = "deliverable_main"
                self.runtime.job_manager.update_job(job)
            try:
                result = self.service.submit(group.group_id, account, overwrite_archive_existing=overwrite_archive_existing,
                                             cancel_existing_in_progress=cancel_existing_in_progress, personnel_overrides=effective)
            except ValueError as exc:
                logger.warning("workload submit rejected job=%s group=%s reason=%s", item_id, group.group_id, exc)
                raise HTTPException(422, str(exc)) from exc
            self.runtime.remove_summary_index("job", job.job_id)
            logger.info("workload submitted job=%s group=%s actor=%s initial_a1=%s", item_id, group.group_id, account.account_id, result["workload"]["initial_workload_a1"])
            return result
