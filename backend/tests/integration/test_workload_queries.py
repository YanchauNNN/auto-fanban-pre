from __future__ import annotations

from API.app.main import create_app
from fastapi.testclient import TestClient

from ..management_test_helpers import configure_management_env
from .test_task_group_submit_flow import _login, _seed_group


def _stub_cad_slot_pool(monkeypatch) -> None:
    import API.app.runtime as runtime_module

    class _ApiOnlyCadSlotPool:
        def __init__(self, *, config, slot_count) -> None:
            self.config = config
            self.slot_count = slot_count

    monkeypatch.setattr(runtime_module, "CADSlotPool", _ApiOnlyCadSlotPool)


def test_workload_queries_return_expected_scopes(monkeypatch, tmp_path) -> None:
    _stub_cad_slot_pool(monkeypatch)
    project_root = configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        admin_token = _login(client, "admin")
        group_id = _seed_group(client, tmp_path)
        client.patch(
            "/api/admin/config",
            json={"archive_root_path": str(project_root / "archive-root")},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        client.post(f"/api/task-groups/{group_id}/submit", headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"})
        client.post(f"/api/workflow/{group_id}/approve", json={"factor": 1.0}, headers={"Authorization": f"Bearer {_login(client, 'lisi')}"})
        client.post(f"/api/workflow/{group_id}/approve", json={"factor": 1.0}, headers={"Authorization": f"Bearer {_login(client, 'wangwu')}"})
        client.post(f"/api/workflow/{group_id}/approve", json={"factor": 1.0}, headers={"Authorization": f"Bearer {admin_token}"})

        me = client.get("/api/workload/me", headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"})
        office = client.get("/api/workload/office", headers={"Authorization": f"Bearer {_login(client, 'lisi')}"})
        institute = client.get("/api/workload/institute", headers={"Authorization": f"Bearer {_login(client, 'wangwu')}"})
        admin = client.get("/api/workload/admin", headers={"Authorization": f"Bearer {admin_token}"})

        assert me.status_code == 200
        assert me.json()["scope"] == "me"
        assert office.status_code == 200
        assert office.json()["scope"] == "office"
        assert institute.status_code == 200
        assert institute.json()["scope"] == "institute"
        assert admin.status_code == 200
        admin_payload = admin.json()
        assert admin_payload["scope"] == "admin"
        assert admin_payload["entries"]
        assert admin_payload["totals_by_account"]
        assert admin_payload["total_workload_a1"] > 0
        assert admin_payload["total_workload_a1"] == round(
            sum(float(entry["workload_a1"]) for entry in admin_payload["entries"]),
            2,
        )
        assert admin_payload["total_workload_a1"] == round(
            sum(float(value) for value in admin_payload["totals_by_account"].values()),
            2,
        )


def test_workload_queries_support_basic_filters(monkeypatch, tmp_path) -> None:
    _stub_cad_slot_pool(monkeypatch)
    project_root = configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        admin_token = _login(client, "admin")
        group_id = _seed_group(client, tmp_path)
        client.patch(
            "/api/admin/config",
            json={"archive_root_path": str(project_root / "archive-root")},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        client.post(
            f"/api/task-groups/{group_id}/submit",
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )
        client.post(
            f"/api/workflow/{group_id}/approve",
            json={"factor": 1.0},
            headers={"Authorization": f"Bearer {_login(client, 'lisi')}"},
        )
        client.post(
            f"/api/workflow/{group_id}/approve",
            json={"factor": 1.0},
            headers={"Authorization": f"Bearer {_login(client, 'wangwu')}"},
        )
        client.post(
            f"/api/workflow/{group_id}/approve",
            json={"factor": 1.0},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        settled_only = client.get(
            "/api/workload/me?status=settled&valid_only=true",
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )
        assert settled_only.status_code == 200
        assert settled_only.json()["filters"]["status"] == "settled"
        assert settled_only.json()["filters"]["valid_only"] is True
        assert settled_only.json()["entries"]
        assert settled_only.json()["entries"][0]["group_display_name"] == "2016-JG001"
        assert settled_only.json()["entries"][0]["album_internal_code"] == "2016-JG001"
