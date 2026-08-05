from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import HTTPException

from src.models import AccountSnapshot, Job, JobStatus, JobType, TaskOwnerSnapshot
from src.task_groups.visibility import TaskGroupVisibility


def _write_calculation_log(
    path: Path,
    *,
    job_id: str,
    events: tuple[str, ...],
) -> bytes:
    records: list[bytes] = []
    for sequence, event in enumerate(events, start=1):
        if event == "task_completed":
            details: dict[str, object] = {
                "duration_ms": 1,
                "figure_count": 1,
                "warning_count": 0,
                "output_filename": "result.docx",
            }
        elif event == "task_failed":
            details = {
                "stage": "render_document",
                "duration_ms": 1,
                "error_code": "RuntimeError",
            }
        else:
            details = {}
        records.append(
            json.dumps(
                {
                    "schema_version": "calculation-book-log-1",
                    "timestamp_utc": "2026-08-06T00:00:00.000+00:00",
                    "sequence": sequence,
                    "event": event,
                    "job_id": job_id,
                    "correlation_id": job_id,
                    "details": details,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
    payload = b"".join(records)
    path.write_bytes(payload)
    return payload


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
    _write_calculation_log(
        log_path,
        job_id="calculation-job",
        events=("task_completed",),
    )
    docx_path = work_dir / "calculation-book" / "result.docx"
    docx_path.write_bytes(b"PK\x03\x04failed-word")
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
    job.artifacts.calculation_docx = docx_path

    from API.app.runtime import DeliverableApiRuntime

    runtime = DeliverableApiRuntime.__new__(DeliverableApiRuntime)
    runtime.process_jobs_in_api = True
    central_log_dir = tmp_path / "central-ai-audit"
    central_log_dir.mkdir()
    runtime.config = SimpleNamespace(
        calculation_book=SimpleNamespace(
            ai_suggestion=SimpleNamespace(
                log_dir=central_log_dir,
                log_max_bytes=8_192,
            )
        )
    )
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

    job.status = JobStatus.FAILED
    failed_artifacts = runtime._serialize_job_artifacts(
        job,
        include_urls=True,
        job_id=job.job_id,
    )
    assert failed_artifacts["calculation_docx_available"] is False
    assert failed_artifacts["calculation_docx_download_url"] is None
    assert failed_artifacts["calculation_log_available"] is False
    assert failed_artifacts["calculation_log_download_url"] is None
    with pytest.raises(HTTPException) as failed_word_exc:
        runtime.get_artifact_path(
            job.job_id,
            "calculation_book",
            account=creator,
        )
    assert failed_word_exc.value.status_code == 404
    with pytest.raises(HTTPException) as mismatched_terminal_exc:
        runtime.get_artifact_path(
            job.job_id,
            "calculation_book_log",
            account=creator,
        )
    assert mismatched_terminal_exc.value.status_code == 404

    _write_calculation_log(
        log_path,
        job_id=job.job_id,
        events=("task_failed",),
    )
    assert runtime.get_artifact_path(
        job.job_id,
        "calculation_book_log",
        account=creator,
    ) == log_path.resolve()

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

    exact_filename = f"calculation-book-{job.job_id}.log"
    outside_exact = tmp_path / "outside" / exact_filename
    outside_exact.parent.mkdir()
    outside_exact.write_text("outside exact name", encoding="utf-8")
    job.artifacts.calculation_log = outside_exact
    with pytest.raises(HTTPException) as outside_exact_exc:
        runtime.get_artifact_path(
            job.job_id,
            "calculation_book_log",
            account=creator,
        )
    assert outside_exact_exc.value.status_code == 404

    wrong_central_name = central_log_dir / "calculation-book-another-job.log"
    wrong_central_name.write_text("wrong job", encoding="utf-8")
    job.artifacts.calculation_log = wrong_central_name
    with pytest.raises(HTTPException) as wrong_name_exc:
        runtime.get_artifact_path(
            job.job_id,
            "calculation_book_log",
            account=creator,
        )
    assert wrong_name_exc.value.status_code == 404

    central_log = central_log_dir / exact_filename
    _write_calculation_log(
        central_log,
        job_id=job.job_id,
        events=("task_failed",),
    )
    job.artifacts.calculation_log = central_log
    assert runtime.get_artifact_path(
        job.job_id,
        "calculation_book_log",
        account=creator,
    ) == central_log.resolve()

    invalid_terminal_cases = (
        (JobStatus.SUCCEEDED, ("task_failed",)),
        (JobStatus.FAILED, ("task_completed",)),
        (JobStatus.FAILED, ("task_started",)),
    )
    for terminal_status, events in invalid_terminal_cases:
        job.status = terminal_status
        _write_calculation_log(
            central_log,
            job_id=job.job_id,
            events=events,
        )
        with pytest.raises(HTTPException) as terminal_exc:
            runtime.get_artifact_path(
                job.job_id,
                "calculation_book_log",
                account=creator,
            )
        assert terminal_exc.value.status_code == 404

    job.status = JobStatus.FAILED
    central_log.write_bytes(b'{"event":"task_failed"\n')
    with pytest.raises(HTTPException) as invalid_json_exc:
        runtime.get_artifact_path(
            job.job_id,
            "calculation_book_log",
            account=creator,
        )
    assert invalid_json_exc.value.status_code == 404

    central_log.write_bytes(b"x" * 8_193)
    with pytest.raises(HTTPException) as oversized_exc:
        runtime.get_artifact_path(
            job.job_id,
            "calculation_book_log",
            account=creator,
        )
    assert oversized_exc.value.status_code == 404

    _write_calculation_log(
        central_log,
        job_id=job.job_id,
        events=("task_failed",),
    )
    original_open = Path.open

    def fail_only_terminal_log_open(
        path: Path,
        *args: object,
        **kwargs: object,
    ):
        if path == central_log.resolve():
            raise PermissionError("simulated terminal log read failure")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_only_terminal_log_open)
    with pytest.raises(HTTPException) as read_error_exc:
        runtime.get_artifact_path(
            job.job_id,
            "calculation_book_log",
            account=creator,
        )
    assert read_error_exc.value.status_code == 404
    monkeypatch.setattr(Path, "open", original_open)

    central_log.unlink()
    central_log.write_text("simulated symlink", encoding="utf-8")
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == central_log or original_is_symlink(path),
    )
    assert central_log.is_symlink()
    with pytest.raises(HTTPException) as linked_exc:
        runtime.get_artifact_path(
            job.job_id,
            "calculation_book_log",
            account=creator,
        )
    assert linked_exc.value.status_code == 404
    assert outside_exact.read_text(encoding="utf-8") == "outside exact name"
