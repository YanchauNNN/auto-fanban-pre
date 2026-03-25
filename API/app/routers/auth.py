from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from ..auth_helpers import require_current_account


router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginPayload(BaseModel):
    account_id: str
    password: str


class ChangePasswordPayload(BaseModel):
    new_password: str


@router.post("/login")
def login(payload: LoginPayload, request: Request) -> dict[str, object]:
    account = request.app.state.management.account_registry.verify_password(
        payload.account_id,
        payload.password,
    )
    if account is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    session = request.app.state.management.session_service.create_session(account.to_snapshot())
    return {
        "token": session.token,
        "account": account.model_dump(mode="json"),
    }


@router.post("/logout")
def logout(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, bool]:
    request.app.state.management.session_service.delete_session(authorization)
    return {"ok": True}


@router.get("/me")
def me(request: Request, account=Depends(require_current_account)) -> dict[str, object]:
    payload = account.model_dump(mode="json")
    payload["pending_todo_count"] = request.app.state.management.task_group_service.pending_todo_count(account)
    return payload


@router.post("/change-password")
def change_password(
    payload: ChangePasswordPayload,
    request: Request,
    account=Depends(require_current_account),
) -> dict[str, object]:
    updated = request.app.state.management.password_service.change_password(
        account.account_id,
        payload.new_password,
    )
    return updated.model_dump(mode="json")
