from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request


router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/ping")
def ping() -> dict[str, object]:
    return {
        "ok": True,
        "server_time": datetime.now().astimezone().isoformat(),
    }


@router.get("/health")
def get_health(request: Request) -> dict:
    return request.app.state.runtime.health()
