from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..auth_helpers import require_current_account


router = APIRouter(prefix="/api/workload", tags=["workload"])


@router.get("/me")
def workload_me(request: Request, account=Depends(require_current_account)) -> dict[str, object]:
    groups = request.app.state.runtime.group_manager.load_all_groups()
    return request.app.state.management.workload_queries.personal(account, groups)


@router.get("/office")
def workload_office(request: Request, account=Depends(require_current_account)) -> dict[str, object]:
    if account.role not in {"室主任", "所领导", "管理员"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="office scope unavailable")
    groups = request.app.state.runtime.group_manager.load_all_groups()
    return request.app.state.management.workload_queries.office(account, groups)


@router.get("/institute")
def workload_institute(request: Request, account=Depends(require_current_account)) -> dict[str, object]:
    if account.role not in {"所领导", "管理员"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="institute scope unavailable")
    groups = request.app.state.runtime.group_manager.load_all_groups()
    return request.app.state.management.workload_queries.institute(groups)


@router.get("/admin")
def workload_admin(request: Request, account=Depends(require_current_account)) -> dict[str, object]:
    if account.role != "管理员":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    groups = request.app.state.runtime.group_manager.load_all_groups()
    return request.app.state.management.workload_queries.admin(groups)
