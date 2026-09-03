from __future__ import annotations

import json
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from src.models import JobStatus

from API.app.main import create_app

from ..management_test_helpers import configure_management_env
from .test_task_group_submit_flow import _login, _seed_group


@pytest.fixture
def client(monkeypatch, tmp_path):
    configure_management_env(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        yield client


def _headers(client, account="zhangsan"):
    return {"Authorization": f"Bearer {_login(client, account)}"}


def _standalone(client, tmp_path):
    group_id = _seed_group(client, tmp_path)
    runtime = cast(Any, client.app).state.runtime
    group = runtime.group_manager.get_group(group_id)
    job = runtime.job_manager.get_job(group.child_job_ids[0])
    job.group_id = None
    job.task_role = None
    job.owner_snapshot = group.owner_snapshot
    source = runtime.config.get_job_dir(job.job_id) / "input.dwg"
    source.write_bytes(b"existing successful source")
    job.input_files = [source]
    job.progress.details["workload"] = {"initial_workload_a1": 3.25}
    for key in ("ied_checked_by", "ied_reviewed_by", "ied_approved_by"):
        job.params.pop(key, None)
    runtime.job_manager.update_job(job)
    runtime.group_manager.delete_group(group_id)
    manifest = {"job_id": job.job_id, "derived": {"document_revision": "A"}, "drawings": [{"internal_code": "2016-JG001-001"}]}
    (runtime.config.get_job_dir(job.job_id) / "manifest.json").write_text(json.dumps(manifest))
    return job


def _personnel():
    return {"ied_checked_by": "李四@lisi", "ied_reviewed_by": "王五@wangwu", "ied_approved_by": "管理员@admin"}


def test_viewing_standalone_does_not_create_workflow(client, tmp_path):
    job = _standalone(client, tmp_path)
    response = client.get(f"/api/jobs/{job.job_id}/workload-submission", headers=_headers(client))
    assert response.status_code == 200
    assert response.json()["can_submit"] is True
    assert response.json()["initial_workload_a1"] == 3.25
    assert response.json()["group_id"] is None
    assert cast(Any, client.app).state.runtime.group_manager.load_all_groups() == []


def test_submit_from_ordinary_job_creates_one_group_and_completes_roles(client, tmp_path):
    job = _standalone(client, tmp_path)
    original_params = dict(job.params)
    admin = _headers(client, "admin")
    runtime = cast(Any, client.app).state.runtime
    client.patch("/api/admin/config", json={"archive_root_path": str(tmp_path / "archive")}, headers=admin)
    payload = {"personnel": _personnel()}
    result = client.post(f"/api/jobs/{job.job_id}/workload-submission", json=payload, headers=_headers(client))
    assert result.status_code == 200, result.text
    group_id = result.json()["group_id"]
    assert result.json()["workflow"]["current_node_key"] == "one_review"
    assert runtime.job_manager.reload_job(job.job_id).params == original_params
    assert runtime.job_manager.reload_job(job.job_id).group_id == group_id
    assert len(runtime.group_manager.load_all_groups()) == 1
    repeat = client.post(f"/api/jobs/{job.job_id}/workload-submission", json=payload, headers=_headers(client))
    assert repeat.status_code == 422
    assert len(runtime.group_manager.load_all_groups()) == 1
    wrong = client.post(f"/api/workflow/{group_id}/approve", json={"factor": 1, "node_key": "one_review"}, headers=admin)
    assert wrong.status_code == 422
    for account, node, factor in [("lisi", "one_review", 1.0), ("wangwu", "two_review", 1.05), ("admin", "three_review", 0.95)]:
        response = client.post(f"/api/workflow/{group_id}/approve", json={"factor": factor, "node_key": node}, headers=_headers(client, account))
        assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["workflow"]["status"] == "archived"
    assert detail["workload"]["settlement_status"] == "settled"
    assert detail["effective_workload"] == round(3.25 * 1.05 * 0.95, 2)
    before = detail["workload"]["contributor_entries"]
    repeat = client.post(f"/api/workflow/{group_id}/approve", json={"factor": 1}, headers=_headers(client, "admin"))
    assert repeat.status_code == 422
    assert runtime.group_manager.reload_group(group_id).workload.model_dump(mode="json")["contributor_entries"] == before


def test_invalid_personnel_rejected_before_creating_group(client, tmp_path):
    job = _standalone(client, tmp_path)
    response = client.post(f"/api/jobs/{job.job_id}/workload-submission", json={"personnel": {}}, headers=_headers(client))
    assert response.status_code == 422
    assert "ied_checked_by" in response.json()["detail"]["field_errors"]
    assert cast(Any, client.app).state.runtime.group_manager.load_all_groups() == []


def test_non_creator_cannot_submit_or_claim_task(client, tmp_path):
    job = _standalone(client, tmp_path)
    response = client.post(f"/api/jobs/{job.job_id}/workload-submission", json={"personnel": _personnel()}, headers=_headers(client, "lisi"))
    assert response.status_code == 403
    assert cast(Any, client.app).state.runtime.group_manager.load_all_groups() == []


@pytest.mark.parametrize("failure", ["failed", "missing_package", "missing_workload"])
def test_unready_job_is_blocked_before_submit(client, tmp_path, failure):
    job = _standalone(client, tmp_path)
    runtime = cast(Any, client.app).state.runtime
    if failure == "failed":
        job.status = JobStatus.FAILED
    elif failure == "missing_package":
        job.artifacts.package_zip = None
    else:
        job.progress.details.pop("workload")
    runtime.job_manager.update_job(job)
    preview = client.get(f"/api/jobs/{job.job_id}/workload-submission", headers=_headers(client))
    assert preview.status_code == 200
    assert preview.json()["can_submit"] is False
    assert preview.json()["blockers"]
    result = client.post(f"/api/jobs/{job.job_id}/workload-submission", json={"personnel": _personnel()}, headers=_headers(client))
    assert result.status_code == 422


def test_group_child_ordinary_route_reuses_existing_group(client, tmp_path):
    group_id = _seed_group(client, tmp_path)
    runtime = cast(Any, client.app).state.runtime
    child = runtime.group_manager.get_group(group_id).child_job_ids[0]
    response = client.post(f"/api/jobs/{child}/workload-submission", json={}, headers=_headers(client))
    assert response.status_code == 200, response.text
    assert response.json()["group_id"] == group_id
    assert len(runtime.group_manager.load_all_groups()) == 1


def test_duplicate_personnel_marks_all_affected_fields(client, tmp_path):
    job = _standalone(client, tmp_path)
    personnel = _personnel()
    personnel["ied_reviewed_by"] = personnel["ied_checked_by"]
    response = client.post(f"/api/jobs/{job.job_id}/workload-submission", json={"personnel": personnel}, headers=_headers(client))
    assert response.status_code == 422
    assert set(response.json()["detail"]["field_errors"]) == {"ied_checked_by", "ied_reviewed_by"}
    assert cast(Any, client.app).state.runtime.group_manager.load_all_groups() == []


def test_ordinary_group_detail_view_is_read_only(client, tmp_path):
    group_id = _seed_group(client, tmp_path)
    runtime = cast(Any, client.app).state.runtime
    child = runtime.group_manager.get_group(group_id).child_job_ids[0]
    preview = client.get(f"/api/jobs/{child}/workload-submission", headers=_headers(client))
    assert preview.status_code == 200
    assert preview.json()["can_submit"] is True
    assert runtime.group_manager.reload_group(group_id).workflow.status.value == "draft"


def test_nonfinite_approval_factor_rejected(client, tmp_path):
    group_id = _seed_group(client, tmp_path)
    client.post(f"/api/jobs/{group_id}/workload-submission", json={}, headers=_headers(client))
    response = client.post(f"/api/workflow/{group_id}/approve", content='{"factor": NaN}', headers={**_headers(client, "lisi"), "Content-Type": "application/json"})
    assert response.status_code == 422


@pytest.mark.parametrize("standalone", [True, False])
def test_historical_ied_personnel_are_preserved_without_blocking_current_submitter(client, tmp_path, standalone):
    runtime = cast(Any, client.app).state.runtime
    if standalone:
        job = _standalone(client, tmp_path)
    else:
        group_id = _seed_group(client, tmp_path)
        job = runtime.job_manager.get_job(runtime.group_manager.get_group(group_id).child_job_ids[0])
    job.params.update(ied_prepared_by="历史编制人@retired", ied_discipline_leader="历史负责人@retired_leader")
    runtime.job_manager.update_job(job)
    original = dict(job.params)
    response = client.post(f"/api/jobs/{job.job_id}/workload-submission", json={"personnel": _personnel()}, headers=_headers(client))
    assert response.status_code == 200, response.text
    group = runtime.group_manager.reload_group(response.json()["group_id"])
    assert group.workflow.initiated_by_account == "zhangsan"
    assert group.personnel_snapshot.members["ied_prepared_by"].raw_value == original["ied_prepared_by"]
    assert group.personnel_snapshot.members["ied_discipline_leader"].raw_value == original["ied_discipline_leader"]
    assert runtime.job_manager.reload_job(job.job_id).params == original


def test_actual_submitter_cannot_approve_even_when_original_preparer_differs(client, tmp_path):
    job = _standalone(client, tmp_path)
    runtime = cast(Any, client.app).state.runtime
    job.params["ied_prepared_by"] = "历史编制人@retired"
    runtime.job_manager.update_job(job)
    personnel = {**_personnel(), "ied_checked_by": "张三@zhangsan"}
    response = client.post(f"/api/jobs/{job.job_id}/workload-submission", json={"personnel": personnel}, headers=_headers(client))
    assert response.status_code == 422
    assert set(response.json()["detail"]["field_errors"]) == {"ied_checked_by"}
    assert runtime.group_manager.load_all_groups() == []


def test_success_snapshot_cannot_submit_until_executor_finishes(client, tmp_path):
    job = _standalone(client, tmp_path)
    runtime = cast(Any, client.app).state.runtime
    runtime.queue_store.begin_execution("job", job.job_id)
    preview = client.get(f"/api/jobs/{job.job_id}/workload-submission", headers=_headers(client))
    assert preview.json()["can_submit"] is False
    assert "workload_execution_active" in {item["code"] for item in preview.json()["blockers"]}
    result = client.post(f"/api/jobs/{job.job_id}/workload-submission", json={"personnel": _personnel()}, headers=_headers(client))
    assert result.status_code == 422
    assert runtime.job_manager.reload_job(job.job_id).group_id is None
    runtime.queue_store.finish_execution("job", job.job_id)
    ready = client.get(f"/api/jobs/{job.job_id}/workload-submission", headers=_headers(client))
    assert ready.json()["can_submit"] is True
