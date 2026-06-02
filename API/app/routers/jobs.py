from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse

from ..auth_helpers import require_current_account
from ..runtime import UploadedFilePayload


router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("/preflight-fonts")
async def preflight_fonts(
    request: Request,
    account=Depends(require_current_account),
    files: list[UploadFile] = File(..., alias="files[]"),
) -> JSONResponse:
    uploads = [
        UploadedFilePayload(
            filename=upload.filename or "upload.dwg",
            content=await upload.read(),
            content_type=upload.content_type,
        )
        for upload in files
    ]
    payload = request.app.state.runtime.preflight_fonts(files=uploads)
    return JSONResponse(status_code=status.HTTP_200_OK, content=payload)


@router.post("/batch")
async def create_batch(
    request: Request,
    params_json: str = Form(...),
    run_audit_check: bool = Form(False),
    split_only: bool = Form(False),
    files: list[UploadFile] = File(..., alias="files[]"),
    account=Depends(require_current_account),
) -> JSONResponse:
    try:
        params = json.loads(params_json)
    except json.JSONDecodeError as exc:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "detail": {
                    "upload_errors": {},
                    "param_errors": {
                        "params_json": [f"invalid_json:{exc.msg}"],
                    },
                },
            },
        )

    uploads = [
        UploadedFilePayload(
            filename=upload.filename or "upload.dwg",
            content=await upload.read(),
            content_type=upload.content_type,
        )
        for upload in files
    ]
    payload = request.app.state.runtime.create_batch(
        files=uploads,
        raw_params=params,
        run_audit_check=run_audit_check,
        split_only=split_only,
        creator_snapshot=account,
    )
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=payload)


@router.post("/audit-replace")
async def create_audit_batch(
    request: Request,
    mode: str = Form(...),
    params_json: str = Form(...),
    files: list[UploadFile] = File(..., alias="files[]"),
    account=Depends(require_current_account),
) -> JSONResponse:
    try:
        params = json.loads(params_json)
    except json.JSONDecodeError as exc:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "detail": {
                    "upload_errors": {},
                    "param_errors": {
                        "params_json": [f"invalid_json:{exc.msg}"],
                    },
                },
            },
        )

    uploads = [
        UploadedFilePayload(
            filename=upload.filename or "upload.dwg",
            content=await upload.read(),
            content_type=upload.content_type,
        )
        for upload in files
    ]
    payload = request.app.state.runtime.create_audit_batch(
        mode=mode,
        files=uploads,
        raw_params=params,
        creator_snapshot=account,
    )
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=payload)


@router.get("")
def list_jobs(
    request: Request,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    account=Depends(require_current_account),
) -> dict:
    return request.app.state.runtime.list_jobs(
        account=account,
        status_filter=status,
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}")
def get_job_detail(request: Request, job_id: str, account=Depends(require_current_account)) -> dict:
    return request.app.state.runtime.get_job_detail(job_id, account=account)


@router.get("/{job_id}/download/package")
def download_package(request: Request, job_id: str, account=Depends(require_current_account)) -> FileResponse:
    path = request.app.state.runtime.get_artifact_path(job_id, "package", account=account)
    return FileResponse(path=path, filename=path.name, media_type="application/zip")


@router.get("/{job_id}/download/ied")
def download_ied(request: Request, job_id: str, account=Depends(require_current_account)) -> FileResponse:
    path = request.app.state.runtime.get_artifact_path(job_id, "ied", account=account)
    return FileResponse(
        path=path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/{job_id}/download/preview")
def download_preview(request: Request, job_id: str, account=Depends(require_current_account)) -> FileResponse:
    path = request.app.state.runtime.get_artifact_path(job_id, "preview", account=account)
    return FileResponse(
        path=path,
        filename=path.name,
        media_type="application/pdf",
    )


@router.get("/{job_id}/download/report")
def download_report(request: Request, job_id: str, account=Depends(require_current_account)) -> FileResponse:
    path = request.app.state.runtime.get_artifact_path(job_id, "report", account=account)
    return FileResponse(
        path=path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/{job_id}/download/replaced")
def download_replaced_dwg(request: Request, job_id: str, account=Depends(require_current_account)) -> FileResponse:
    path = request.app.state.runtime.get_artifact_path(job_id, "replaced", account=account)
    return FileResponse(
        path=path,
        filename=path.name,
        media_type="application/acad",
    )
