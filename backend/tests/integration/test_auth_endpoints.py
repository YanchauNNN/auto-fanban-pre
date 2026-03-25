from __future__ import annotations

from API.app.main import create_app
from fastapi.testclient import TestClient

from ..management_test_helpers import configure_management_env
from .test_task_group_submit_flow import _login, _seed_group


def test_auth_login_me_change_password(monkeypatch, tmp_path) -> None:
    configure_management_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        login = client.post("/api/auth/login", json={"account_id": "zhangsan", "password": "password"})
        assert login.status_code == 200
        token = login.json()["token"]

        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["account_id"] == "zhangsan"

        change = client.post(
            "/api/auth/change-password",
            json={"new_password": "new-password"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert change.status_code == 200

        relogin = client.post("/api/auth/login", json={"account_id": "zhangsan", "password": "new-password"})
        assert relogin.status_code == 200


def test_auth_me_includes_pending_todo_count(monkeypatch, tmp_path) -> None:
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

        me_lisi = client.get("/api/auth/me", headers={"Authorization": f"Bearer {_login(client, 'lisi')}"})
        assert me_lisi.status_code == 200
        assert me_lisi.json()["pending_todo_count"] == 1

        me_zhangsan = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {_login(client, 'zhangsan')}"},
        )
        assert me_zhangsan.status_code == 200
        assert me_zhangsan.json()["pending_todo_count"] == 0


def test_accounts_normalize_personnel_endpoint_returns_candidates(monkeypatch, tmp_path) -> None:
    configure_management_env(
        monkeypatch,
        tmp_path,
        rows=[
            {
                "科室编码": "S01",
                "科室": "结构一室",
                "账号": "dup-1",
                "姓名": "重名",
                "角色": "设计人员",
                "密码": "password",
            },
            {
                "科室编码": "S02",
                "科室": "结构二室",
                "账号": "dup-2",
                "姓名": "重名",
                "角色": "设计人员",
                "密码": "password",
            },
        ],
    )

    with TestClient(create_app()) as client:
        token = _login(client, "dup-1")
        response = client.post(
            "/api/accounts/normalize-personnel",
            json={"field_name": "ied_checked_by", "raw_value": "重名"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["normalized"]["status"] == "ambiguous"
        assert [item["account_id"] for item in payload["candidates"]] == ["dup-1", "dup-2"]
