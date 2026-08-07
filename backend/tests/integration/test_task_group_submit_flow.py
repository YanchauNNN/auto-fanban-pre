from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from zipfile import ZipFile

import pytest
import yaml
from API.app.main import create_app
from fastapi.testclient import TestClient

from src.config import MechanismSpecLoader
from src.models import JobArtifacts, JobStatus
from src.workflow.models import WorkflowStatus

from ..management_test_helpers import configure_management_env


def _login(client: TestClient, account_id: str) -> str:
    response = client.post("/api/auth/login", json={"account_id": account_id, "password": "password"})
    assert response.status_code == 200
    return response.json()["token"]


def _seed_group(
    client: TestClient,
    tmp_path: Path,
    *,
    include_ied_plan: bool = False,
) -> str:
    runtime = cast(Any, client.app).state.runtime
    creator = cast(Any, client.app).state.management.account_registry.to_snapshot("zhangsan")
    group = runtime.group_manager.create_group(
        batch_id="batch-1",
        source_filenames=["sample.dwg"],
        project_no="2016",
        run_audit_check=False,
        creator_snapshot=creator,
    )
    group.shared_dir = runtime.config.get_group_dir(group.group_id) / "shared"
    group.shared_dir.mkdir(parents=True, exist_ok=True)

    job = runtime.job_manager.create_job(
        job_type="deliverable",
        project_no="2016",
        batch_id="batch-1",
        group_id=group.group_id,
        source_filename="sample.dwg",
        task_role="deliverable_main",
        params={
            "project_no": "2016",
            "classification": "非密",
            "subitem_name": "测试子项",
            "album_title_cn": "测试图册",
            "cover_variant": "通用",
            "engineering_no": "2016",
            "subitem_no": "JG001",
            "revision": "A",
            "ied_prepared_by": "张三",
            "ied_checked_by": "李四",
            "ied_discipline_leader": "王五",
            "ied_reviewed_by": "王五",
            "ied_approved_by": "管理员",
            "include_ied_plan": include_ied_plan,
        },
    )
    job_dir = runtime.config.get_job_dir(job.job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    package_zip = job_dir / "package.zip"
    with ZipFile(package_zip, "w") as archive:
        archive.writestr("manifest.txt", "minimal deliverable package")
    ied_xlsx = None
    if include_ied_plan:
        ied_xlsx = job_dir / "ied.xlsx"
        ied_xlsx.write_bytes(b"minimal ied workbook")
    job.artifacts = JobArtifacts(package_zip=package_zip, ied_xlsx=ied_xlsx)
    job.mark_succeeded()
    runtime.job_manager.update_job(job)

    group.child_job_ids = [job.job_id]
    group.mark_succeeded()
    runtime.group_manager.update_group(group)

    (group.shared_dir / "source_input.dwg").write_text("dwg", encoding="utf-8")
    (group.shared_dir / "source_converted.dxf").write_text("dxf", encoding="utf-8")
    (group.shared_dir / "prep_summary.json").write_text(
        json.dumps(
            {
                "source_input_dwg": str(group.shared_dir / "source_input.dwg"),
                "source_converted_dxf": str(group.shared_dir / "source_converted.dxf"),
            }
        ),
        encoding="utf-8",
    )
    frame_payload = {
        "runtime": {
            "frame_id": "frame-001",
            "source_file": str(group.shared_dir / "source_converted.dxf"),
            "outer_bbox": {"xmin": 0, "ymin": 0, "xmax": 841, "ymax": 594},
            "paper_variant_id": "A1",
            "sx": 1.0,
            "sy": 1.0,
            "geom_scale_factor": 1.0,
            "roi_profile_id": "BASE10",
        },
        "titleblock": {
            "internal_code": "2016-JG001-001",
            "revision": "A",
        },
        "raw_extracts": {},
    }
    (group.shared_dir / "frames.json").write_text(json.dumps([frame_payload], ensure_ascii=False), encoding="utf-8")
    (group.shared_dir / "sheet_sets.json").write_text("[]", encoding="utf-8")
    return group.group_id


def _write_task_group_submission_mechanism(
    project_root: Path,
    payload: dict[str, object],
) -> None:
    mechanism_path = project_root / "documents" / "参数规范-3.yaml"
    mechanism_payload = yaml.safe_load(mechanism_path.read_text(encoding="utf-8"))
    mechanism_payload["backend_mechanism"]["task_group_submission"] = payload
    mechanism_path.write_text(
        yaml.safe_dump(mechanism_payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    MechanismSpecLoader.clear_cache()


def _runtime_group_and_child(client: TestClient, group_id: str):
    runtime = cast(Any, client.app).state.runtime
    group = runtime.group_manager.get_group(group_id)
    assert group is not None
    assert len(group.child_job_ids) == 1
    child = runtime.job_manager.get_job(group.child_job_ids[0])
    assert child is not None
    return runtime, group, child


def _assert_submit_blocked(
    client: TestClient,
    group_id: str,
    expected_error: str,
) -> None:
    token = _login(client, "zhangsan")
    detail = client.get(
        f"/api/task-groups/{group_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200
    assert detail.json()["can_submit"] is False

    submit = client.post(
        f"/api/task-groups/{group_id}/submit",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert submit.status_code == 422
    assert submit.json()["detail"] == expected_error


@pytest.mark.parametrize(
    "group_status",
    [JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.FAILED],
)
def test_submit_requires_succeeded_task_group(monkeypatch, tmp_path, group_status: JobStatus) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path)
        runtime, group, _ = _runtime_group_and_child(client, group_id)
        group.status = group_status
        runtime.group_manager.update_group(group)

        _assert_submit_blocked(client, group_id, "task_group_not_succeeded")


def test_submit_requires_at_least_one_child_job(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path)
        runtime, group, _ = _runtime_group_and_child(client, group_id)
        group.child_job_ids = []
        runtime.group_manager.update_group(group)

        _assert_submit_blocked(client, group_id, "task_group_children_missing")


def test_submit_rejects_missing_child_job_record(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path)
        runtime, group, _ = _runtime_group_and_child(client, group_id)
        group.child_job_ids = ["missing-child"]
        runtime.group_manager.update_group(group)

        _assert_submit_blocked(client, group_id, "task_group_child_not_found")


def test_submit_requires_every_child_job_to_succeed(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path)
        runtime, _, child = _runtime_group_and_child(client, group_id)
        child.status = JobStatus.FAILED
        runtime.job_manager.update_job(child)

        _assert_submit_blocked(client, group_id, "task_group_child_not_succeeded")


def test_submit_requires_deliverable_main_child(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path)
        runtime, _, child = _runtime_group_and_child(client, group_id)
        child.task_role = "audit_check"
        runtime.job_manager.update_job(child)

        _assert_submit_blocked(client, group_id, "deliverable_main_missing")


def test_submit_requires_declared_deliverable_package(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path)
        runtime, _, child = _runtime_group_and_child(client, group_id)
        child.artifacts.package_zip = None
        runtime.job_manager.update_job(child)

        _assert_submit_blocked(client, group_id, "deliverable_package_not_declared")


def test_submit_requires_existing_deliverable_package(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path)
        runtime, _, child = _runtime_group_and_child(client, group_id)
        child.artifacts.package_zip = tmp_path / "missing-package.zip"
        runtime.job_manager.update_job(child)

        _assert_submit_blocked(client, group_id, "deliverable_package_not_found")


def test_detail_and_submit_reload_worker_persisted_group_and_child_state(
    monkeypatch,
    tmp_path,
) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path)
        runtime, cached_group, cached_child = _runtime_group_and_child(client, group_id)

        cached_group.status = JobStatus.QUEUED
        cached_child.status = JobStatus.QUEUED
        token = _login(client, "zhangsan")

        detail = client.get(
            f"/api/task-groups/{group_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert detail.status_code == 200
        assert detail.json()["status"] == "succeeded"
        assert detail.json()["can_submit"] is True

        runtime.group_manager.get_group(group_id).status = JobStatus.QUEUED
        runtime.job_manager.get_job(cached_child.job_id).status = JobStatus.QUEUED
        submit = client.post(
            f"/api/task-groups/{group_id}/submit",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert submit.status_code == 200
        assert submit.json()["workflow"]["status"] == "in_review"


@pytest.mark.parametrize(
    ("group_status", "workflow_status", "expected_error"),
    [
        (JobStatus.QUEUED, WorkflowStatus.DRAFT, "task_group_not_succeeded"),
        (JobStatus.SUCCEEDED, WorkflowStatus.IN_REVIEW, "workflow_not_draft"),
    ],
)
def test_rejected_status_short_circuits_child_and_shared_prep_io(
    monkeypatch,
    tmp_path,
    group_status: JobStatus,
    workflow_status: WorkflowStatus,
    expected_error: str,
) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path)
        runtime, group, _ = _runtime_group_and_child(client, group_id)
        group.status = group_status
        group.workflow.status = workflow_status
        policy = cast(Any, client.app).state.management.task_group_service.submission_readiness
        monkeypatch.setattr(
            policy.job_manager,
            "reload_job",
            lambda _job_id: pytest.fail("rejected status must not reload child jobs"),
        )
        monkeypatch.setattr(
            policy,
            "_inspect_shared_prep",
            lambda _group: pytest.fail("rejected status must not read shared prep"),
        )

        result = policy.inspect(group)

        assert result.is_ready is False
        assert result.primary_error == expected_error


def test_ready_policy_reads_each_shared_prep_json_once(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path)
        _, group, _ = _runtime_group_and_child(client, group_id)
        shared_dir = group.shared_dir.resolve()
        counts: dict[str, int] = {}
        original_read_text = Path.read_text

        def counting_read_text(path: Path, *args, **kwargs):
            if path.parent.resolve() == shared_dir:
                counts[path.name] = counts.get(path.name, 0) + 1
            return original_read_text(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", counting_read_text)
        policy = cast(Any, client.app).state.management.task_group_service.submission_readiness

        result = policy.inspect(group)

        assert result.is_ready is True
        assert counts["frames.json"] == 1
        assert counts["sheet_sets.json"] == 1
        assert counts["prep_summary.json"] == 1


@pytest.mark.parametrize(
    ("filename", "invalid_contents"),
    [
        ("frames.json", "{"),
        ("sheet_sets.json", None),
    ],
)
def test_submit_rejects_missing_or_invalid_shared_prep_json(
    monkeypatch,
    tmp_path,
    filename: str,
    invalid_contents: str | None,
) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path)
        runtime, group, _ = _runtime_group_and_child(client, group_id)
        target = group.shared_dir / filename
        if invalid_contents is None:
            target.unlink()
        else:
            target.write_text(invalid_contents, encoding="utf-8")

        _assert_submit_blocked(client, group_id, "shared_prep_invalid")


def test_submit_rejects_missing_shared_prep_source_input(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path)
        _, group, _ = _runtime_group_and_child(client, group_id)
        (group.shared_dir / "source_input.dwg").unlink()

        _assert_submit_blocked(client, group_id, "shared_prep_source_missing")


@pytest.mark.parametrize("source_kind", ["relative_parent", "absolute_external"])
def test_submit_rejects_shared_prep_source_outside_shared_directory(
    monkeypatch,
    tmp_path,
    source_kind: str,
) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path)
        _, group, _ = _runtime_group_and_child(client, group_id)
        if source_kind == "relative_parent":
            outside = group.shared_dir.parent / "outside-relative.dwg"
            summary_value = "../outside-relative.dwg"
        else:
            outside = tmp_path / "outside-absolute.dwg"
            summary_value = str(outside.resolve())
        outside.write_text("outside", encoding="utf-8")
        (group.shared_dir / "prep_summary.json").write_text(
            json.dumps(
                {
                    "source_input_dwg": summary_value,
                    "source_converted_dxf": str(group.shared_dir / "source_converted.dxf"),
                }
            ),
            encoding="utf-8",
        )

        _assert_submit_blocked(client, group_id, "shared_prep_source_outside")


def test_shared_prep_validation_precedes_duplicate_cancellation_side_effect(
    monkeypatch,
    tmp_path,
) -> None:
    project_root = configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        admin_token = _login(client, "admin")
        patch = client.patch(
            "/api/admin/config",
            json={"archive_root_path": str(project_root / "archive-root")},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert patch.status_code == 200

        first_group_id = _seed_group(client, tmp_path)
        first_submit = client.post(
            f"/api/task-groups/{first_group_id}/submit",
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )
        assert first_submit.status_code == 200

        second_group_id = _seed_group(client, tmp_path)
        runtime, second_group, _ = _runtime_group_and_child(client, second_group_id)
        (second_group.shared_dir / "frames.json").write_text("{", encoding="utf-8")
        blocked = client.post(
            f"/api/task-groups/{second_group_id}/submit",
            json={"cancel_existing_in_progress": True},
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )

        assert blocked.status_code == 422
        assert blocked.json()["detail"] == "shared_prep_invalid"
        assert runtime.group_manager.reload_group(first_group_id) is not None


def test_include_ied_plan_false_does_not_require_ied_artifact(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path, include_ied_plan=False)
        detail = client.get(
            f"/api/task-groups/{group_id}",
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )

        assert detail.status_code == 200
        assert detail.json()["can_submit"] is True


def test_include_ied_plan_true_requires_declared_ied_artifact(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path, include_ied_plan=True)
        runtime, _, child = _runtime_group_and_child(client, group_id)
        child.artifacts.ied_xlsx = None
        runtime.job_manager.update_job(child)

        _assert_submit_blocked(client, group_id, "deliverable_ied_not_declared")


def test_include_ied_plan_true_requires_existing_ied_artifact(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path, include_ied_plan=True)
        runtime, _, child = _runtime_group_and_child(client, group_id)
        child.artifacts.ied_xlsx = tmp_path / "missing-ied.xlsx"
        runtime.job_manager.update_job(child)

        _assert_submit_blocked(client, group_id, "deliverable_ied_not_found")


def test_include_ied_plan_true_accepts_existing_ied_artifact(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path, include_ied_plan=True)
        detail = client.get(
            f"/api/task-groups/{group_id}",
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )

        assert detail.status_code == 200
        assert detail.json()["can_submit"] is True


def test_submission_role_and_error_code_are_loaded_from_mechanism_yaml(
    monkeypatch,
    tmp_path,
) -> None:
    project_root = configure_management_env(monkeypatch, tmp_path)
    _write_task_group_submission_mechanism(
        project_root,
        {
            "required_task_roles": [
                {
                    "task_role": "configured_deliverable",
                    "missing_role_error": "configured_deliverable_missing",
                    "duplicate_role_error": "configured_deliverable_duplicate",
                    "artifacts": [
                        {
                            "field": "package_zip",
                            "not_declared_error": "configured_package_not_declared",
                            "not_found_error": "configured_package_not_found",
                        }
                    ],
                }
            ]
        },
    )

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path)

        _assert_submit_blocked(client, group_id, "configured_deliverable_missing")


def test_submit_rejects_duplicate_required_task_role(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path)
        runtime, group, child = _runtime_group_and_child(client, group_id)
        duplicate = runtime.job_manager.create_job(
            job_type="deliverable",
            project_no=child.project_no,
            group_id=group.group_id,
            task_role="deliverable_main",
            params=dict(child.params),
        )
        duplicate.artifacts = child.artifacts.model_copy(deep=True)
        duplicate.mark_succeeded()
        runtime.job_manager.update_job(duplicate)
        group.child_job_ids.append(duplicate.job_id)
        runtime.group_manager.update_group(group)

        _assert_submit_blocked(client, group_id, "deliverable_main_duplicate")


@pytest.mark.parametrize(
    "workflow_status",
    [status for status in WorkflowStatus if status is not WorkflowStatus.DRAFT],
)
def test_submit_and_restart_reject_non_draft_workflow(
    monkeypatch,
    tmp_path,
    workflow_status: WorkflowStatus,
) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path)
        runtime, group, _ = _runtime_group_and_child(client, group_id)
        group.workflow.status = workflow_status
        runtime.group_manager.update_group(group)
        token = _login(client, "zhangsan")

        detail = client.get(
            f"/api/task-groups/{group_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert detail.status_code == 200
        assert detail.json()["can_submit"] is False

        for action in ("submit", "restart-submit"):
            response = client.post(
                f"/api/task-groups/{group_id}/{action}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 422
            assert response.json()["detail"] == "workflow_not_draft"

        persisted = runtime.group_manager.reload_group(group_id)
        assert persisted is not None
        assert persisted.workflow.status is workflow_status


def test_submit_preserves_configured_discipline_leader_in_personnel_snapshot(
    monkeypatch,
    tmp_path,
) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path)
        submit = client.post(
            f"/api/task-groups/{group_id}/submit",
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )

        assert submit.status_code == 200
        discipline_leader = submit.json()["personnel_snapshot"]["members"]["ied_discipline_leader"]
        assert discipline_leader["matched_account"] == "wangwu"


def test_task_group_submit_and_approve_until_archive(monkeypatch, tmp_path) -> None:
    project_root = configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        admin_token = _login(client, "admin")
        group_id = _seed_group(client, tmp_path)

        patch = client.patch(
            "/api/admin/config",
            json={"archive_root_path": str(project_root / "archive-root")},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert patch.status_code == 200

        submit = client.post(
            f"/api/task-groups/{group_id}/submit",
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )
        assert submit.status_code == 200
        assert submit.json()["workflow"]["current_node_key"] == "one_review"

        approve1 = client.post(
            f"/api/workflow/{group_id}/approve",
            json={"factor": 1.0},
            headers={"Authorization": f"Bearer {_login(client, 'lisi')}"},
        )
        assert approve1.status_code == 200
        assert approve1.json()["workflow"]["current_node_key"] == "two_review"

        approve2 = client.post(
            f"/api/workflow/{group_id}/approve",
            json={"factor": 1.05},
            headers={"Authorization": f"Bearer {_login(client, 'wangwu')}"},
        )
        assert approve2.status_code == 200
        assert approve2.json()["workflow"]["current_node_key"] == "three_review"

        approve3 = client.post(
            f"/api/workflow/{group_id}/approve",
            json={"factor": 0.95},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert approve3.status_code == 200
        detail = approve3.json()
        assert detail["workflow"]["status"] == "archived"
        assert detail["archive"]["status"] == "succeeded"
        assert detail["workload"]["settlement_status"] == "settled"


def test_task_group_detail_and_monitor_include_frontend_action_flags(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path)

        before_submit = client.get(
            f"/api/task-groups/{group_id}",
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )
        assert before_submit.status_code == 200
        before_payload = before_submit.json()
        assert before_payload["can_submit"] is True
        assert before_payload["can_approve"] is False
        assert before_payload["effective_workload"] == 0.0

        client.post(
            f"/api/task-groups/{group_id}/submit",
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )

        detail = client.get(
            f"/api/task-groups/{group_id}",
            headers={"Authorization": f"Bearer {_login(client, 'lisi')}"},
        )
        assert detail.status_code == 200
        payload = detail.json()
        assert payload["can_submit"] is False
        assert payload["can_approve"] is True
        assert payload["is_related_to_current_user"] is True
        assert payload["album_internal_code"] == "2016-JG001"
        assert payload["display_name"] == "2016-JG001"
        assert payload["creator_name"] == "张三"
        assert payload["effective_workload"] == payload["workload"]["initial_workload_a1"]

        monitor = client.get(
            "/api/workflow/monitor",
            headers={"Authorization": f"Bearer {_login(client, 'lisi')}"},
        )
        assert monitor.status_code == 200
        monitor_item = monitor.json()["items"][0]
        assert monitor_item["can_approve"] is True
        assert monitor_item["current_node_key"] == "one_review"
        assert monitor_item["display_name"] == "2016-JG001"


def test_workflow_approve_requires_matching_node_key_when_provided(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path)
        client.post(
            f"/api/task-groups/{group_id}/submit",
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )

        wrong_node = client.post(
            f"/api/workflow/{group_id}/approve",
            json={"node_key": "two_review", "factor": 1.0},
            headers={"Authorization": f"Bearer {_login(client, 'lisi')}"},
        )
        assert wrong_node.status_code == 422
        assert wrong_node.json()["detail"] == "node_key_mismatch"

        correct_node = client.post(
            f"/api/workflow/{group_id}/approve",
            json={"node_key": "one_review", "factor": 1.0},
            headers={"Authorization": f"Bearer {_login(client, 'lisi')}"},
        )
        assert correct_node.status_code == 200
        assert correct_node.json()["workflow"]["current_node_key"] == "two_review"


def test_workflow_repair_current_node_can_create_account_and_reassign(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        group_id = _seed_group(client, tmp_path)
        client.post(
            f"/api/task-groups/{group_id}/submit",
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )

        repaired = client.post(
            f"/api/workflow/{group_id}/repair-current-node",
            json={
                "create_account_payload": {
                    "office_code": "S01",
                    "office_name": "结构一室",
                    "account_id": "newchecker",
                    "display_name": "新校核",
                    "role": "设计人员",
                }
            },
            headers={"Authorization": f"Bearer {_login(client, 'admin')}"},
        )
        assert repaired.status_code == 200
        payload = repaired.json()
        assert payload["workflow"]["current_node_key"] == "one_review"
        assert payload["workflow"]["nodes"][0]["assignee_account"] == "newchecker"


def test_jobs_batch_grouped_submission_binds_owner_snapshot_from_login(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        runtime = cast(Any, client.app).state.runtime
        monkeypatch.setattr(runtime, "_enqueue_group", lambda group_id: None)

        response = client.post(
            "/api/jobs/batch",
            data={
                "params_json": json.dumps(
                    {
                        "project_no": "2016",
                        "unit_no": "1",
                        "classification": "非密",
                        "subitem_name": "测试子项",
                        "album_title_cn": "测试图册",
                        "wbs_code": "WBS-001",
                        "file_category": "1 总体文件",
                        "ied_status": "编制",
                        "ied_doc_type": "图册",
                        "cover_variant": "通用",
                        "engineering_no": "2016",
                        "subitem_no": "JG001",
                        "revision": "A",
                        "ied_prepared_by": "张三@zhangsan",
                        "ied_checked_by": "李四@lisi",
                        "ied_discipline_leader": "王五@wangwu",
                        "ied_reviewed_by": "王五@wangwu",
                        "ied_approved_by": "管理员@admin",
                    },
                    ensure_ascii=False,
                ),
                "run_audit_check": "true",
            },
            files={"files[]": ("sample.dwg", b"dwg", "application/acad")},
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )

        assert response.status_code == 201
        group_id = response.json()["jobs"][0]["group_id"]
        group = runtime.group_manager.get_group(group_id)
        assert group is not None
        assert group.owner_snapshot is not None
        assert group.owner_snapshot.creator_account == "zhangsan"
        assert group.owner_snapshot.creator_name == "张三"


def test_jobs_batch_plain_submission_binds_owner_snapshot_from_login(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        runtime = cast(Any, client.app).state.runtime
        monkeypatch.setattr(runtime, "_enqueue_job", lambda job_id: None)

        response = client.post(
            "/api/jobs/batch",
            data={
                "params_json": json.dumps(
                    {
                        "project_no": "2016",
                        "unit_no": "1",
                        "classification": "闈炲瘑",
                        "subitem_name": "娴嬭瘯瀛愰」",
                        "album_title_cn": "娴嬭瘯鍥惧唽",
                        "wbs_code": "WBS-001",
                        "file_category": "1 鎬讳綋鏂囦欢",
                        "ied_status": "缂栧埗",
                        "ied_doc_type": "鍥惧唽",
                        "cover_variant": "閫氱敤",
                    },
                    ensure_ascii=False,
                ),
            },
            files={"files[]": ("plain.dwg", b"dwg", "application/acad")},
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )

        assert response.status_code == 201
        job_id = response.json()["jobs"][0]["job_id"]
        job = runtime.job_manager.get_job(job_id)
        assert job is not None
        assert job.owner_snapshot is not None
        assert job.owner_snapshot.creator_account == "zhangsan"


def test_jobs_list_requires_login_and_filters_by_owner_scope(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        runtime = cast(Any, client.app).state.runtime
        registry = client.app.state.management.account_registry
        zhangsan = registry.to_snapshot("zhangsan")
        lisi = registry.to_snapshot("lisi")

        own_job = runtime.job_manager.create_job(
            job_type="deliverable",
            project_no="2016",
            source_filename="own.dwg",
            creator_snapshot=zhangsan,
        )
        office_job = runtime.job_manager.create_job(
            job_type="deliverable",
            project_no="2016",
            source_filename="office.dwg",
            creator_snapshot=lisi,
        )
        legacy_job = runtime.job_manager.create_job(
            job_type="deliverable",
            project_no="2016",
            source_filename="legacy.dwg",
        )
        for job in (own_job, office_job, legacy_job):
            runtime._index_job_summary(job)

        assert client.get("/api/jobs").status_code == 401

        zhangsan_jobs = client.get(
            "/api/jobs",
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )
        assert zhangsan_jobs.status_code == 200
        assert [item["job_id"] for item in zhangsan_jobs.json()["items"]] == [own_job.job_id]

        lisi_jobs = client.get(
            "/api/jobs",
            headers={"Authorization": f"Bearer {_login(client, 'lisi')}"},
        )
        assert lisi_jobs.status_code == 200
        assert {item["job_id"] for item in lisi_jobs.json()["items"]} == {
            own_job.job_id,
            office_job.job_id,
        }

        admin_jobs = client.get(
            "/api/jobs",
            headers={"Authorization": f"Bearer {_login(client, 'admin')}"},
        )
        assert admin_jobs.status_code == 200
        assert {item["job_id"] for item in admin_jobs.json()["items"]} == {
            own_job.job_id,
            office_job.job_id,
            legacy_job.job_id,
        }

        forbidden_detail = client.get(
            f"/api/jobs/{office_job.job_id}",
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )
        assert forbidden_detail.status_code == 403

        visible_detail = client.get(
            f"/api/jobs/{office_job.job_id}",
            headers={"Authorization": f"Bearer {_login(client, 'lisi')}"},
        )
        assert visible_detail.status_code == 200
        assert visible_detail.json()["creator_account"] == "lisi"


def test_task_group_submit_blocks_archive_conflict_without_explicit_overwrite(monkeypatch, tmp_path) -> None:
    project_root = configure_management_env(monkeypatch, tmp_path)
    archive_root = project_root / "archive-root"
    existing_target = archive_root / "2016" / "JG001" / "2016-JG001" / "A"
    existing_target.mkdir(parents=True, exist_ok=True)
    (existing_target / "package.zip").write_bytes(b"old")

    with TestClient(create_app()) as client:
        admin_token = _login(client, "admin")
        group_id = _seed_group(client, tmp_path)
        patch = client.patch(
            "/api/admin/config",
            json={"archive_root_path": str(archive_root)},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert patch.status_code == 200

        blocked = client.post(
            f"/api/task-groups/{group_id}/submit",
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )
        assert blocked.status_code == 422
        assert blocked.json()["detail"] == "archive_target_exists"

        allowed = client.post(
            f"/api/task-groups/{group_id}/submit",
            json={"overwrite_archive_existing": True},
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )
        assert allowed.status_code == 200
        payload = allowed.json()
        assert payload["workflow"]["duplicate_policy"] == "overwrite_archive_existing"
        assert payload["workflow"]["overwrite_archive_target"] == str(existing_target.resolve())


def test_task_group_submit_blocks_in_progress_duplicate_without_explicit_cancel(monkeypatch, tmp_path) -> None:
    project_root = configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        admin_token = _login(client, "admin")
        patch = client.patch(
            "/api/admin/config",
            json={"archive_root_path": str(project_root / "archive-root")},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert patch.status_code == 200

        first_group_id = _seed_group(client, tmp_path)
        second_group_id = _seed_group(client, tmp_path)

        first_submit = client.post(
            f"/api/task-groups/{first_group_id}/submit",
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )
        assert first_submit.status_code == 200

        blocked = client.post(
            f"/api/task-groups/{second_group_id}/submit",
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )
        assert blocked.status_code == 422
        assert blocked.json()["detail"] == "duplicate_in_progress_exists"

        allowed = client.post(
            f"/api/task-groups/{second_group_id}/submit",
            json={"cancel_existing_in_progress": True},
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )
        assert allowed.status_code == 200
        assert allowed.json()["workflow"]["duplicate_policy"] == "cancel_existing_in_progress"

        runtime = cast(Any, client.app).state.management.task_group_service.group_manager
        assert runtime.get_group(first_group_id) is None
