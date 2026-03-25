from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from src.accounts.account_models import AccountCreatePayload

from ..auth_helpers import require_current_account
from .accounts import require_admin


router = APIRouter(prefix="/api/workflow", tags=["workflow"])


class ApprovePayload(BaseModel):
    factor: float
    node_key: str | None = None


class RepairPayload(BaseModel):
    assignee_account_id: str | None = None
    replace_with_account_id: str | None = None
    create_account_payload: AccountCreatePayload | None = None


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
        return request.app.state.management.task_group_service.approve(
            group_id,
            account,
            payload.factor,
            node_key=payload.node_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/{group_id}/repair-current-node")
def repair_current_node(
    group_id: str,
    payload: RepairPayload,
    request: Request,
    _=Depends(require_admin),
) -> dict[str, object]:
    management = request.app.state.management
    try:
        assignee_snapshot = _resolve_repair_target(management, payload)
        return management.task_group_service.repair_current_node(group_id, assignee_snapshot)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


def _resolve_repair_target(management, payload: RepairPayload):
    if payload.create_account_payload is not None:
        account = management.account_registry.create_account(payload.create_account_payload)
        return account.to_snapshot()
    account_id = payload.replace_with_account_id or payload.assignee_account_id
    if not account_id:
        raise ValueError("repair_target_required")
    return management.account_registry.to_snapshot(account_id)
