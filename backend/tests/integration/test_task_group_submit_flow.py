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
