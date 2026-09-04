from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from API.app.main import create_app

from ..management_test_helpers import configure_management_env
from .test_task_group_submit_flow import _login, _seed_group


def _headers(client, account):
    return {"Authorization": f"Bearer {_login(client, account)}"}


def _approve_all(client, group_id):
    for account, node in [("lisi", "one_review"), ("wangwu", "two_review"), ("admin", "three_review")]:
        response = client.post(f"/api/workflow/{group_id}/approve", json={"factor": 1.0, "node_key": node}, headers=_headers(client, account))
        assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("field,code", [("package_zip", "deliverable_package"), ("ied_xlsx", "deliverable_ied")])
@pytest.mark.parametrize("remove_declaration", [False, True])
def test_lost_required_artifact_blocks_archive_and_settlement_until_recovered(monkeypatch, tmp_path, field, code, remove_declaration):
    project_root = configure_management_env(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        runtime = cast(Any, client.app).state.runtime
        management = cast(Any, client.app).state.management
        group_id = _seed_group(client, tmp_path, include_ied_plan=True)
        management.admin_config_store.update({"archive_root_path": str(project_root / "archive")})
        group = runtime.group_manager.reload_group(group_id)
        target = management.task_group_service.submit_guards._build_identity(group).archive_target
        target.mkdir(parents=True)
        sentinel = target / "existing-deliverable.txt"
        sentinel.write_bytes(b"preserve until every required artifact is ready")

        submitted = client.post(f"/api/jobs/{group_id}/workload-submission", json={"overwrite_archive_existing": True}, headers=_headers(client, "zhangsan"))
        assert submitted.status_code == 200, submitted.text
        child = runtime.job_manager.reload_job(group.child_job_ids[0])
        artifact = getattr(child.artifacts, field)
        original_bytes = artifact.read_bytes()
        held = artifact.with_suffix(artifact.suffix + ".held")
        if remove_declaration:
            setattr(child.artifacts, field, None)
            runtime.job_manager.update_job(child)
        else:
            artifact.rename(held)

        result = _approve_all(client, group_id)
        assert result["archive"]["status"] == "failed"
        assert result["workflow"]["status"] == "archive_failed"
        assert result["workload"]["settlement_status"] != "settled"
        assert result["workload"]["contributor_entries"] == []
        expected_code = code + ("_not_declared" if remove_declaration else "_not_found")
        assert expected_code in result["archive"]["last_error"]
        assert child.job_id in result["archive"]["last_error"]
        assert field in result["archive"]["last_error"]
        assert sentinel.read_bytes() == b"preserve until every required artifact is ready"

        if remove_declaration:
            child = runtime.job_manager.reload_job(child.job_id)
            setattr(child.artifacts, field, artifact)
            runtime.job_manager.update_job(child)
        else:
            held.rename(artifact)
        assert management.archive_retry_worker.run_once() == 1
        recovered = runtime.group_manager.reload_group(group_id)
        assert recovered.archive.status.value == "succeeded"
        assert recovered.workflow.status.value == "archived"
        assert recovered.workload.settlement_status.value == "settled"
        assert len(recovered.workload.contributor_entries) == 4
        assert (target / artifact.name).read_bytes() == original_bytes
        assert management.archive_retry_worker.run_once() == 0


def test_optional_ied_remains_optional_during_archive(monkeypatch, tmp_path):
    project_root = configure_management_env(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        management = cast(Any, client.app).state.management
        management.admin_config_store.update({"archive_root_path": str(project_root / "archive")})
        group_id = _seed_group(client, tmp_path, include_ied_plan=False)
        submitted = client.post(f"/api/jobs/{group_id}/workload-submission", json={}, headers=_headers(client, "zhangsan"))
        assert submitted.status_code == 200, submitted.text
        result = _approve_all(client, group_id)
        assert result["archive"]["status"] == "succeeded"
        assert result["workload"]["settlement_status"] == "settled"
