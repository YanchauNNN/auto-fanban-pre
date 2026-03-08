from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI

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
    app.include_router(system_router)
    app.include_router(meta_router)
    app.include_router(jobs_router)
    return app


app = create_app()
