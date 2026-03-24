from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from ..auth_helpers import require_current_account
from .accounts import require_admin


router = APIRouter(prefix="/api/workflow", tags=["workflow"])


class ApprovePayload(BaseModel):
    factor: float


class RepairPayload(BaseModel):
    assignee_account_id: str


@router.get("/monitor")
def workflow_monitor(request: Request, account=Depends(require_current_account)) -> dict[str, object]:
    items = request.app.state.management.task_group_service.workflow_monitor(account)
    return {"items": items, "total": len(items)}


@router.post("/{group_id}/approve")
def approve(
    group_id: str,
    payload: ApprovePayload,
    request: Request,
    account=Depends(require_current_account),
) -> dict[str, object]:
    try:
        return request.app.state.management.task_group_service.approve(group_id, account, payload.factor)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/{group_id}/repair-current-node")
def repair_current_node(
    group_id: str,
    payload: RepairPayload,
    request: Request,
    _=Depends(require_admin),
) -> dict[str, object]:
    snapshot = request.app.state.management.account_registry.to_snapshot(payload.assignee_account_id)
    try:
        return request.app.state.management.task_group_service.repair_current_node(group_id, snapshot)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
