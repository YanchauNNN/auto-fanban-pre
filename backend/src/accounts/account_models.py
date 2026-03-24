from __future__ import annotations

from pydantic import BaseModel, Field

from ..models.task_group_management import AccountSnapshot


class AccountRecord(BaseModel):
    office_code: str | None = None
    office_name: str | None = None
    account_id: str
    display_name: str
    role: str
    password: str
    valid: bool = True
    row_number: int | None = None
    errors: list[str] = Field(default_factory=list)

    def to_snapshot(self) -> AccountSnapshot:
        return AccountSnapshot(
            account_id=self.account_id,
            display_name=self.display_name,
            role=self.role,
            office_code=self.office_code,
            office_name=self.office_name,
            valid=self.valid,
        )


class InvalidAccountRow(BaseModel):
    row_number: int
    raw: dict[str, str] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class AccountCreatePayload(BaseModel):
    office_code: str | None = None
    office_name: str | None = None
    account_id: str
    display_name: str
    role: str
    password: str | None = None


class AccountUpdatePayload(BaseModel):
    office_code: str | None = None
    office_name: str | None = None
    account_id: str | None = None
    display_name: str | None = None
    role: str | None = None
    password: str | None = None
