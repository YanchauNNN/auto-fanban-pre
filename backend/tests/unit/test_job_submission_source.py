from __future__ import annotations

import json

import pytest

from src.config import get_config, reload_config
from src.models import Job, JobType
from src.task_groups.job_submission_source import read_job_submission


@pytest.fixture
def successful_job(monkeypatch, tmp_path):
    monkeypatch.setenv("FANBAN_STORAGE_DIR", str(tmp_path / "storage"))
    reload_config()
    job = Job(
        job_id="revision-evidence", job_type=JobType.DELIVERABLE, project_no="2016",
        params={"project_no": "2016", "engineering_no": "2016", "subitem_no": "JG001", "cover_revision": "A", "revision": "A"},
    )
    job.progress.details["workload"] = {"initial_workload_a1": 2.0}
    get_config().get_job_dir(job.job_id).mkdir(parents=True)
    return job


def _manifest(job, drawings, **extra):
    path = get_config().get_job_dir(job.job_id) / "manifest.json"
    path.write_text(json.dumps({"job_id": job.job_id, "drawings": drawings, **extra}), encoding="utf-8")


def _drawing(*, suffix="CCFC", code="001"):
    return {"internal_code": f"2016-JG001-{code}", "external_code": f"DRAW{code}", "name": f"DRAW{code}{suffix} (2016-JG001-{code})"}


def test_persisted_document_revision_not_cover_revision_is_archive_identity(successful_job):
    _manifest(successful_job, [_drawing()], derived={"document_revision": "C"})
    _, identity = read_job_submission(successful_job)
    assert identity.revision == "C"


@pytest.mark.parametrize("suffix", ["CCFC", "C1@3CFC"])
def test_legacy_manifest_recovers_revision_from_exact_output_name(successful_job, suffix):
    _manifest(successful_job, [_drawing(suffix=suffix)])
    _, identity = read_job_submission(successful_job)
    assert identity.revision == "C"


def test_legacy_manifest_uses_persisted_task_status(successful_job):
    _manifest(successful_job, [_drawing(suffix="C4DB")], inputs={"params": {"doc_status": "4DB"}})
    _, identity = read_job_submission(successful_job)
    assert identity.revision == "C"


def test_explicit_drawing_revisions_use_same_highest_revision_order(successful_job):
    _manifest(successful_job, [{**_drawing(code="001"), "revision": "B2"}, {**_drawing(code="002"), "revision": "B10"}])
    _, identity = read_job_submission(successful_job)
    assert identity.revision == "B10"


@pytest.mark.parametrize("drawing", [
    {"internal_code": "2016-JG001-002"},
    {**_drawing(code="002"), "external_code": "MISMATCH"},
    _drawing(suffix="C4@3CFC", code="002"),
    _drawing(suffix="CUNKNOWN", code="002"),
])
def test_missing_or_ambiguous_revision_never_guesses_cover_revision(successful_job, drawing):
    _manifest(successful_job, [_drawing(), drawing])
    with pytest.raises(ValueError, match="workload_revision_missing"):
        read_job_submission(successful_job)
