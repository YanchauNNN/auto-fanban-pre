from __future__ import annotations

from fastapi import APIRouter, Request


router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
def get_health(request: Request) -> dict:
    return request.app.state.runtime.health()
