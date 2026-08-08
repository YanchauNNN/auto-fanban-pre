from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from ..models.task_group_management import AccountSnapshot

_SENSITIVE_RAW_KEY_MARKERS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "apikey",
    "accesskey",
    "密码",
    "密碼",
    "口令",
)


def _is_sensitive_raw_key(value: object) -> bool:
    normalized = "".join(
        character for character in str(value).casefold() if character.isalnum()
    )
    return any(marker in normalized for marker in _SENSITIVE_RAW_KEY_MARKERS)


class PublicAccount(BaseModel):
    office_code: str | None = None
    office_name: str | None = None
    account_id: str
    display_name: str
    role: str
    valid: bool = True
    row_number: int | None = None
    errors: list[str] = Field(default_factory=list)


class AccountRecord(PublicAccount):
    password: str

    def to_snapshot(self) -> AccountSnapshot:
        return AccountSnapshot(
            account_id=self.account_id,
            display_name=self.display_name,
            role=self.role,
            office_code=self.office_code,
            office_name=self.office_name,
            valid=self.valid,
        )

    def to_public(self) -> PublicAccount:
        return PublicAccount.model_validate(self.model_dump(exclude={"password"}))


class InvalidAccountRow(BaseModel):
    row_number: int
    raw: dict[str, str] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)

    @field_validator("raw", mode="before")
    @classmethod
    def remove_sensitive_raw_fields(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {key: item for key, item in value.items() if not _is_sensitive_raw_key(key)}


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
