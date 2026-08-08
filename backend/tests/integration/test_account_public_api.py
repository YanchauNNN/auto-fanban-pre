from __future__ import annotations

from typing import Any

import yaml
from API.app.main import create_app
from fastapi.testclient import TestClient

from src.config import MechanismSpecLoader, SpecLoader

from ..management_test_helpers import configure_management_env

_SENSITIVE_KEY_PARTS = ("password", "passwd", "pwd", "secret", "密码", "密碼", "口令")


def _assert_public_payload(payload: Any, *, forbidden_values: set[str]) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized_key = "".join(character for character in str(key).casefold() if character.isalnum())
            assert not any(part in normalized_key for part in _SENSITIVE_KEY_PARTS), key
            _assert_public_payload(value, forbidden_values=forbidden_values)
        return
    if isinstance(payload, list):
        for item in payload:
            _assert_public_payload(item, forbidden_values=forbidden_values)
        return
    if isinstance(payload, str):
        assert payload not in forbidden_values


def test_account_endpoints_never_expose_passwords(monkeypatch, tmp_path) -> None:
    import API.app.runtime as runtime_module

    class _ApiOnlyCadSlotPool:
        def __init__(self, *, config, slot_count) -> None:
            self.config = config
            self.slot_count = slot_count

    monkeypatch.setattr(runtime_module, "CADSlotPool", _ApiOnlyCadSlotPool)

    secrets = {
        "admin-login-secret",
        "  changed admin secret  ",
        "invalid-row-secret",
        "  created-account-secret  ",
        "updated-account-secret",
    }
    project_root = configure_management_env(
        monkeypatch,
        tmp_path,
        rows=[
            {
                "科室编码": "ADM",
                "科室": "信息中心",
                "账号": "admin",
                "姓名": "管理员",
                "角色": "管理员",
                "密码": "admin-login-secret",
            },
            {
                "科室编码": "S01",
                "科室": "结构一室",
                "账号": "invalid-role",
                "姓名": "待修复人员",
                "角色": "未知角色",
                "密码": "invalid-row-secret",
            },
            {
                "科室编码": "S02",
                "科室": "结构二室",
                "账号": "missing-password",
                "姓名": "缺少密码人员",
                "角色": "设计人员",
                "密码": "",
            },
        ],
    )
    metadata_secret = "metadata-default-secret-must-stay-private"
    spec_path = project_root / "documents" / "参数规范.yaml"
    spec_payload = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    spec_payload["management_features"]["account"][
        "admin_created_default_password"
    ] = metadata_secret
    spec_path.write_text(
        yaml.safe_dump(spec_payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    SpecLoader.clear_cache()
    MechanismSpecLoader.clear_cache()
    secrets.add(metadata_secret)

    app = create_app(job_processor=lambda _job: None)

    with TestClient(app) as client:
        monkeypatch.setattr(app.state.runtime.metadata, "_resolve_options", lambda *_args: [])
        form_schema = client.get("/api/meta/form-schema")
        assert form_schema.status_code == 200
        account_schema = form_schema.json()["management"]["account"]
        assert account_schema["admin_created_default_password_configured"] is True
        assert "admin_created_default_password" not in account_schema
        assert metadata_secret not in form_schema.text

        login = client.post(
            "/api/auth/login",
            json={"account_id": "admin", "password": "admin-login-secret"},
        )
        assert login.status_code == 200
        _assert_public_payload(login.json(), forbidden_values=secrets)
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        change_password = client.post(
            "/api/auth/change-password",
            json={"new_password": "  changed admin secret  "},
            headers=headers,
        )
        assert change_password.status_code == 200
        _assert_public_payload(change_password.json(), forbidden_values=secrets)

        exact_relogin = client.post(
            "/api/auth/login",
            json={"account_id": "admin", "password": "  changed admin secret  "},
        )
        assert exact_relogin.status_code == 200
        _assert_public_payload(exact_relogin.json(), forbidden_values=secrets)
        headers = {"Authorization": f"Bearer {exact_relogin.json()['token']}"}

        current_account = client.get("/api/auth/me", headers=headers)
        assert current_account.status_code == 200
        _assert_public_payload(current_account.json(), forbidden_values=secrets)

        normalized_personnel = client.post(
            "/api/accounts/normalize-personnel",
            json={"field_name": "ied_checked_by", "raw_value": "管理员"},
            headers=headers,
        )
        assert normalized_personnel.status_code == 200
        _assert_public_payload(normalized_personnel.json(), forbidden_values=secrets)

        accounts = client.get("/api/accounts", headers=headers)
        assert accounts.status_code == 200
        _assert_public_payload(accounts.json(), forbidden_values=secrets)

        invalid_rows = client.get("/api/accounts/invalid-rows", headers=headers)
        assert invalid_rows.status_code == 200
        assert {item["row_number"] for item in invalid_rows.json()["items"]} == {3, 4}
        _assert_public_payload(invalid_rows.json(), forbidden_values=secrets)

        created = client.post(
            "/api/accounts",
            json={
                "office_code": "S03",
                "office_name": "结构三室",
                "account_id": "created-user",
                "display_name": "新建人员",
                "role": "设计人员",
                "password": "  created-account-secret  ",
            },
            headers=headers,
        )
        assert created.status_code == 200
        _assert_public_payload(created.json(), forbidden_values=secrets)

        exact_created_login = client.post(
            "/api/auth/login",
            json={"account_id": "created-user", "password": "  created-account-secret  "},
        )
        assert exact_created_login.status_code == 200
        _assert_public_payload(exact_created_login.json(), forbidden_values=secrets)
        trimmed_created_login = client.post(
            "/api/auth/login",
            json={"account_id": "created-user", "password": "created-account-secret"},
        )
        assert trimmed_created_login.status_code == 401

        updated = client.patch(
            "/api/accounts/created-user",
            json={
                "account_id": "renamed-user",
                "display_name": "更名人员",
                "password": "updated-account-secret",
            },
            headers=headers,
        )
        assert updated.status_code == 200
        assert updated.json()["account_id"] == "renamed-user"
        _assert_public_payload(updated.json(), forbidden_values=secrets)

        repaired = client.patch(
            "/api/accounts/rows/3",
            json={"role": "设计人员"},
            headers=headers,
        )
        assert repaired.status_code == 200
        _assert_public_payload(repaired.json(), forbidden_values=secrets)
