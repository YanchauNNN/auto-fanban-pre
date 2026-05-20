from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse

from ..runtime import UploadedFilePayload


router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _resolve_optional_account(request: Request, authorization: str | None):
    if authorization is None:
        return None
    account = request.app.state.management.session_service.resolve_account(authorization)
    if account is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
    return account


@router.post("/preflight-fonts")
async def preflight_fonts(
    request: Request,
    authorization: str | None = Header(default=None),
    files: list[UploadFile] = File(..., alias="files[]"),
) -> JSONResponse:
    _resolve_optional_account(request, authorization)
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
    authorization: str | None = Header(default=None),
    params_json: str = Form(...),
    run_audit_check: bool = Form(False),
    split_only: bool = Form(False),
    files: list[UploadFile] = File(..., alias="files[]"),
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
        creator_snapshot=_resolve_optional_account(request, authorization),
    )
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=payload)


@router.post("/audit-replace")
async def create_audit_batch(
    request: Request,
    authorization: str | None = Header(default=None),
    mode: str = Form(...),
    params_json: str = Form(...),
    files: list[UploadFile] = File(..., alias="files[]"),
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
        creator_snapshot=_resolve_optional_account(request, authorization),
    )
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=payload)


@router.get("")
def list_jobs(
    request: Request,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    return request.app.state.runtime.list_jobs(status_filter=status, limit=limit, offset=offset)


@router.get("/{job_id}")
def get_job_detail(request: Request, job_id: str) -> dict:
    return request.app.state.runtime.get_job_detail(job_id)


@router.get("/{job_id}/download/package")
def download_package(request: Request, job_id: str) -> FileResponse:
    path = request.app.state.runtime.get_artifact_path(job_id, "package")
    return FileResponse(path=path, filename=path.name, media_type="application/zip")


@router.get("/{job_id}/download/ied")
def download_ied(request: Request, job_id: str) -> FileResponse:
    path = request.app.state.runtime.get_artifact_path(job_id, "ied")
    return FileResponse(
        path=path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/{job_id}/download/preview")
def download_preview(request: Request, job_id: str) -> FileResponse:
    path = request.app.state.runtime.get_artifact_path(job_id, "preview")
    return FileResponse(
        path=path,
        filename=path.name,
        media_type="application/pdf",
    )


@router.get("/{job_id}/download/report")
def download_report(request: Request, job_id: str) -> FileResponse:
    path = request.app.state.runtime.get_artifact_path(job_id, "report")
    return FileResponse(
        path=path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/{job_id}/download/replaced")
def download_replaced_dwg(request: Request, job_id: str) -> FileResponse:
    path = request.app.state.runtime.get_artifact_path(job_id, "replaced")
    return FileResponse(
        path=path,
        filename=path.name,
        media_type="application/acad",
    )
