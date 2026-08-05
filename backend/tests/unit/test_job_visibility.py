from __future__ import annotations

import pytest
import yaml
from fastapi import HTTPException

from src.models import AccountSnapshot, Job, JobStatus, JobType, TaskOwnerSnapshot
from src.task_groups.visibility import TaskGroupVisibility


def test_job_visibility_reads_owner_scope_from_yaml(monkeypatch, tmp_path) -> None:
    spec_path = tmp_path / "documents" / "params.yaml"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "2.0",
                "management_features": {
                    "task_visibility": {
                        "roles": {
                            "admin": "all",
                            "lead": "office_only",
                            "designer": "self_only",
                        },
                        "legacy_default_scope": "admin_only",
                    }
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FANBAN_SPEC_PATH", str(spec_path))

    job = Job(job_id="job-1", job_type=JobType.DELIVERABLE, project_no="2016")
    job.owner_snapshot = TaskOwnerSnapshot(
        creator_account="creator",
        creator_name="Creator",
        creator_role="designer",
        creator_office="office-a",
    )
    visibility = TaskGroupVisibility()

    assert visibility.can_view_job(
        job,
        AccountSnapshot(account_id="creator", display_name="Creator", role="designer", office_name="office-a"),
    )
    assert visibility.can_view_job(
        job,
        AccountSnapshot(account_id="lead", display_name="Lead", role="lead", office_name="office-a"),
    )
    assert not visibility.can_view_job(
        job,
        AccountSnapshot(account_id="other", display_name="Other", role="designer", office_name="office-a"),
    )

    legacy_job = Job(job_id="legacy-job", job_type=JobType.DELIVERABLE, project_no="2016")
    assert not visibility.can_view_job(
        legacy_job,
        AccountSnapshot(account_id="lead", display_name="Lead", role="lead", office_name="office-a"),
    )
    assert visibility.can_view_job(
        legacy_job,
        AccountSnapshot(account_id="admin", display_name="Admin", role="admin", office_name="office-z"),
    )


def test_calculation_log_download_reuses_job_visibility_and_fixed_artifact_path(
    monkeypatch,
    tmp_path,
) -> None:
    spec_path = tmp_path / "documents" / "params.yaml"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "2.0",
                "management_features": {
                    "task_visibility": {
                        "roles": {
                            "admin": "all",
                            "lead": "office_only",
                            "designer": "self_only",
                        },
                        "legacy_default_scope": "admin_only",
                    }
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FANBAN_SPEC_PATH", str(spec_path))

    work_dir = tmp_path / "job"
    log_path = (
        work_dir
        / "calculation-book"
        / "logs"
        / "calculation-book-calculation-job.log"
    )
    log_path.parent.mkdir(parents=True)
    log_path.write_bytes(b'{"event":"task_completed"}\n')
    job = Job(
        job_id="calculation-job",
        job_type=JobType.CALCULATION_BOOK,
        project_no="JQ",
        work_dir=work_dir,
        status=JobStatus.RUNNING,
        owner_snapshot=TaskOwnerSnapshot(
            creator_account="creator",
            creator_name="Creator",
            creator_role="designer",
            creator_office="office-a",
        ),
    )
    job.artifacts.calculation_log = log_path

    from API.app.runtime import DeliverableApiRuntime

    runtime = DeliverableApiRuntime.__new__(DeliverableApiRuntime)
    runtime.process_jobs_in_api = True
    runtime.job_manager = type(
        "JobManagerStub",
        (),
        {"get_job": staticmethod(lambda job_id: job if job_id == job.job_id else None)},
    )()
    runtime.group_manager = type(
        "GroupManagerStub",
        (),
        {"get_group": staticmethod(lambda _group_id: None)},
    )()
    runtime.task_visibility = TaskGroupVisibility()
    creator = AccountSnapshot(
        account_id="creator",
        display_name="Creator",
        role="designer",
        office_name="office-a",
    )
    other = AccountSnapshot(
        account_id="other",
        display_name="Other",
        role="designer",
        office_name="office-a",
    )

    with pytest.raises(HTTPException) as running_exc:
        runtime.get_artifact_path(
            job.job_id,
            "calculation_book_log",
            account=creator,
        )
    assert running_exc.value.status_code == 404
    job.status = JobStatus.SUCCEEDED

    assert runtime.get_artifact_path(
        job.job_id,
        "calculation_book_log",
        account=creator,
    ) == log_path.resolve()
    with pytest.raises(HTTPException) as exc_info:
        runtime.get_artifact_path(
            job.job_id,
            "calculation_book_log",
            account=other,
        )
    assert exc_info.value.status_code == 403

    outside = tmp_path / "outside.log"
    outside.write_text("secret", encoding="utf-8")
    job.artifacts.calculation_log = outside
    with pytest.raises(HTTPException) as outside_exc:
        runtime.get_artifact_path(
            job.job_id,
            "calculation_book_log",
            account=creator,
        )
    assert outside_exc.value.status_code == 404
