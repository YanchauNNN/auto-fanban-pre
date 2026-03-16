from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .job import JobArtifacts, JobProgress, JobStatus


class TaskGroup(BaseModel):
    group_id: str = Field(..., description="top-level task group id")
    batch_id: str | None = None
    source_filenames: list[str] = Field(default_factory=list)
    project_no: str
    status: JobStatus = JobStatus.QUEUED
    progress: JobProgress = Field(default_factory=JobProgress)
    run_audit_check: bool = False
    shared_run_id: str | None = None
    child_job_ids: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    shared_dir: Path | None = None
    artifacts: JobArtifacts = Field(default_factory=JobArtifacts)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}

    def mark_running(self, stage: str) -> None:
        self.status = JobStatus.RUNNING
        if self.started_at is None:
            self.started_at = datetime.now()
        self.progress.stage = stage

    def mark_succeeded(self) -> None:
        self.status = JobStatus.SUCCEEDED
        self.finished_at = datetime.now()
        self.progress.percent = 100

    def mark_failed(self, error: str) -> None:
        self.status = JobStatus.FAILED
        self.finished_at = datetime.now()
        self.errors.append(error)

    def add_flag(self, flag: str) -> None:
        if flag not in self.flags:
            self.flags.append(flag)
