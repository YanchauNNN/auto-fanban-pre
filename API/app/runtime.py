from __future__ import annotations

import importlib.util
import queue
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException, status

from .metadata import FormMetadataService

from src.audit_check.executor import AuditCheckExecutor
from src.cad.slot_pool import CADSlotPool
from src.cad.autocad_path_resolver import resolve_autocad_paths
from src.config import get_config
from src.doc_gen.param_validator import DocParamValidator
from src.models import Job, JobArtifacts, JobStatus, JobType, TaskGroup
from src.pipeline.executor import PipelineExecutor
from src.pipeline.group_manager import GroupManager
from src.pipeline.job_manager import JobManager
from src.pipeline.project_no_inference import infer_project_no_from_path, resolve_project_no
from src.pipeline.shared_prep import SharedPrepService


@dataclass(frozen=True)
class UploadedFilePayload:
    filename: str
    content: bytes
    content_type: str | None = None


class PipelineJobProcessor:
    def __call__(self, job: Job) -> None:
        if job.job_type == JobType.AUDIT_REPLACE:
            AuditCheckExecutor().execute(job)
            return
        PipelineExecutor().execute(job)


class DeliverableApiRuntime:
    def __init__(
        self,
        job_processor: Callable[[Job], None] | None = None,
        shared_prep_service: SharedPrepService | None = None,
    ) -> None:
        self.config = get_config()
        self.config.ensure_dirs()
        self.job_manager = JobManager()
        self.group_manager = GroupManager()
        self.validator = DocParamValidator()
        self.metadata = FormMetadataService()
        self.job_processor = job_processor or PipelineJobProcessor()
        self.shared_prep_service = shared_prep_service or SharedPrepService()
        self.cad_slot_pool = CADSlotPool(config=self.config, slot_count=4)

        self._group_queue: queue.Queue[str | None] = queue.Queue()
        self._job_queue: queue.Queue[str | None] = queue.Queue()
        self._stop_event = threading.Event()
        self._group_dispatcher_thread: threading.Thread | None = None
        self._job_dispatcher_thread: threading.Thread | None = None

        self._group_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='fanban-group')
        self._heavy_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='fanban-heavy')
        self._doc_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='fanban-doc')
        self._group_futures: set[Future[None]] = set()
        self._job_futures: set[Future[None]] = set()
        self._future_lock = threading.Lock()

    def start(self) -> None:
        self._recover_groups_and_jobs()
        if self._group_dispatcher_thread and self._group_dispatcher_thread.is_alive():
            return
        self._stop_event.clear()
        self._group_dispatcher_thread = threading.Thread(
            target=self._group_dispatch_loop,
            name='deliverable-group-dispatcher',
            daemon=True,
        )
        self._job_dispatcher_thread = threading.Thread(
            target=self._job_dispatch_loop,
            name='deliverable-job-dispatcher',
            daemon=True,
        )
        self._group_dispatcher_thread.start()
        self._job_dispatcher_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._group_queue.put(None)
        self._job_queue.put(None)
        if self._group_dispatcher_thread:
            self._group_dispatcher_thread.join(timeout=3)
        if self._job_dispatcher_thread:
            self._job_dispatcher_thread.join(timeout=3)
        self._group_executor.shutdown(wait=False, cancel_futures=True)
        self._heavy_executor.shutdown(wait=False, cancel_futures=True)
        self._doc_executor.shutdown(wait=False, cancel_futures=True)

    def health(self) -> dict[str, Any]:
        storage_writable = self._storage_writable()
        group_alive = bool(self._group_dispatcher_thread and self._group_dispatcher_thread.is_alive())
        job_alive = bool(self._job_dispatcher_thread and self._job_dispatcher_thread.is_alive())
        queue_depth = self._group_queue.qsize() + self._job_queue.qsize()
        return {
            'status': 'ok',
            'server_time': datetime.now().astimezone().isoformat(),
            'ready': storage_writable and group_alive and job_alive,
            'storage_writable': storage_writable,
            'worker_alive': group_alive and job_alive,
            'queue_depth': queue_depth,
            'autocad_ready': self._autocad_ready(),
            'office_ready': importlib.util.find_spec('win32com.client') is not None,
            'active_groups': self._active_group_count(),
            'active_jobs': self._active_job_count(),
        }

    def form_schema(self) -> dict[str, Any]:
        return self.metadata.build_form_schema()

    def create_batch(
        self,
        *,
        files: list[UploadedFilePayload],
        raw_params: dict[str, Any],
        run_audit_check: bool = False,
    ) -> dict[str, Any]:
        upload_errors = self._validate_uploads(files)
        resolved_submissions = [
            (upload, self._resolve_params_for_upload(raw_params, upload.filename)) for upload in files
        ]
        param_errors = self._collect_param_errors(resolved_submissions)
        if upload_errors or param_errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={'upload_errors': upload_errors, 'param_errors': param_errors},
            )

        batch_id = self._new_batch_id()
        if run_audit_check:
            groups = [
                self._create_grouped_submission(
                    batch_id=batch_id,
                    upload=upload,
                    resolved_params=resolved_params,
                )
                for upload, resolved_params in resolved_submissions
            ]
            return {'batch_id': batch_id, 'jobs': groups}

        jobs: list[dict[str, Any]] = []
        options = {'enabled': True, 'export_pdf': True, 'split_only': False}
        for upload, resolved_params in resolved_submissions:
            source_filename = Path(upload.filename).name or 'upload.dwg'
            job = self.job_manager.create_job(
                job_type=JobType.DELIVERABLE.value,
                project_no=str(resolved_params['project_no']),
                options=options,
                params=resolved_params,
                batch_id=batch_id,
                source_filename=source_filename,
            )
            self._store_job_upload(job, upload)
            self.job_manager.update_job(job)
            self._job_queue.put(job.job_id)
            jobs.append(self._serialize_job_summary(job))
        return {'batch_id': batch_id, 'jobs': jobs}

    def create_audit_batch(
        self,
        *,
        mode: str,
        files: list[UploadedFilePayload],
        raw_params: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_mode = str(mode or '').strip().lower()
        if normalized_mode != 'check':
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={'upload_errors': {}, 'param_errors': {'mode': ['unsupported_audit_mode']}},
            )

        upload_errors = self._validate_uploads(files)
        resolved_submissions = [
            (upload, self._resolve_audit_params_for_upload(raw_params, upload.filename))
            for upload in files
        ]
        param_errors = self._collect_audit_param_errors(resolved_submissions)
        if upload_errors or param_errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={'upload_errors': upload_errors, 'param_errors': param_errors},
            )

        explicit_batch_id = str(raw_params.get('batch_id') or '').strip()
        batch_id = explicit_batch_id or self._new_batch_id()
        jobs: list[dict[str, Any]] = []
        for upload, resolved_params in resolved_submissions:
            source_filename = Path(upload.filename).name or 'upload.dwg'
            job = self.job_manager.create_job(
                job_type=JobType.AUDIT_REPLACE.value,
                project_no=str(resolved_params['project_no']),
                options={'mode': 'check'},
                params={key: value for key, value in resolved_params.items() if key != 'batch_id'},
                batch_id=batch_id,
                source_filename=source_filename,
                task_role='audit_check',
            )
            self._store_job_upload(job, upload)
            self.job_manager.update_job(job)
            self._job_queue.put(job.job_id)
            jobs.append(self._serialize_job_summary(job))
        return {'batch_id': batch_id, 'jobs': jobs}

    @staticmethod
    def _resolve_params_for_upload(raw_params: dict[str, Any], filename: str) -> dict[str, Any]:
        resolved = dict(raw_params)
        resolved['project_no'] = resolve_project_no(raw_params.get('project_no'), filename)
        return resolved

    @staticmethod
    def _resolve_audit_params_for_upload(raw_params: dict[str, Any], filename: str) -> dict[str, Any]:
        resolved = dict(raw_params)
        explicit = str(raw_params.get('project_no') or '').strip()
        inferred = infer_project_no_from_path(filename)
        resolved['project_no'] = explicit or inferred or ''
        return resolved

    def _collect_param_errors(
        self,
        resolved_submissions: list[tuple[UploadedFilePayload, dict[str, Any]]],
    ) -> dict[str, list[str]]:
        merged: dict[str, list[str]] = {}
        for _, params in resolved_submissions:
            for field_name, field_errors in self.validator.validate_frontend_params(params).items():
                bucket = merged.setdefault(field_name, [])
                for error in field_errors:
                    if error not in bucket:
                        bucket.append(error)
        return merged

    @staticmethod
    def _collect_audit_param_errors(
        resolved_submissions: list[tuple[UploadedFilePayload, dict[str, Any]]],
    ) -> dict[str, list[str]]:
        merged: dict[str, list[str]] = {}
        for _, params in resolved_submissions:
            if not str(params.get('project_no') or '').strip():
                merged.setdefault('project_no', []).append('required_for_audit_check')
        return merged
    def list_jobs(self, *, status_filter: str | None = None, limit: int = 100) -> dict[str, Any]:
        groups = [
            self._serialize_group_summary(group)
            for group in self.group_manager.load_all_groups()
            if status_filter is None or group.status.value == status_filter
        ]
        standalone_jobs = [
            self._serialize_job_summary(job)
            for job in self.job_manager.load_all_jobs()
            if job.group_id is None and (status_filter is None or job.status.value == status_filter)
        ]
        items = sorted([*groups, *standalone_jobs], key=lambda item: item['created_at'], reverse=True)[:limit]
        return {'items': items, 'total': len(groups) + len(standalone_jobs)}

    def get_job_detail(self, job_id: str) -> dict[str, Any]:
        group = self.group_manager.get_group(job_id)
        if group is not None:
            return self._serialize_group_detail(group)
        job = self.job_manager.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='job not found')
        return self._serialize_job_detail(job)

    def get_artifact_path(self, job_id: str, artifact: str) -> Path:
        group = self.group_manager.get_group(job_id)
        if group is not None:
            owner_job = self._resolve_group_artifact_owner(group, artifact)
            if owner_job is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'{artifact} artifact not found')
            return self.get_artifact_path(owner_job.job_id, artifact)

        job = self.job_manager.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='job not found')
        path = {
            'package': job.artifacts.package_zip,
            'ied': job.artifacts.ied_xlsx,
            'report': job.artifacts.report_xlsx,
        }.get(artifact)
        if path is None or not Path(path).exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'{artifact} artifact not found')
        return Path(path)

    def _create_grouped_submission(
        self,
        *,
        batch_id: str,
        upload: UploadedFilePayload,
        resolved_params: dict[str, Any],
    ) -> dict[str, Any]:
        source_filename = Path(upload.filename).name or 'upload.dwg'
        group = self.group_manager.create_group(
            batch_id=batch_id,
            source_filenames=[source_filename],
            project_no=str(resolved_params['project_no']),
            run_audit_check=True,
        )
        upload_path = self._store_group_upload(group, upload)
        group.shared_dir = self.config.get_group_dir(group.group_id) / 'shared' / self._safe_source_key(source_filename)
        group.metadata['source_input_path'] = str(upload_path)

        deliverable_job = self.job_manager.create_job(
            job_type=JobType.DELIVERABLE.value,
            project_no=group.project_no,
            options={'enabled': True, 'export_pdf': True, 'split_only': False},
            params=dict(resolved_params),
            batch_id=batch_id,
            source_filename=source_filename,
            group_id=group.group_id,
            task_role='deliverable_main',
            shared_run_id=group.shared_run_id,
        )
        audit_job = self.job_manager.create_job(
            job_type=JobType.AUDIT_REPLACE.value,
            project_no=group.project_no,
            options={'mode': 'check'},
            params=dict(resolved_params),
            batch_id=batch_id,
            source_filename=source_filename,
            group_id=group.group_id,
            task_role='audit_check',
            shared_run_id=group.shared_run_id,
        )
        for child in (deliverable_job, audit_job):
            child.input_files = [upload_path.resolve()]
            self.job_manager.update_job(child)

        group.child_job_ids = [deliverable_job.job_id, audit_job.job_id]
        self.group_manager.update_group(group)
        self._group_queue.put(group.group_id)
        return self._serialize_group_summary(group)

    def _recover_groups_and_jobs(self) -> None:
        for job in self.job_manager.load_all_jobs():
            if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                if 'service_restarted_before_completion' not in job.errors:
                    job.mark_failed('service_restarted_before_completion')
                self.job_manager.update_job(job)
        for group in self.group_manager.load_all_groups():
            if group.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                if 'service_restarted_before_completion' not in group.errors:
                    group.mark_failed('service_restarted_before_completion')
                self.group_manager.update_group(group)

    def _group_dispatch_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                group_id = self._group_queue.get(timeout=0.2)
            except queue.Empty:
                self._prune_futures()
                continue
            if group_id is None:
                break
            self._prune_futures()
            future = self._group_executor.submit(self._process_group, group_id)
            with self._future_lock:
                self._group_futures.add(future)
            future.add_done_callback(self._discard_group_future)
            self._group_queue.task_done()

    def _job_dispatch_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job_id = self._job_queue.get(timeout=0.2)
            except queue.Empty:
                self._prune_futures()
                continue
            if job_id is None:
                break
            self._prune_futures()
            future = self._heavy_executor.submit(self._run_job, job_id)
            with self._future_lock:
                self._job_futures.add(future)
            future.add_done_callback(self._discard_job_future)
            self._job_queue.task_done()

    def _process_group(self, group_id: str) -> None:
        group = self.group_manager.get_group(group_id)
        if group is None or group.status != JobStatus.QUEUED:
            return
        try:
            group.mark_running('PREP_SOURCE')
            group.progress.percent = 5
            group.progress.message = '共享前处理准备中'
            self.group_manager.update_group(group)

            source_input = self._resolve_group_source_input(group)
            shared_dir = group.shared_dir or (self.config.get_group_dir(group.group_id) / 'shared' / self._safe_source_key(source_input.name))
            prep = self.shared_prep_service.prepare(group_id=group.group_id, source_dwg=source_input, shared_dir=shared_dir)
            group.shared_dir = prep.shared_dir
            group.progress.percent = 35
            group.progress.message = '共享前处理完成'
            self.group_manager.update_group(group)

            for child_job_id in group.child_job_ids:
                child = self.job_manager.get_job(child_job_id)
                if child is None:
                    continue
                child.params['shared_prep_dir'] = str(prep.shared_dir)
                child.params['shared_source_dwg'] = str(prep.source_input_dwg)
                child.params['shared_source_dxf'] = str(prep.source_converted_dxf)
                self.job_manager.update_job(child)

            group.progress.stage = 'DELIVERABLE_BRANCH' if group.run_audit_check else 'DOCS_AND_PACKAGE'
            group.progress.percent = 45
            group.progress.message = '子任务执行中'
            self.group_manager.update_group(group)

            child_futures = [self._heavy_executor.submit(self._run_job, child_job_id) for child_job_id in group.child_job_ids]
            wait(child_futures)

            children = [child for child in (self.job_manager.get_job(job_id) for job_id in group.child_job_ids) if child is not None]
            group.flags = self._merge_unique(*(child.flags for child in children))
            group.errors = self._merge_unique(*(child.errors for child in children))
            group.artifacts = self._merge_group_artifacts(children)
            group.progress.stage = 'GROUP_COMPLETE'
            group.progress.percent = 100
            group.progress.message = '任务完成'
            if any(child.status == JobStatus.FAILED for child in children):
                group.mark_failed('child_job_failed')
            else:
                group.mark_succeeded()
            self.group_manager.update_group(group)
        except Exception as exc:  # noqa: BLE001
            group.mark_failed(str(exc))
            group.progress.message = f'任务组失败: {exc}'
            self.group_manager.update_group(group)

    def _run_job(self, job_id: str) -> None:
        job = self.job_manager.get_job(job_id)
        if job is None or job.status != JobStatus.QUEUED:
            return
        slot = None
        try:
            slot = self.cad_slot_pool.acquire(job.job_id, timeout=300)
            job.slot_id = slot.slot_id
            job.cad_version = str(slot.cad_version) if slot.cad_version is not None else None
            job.accoreconsole_exe = str(slot.accoreconsole_exe) if slot.accoreconsole_exe else None
            job.profile_arg = str(slot.profile_arg_path)
            job.pc3_path = str(slot.plotters_dir / self.config.module5_export.plot.pc3_name)
            job.pmp_path = str(slot.pmp_dir / "tszdef-02fc5f1cb3db4a5b8afc9cce5dca6cd1.pmp")
            job.ctb_path = str(slot.plot_styles_dir / self.config.module5_export.plot.ctb_name)
            job.params["cad_slot_id"] = slot.slot_id
            job.params["cad_slot_root"] = str(slot.slot_root)
            job.params["cad_slot_profile_arg"] = str(slot.profile_arg_path)
            job.params["cad_slot_plotters_dir"] = str(slot.plotters_dir)
            job.params["cad_slot_pmp_dir"] = str(slot.pmp_dir)
            job.params["cad_slot_plot_styles_dir"] = str(slot.plot_styles_dir)
            job.params["cad_slot_runtime"] = {
                "slot_id": slot.slot_id,
                "slot_root": str(slot.slot_root),
                "profile_arg": str(slot.profile_arg_path),
                "plotters_dir": str(slot.plotters_dir),
                "pmp_dir": str(slot.pmp_dir),
                "plot_styles_dir": str(slot.plot_styles_dir),
                "spool_dir": str(slot.spool_dir),
                "temp_dir": str(slot.temp_dir),
            }
            job.work_dir = self.config.get_job_dir(job.job_id)
            job.work_dir.mkdir(parents=True, exist_ok=True)
            self.job_processor(job)
        except Exception as exc:  # noqa: BLE001
            if job.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
                job.mark_failed(str(exc))
        finally:
            self.job_manager.update_job(job)
            if slot is not None:
                self.cad_slot_pool.release(slot.slot_id)
    def _resolve_group_source_input(self, group: TaskGroup) -> Path:
        raw = str(group.metadata.get('source_input_path') or '').strip()
        if raw:
            return Path(raw).resolve()
        for child_job_id in group.child_job_ids:
            child = self.job_manager.get_job(child_job_id)
            if child and child.input_files:
                return Path(child.input_files[0]).resolve()
        raise FileNotFoundError(f'group source input not found: {group.group_id}')

    def _storage_writable(self) -> bool:
        try:
            self.config.ensure_dirs()
            probe = self.config.storage_dir / '.api-healthcheck'
            probe.write_text('ok', encoding='utf-8')
            probe.unlink(missing_ok=True)
        except Exception:
            return False
        return True

    def _autocad_ready(self) -> bool:
        configured_runner = str(self.config.module5_export.cad_runner.accoreconsole_exe or '').strip()
        if configured_runner and Path(configured_runner).is_file():
            return True
        detected = resolve_autocad_paths(configured_install_dir=self.config.autocad.install_dir).accoreconsole_exe
        return detected is not None and Path(detected).is_file()

    def _validate_uploads(self, files: list[UploadedFilePayload]) -> dict[str, list[str]]:
        errors: dict[str, list[str]] = {}
        limits = self.config.upload_limits
        if not files:
            errors.setdefault('files', []).append('at least one file is required')
            return errors
        if len(files) > limits.max_files:
            errors.setdefault('files', []).append(f'too many files: max {limits.max_files}')
        allowed_exts = {ext.lower() for ext in limits.allowed_exts}
        invalid = [upload.filename for upload in files if Path(upload.filename).suffix.lower() not in allowed_exts]
        if invalid:
            errors.setdefault('files', []).append('only .dwg files are allowed')
        max_total_bytes = limits.max_total_mb * 1024 * 1024
        if sum(len(upload.content) for upload in files) > max_total_bytes:
            errors.setdefault('files', []).append(f'total upload exceeds {limits.max_total_mb} MB')
        return errors

    def _store_job_upload(self, job: Job, upload: UploadedFilePayload) -> None:
        job_dir = self.config.get_job_dir(job.job_id)
        upload_dir = job_dir / 'uploads'
        upload_dir.mkdir(parents=True, exist_ok=True)
        upload_path = upload_dir / (Path(upload.filename).name or f'{job.job_id}.dwg')
        upload_path.write_bytes(upload.content)
        job.work_dir = job_dir
        job.input_files = [upload_path.resolve()]

    def _store_group_upload(self, group: TaskGroup, upload: UploadedFilePayload) -> Path:
        group_dir = self.config.get_group_dir(group.group_id)
        upload_dir = group_dir / 'input'
        upload_dir.mkdir(parents=True, exist_ok=True)
        upload_path = upload_dir / (Path(upload.filename).name or f'{group.group_id}.dwg')
        upload_path.write_bytes(upload.content)
        return upload_path.resolve()

    @staticmethod
    def _new_batch_id() -> str:
        return f"batch-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

    @staticmethod
    def _safe_source_key(source_name: str) -> str:
        stem = Path(source_name).stem
        safe = ''.join(ch if ch.isalnum() or ch in ('-', '_') else '_' for ch in stem)
        return safe.strip('_') or 'source'

    def _serialize_job_summary(self, job: Job) -> dict[str, Any]:
        task_kind = 'deliverable'
        job_mode = 'deliverable'
        if job.job_type == JobType.AUDIT_REPLACE:
            mode = str(job.options.get('mode', '')).strip().lower()
            if mode == 'check':
                task_kind = 'audit_check'
                job_mode = 'check'
            else:
                task_kind = 'audit_replace'
                job_mode = mode or 'replace'
        return {
            'job_id': job.job_id,
            'batch_id': job.batch_id,
            'group_id': job.group_id,
            'shared_run_id': job.shared_run_id,
            'task_role': job.task_role,
            'is_group': False,
            'source_filename': job.source_filename,
            'task_kind': task_kind,
            'job_mode': job_mode,
            'project_no': job.project_no,
            'status': job.status.value,
            'stage': job.progress.stage,
            'percent': job.progress.percent,
            'message': job.progress.message,
            'created_at': job.created_at.isoformat(),
            'finished_at': job.finished_at.isoformat() if job.finished_at else None,
            'artifacts': self._serialize_job_artifacts(job),
            'findings_count': int(job.progress.details.get('findings_count', 0) or 0),
            'affected_drawings_count': int(job.progress.details.get('affected_drawings_count', 0) or 0),
            'retry_available': False,
        }

    def _serialize_job_detail(self, job: Job) -> dict[str, Any]:
        payload = self._serialize_job_summary(job)
        payload.update({
            'started_at': job.started_at.isoformat() if job.started_at else None,
            'current_file': job.progress.current_file,
            'flags': job.flags,
            'errors': job.errors,
            'top_wrong_texts': list(job.progress.details.get('top_wrong_texts', []) or []),
            'top_internal_codes': list(job.progress.details.get('top_internal_codes', []) or []),
            'artifacts': self._serialize_job_artifacts(job, include_urls=True, job_id=job.job_id),
            'slot_id': job.slot_id,
            'cad_version': job.cad_version,
            'accoreconsole_exe': job.accoreconsole_exe,
            'profile_arg': job.profile_arg,
            'pc3_path': job.pc3_path,
            'pmp_path': job.pmp_path,
            'ctb_path': job.ctb_path,
        })
        return payload

    def _serialize_job_artifacts(self, job: Job, *, include_urls: bool = False, job_id: str | None = None) -> dict[str, Any]:
        package_available = bool(job.artifacts.package_zip and Path(job.artifacts.package_zip).exists())
        ied_available = bool(job.artifacts.ied_xlsx and Path(job.artifacts.ied_xlsx).exists())
        report_available = bool(job.artifacts.report_xlsx and Path(job.artifacts.report_xlsx).exists())
        replaced_dwg_available = bool(job.artifacts.replaced_dwg and Path(job.artifacts.replaced_dwg).exists())
        payload: dict[str, Any] = {
            'package_available': package_available,
            'ied_available': ied_available,
            'report_available': report_available,
            'replaced_dwg_available': replaced_dwg_available,
        }
        if include_urls and job_id is not None:
            payload.update({
                'package_download_url': f'/api/jobs/{job_id}/download/package' if package_available else None,
                'ied_download_url': f'/api/jobs/{job_id}/download/ied' if ied_available else None,
                'report_download_url': f'/api/jobs/{job_id}/download/report' if report_available else None,
                'replaced_dwg_download_url': None,
            })
        return payload
    def _serialize_group_summary(self, group: TaskGroup) -> dict[str, Any]:
        source_filename = group.source_filenames[0] if group.source_filenames else None
        findings_count = 0
        affected_drawings_count = 0
        for child in self._iter_group_children(group):
            findings_count = max(findings_count, int(child.progress.details.get('findings_count', 0) or 0))
            affected_drawings_count = max(
                affected_drawings_count,
                int(child.progress.details.get('affected_drawings_count', 0) or 0),
            )
        return {
            'job_id': group.group_id,
            'group_id': group.group_id,
            'batch_id': group.batch_id,
            'is_group': True,
            'source_filename': source_filename,
            'source_filenames': list(group.source_filenames),
            'project_no': group.project_no,
            'status': group.status.value,
            'stage': group.progress.stage,
            'percent': group.progress.percent,
            'message': group.progress.message,
            'created_at': group.created_at.isoformat(),
            'finished_at': group.finished_at.isoformat() if group.finished_at else None,
            'run_audit_check': group.run_audit_check,
            'child_job_ids': list(group.child_job_ids),
            'artifacts': self._serialize_group_artifacts(group),
            'findings_count': findings_count,
            'affected_drawings_count': affected_drawings_count,
            'retry_available': False,
        }

    def _serialize_group_detail(self, group: TaskGroup) -> dict[str, Any]:
        payload = self._serialize_group_summary(group)
        payload.update({
            'started_at': group.started_at.isoformat() if group.started_at else None,
            'flags': list(group.flags),
            'errors': list(group.errors),
            'shared_run_id': group.shared_run_id,
            'shared_dir': str(group.shared_dir) if group.shared_dir else None,
            'children': [self._serialize_job_summary(child) for child in self._iter_group_children(group)],
        })
        return payload

    def _serialize_group_artifacts(self, group: TaskGroup) -> dict[str, Any]:
        artifacts = self._merge_group_artifacts(self._iter_group_children(group))
        package_available = bool(artifacts.package_zip and Path(artifacts.package_zip).exists())
        ied_available = bool(artifacts.ied_xlsx and Path(artifacts.ied_xlsx).exists())
        report_available = bool(artifacts.report_xlsx and Path(artifacts.report_xlsx).exists())
        return {
            'package_available': package_available,
            'ied_available': ied_available,
            'report_available': report_available,
            'replaced_dwg_available': False,
            'package_download_url': f'/api/jobs/{group.group_id}/download/package' if package_available else None,
            'ied_download_url': f'/api/jobs/{group.group_id}/download/ied' if ied_available else None,
            'report_download_url': f'/api/jobs/{group.group_id}/download/report' if report_available else None,
        }

    def _resolve_group_artifact_owner(self, group: TaskGroup, artifact: str) -> Job | None:
        for child in self._iter_group_children(group):
            if artifact == 'package' and child.artifacts.package_zip:
                return child
            if artifact == 'ied' and child.artifacts.ied_xlsx:
                return child
            if artifact == 'report' and child.artifacts.report_xlsx:
                return child
        return None

    @staticmethod
    def _merge_unique(*groups: list[str]) -> list[str]:
        merged: list[str] = []
        for items in groups:
            for item in items:
                if item not in merged:
                    merged.append(item)
        return merged

    @staticmethod
    def _merge_group_artifacts(children: list[Job]) -> JobArtifacts:
        merged = JobArtifacts()
        for child in children:
            if merged.package_zip is None and child.artifacts.package_zip:
                merged.package_zip = child.artifacts.package_zip
            if merged.ied_xlsx is None and child.artifacts.ied_xlsx:
                merged.ied_xlsx = child.artifacts.ied_xlsx
            if merged.drawings_dir is None and child.artifacts.drawings_dir:
                merged.drawings_dir = child.artifacts.drawings_dir
            if merged.docs_dir is None and child.artifacts.docs_dir:
                merged.docs_dir = child.artifacts.docs_dir
            if merged.reports_dir is None and child.artifacts.reports_dir:
                merged.reports_dir = child.artifacts.reports_dir
            if merged.report_xlsx is None and child.artifacts.report_xlsx:
                merged.report_xlsx = child.artifacts.report_xlsx
            if merged.report_json is None and child.artifacts.report_json:
                merged.report_json = child.artifacts.report_json
            if merged.replaced_dwg is None and child.artifacts.replaced_dwg:
                merged.replaced_dwg = child.artifacts.replaced_dwg
        return merged

    def _iter_group_children(self, group: TaskGroup) -> list[Job]:
        children: list[Job] = []
        for child_job_id in group.child_job_ids:
            child = self.job_manager.get_job(child_job_id)
            if child is not None:
                children.append(child)
        return children

    def _discard_group_future(self, future: Future[None]) -> None:
        with self._future_lock:
            self._group_futures.discard(future)

    def _discard_job_future(self, future: Future[None]) -> None:
        with self._future_lock:
            self._job_futures.discard(future)

    def _prune_futures(self) -> None:
        with self._future_lock:
            self._group_futures = {future for future in self._group_futures if not future.done()}
            self._job_futures = {future for future in self._job_futures if not future.done()}

    def _active_group_count(self) -> int:
        self._prune_futures()
        with self._future_lock:
            return len(self._group_futures)

    def _active_job_count(self) -> int:
        self._prune_futures()
        with self._future_lock:
            return len(self._job_futures)
