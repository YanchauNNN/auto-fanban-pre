from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from .accounts import require_admin


router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdminConfigPayload(BaseModel):
    archive_root_path: str | None = None


@router.get("/config")
def get_admin_config(request: Request, _=Depends(require_admin)) -> dict[str, object]:
    return request.app.state.management.admin_config_store.get()


@router.patch("/config")
def patch_admin_config(
    payload: AdminConfigPayload,
    request: Request,
    _=Depends(require_admin),
) -> dict[str, object]:
    updates = payload.model_dump(mode="json", exclude_none=True)
    return request.app.state.management.admin_config_store.update(updates)
