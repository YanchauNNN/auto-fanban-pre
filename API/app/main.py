from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import bootstrap  # noqa: F401
from .routers.jobs import router as jobs_router
from .routers.meta import router as meta_router
from .routers.system import router as system_router
from .runtime import DeliverableApiRuntime

from src.models import Job


def create_app(job_processor: Callable[[Job], None] | None = None) -> FastAPI:
    runtime = DeliverableApiRuntime(job_processor=job_processor)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.runtime = runtime
        runtime.start()
        try:
            yield
        finally:
            runtime.stop()

    app = FastAPI(
        title="Auto Fanban API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(system_router)
    app.include_router(meta_router)
    app.include_router(jobs_router)
    return app


app = create_app()
