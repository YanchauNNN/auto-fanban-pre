from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from ..config import get_config
from ..interfaces import IJobManager
from ..models import Job, JobStatus, JobType
from ..models.task_group_management import AccountSnapshot, TaskOwnerSnapshot


class JobManager(IJobManager):
    """Manage job creation, persistence, querying, and cancellation."""

    def __init__(self) -> None:
        self.config = get_config()
        self._jobs: dict[str, Job] = {}

    def create_job(
        self,
        job_type: str,
        project_no: str,
        input_files: list[Path] | None = None,
        options: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        batch_id: str | None = None,
        source_filename: str | None = None,
        group_id: str | None = None,
        task_role: str | None = None,
        shared_run_id: str | None = None,
        creator_snapshot: AccountSnapshot | None = None,
        owner_snapshot: TaskOwnerSnapshot | None = None,
        **kwargs: Any,
    ) -> Job:
        """Create a new job and persist its initial metadata."""
        input_files = kwargs.get("input_files", input_files)
        options = kwargs.get("options", options)
        params = kwargs.get("params", params)
        batch_id = kwargs.get("batch_id", batch_id)
        source_filename = kwargs.get("source_filename", source_filename)
        group_id = kwargs.get("group_id", group_id)
        task_role = kwargs.get("task_role", task_role)
        shared_run_id = kwargs.get("shared_run_id", shared_run_id)
        creator_snapshot = kwargs.get("creator_snapshot", creator_snapshot)
        owner_snapshot = kwargs.get("owner_snapshot", owner_snapshot)
        if owner_snapshot is None and creator_snapshot is not None:
            owner_snapshot = TaskOwnerSnapshot(
                creator_account=creator_snapshot.account_id,
                creator_name=creator_snapshot.display_name,
                creator_role=creator_snapshot.role,
                creator_office=creator_snapshot.office_name,
            )

        job_id = str(uuid.uuid4())

        job = Job(
            job_id=job_id,
            job_type=JobType(job_type),
            project_no=project_no,
            batch_id=batch_id,
            source_filename=source_filename,
            group_id=group_id,
            task_role=task_role,
            shared_run_id=shared_run_id,
            owner_snapshot=owner_snapshot,
            input_files=input_files or [],
            options=options or {},
            params=params or {},
        )

        self._jobs[job_id] = job
        self._persist_job(job)
        return job

    def get_job(self, job_id: str) -> Job | None:
        """Load a job from cache or disk."""
        if job_id in self._jobs:
            return self._jobs[job_id]

        job = self._load_job(job_id)
        if job is not None:
            self._jobs[job_id] = job
        return job

    def reload_job(self, job_id: str) -> Job | None:
        """Reload a job from disk and refresh the in-memory cache."""
        job = self._load_job(job_id)
        if job is not None:
            self._jobs[job.job_id] = job
        return job

    def update_job(self, job: Job) -> None:
        """Persist updated job state."""
        self._jobs[job.job_id] = job
        self._persist_job(job)

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a queued or running job."""
        job = self.get_job(job_id)
        if not job:
            return False

        if job.status in [JobStatus.QUEUED, JobStatus.RUNNING]:
            job.status = JobStatus.CANCELLED
            self.update_job(job)
            return True

        return False

    def list_jobs(
        self,
        status: JobStatus | None = None,
        limit: int = 100,
    ) -> list[Job]:
        """List jobs, optionally filtered by status."""
        jobs = list(self._jobs.values())

        if status:
            jobs = [j for j in jobs if j.status == status]

        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def load_all_jobs(self) -> list[Job]:
        """Load all jobs from disk and refresh the in-memory cache."""
        jobs_root = self.config.storage_dir / "jobs"
        if not jobs_root.exists():
            jobs = list(self._jobs.values())
            jobs.sort(key=lambda j: j.created_at, reverse=True)
            return jobs

        loaded_by_id: dict[str, Job] = dict(self._jobs)
        for job_file in sorted(jobs_root.glob("*/job.json")):
            try:
                with open(job_file, encoding="utf-8") as f:
                    data = json.load(f)
                job = Job(**data)
            except Exception:
                continue
            self._jobs[job.job_id] = job
            loaded_by_id[job.job_id] = job

        loaded = list(loaded_by_id.values())
        loaded.sort(key=lambda j: j.created_at, reverse=True)
        return loaded

    def _persist_job(self, job: Job) -> None:
        """Persist job metadata to disk."""
        job_dir = self.config.get_job_dir(job.job_id)
        job_dir.mkdir(parents=True, exist_ok=True)

        job_file = job_dir / "job.json"
        tmp_file = job_dir / "job.json.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(job.model_dump(mode="json"), f, ensure_ascii=False, indent=2, default=str)
        for attempt in range(5):
            try:
                tmp_file.replace(job_file)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02)

    def _load_job(self, job_id: str) -> Job | None:
        """Load job metadata from disk."""
        job_file = self.config.get_job_dir(job_id) / "job.json"

        if not job_file.exists():
            return None

        try:
            with open(job_file, encoding="utf-8") as f:
                data = json.load(f)
            return Job(**data)
        except Exception:
            return None

    def delete_job(self, job_id: str) -> None:
        """Remove a job from cache and delete its persisted artifacts."""
        self._jobs.pop(job_id, None)
        job_dir = self.config.get_job_dir(job_id)
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
