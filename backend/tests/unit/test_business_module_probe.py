from __future__ import annotations

import json
from pathlib import Path

import httpx

from src.deploy.business_module_probe import BusinessProbeConfig, run_business_probe


def _healthy_payload(path: str) -> dict[str, object] | list[object]:
    if path == "/api/system/health":
        return {
            "ready": True,
            "storage_writable": True,
            "worker_alive": True,
            "worker_count": 1,
        }
    if path == "/api/auth/me":
        return {
            "account_id": "admin",
            "display_name": "管理员",
            "role": "管理员",
            "office_code": "ADM",
            "office_name": "管理室",
        }
    if path in {"/api/accounts", "/api/accounts/invalid-rows"}:
        return {"items": [], "total": 0}
    if path.startswith("/api/workload/"):
        return {"entries": [], "total_workload_a1": 0.0}
    if path == "/api/task-groups":
        return {"items": []}
    if path == "/api/workflow/monitor":
        return {"items": []}
    raise AssertionError(f"unexpected path: {path}")


def _config(tmp_path: Path, **overrides: object) -> BusinessProbeConfig:
    values: dict[str, object] = {
        "api_base_url": "http://probe.local",
        "output_dir": tmp_path / "probe",
        "token": "existing-token",
        "request_timeout_sec": 3.0,
    }
    values.update(overrides)
    return BusinessProbeConfig(**values)


def test_read_only_probe_never_calls_mutating_business_routes(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json=_healthy_payload(request.url.path))

    result = run_business_probe(
        _config(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    assert result.status == "PASS"
    assert calls
    assert all(method == "GET" for method, _path in calls)
    assert ("GET", "/api/accounts") in calls
    assert ("GET", "/api/workload/admin") in calls
    assert ("GET", "/api/workflow/monitor") in calls


def test_probe_fails_when_worker_health_is_not_ready(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = _healthy_payload(request.url.path)
        if request.url.path == "/api/system/health":
            payload = {
                "ready": False,
                "storage_writable": True,
                "worker_alive": False,
                "worker_count": 0,
            }
        return httpx.Response(200, json=payload)

    result = run_business_probe(
        _config(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    assert result.status == "FAIL"
    events = result.events_path.read_text("utf-8")
    assert "worker_not_alive" in events


def test_probe_rejects_sensitive_fields_without_logging_secret(tmp_path: Path) -> None:
    secret = "must-not-enter-probe-log"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/accounts":
            return httpx.Response(
                200,
                json={"items": [{"account_id": "a", "password": secret}]},
            )
        return httpx.Response(200, json=_healthy_payload(request.url.path))

    result = run_business_probe(
        _config(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    assert result.status == "FAIL"
    raw = result.events_path.read_text("utf-8")
    assert "sensitive_field_exposed" in raw
    assert secret not in raw


def test_non_admin_probe_accepts_expected_scope_forbidden_responses(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/me":
            return httpx.Response(
                200,
                json={
                    "account_id": "designer",
                    "display_name": "设计人员",
                    "role": "设计人员",
                    "office_code": "S01",
                    "office_name": "结构室",
                },
            )
        if request.url.path in {
            "/api/accounts",
            "/api/accounts/invalid-rows",
            "/api/workload/office",
            "/api/workload/institute",
            "/api/workload/admin",
        }:
            return httpx.Response(403, json={"detail": "scope unavailable"})
        return httpx.Response(200, json=_healthy_payload(request.url.path))

    result = run_business_probe(
        _config(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    assert result.status == "PASS"


def test_mutation_switch_skips_when_safe_cleanup_api_is_unavailable(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json=_healthy_payload(request.url.path))

    result = run_business_probe(
        _config(tmp_path, allow_synthetic_mutation=True),
        transport=httpx.MockTransport(handler),
    )

    assert result.status == "PASS"
    payload = json.loads(result.summary_path.read_text("utf-8"))
    assert payload["checks"]["synthetic_mutation"] == "SKIPPED"
    assert all(method == "GET" for method, _path in calls)


def test_probe_can_login_without_logging_credentials(tmp_path: Path) -> None:
    username = "probe-user"
    password = "probe-password-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"token": "issued-secret-token"})
        return httpx.Response(200, json=_healthy_payload(request.url.path))

    result = run_business_probe(
        _config(
            tmp_path,
            token="",
            username=username,
            password=password,
        ),
        transport=httpx.MockTransport(handler),
    )

    assert result.status == "PASS"
    raw = result.events_path.read_text("utf-8")
    assert username not in raw
    assert password not in raw
    assert "issued-secret-token" not in raw
