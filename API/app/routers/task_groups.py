from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..auth_helpers import require_current_account


router = APIRouter(prefix="/api/task-groups", tags=["task-groups"])


@router.get("")
def list_task_groups(
    request: Request,
    account=Depends(require_current_account),
) -> dict[str, object]:
    items = request.app.state.management.task_group_service.list_recent(account)
    return {"items": items, "total": len(items)}


@router.get("/{group_id}")
def get_task_group(
    group_id: str,
    request: Request,
    account=Depends(require_current_account),
) -> dict[str, object]:
    try:
        return request.app.state.management.task_group_service.get_detail(group_id, account)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{group_id}/submit")
def submit_task_group(
    group_id: str,
    request: Request,
    account=Depends(require_current_account),
) -> dict[str, object]:
    try:
        return request.app.state.management.task_group_service.submit(group_id, account)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/{group_id}/restart-submit")
def restart_submit_task_group(
    group_id: str,
    request: Request,
    account=Depends(require_current_account),
) -> dict[str, object]:
    try:
        return request.app.state.management.task_group_service.restart_submit(group_id, account)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
