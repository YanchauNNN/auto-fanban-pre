from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import bootstrap  # noqa: F401
from .management_services import ManagementServices
from .routers.accounts import router as accounts_router
from .routers.admin import router as admin_router
from .routers.auth import router as auth_router
from .routers.jobs import router as jobs_router
from .routers.meta import router as meta_router
from .routers.system import router as system_router
from .routers.task_groups import router as task_groups_router
from .routers.workflow import router as workflow_router
from .routers.workload import router as workload_router
from .runtime import DeliverableApiRuntime

from src.cad import FontPreflightService
from src.models import Job
from src.pipeline.shared_prep import SharedPrepService


def create_app(
    job_processor: Callable[[Job], None] | None = None,
    shared_prep_service: SharedPrepService | None = None,
    font_preflight_service: FontPreflightService | None = None,
) -> FastAPI:
    runtime = DeliverableApiRuntime(
        job_processor=job_processor,
        shared_prep_service=shared_prep_service,
        font_preflight_service=font_preflight_service,
    )
    management = ManagementServices.build(runtime)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.runtime = runtime
        app.state.management = management
        runtime.start()
        management.start()
        try:
            yield
        finally:
            management.stop()
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
    app.include_router(auth_router)
    app.include_router(accounts_router)
    app.include_router(task_groups_router)
    app.include_router(workflow_router)
    app.include_router(workload_router)
    app.include_router(admin_router)
    return app


app = create_app()
