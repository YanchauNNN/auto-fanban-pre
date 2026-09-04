from __future__ import annotations

import hashlib
import logging
import re
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.config import load_mechanism_spec
from src.models import AccountSnapshot, Job, JobStatus, TaskGroup
from src.pipeline.cross_process_lock import exclusive_file_lock
from src.workflow.models import WorkflowStatus

if TYPE_CHECKING:
    from .runtime import DeliverableApiRuntime


logger = logging.getLogger(__name__)
_OWNER_ONLY = "仅任务创建人或管理员可以执行此操作"
_ACTIVE_WORKFLOW = "该任务已进入审批或归档流程，不能取消生成或重新生成"


class JobActionService:
    """Execution controls are separate from, and never implicitly start, approval."""

    def __init__(self, runtime: DeliverableApiRuntime) -> None:
        self.runtime = runtime
        self.admin_roles = set(load_mechanism_spec().permissions.workflow_admin_roles)

    def _resolve(
        self, item_id: str, *, viewer: AccountSnapshot | None = None
    ) -> tuple[str, Job | TaskGroup]:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", item_id):
            raise LookupError("任务不存在")
        group = self.runtime.group_manager.reload_group(item_id)
        if group is not None:
            if viewer is not None:
                self._require_visible(group, viewer)
            return "group", group
        job = self.runtime.job_manager.reload_job(item_id)
        if job is None:
            raise LookupError("任务不存在")
        if viewer is not None:
            self._require_visible(job, viewer)
        if job.group_id:
            group = self.runtime.group_manager.reload_group(job.group_id)
            if group is None:
                raise ValueError("任务包关联缺失，请管理员检查任务记录")
            return "group", group
        return "job", job

    @staticmethod
    def _id(item: Job | TaskGroup) -> str:
        return item.job_id if isinstance(item, Job) else item.group_id

    def _allowed(self, item: Job | TaskGroup, account: AccountSnapshot) -> bool:
        owner = item.owner_snapshot
        return account.role in self.admin_roles or bool(
            owner and owner.creator_account == account.account_id
        )

    @staticmethod
    def _workflow_blocked(item: Job | TaskGroup) -> bool:
        return isinstance(item, TaskGroup) and item.workflow.status not in {
            WorkflowStatus.DRAFT,
            WorkflowStatus.CANCELLED,
        }

    def get_actions(self, item_id: str, account: AccountSnapshot) -> dict[str, object]:
        item_type, item = self._resolve(item_id, viewer=account)
        self._require_visible(item, account)
        return self._actions_for_item(item_type, item, account)

    def _require_visible(self, item: Job | TaskGroup, account: AccountSnapshot) -> None:
        visible = (
            self.runtime.task_visibility.can_view(item, account)
            if isinstance(item, TaskGroup)
            else self.runtime.task_visibility.can_view_job(item, account)
        )
        if not visible and not self._allowed(item, account):
            raise LookupError("任务不存在")

    def _actions_for_item(
        self, item_type: str, item: Job | TaskGroup, account: AccountSnapshot
    ) -> dict[str, object]:
        control = self.runtime.queue_store.execution_control(item_type, self._id(item))
        pending = bool(
            control and control["state"] == "running" and control["cancel_requested"]
        )
        denied = None if self._allowed(item, account) else _OWNER_ONLY
        if self._workflow_blocked(item):
            denied = denied or _ACTIVE_WORKFLOW
        cancel_reason = denied
        retry_reason = denied
        if pending:
            cancel_reason = (
                cancel_reason or "已提交取消请求，正在等待当前处理阶段安全结束"
            )
            retry_reason = retry_reason or "请等待任务安全取消后再重试"
        elif item.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            cancel_reason = cancel_reason or "仅排队或运行中的任务可以取消"
        if item.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
            retry_reason = retry_reason or "仅失败或已取消的任务可以重试"
        if control and control["state"] == "running":
            retry_reason = retry_reason or "任务执行器尚未安全退出，请稍后重试"
        if isinstance(item, TaskGroup) and item.metadata.get("workload_source_job_id"):
            retry_reason = (
                retry_reason or "该任务包仅用于工作量关联，不能作为生成任务包重试"
            )
        if retry_reason is None:
            try:
                self._source_inputs(item)
            except ValueError as exc:
                retry_reason = str(exc)
        return {
            "can_cancel": cancel_reason is None,
            "can_retry": retry_reason is None,
            "cancel_requested": pending,
            "cancel_reason": cancel_reason,
            "retry_reason": retry_reason,
        }

    @contextmanager
    def _action_lock(self, item_id: str) -> Iterator[None]:
        digest = hashlib.sha256(item_id.encode()).hexdigest()
        config = self.runtime.config
        with exclusive_file_lock(
            config.storage_dir / "locks" / "execution-actions" / f"{digest}.lock",
            timeout_seconds=float(config.management.task_group_lock_timeout_seconds),
            poll_interval_seconds=float(
                config.management.task_group_lock_poll_interval_seconds
            ),
        ):
            yield

    def cancel(self, item_id: str, account: AccountSnapshot) -> dict[str, object]:
        _, resolved = self._resolve(item_id)
        with self._action_lock(self._id(resolved)):
            item_type, item = self._resolve(item_id)
            if not self._allowed(item, account):
                raise PermissionError(_OWNER_ONLY)
            actions = self.get_actions(item_id, account)
            if actions["cancel_requested"]:
                return actions
            if not actions["can_cancel"]:
                raise ValueError(str(actions["cancel_reason"]))
            control = self.runtime.queue_store.request_execution_cancel(
                item_type,
                self._id(item),
                requested_by=account.account_id,
            )
            if control["state"] == "completed":
                raise ValueError("任务已完成，请刷新任务详情")
            if isinstance(item, TaskGroup):
                for child_id in item.child_job_ids:
                    child = self.runtime.job_manager.reload_job(child_id)
                    if child and child.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                        self._cancel_child(child, account)
                if control["state"] == "cancelled":
                    item.status = JobStatus.CANCELLED
                    item.finished_at = datetime.now()
                    item.progress.message = "任务包已安全取消"
                    self.runtime.group_manager.update_group(item)
            elif control["state"] == "cancelled":
                item.mark_cancelled()
                self.runtime.job_manager.update_job(item)
                self.runtime._signal_job_completion(item.job_id)
            self.runtime.refresh_summary_index(item_type, self._id(item))
            logger.info(
                "execution cancel requested item=%s:%s by=%s state=%s",
                item_type,
                self._id(item),
                account.account_id,
                control["state"],
            )
            return self.get_actions(item_id, account)

    def _cancel_child(self, child: Job, account: AccountSnapshot) -> None:
        control = self.runtime.queue_store.request_execution_cancel(
            "job",
            child.job_id,
            requested_by=account.account_id,
        )
        if control["state"] == "cancelled":
            child.mark_cancelled()
            self.runtime.job_manager.update_job(child)
            self.runtime._signal_job_completion(child.job_id)
        self.runtime.refresh_summary_index("job", child.job_id)

    def _source_inputs(self, item: Job | TaskGroup) -> list[Path]:
        if isinstance(item, TaskGroup):
            try:
                sources = [self.runtime._resolve_group_source_input(item)]
            except (ValueError, FileNotFoundError) as exc:
                raise ValueError("原始上传文件缺失，请重新上传创建任务") from exc
            roots = [self.runtime.config.get_group_dir(item.group_id).resolve()]
            roots.extend(
                self.runtime.config.get_job_dir(child_id).resolve()
                for child_id in item.child_job_ids
                if re.fullmatch(r"[A-Za-z0-9_-]+", child_id)
            )
        else:
            sources = list(item.input_files)
            roots = [self.runtime.config.get_job_dir(item.job_id).resolve()]
        if not sources or any(not Path(source).is_file() for source in sources):
            raise ValueError("原始上传文件缺失，请重新上传创建任务")
        if any(
            not any(Path(source).resolve().is_relative_to(root) for root in roots)
            for source in sources
        ):
            raise ValueError("原始上传文件不在本任务目录内，请重新上传创建任务")
        return [Path(source) for source in sources]

    @staticmethod
    def _retry_params(job: Job) -> dict[str, object]:
        return {
            key: deepcopy(value)
            for key, value in job.params.items()
            if not key.startswith(("cad_slot_", "shared_"))
            and key not in {"plot_resource_mode", "preflight_token"}
        }

    def _clone_job(
        self,
        old: Job,
        account: AccountSnapshot,
        *,
        group: TaskGroup | None = None,
        inputs: list[Path] | None = None,
    ) -> Job:
        source_paths = self._source_inputs(old) if inputs is None else []
        new = self.runtime.job_manager.create_job(
            job_type=old.job_type.value,
            project_no=old.project_no,
            batch_id=group.batch_id if group else self.runtime._new_batch_id(),
            source_filename=old.source_filename,
            task_role=old.task_role,
            group_id=group.group_id if group else None,
            shared_run_id=group.shared_run_id if group else None,
            options=deepcopy(old.options),
            params=self._retry_params(old),
            creator_snapshot=account,
        )
        if inputs is None:
            copied = []
            for index, source in enumerate(source_paths):
                target = (
                    self.runtime.config.get_job_dir(new.job_id)
                    / "input"
                    / str(index)
                    / source.name
                )
                self._copy_retry_source(source, target, new)
                copied.append(target)
            new.input_files = copied
        else:
            new.input_files = list(inputs)
        new.progress.details["retry_of"] = old.job_id
        self.runtime.job_manager.update_job(new)
        return new

    def _copy_retry_source(
        self, source: Path, target: Path, item: Job | TaskGroup
    ) -> None:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        except OSError as exc:
            logger.exception("retry input copy failed item=%s", self._id(item))
            item.mark_failed(f"retry_input_copy_failed:{exc}")
            if isinstance(item, Job):
                self.runtime.job_manager.update_job(item)
                self.runtime.refresh_summary_index("job", item.job_id)
            else:
                self.runtime.group_manager.update_group(item)
                self.runtime.refresh_summary_index("group", item.group_id)
            raise ValueError("重试文件复制失败，请检查磁盘空间和目录权限") from exc

    def retry(self, item_id: str, account: AccountSnapshot) -> dict[str, object]:
        _, resolved = self._resolve(item_id)
        with self._action_lock(self._id(resolved)):
            item_type, item = self._resolve(item_id)
            if not self._allowed(item, account):
                raise PermissionError(_OWNER_ONLY)
            actions = self.get_actions(item_id, account)
            if not actions["can_retry"]:
                raise ValueError(str(actions["retry_reason"]))
            metadata = (
                item.metadata if isinstance(item, TaskGroup) else item.progress.details
            )
            existing = metadata.get("execution_retry")
            if isinstance(existing, dict):
                retry_id = existing.get("group_id") or existing.get("job_id")
                retry_type, retry_item = self._resolve(str(retry_id))
                if retry_item.status == JobStatus.QUEUED:
                    if retry_type == "group":
                        self.runtime._enqueue_group(self._id(retry_item))
                    else:
                        self.runtime._enqueue_job(self._id(retry_item))
                return dict(existing)
            sources = self._source_inputs(item)
            if isinstance(item, TaskGroup):
                children = [
                    self.runtime.job_manager.reload_job(child_id)
                    for child_id in item.child_job_ids
                ]
                if not children or any(child is None for child in children):
                    raise ValueError("任务包子任务记录缺失，请管理员检查")
                new_group = self.runtime.group_manager.create_group(
                    batch_id=self.runtime._new_batch_id(),
                    source_filenames=list(item.source_filenames),
                    project_no=item.project_no,
                    run_audit_check=item.run_audit_check,
                    creator_snapshot=account,
                )
                source = sources[0]
                target = (
                    self.runtime.config.get_group_dir(new_group.group_id)
                    / "input"
                    / source.name
                )
                self._copy_retry_source(source, target, new_group)
                new_group.metadata["source_input_path"] = str(target)
                new_group.metadata["retry_of"] = item.group_id
                if item.metadata.get("group_mode"):
                    new_group.metadata["group_mode"] = item.metadata["group_mode"]
                new_group.child_job_ids = [
                    self._clone_job(
                        child, account, group=new_group, inputs=[target]
                    ).job_id
                    for child in children
                    if child is not None
                ]
                self.runtime.group_manager.update_group(new_group)
                result = {
                    "job_id": new_group.child_job_ids[0],
                    "group_id": new_group.group_id,
                }
                metadata["execution_retry"] = result
                self.runtime.group_manager.update_group(item)
                self.runtime.refresh_summary_index("group", new_group.group_id)
                self.runtime._enqueue_group(new_group.group_id)
            else:
                new = self._clone_job(item, account)
                result = {"job_id": new.job_id, "group_id": None}
                metadata["execution_retry"] = result
                self.runtime.job_manager.update_job(item)
                self.runtime.refresh_summary_index("job", new.job_id)
                self.runtime._enqueue_job(new.job_id)
            logger.info(
                "execution retry item=%s:%s by=%s result=%s",
                item_type,
                self._id(item),
                account.account_id,
                result,
            )
            return result
