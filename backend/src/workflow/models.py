from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class WorkflowNodeStatus(StrEnum):
    PENDING = "pending"
    CURRENT = "current"
    APPROVED = "approved"
    CANCELLED = "cancelled"


class WorkflowStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    IN_REVIEW = "in_review"
    THREE_REVIEW_APPROVED = "three_review_approved"
    ARCHIVING = "archiving"
    ARCHIVED = "archived"
    ARCHIVE_FAILED = "archive_failed"
    CANCELLED = "cancelled"


class WorkflowNodeState(BaseModel):
    node_key: str
    node_label: str
    assignee_account: str | None = None
    assignee_name: str | None = None
    status: WorkflowNodeStatus = WorkflowNodeStatus.PENDING
    factor: float = 1.0
    approved_at: datetime | None = None
    acted_by_account: str | None = None
    acted_by_name: str | None = None


class WorkflowState(BaseModel):
    status: WorkflowStatus = WorkflowStatus.DRAFT
    initiated_at: datetime | None = None
    initiated_by_account: str | None = None
    initiated_by_name: str | None = None
    duplicate_policy: str | None = None
    overwrite_archive_target: str | None = None
    current_node_key: str | None = None
    nodes: list[WorkflowNodeState] = Field(default_factory=list)
    archive_status: str | None = None
    archive_retry_count: int = 0
    archive_last_error: str | None = None
    archive_last_attempt_at: datetime | None = None
