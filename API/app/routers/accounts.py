from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from src.accounts.account_models import AccountCreatePayload, AccountUpdatePayload
from src.config import load_mechanism_spec

from ..auth_helpers import require_current_account


router = APIRouter(prefix="/api/accounts", tags=["accounts"])


class NormalizePersonnelPayload(BaseModel):
    field_name: str
    raw_value: str | None = None


def require_admin(account=Depends(require_current_account)):
    admin_roles = set(load_mechanism_spec().permissions.account_admin_roles)
    if account.role not in admin_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    return account


@router.get("")
def list_accounts(request: Request, _=Depends(require_admin)) -> dict[str, object]:
    accounts, invalid_rows = request.app.state.management.account_registry.list_accounts()
    return {
        "items": [account.model_dump(mode="json") for account in accounts],
        "invalid_rows": [row.model_dump(mode="json") for row in invalid_rows],
    }


@router.get("/invalid-rows")
def invalid_rows(request: Request, _=Depends(require_admin)) -> dict[str, object]:
    rows = request.app.state.management.account_registry.list_invalid_rows()
    return {"items": [row.model_dump(mode="json") for row in rows]}


@router.post("/normalize-personnel")
def normalize_personnel(
    payload: NormalizePersonnelPayload,
    request: Request,
    _=Depends(require_current_account),
) -> dict[str, object]:
    result, candidates = request.app.state.management.personnel_normalizer.resolve_with_candidates(
        payload.field_name,
        payload.raw_value,
    )
    return {
        "normalized": result.model_dump(mode="json"),
        "candidates": [candidate.to_snapshot().model_dump(mode="json") for candidate in candidates],
    }


@router.post("")
def create_account(
    payload: AccountCreatePayload,
    request: Request,
    _=Depends(require_admin),
) -> dict[str, object]:
    account = request.app.state.management.account_registry.create_account(payload)
    return account.model_dump(mode="json")


@router.patch("/{account_id}")
def update_account(
    account_id: str,
    payload: AccountUpdatePayload,
    request: Request,
    _=Depends(require_admin),
) -> dict[str, object]:
    old_account, updated = request.app.state.management.account_registry.update_account(account_id, payload)
    request.app.state.management.task_group_service.rebind_account_references(
        old_account.account_id,
        updated.to_snapshot(),
    )
    return updated.model_dump(mode="json")
