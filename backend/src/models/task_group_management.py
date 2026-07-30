from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AccountSnapshot(BaseModel):
    account_id: str
    display_name: str
    role: str
    office_code: str | None = None
    office_name: str | None = None
    valid: bool = True


class TaskOwnerSnapshot(BaseModel):
    creator_account: str
    creator_name: str
    creator_role: str
    creator_office: str | None = None
    created_by_scope: str = ""
    submitted_at: datetime | None = None


class NormalizedPersonnel(BaseModel):
    field_name: str
    raw_value: str | None = None
    normalized_value: str | None = None
    matched_account: str | None = None
    matched_name: str | None = None
    match_strategy: str | None = None
    status: str = "empty"
    errors: list[str] = Field(default_factory=list)


class PersonnelSnapshot(BaseModel):
    members: dict[str, NormalizedPersonnel] = Field(default_factory=dict)


class ReplacementState(BaseModel):
    album_internal_code: str | None = None
    revision: str | None = None
    replaced_group_id: str | None = None
    replaced_record_pending_delete: bool = False


class LegacyVisibilityState(BaseModel):
    scope: str = "admin_only"
    reason: str | None = None
