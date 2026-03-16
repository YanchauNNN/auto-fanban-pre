from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse

from ..runtime import UploadedFilePayload


router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("/batch")
async def create_batch(
    request: Request,
    params_json: str = Form(...),
    run_audit_check: bool = Form(False),
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
    )
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=payload)


@router.post("/audit-replace")
async def create_audit_batch(
    request: Request,
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
    )
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=payload)


@router.get("")
def list_jobs(request: Request, status: str | None = None, limit: int = 100) -> dict:
    return request.app.state.runtime.list_jobs(status_filter=status, limit=limit)


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


@router.get("/{job_id}/download/report")
def download_report(request: Request, job_id: str) -> FileResponse:
    path = request.app.state.runtime.get_artifact_path(job_id, "report")
    return FileResponse(
        path=path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
