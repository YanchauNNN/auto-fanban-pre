from __future__ import annotations

from fastapi import APIRouter, File, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse

from ..runtime import UploadedFilePayload


router = APIRouter(prefix="/api/font-sync", tags=["font-sync"])


@router.post("/source-scan")
async def source_scan(
    request: Request,
    file: UploadFile = File(...),
) -> JSONResponse:
    payload = UploadedFilePayload(
        filename=file.filename or "source.dwg",
        content=await file.read(),
        content_type=file.content_type,
    )
    result = request.app.state.runtime.scan_font_sync_source(file=payload)
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


@router.post("/export")
async def export_bundle(
    request: Request,
    file: UploadFile = File(...),
) -> JSONResponse:
    payload = UploadedFilePayload(
        filename=file.filename or "source.dwg",
        content=await file.read(),
        content_type=file.content_type,
    )
    result = request.app.state.runtime.export_font_sync_bundle(file=payload)
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=result)


@router.get("/download/{bundle_id}")
def download_bundle(request: Request, bundle_id: str) -> FileResponse:
    path = request.app.state.runtime.get_font_sync_bundle_path(bundle_id)
    return FileResponse(
        path=path,
        filename=path.name,
        media_type="application/octet-stream",
    )


@router.post("/target-scan")
def target_scan(request: Request) -> JSONResponse:
    result = request.app.state.runtime.scan_font_sync_target()
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


@router.post("/import-preview")
async def import_preview(
    request: Request,
    bundle: UploadFile = File(...),
) -> JSONResponse:
    payload = UploadedFilePayload(
        filename=bundle.filename or "bundle.fanfontsync",
        content=await bundle.read(),
        content_type=bundle.content_type,
    )
    result = request.app.state.runtime.preview_font_sync_bundle(file=payload)
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


@router.post("/apply")
def apply_bundle(request: Request, import_id: str) -> JSONResponse:
    result = request.app.state.runtime.apply_font_sync_bundle(import_id=import_id)
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)
