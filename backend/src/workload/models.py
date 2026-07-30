from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class WorkloadSettlementStatus(StrEnum):
    PENDING = "pending"
    SETTLED = "settled"


class WorkloadContributorEntry(BaseModel):
    role_key: str
    account_id: str | None = None
    display_name: str | None = None
    workload_a1: float = 0.0
    settled_at: datetime | None = None


class WorkloadSummary(BaseModel):
    initial_workload_a1: float = 0.0
    final_workload_a1: float = 0.0
    one_review_factor: float = 1.0
    two_review_factor: float = 1.0
    three_review_factor: float = 1.0
    node_factors: dict[str, float] = Field(default_factory=dict)
    settlement_status: WorkloadSettlementStatus = WorkloadSettlementStatus.PENDING
    settled_at: datetime | None = None
    contributor_entries: list[WorkloadContributorEntry] = Field(default_factory=list)
