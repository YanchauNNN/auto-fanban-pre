from __future__ import annotations

import importlib.util
import queue
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException, status

from .metadata import FormMetadataService

from src.audit_check.executor import AuditCheckExecutor
from src.cad.autocad_path_resolver import resolve_autocad_paths
from src.config import get_config
from src.doc_gen.param_validator import DocParamValidator
from src.models import Job, JobStatus, JobType
from src.pipeline.executor import PipelineExecutor
from src.pipeline.job_manager import JobManager
from src.pipeline.project_no_inference import infer_project_no_from_path, resolve_project_no


@dataclass(frozen=True)
class UploadedFilePayload:
    filename: str
    content: bytes
    content_type: str | None = None


class PipelineJobProcessor:
    def __init__(self) -> None:
        self.deliverable_executor = PipelineExecutor()
        self.audit_executor = AuditCheckExecutor()

    def __call__(self, job: Job) -> None:
        if job.job_type == JobType.AUDIT_REPLACE:
            self.audit_executor.execute(job)
            return
        self.deliverable_executor.execute(job)


class DeliverableApiRuntime:
    def __init__(self, job_processor: Callable[[Job], None] | None = None) -> None:
        self.config = get_config()
        self.config.ensure_dirs()
        self.job_manager = JobManager()
        self.validator = DocParamValidator()
        self.metadata = FormMetadataService()
        self.job_processor = job_processor or PipelineJobProcessor()
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None

    def start(self) -> None:
        self._recover_jobs()
        if self._worker_thread and self._worker_thread.is_alive():
            return

        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="deliverable-api-worker",
            daemon=True,
        )
        self._worker_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._queue.put(None)
        if self._worker_thread:
            self._worker_thread.join(timeout=3)

    def health(self) -> dict[str, Any]:
        storage_writable = self._storage_writable()
        worker_alive = bool(self._worker_thread and self._worker_thread.is_alive())
        autocad_ready = self._autocad_ready()
        office_ready = importlib.util.find_spec("win32com.client") is not None
        return {
            "status": "ok",
            "server_time": datetime.now().astimezone().isoformat(),
            "ready": storage_writable and worker_alive,
            "storage_writable": storage_writable,
            "worker_alive": worker_alive,
            "queue_depth": self._queue.qsize(),
            "autocad_ready": autocad_ready,
            "office_ready": office_ready,
        }

    def _autocad_ready(self) -> bool:
        configured_runner = str(self.config.module5_export.cad_runner.accoreconsole_exe or "").strip()
        if configured_runner and Path(configured_runner).is_file():
            return True

        detected = resolve_autocad_paths(
            configured_install_dir=self.config.autocad.install_dir,
        ).accoreconsole_exe
        return detected is not None and Path(detected).is_file()

    def form_schema(self) -> dict[str, Any]:
        return self.metadata.build_form_schema()

    def create_batch(self, *, files: list[UploadedFilePayload], raw_params: dict[str, Any]) -> dict[str, Any]:
        upload_errors = self._validate_uploads(files)
        resolved_submissions = [
            (upload, self._resolve_params_for_upload(raw_params, upload.filename)) for upload in files
        ]
        param_errors = self._collect_param_errors(resolved_submissions)

        if upload_errors or param_errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "upload_errors": upload_errors,
                    "param_errors": param_errors,
                },
            )

        batch_id = self._new_batch_id()
        jobs: list[dict[str, Any]] = []
        options = {
            "enabled": True,
            "export_pdf": True,
            "split_only": False,
        }

        for upload, resolved_params in resolved_submissions:
            source_filename = Path(upload.filename).name or "upload.dwg"
            job = self.job_manager.create_job(
                job_type=JobType.DELIVERABLE.value,
                project_no=str(resolved_params["project_no"]),
                options=options,
                params=resolved_params,
                batch_id=batch_id,
                source_filename=source_filename,
            )
            self._store_upload(job, upload)
            self.job_manager.update_job(job)
            self._queue.put(job.job_id)
            jobs.append(self._serialize_summary(job))

        return {
            "batch_id": batch_id,
            "jobs": jobs,
        }

    def create_audit_batch(
        self,
        *,
        mode: str,
        files: list[UploadedFilePayload],
        raw_params: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_mode = str(mode or "").strip().lower()
        if normalized_mode != "check":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "upload_errors": {},
                    "param_errors": {"mode": ["unsupported_audit_mode"]},
                },
            )

        upload_errors = self._validate_uploads(files)
        resolved_submissions = [
            (upload, self._resolve_audit_params_for_upload(raw_params, upload.filename)) for upload in files
        ]
        param_errors = self._collect_audit_param_errors(resolved_submissions)

        if upload_errors or param_errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "upload_errors": upload_errors,
                    "param_errors": param_errors,
                },
            )

        explicit_batch_id = str(raw_params.get("batch_id") or "").strip()
        batch_id = explicit_batch_id or self._new_batch_id()
        jobs: list[dict[str, Any]] = []
        options = {"mode": "check"}

        for upload, resolved_params in resolved_submissions:
            source_filename = Path(upload.filename).name or "upload.dwg"
            job = self.job_manager.create_job(
                job_type=JobType.AUDIT_REPLACE.value,
                project_no=str(resolved_params["project_no"]),
                options=options,
                params={key: value for key, value in resolved_params.items() if key != "batch_id"},
                batch_id=batch_id,
                source_filename=source_filename,
            )
            self._store_upload(job, upload)
            self.job_manager.update_job(job)
            self._queue.put(job.job_id)
            jobs.append(self._serialize_summary(job))

        return {
            "batch_id": batch_id,
            "jobs": jobs,
        }

    @staticmethod
    def _resolve_params_for_upload(raw_params: dict[str, Any], filename: str) -> dict[str, Any]:
        resolved = dict(raw_params)
        resolved["project_no"] = resolve_project_no(raw_params.get("project_no"), filename)
        return resolved

    @staticmethod
    def _resolve_audit_params_for_upload(raw_params: dict[str, Any], filename: str) -> dict[str, Any]:
        resolved = dict(raw_params)
        explicit = str(raw_params.get("project_no") or "").strip()
        inferred = infer_project_no_from_path(filename)
        resolved["project_no"] = explicit or inferred or ""
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
            project_no = str(params.get("project_no") or "").strip()
            if not project_no:
                merged.setdefault("project_no", []).append("required_for_audit_check")
        return merged

    def list_jobs(self, *, status_filter: str | None = None, limit: int = 100) -> dict[str, Any]:
        jobs = self.job_manager.load_all_jobs()
        if status_filter:
            jobs = [job for job in jobs if job.status.value == status_filter]

        items = [self._serialize_summary(job) for job in jobs[:limit]]
        return {
            "items": items,
            "total": len(jobs),
        }

    def get_job_detail(self, job_id: str) -> dict[str, Any]:
        job = self.job_manager.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
        return self._serialize_detail(job)

    def get_artifact_path(self, job_id: str, artifact: str) -> Path:
        job = self.job_manager.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")

        path = {
            "package": job.artifacts.package_zip,
            "ied": job.artifacts.ied_xlsx,
            "report": job.artifacts.report_xlsx,
        }.get(artifact)

        if path is None or not Path(path).exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{artifact} artifact not found",
            )
        return Path(path)

    def _recover_jobs(self) -> None:
        for job in self.job_manager.load_all_jobs():
            if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                if "service_restarted_before_completion" not in job.errors:
                    job.mark_failed("service_restarted_before_completion")
                self.job_manager.update_job(job)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job_id = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if job_id is None:
                break

            job = self.job_manager.get_job(job_id)
            if job is None or job.status != JobStatus.QUEUED:
                continue

            try:
                job.work_dir = self.config.get_job_dir(job.job_id)
                job.work_dir.mkdir(parents=True, exist_ok=True)
                self.job_processor(job)
            except Exception as exc:  # noqa: BLE001
                if job.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
                    job.mark_failed(str(exc))
            finally:
                self.job_manager.update_job(job)
                self._queue.task_done()

    def _storage_writable(self) -> bool:
        try:
            self.config.ensure_dirs()
            probe = self.config.storage_dir / ".api-healthcheck"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except Exception:
            return False
        return True

    def _validate_uploads(self, files: list[UploadedFilePayload]) -> dict[str, list[str]]:
        errors: dict[str, list[str]] = {}
        limits = self.config.upload_limits

        if not files:
            errors.setdefault("files", []).append("at least one file is required")
            return errors

        if len(files) > limits.max_files:
            errors.setdefault("files", []).append(f"too many files: max {limits.max_files}")

        allowed_exts = {ext.lower() for ext in limits.allowed_exts}
        invalid = [
            upload.filename
            for upload in files
            if Path(upload.filename).suffix.lower() not in allowed_exts
        ]
        if invalid:
            errors.setdefault("files", []).append("only .dwg files are allowed")

        max_total_bytes = limits.max_total_mb * 1024 * 1024
        total_bytes = sum(len(upload.content) for upload in files)
        if total_bytes > max_total_bytes:
            errors.setdefault("files", []).append(
                f"total upload exceeds {limits.max_total_mb} MB",
            )

        return errors

    def _store_upload(self, job: Job, upload: UploadedFilePayload) -> None:
        job_dir = self.config.get_job_dir(job.job_id)
        upload_dir = job_dir / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        upload_path = upload_dir / (Path(upload.filename).name or f"{job.job_id}.dwg")
        upload_path.write_bytes(upload.content)
        job.work_dir = job_dir
        job.input_files = [upload_path.resolve()]

    @staticmethod
    def _new_batch_id() -> str:
        return f"batch-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

    def _serialize_summary(self, job: Job) -> dict[str, Any]:
        task_kind = "deliverable"
        job_mode = "deliverable"
        if job.job_type == JobType.AUDIT_REPLACE:
            mode = str(job.options.get("mode", "")).strip().lower()
            if mode == "check":
                task_kind = "audit_check"
                job_mode = "check"
            else:
                task_kind = "audit_replace"
                job_mode = mode or "replace"
        return {
            "job_id": job.job_id,
            "batch_id": job.batch_id,
            "source_filename": job.source_filename,
            "task_kind": task_kind,
            "job_mode": job_mode,
            "project_no": job.project_no,
            "status": job.status.value,
            "stage": job.progress.stage,
            "percent": job.progress.percent,
            "message": job.progress.message,
            "created_at": job.created_at.isoformat(),
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            "artifacts": self._serialize_artifacts(job),
            "findings_count": int(job.progress.details.get("findings_count", 0) or 0),
            "affected_drawings_count": int(job.progress.details.get("affected_drawings_count", 0) or 0),
            "retry_available": False,
        }

    def _serialize_detail(self, job: Job) -> dict[str, Any]:
        data = self._serialize_summary(job)
        data.update(
            {
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "current_file": job.progress.current_file,
                "flags": job.flags,
                "errors": job.errors,
                "top_wrong_texts": list(job.progress.details.get("top_wrong_texts", []) or []),
                "top_internal_codes": list(job.progress.details.get("top_internal_codes", []) or []),
                "artifacts": self._serialize_artifacts(job, include_urls=True, job_id=job.job_id),
            },
        )
        return data

    def _serialize_artifacts(
        self,
        job: Job,
        *,
        include_urls: bool = False,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        package_available = bool(job.artifacts.package_zip and Path(job.artifacts.package_zip).exists())
        ied_available = bool(job.artifacts.ied_xlsx and Path(job.artifacts.ied_xlsx).exists())
        report_available = bool(job.artifacts.report_xlsx and Path(job.artifacts.report_xlsx).exists())
        replaced_dwg_available = bool(job.artifacts.replaced_dwg and Path(job.artifacts.replaced_dwg).exists())
        payload = {
            "package_available": package_available,
            "ied_available": ied_available,
            "report_available": report_available,
            "replaced_dwg_available": replaced_dwg_available,
        }
        if include_urls and job_id is not None:
            payload.update(
                {
                    "package_download_url": f"/api/jobs/{job_id}/download/package" if package_available else None,
                    "ied_download_url": f"/api/jobs/{job_id}/download/ied" if ied_available else None,
                    "report_download_url": f"/api/jobs/{job_id}/download/report" if report_available else None,
                    "replaced_dwg_download_url": None,
                },
            )
        return payload
