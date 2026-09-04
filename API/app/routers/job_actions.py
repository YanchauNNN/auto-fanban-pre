from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from src.models import AccountSnapshot

from ..auth_helpers import require_current_account
from ..job_actions import JobActionService

router = APIRouter(prefix="/api/jobs", tags=["job-execution-actions"])
CurrentAccount = Annotated[AccountSnapshot, Depends(require_current_account)]


def _execute(action: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return action()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, TimeoutError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{item_id}/execution-actions")
def get_execution_actions(
    item_id: str, request: Request, account: CurrentAccount
) -> dict[str, object]:
    return _execute(
        lambda: JobActionService(request.app.state.runtime).get_actions(
            item_id, account
        )
    )


@router.post("/{item_id}/cancel")
def cancel_execution(
    item_id: str, request: Request, account: CurrentAccount
) -> dict[str, object]:
    return _execute(
        lambda: JobActionService(request.app.state.runtime).cancel(item_id, account)
    )


@router.post("/{item_id}/retry")
def retry_execution(
    item_id: str, request: Request, account: CurrentAccount
) -> dict[str, object]:
    return _execute(
        lambda: JobActionService(request.app.state.runtime).retry(item_id, account)
    )
