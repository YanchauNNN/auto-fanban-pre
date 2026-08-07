from __future__ import annotations

from API.app.main import create_app
from fastapi.testclient import TestClient

from ..management_test_helpers import configure_management_env
from .test_task_group_submit_flow import _login, _seed_group


def test_archive_overwrite_clears_existing_target_dir(monkeypatch, tmp_path) -> None:
    project_root = configure_management_env(monkeypatch, tmp_path)
    archive_root = project_root / "archive-root"
    stale_target = archive_root / "2016" / "JG001" / "2016-JG001" / "A"
    stale_target.mkdir(parents=True, exist_ok=True)
    stale_file = stale_target / "stale.txt"
    stale_file.write_text("old", encoding="utf-8")

    with TestClient(create_app()) as client:
        admin_token = _login(client, "admin")
        group_id = _seed_group(client, tmp_path)
        patch = client.patch(
            "/api/admin/config",
            json={"archive_root_path": str(archive_root)},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert patch.status_code == 200

        client.post(
            f"/api/task-groups/{group_id}/submit",
            json={"overwrite_archive_existing": True},
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )
        client.post(f"/api/workflow/{group_id}/approve", json={"factor": 1.0}, headers={"Authorization": f"Bearer {_login(client, 'lisi')}"})
        client.post(f"/api/workflow/{group_id}/approve", json={"factor": 1.0}, headers={"Authorization": f"Bearer {_login(client, 'wangwu')}"})
        final = client.post(
            f"/api/workflow/{group_id}/approve",
            json={"factor": 1.0},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert final.status_code == 200
        assert not stale_file.exists()
        assert (stale_target / "package.zip").exists()


def test_archive_replacement_removes_old_group_summary(monkeypatch, tmp_path) -> None:
    project_root = configure_management_env(monkeypatch, tmp_path)
    archive_root = project_root / "archive-root"

    with TestClient(create_app()) as client:
        admin_token = _login(client, "admin")
        patch = client.patch(
            "/api/admin/config",
            json={"archive_root_path": str(archive_root)},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert patch.status_code == 200

        old_group_id = _seed_group(client, tmp_path)
        client.post(
            f"/api/task-groups/{old_group_id}/submit",
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )
        client.post(
            f"/api/workflow/{old_group_id}/approve",
            json={"factor": 1.0},
            headers={"Authorization": f"Bearer {_login(client, 'lisi')}"},
        )
        client.post(
            f"/api/workflow/{old_group_id}/approve",
            json={"factor": 1.0},
            headers={"Authorization": f"Bearer {_login(client, 'wangwu')}"},
        )
        archived = client.post(
            f"/api/workflow/{old_group_id}/approve",
            json={"factor": 1.0},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert archived.status_code == 200
        assert archived.json()["archive"]["status"] == "succeeded"
        runtime = client.app.state.runtime
        runtime.refresh_summary_index("group", old_group_id)
        assert old_group_id in {
            item["item_id"] for item in runtime.queue_store.list_summaries()["items"]
        }

        new_group_id = _seed_group(client, tmp_path)
        submitted = client.post(
            f"/api/task-groups/{new_group_id}/submit",
            json={"overwrite_archive_existing": True},
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )
        assert submitted.status_code == 200
        client.post(
            f"/api/workflow/{new_group_id}/approve",
            json={"factor": 1.0},
            headers={"Authorization": f"Bearer {_login(client, 'lisi')}"},
        )
        client.post(
            f"/api/workflow/{new_group_id}/approve",
            json={"factor": 1.0},
            headers={"Authorization": f"Bearer {_login(client, 'wangwu')}"},
        )
        replaced = client.post(
            f"/api/workflow/{new_group_id}/approve",
            json={"factor": 1.0},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert replaced.status_code == 200

        assert runtime.group_manager.get_group(old_group_id) is None
        summaries = client.get(
            "/api/jobs",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert summaries.status_code == 200
        assert old_group_id not in {item["group_id"] for item in summaries.json()["items"]}
