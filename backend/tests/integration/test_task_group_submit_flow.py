from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from API.app.main import create_app
from fastapi.testclient import TestClient

from src.models import JobArtifacts

from ..management_test_helpers import configure_management_env


def _login(client: TestClient, account_id: str) -> str:
    response = client.post("/api/auth/login", json={"account_id": account_id, "password": "password"})
    assert response.status_code == 200
    return response.json()["token"]


def _seed_group(client: TestClient, tmp_path: Path) -> str:
    runtime = cast(Any, client.app).state.runtime
    group = runtime.group_manager.create_group(
        batch_id="batch-1",
        source_filenames=["sample.dwg"],
        project_no="2016",
        run_audit_check=False,
    )
    group.shared_dir = runtime.config.get_group_dir(group.group_id) / "shared"
    group.shared_dir.mkdir(parents=True, exist_ok=True)

    job = runtime.job_manager.create_job(
        job_type="deliverable",
        project_no="2016",
        batch_id="batch-1",
        group_id=group.group_id,
        source_filename="sample.dwg",
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
        },
    )
    job_dir = runtime.config.get_job_dir(job.job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    package_zip = job_dir / "package.zip"
    ied_xlsx = job_dir / "ied.xlsx"
    package_zip.write_bytes(b"zip")
    ied_xlsx.write_bytes(b"xlsx")
    job.artifacts = JobArtifacts(package_zip=package_zip, ied_xlsx=ied_xlsx)
    runtime.job_manager.update_job(job)

    group.child_job_ids = [job.job_id]
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
            headers={"Authorization": f"Bearer {_login(client, 'admin')}"},
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
