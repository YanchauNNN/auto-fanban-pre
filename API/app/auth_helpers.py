from __future__ import annotations

from fastapi import Header, HTTPException, Request, status


def require_current_account(
    request: Request,
    authorization: str | None = Header(default=None),
):
    account = request.app.state.management.session_service.resolve_account(authorization)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    return account
