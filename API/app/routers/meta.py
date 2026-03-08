from __future__ import annotations

from fastapi import APIRouter, Request


router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("/form-schema")
def get_form_schema(request: Request) -> dict:
    return request.app.state.runtime.form_schema()
