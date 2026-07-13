from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from src.config import append_audit_replace_factory_codes


router = APIRouter(prefix="/api/meta", tags=["meta"])


class AuditReplaceFactoryCodesPayload(BaseModel):
    codes: list[str] = Field(default_factory=list)


@router.get("/form-schema")
def get_form_schema(request: Request) -> dict:
    return request.app.state.runtime.form_schema()


@router.post("/audit-replace/factory-codes")
def remember_audit_replace_factory_codes(payload: AuditReplaceFactoryCodesPayload) -> dict:
    return {
        "factory_codes": append_audit_replace_factory_codes(payload.codes),
    }
