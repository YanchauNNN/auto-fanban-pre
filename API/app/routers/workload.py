from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.workload.queries import WorkloadQueryFilters

from ..auth_helpers import require_current_account


router = APIRouter(prefix="/api/workload", tags=["workload"])


def _build_filters(
    start_date: date | None,
    end_date: date | None,
    status_value: str | None,
    valid_only: bool,
) -> WorkloadQueryFilters:
    return WorkloadQueryFilters(
        start_date=start_date,
        end_date=end_date,
        status=str(status_value or "").strip().lower() or None,
        valid_only=valid_only,
    )


@router.get("/me")
def workload_me(
    request: Request,
    account=Depends(require_current_account),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    status_value: str | None = Query(default=None, alias="status"),
    valid_only: bool = Query(default=False),
) -> dict[str, object]:
    groups = request.app.state.runtime.group_manager.load_all_groups()
    filters = _build_filters(start_date, end_date, status_value, valid_only)
    return request.app.state.management.workload_queries.personal(account, groups, filters)


@router.get("/office")
def workload_office(
    request: Request,
    account=Depends(require_current_account),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    status_value: str | None = Query(default=None, alias="status"),
    valid_only: bool = Query(default=False),
) -> dict[str, object]:
    if account.role not in {"室主任", "所领导", "管理员"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="office scope unavailable")
    groups = request.app.state.runtime.group_manager.load_all_groups()
    filters = _build_filters(start_date, end_date, status_value, valid_only)
    return request.app.state.management.workload_queries.office(account, groups, filters)


@router.get("/institute")
def workload_institute(
    request: Request,
    account=Depends(require_current_account),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    status_value: str | None = Query(default=None, alias="status"),
    valid_only: bool = Query(default=False),
) -> dict[str, object]:
    if account.role not in {"所领导", "管理员"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="institute scope unavailable")
    groups = request.app.state.runtime.group_manager.load_all_groups()
    filters = _build_filters(start_date, end_date, status_value, valid_only)
    return request.app.state.management.workload_queries.institute(groups, filters)


@router.get("/admin")
def workload_admin(
    request: Request,
    account=Depends(require_current_account),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    status_value: str | None = Query(default=None, alias="status"),
    valid_only: bool = Query(default=False),
) -> dict[str, object]:
    if account.role != "管理员":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    groups = request.app.state.runtime.group_manager.load_all_groups()
    filters = _build_filters(start_date, end_date, status_value, valid_only)
    return request.app.state.management.workload_queries.admin(groups, filters)
