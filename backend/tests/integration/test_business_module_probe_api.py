from __future__ import annotations

from API.app.main import create_app
from fastapi.testclient import TestClient

from src.deploy.business_module_probe import BusinessProbeConfig, run_business_probe

from ..management_test_helpers import configure_management_env


def test_business_probe_passes_real_read_only_management_api(
    monkeypatch,
    tmp_path,
) -> None:
    import API.app.runtime as runtime_module

    class _ApiOnlyCadSlotPool:
        def __init__(self, *, config, slot_count) -> None:
            self.config = config
            self.slot_count = slot_count

    monkeypatch.setattr(runtime_module, "CADSlotPool", _ApiOnlyCadSlotPool)
    configure_management_env(
        monkeypatch,
        tmp_path,
        rows=[
            {
                "科室编码": "ADM",
                "科室": "管理室",
                "账号": "admin",
                "姓名": "管理员",
                "角色": "管理员",
                "密码": "admin-secret",
            },
        ],
    )
    app = create_app()

    with TestClient(app) as client:
        app.state.runtime.queue_store.upsert_worker_heartbeat(
            worker_id="probe-test-worker",
            state="idle",
        )
        login = client.post(
            "/api/auth/login",
            json={"account_id": "admin", "password": "admin-secret"},
        )
        assert login.status_code == 200
        result = run_business_probe(
            BusinessProbeConfig(
                api_base_url="http://testserver",
                output_dir=tmp_path / "probe-result",
                token=login.json()["token"],
                request_timeout_sec=3.0,
            ),
            client=client,
        )

    assert result.status == "PASS"
    assert result.summary_path.exists()
    assert result.events_path.exists()
