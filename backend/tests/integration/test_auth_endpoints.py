from __future__ import annotations

from API.app.main import create_app
from fastapi.testclient import TestClient

from ..management_test_helpers import configure_management_env


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
