from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class ArchiveStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ArchiveState(BaseModel):
    archive_root_path: str | None = None
    target_dir: Path | None = None
    status: ArchiveStatus = ArchiveStatus.PENDING
    overwrite_mode: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_error: str | None = None
    retry_count: int = 0
    last_attempt_at: datetime | None = None
    archived_files: list[str] = Field(default_factory=list)
