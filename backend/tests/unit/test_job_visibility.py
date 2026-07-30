from __future__ import annotations

import yaml

from src.models import AccountSnapshot, Job, JobType, TaskOwnerSnapshot
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
