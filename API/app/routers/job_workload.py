from fastapi import APIRouter, Body, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from ..auth_helpers import require_current_account
from ..job_workload import JobWorkloadSubmission

router = APIRouter(prefix="/api/jobs", tags=["job-workload"])


class WorkloadSubmissionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    personnel: dict[str, str] = Field(default_factory=dict)
    overwrite_archive_existing: bool = False
    cancel_existing_in_progress: bool = False


@router.get("/{item_id}/workload-submission")
def preview(item_id: str, request: Request, account=Depends(require_current_account)):
    return JobWorkloadSubmission(request.app.state.runtime, request.app.state.management).preview(item_id, account)


@router.post("/{item_id}/workload-submission")
def submit(item_id: str, request: Request, payload: WorkloadSubmissionPayload = Body(default_factory=WorkloadSubmissionPayload), account=Depends(require_current_account)):
    return JobWorkloadSubmission(request.app.state.runtime, request.app.state.management).submit(item_id, account, **payload.model_dump())
