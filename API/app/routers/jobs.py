from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from src.config import load_mechanism_spec

from ..auth_helpers import require_current_account
from ..runtime import UploadedFilePayload

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

@router.post("/preflight-fonts")
async def preflight_fonts(
    request: Request,
    _=Depends(require_current_account),
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
    payload = await run_in_threadpool(request.app.state.runtime.preflight_fonts, files=uploads)
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


@router.post("/calculation-books")
async def create_calculation_book(
    request: Request,
    params_json: str = Form(...),
    archive: UploadFile | None = File(None),
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
                    "param_errors": {"params_json": [f"invalid_json:{exc.msg}"]},
                }
            },
        )
    upload = (
        UploadedFilePayload(
            filename=archive.filename or "calculation-images.zip",
            content=await archive.read(),
            content_type=archive.content_type,
        )
        if archive is not None
        else None
    )
    payload = request.app.state.runtime.create_calculation_book(
        archive=upload,
        raw_params=params,
        creator_snapshot=account,
    )
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=payload)


@router.post("/calculation-books/preflight")
async def preflight_calculation_book(
    request: Request,
    archive: UploadFile = File(...),
    _=Depends(require_current_account),
) -> JSONResponse:
    upload = UploadedFilePayload(
        filename=archive.filename or "calculation-images.zip",
        content=await archive.read(),
        content_type=archive.content_type,
    )
    payload = await run_in_threadpool(
        request.app.state.runtime.preflight_calculation_book,
        archive=upload,
    )
    return JSONResponse(status_code=status.HTTP_200_OK, content=payload)


@router.get("")
def list_jobs(
    request: Request,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    sort: str = "updated_at",
    account=Depends(require_current_account),
) -> dict:
    return request.app.state.runtime.list_jobs(
        account=account,
        status_filter=status,
        limit=limit,
        offset=offset,
        sort_by=sort,
    )


@router.get("/activity")
def jobs_activity(request: Request) -> dict:
    return request.app.state.runtime.jobs_activity()


def _jobs_activity_marker(activity: dict[str, Any]) -> str:
    return f"{activity.get('total', 0)}:{activity.get('active', 0)}:{activity.get('last_changed_at') or ''}"


def _format_jobs_activity_sse(activity: dict[str, Any], *, retry_ms: int | None = None) -> str:
    marker = _jobs_activity_marker(activity)
    data = json.dumps(activity, ensure_ascii=False, separators=(",", ":"))
    retry_line = f"retry: {max(1000, int(retry_ms))}\n" if retry_ms is not None else ""
    return f"event: jobs_activity\nid: {marker}\n{retry_line}data: {data}\n\n"


async def _jobs_activity_event_stream(
    request: Request,
    runtime: Any,
    *,
    poll_interval_sec: float,
    keepalive_sec: float,
    max_duration_sec: float,
    retry_ms: int,
) -> AsyncIterator[str]:
    last_marker: str | None = None
    last_sent_at = 0.0
    started_at = time.monotonic()
    poll_interval = max(0.1, float(poll_interval_sec))
    keepalive_interval = max(poll_interval, float(keepalive_sec))
    max_duration = max(poll_interval, float(max_duration_sec))
    while True:
        activity = runtime.jobs_activity()
        marker = _jobs_activity_marker(activity)
        now = time.monotonic()
        if marker != last_marker:
            yield _format_jobs_activity_sse(activity, retry_ms=retry_ms)
            last_marker = marker
            last_sent_at = now
        elif now - last_sent_at >= keepalive_interval:
            yield f": keepalive {int(now)}\n\n"
            last_sent_at = now
        if await request.is_disconnected():
            break
        if now - started_at >= max_duration:
            yield f": stream-close {int(now)}\n\n"
            break
        await asyncio.sleep(poll_interval)


@router.get("/activity/stream")
def jobs_activity_stream(request: Request) -> StreamingResponse:
    api_runtime_cfg = load_mechanism_spec().api_runtime
    return StreamingResponse(
        _jobs_activity_event_stream(
            request,
            request.app.state.runtime,
            poll_interval_sec=api_runtime_cfg.jobs_activity_stream_poll_interval_sec,
            keepalive_sec=api_runtime_cfg.jobs_activity_stream_keepalive_sec,
            max_duration_sec=api_runtime_cfg.jobs_activity_stream_max_duration_sec,
            retry_ms=api_runtime_cfg.jobs_activity_stream_retry_ms,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
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


@router.get("/{job_id}/download/calculation-book")
def download_calculation_book(
    request: Request,
    job_id: str,
    account=Depends(require_current_account),
) -> FileResponse:
    path = request.app.state.runtime.get_artifact_path(
        job_id,
        "calculation_book",
        account=account,
    )
    return FileResponse(
        path=path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
