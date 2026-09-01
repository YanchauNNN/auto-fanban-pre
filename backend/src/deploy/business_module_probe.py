from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from .probe_report import ProbeReporter, ProbeSummary

_SENSITIVE_PUBLIC_KEY_PARTS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "密码",
    "口令",
)


class _HttpClient(Protocol):
    def get(self, url: str, **kwargs: Any) -> Any: ...

    def post(self, url: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class BusinessProbeConfig:
    api_base_url: str
    output_dir: Path
    token: str = ""
    username: str = ""
    password: str = ""
    request_timeout_sec: float = 15.0
    allow_synthetic_mutation: bool = False


class BusinessProbeFailure(RuntimeError):
    def __init__(self, message: str, *, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _normalize_public_key(value: object) -> str:
    return "".join(character for character in str(value).casefold() if character.isalnum())


def _assert_public_payload(payload: Any, *, path: str = "$") -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            normalized = _normalize_public_key(key)
            if any(part in normalized for part in _SENSITIVE_PUBLIC_KEY_PARTS):
                raise BusinessProbeFailure(
                    f"public response exposed a sensitive field at {path}.{key}",
                    error_code="sensitive_field_exposed",
                )
            _assert_public_payload(value, path=f"{path}.{key}")
        return
    if isinstance(payload, list):
        for index, item in enumerate(payload):
            _assert_public_payload(item, path=f"{path}[{index}]")


def _json_response(response: Any, *, operation: str) -> Any:
    try:
        return response.json()
    except (ValueError, TypeError) as exc:
        raise BusinessProbeFailure(
            f"{operation} returned invalid JSON",
            error_code="invalid_json_response",
        ) from exc


def _request_check(
    client: _HttpClient,
    reporter: ProbeReporter,
    *,
    check: str,
    path: str,
    headers: Mapping[str, str],
    allow_forbidden: bool = False,
) -> Any | None:
    try:
        response = client.get(path, headers=dict(headers))
        status_code = int(response.status_code)
        if status_code == 403 and allow_forbidden:
            reporter.event(
                check,
                "PASS",
                context={"path": path, "authorized": False, "status_code": status_code},
            )
            return None
        if status_code < 200 or status_code >= 300:
            raise BusinessProbeFailure(
                f"{path} returned HTTP {status_code}",
                error_code="http_request_failed",
            )
        payload = _json_response(response, operation=path)
        _assert_public_payload(payload)
        reporter.event(
            check,
            "PASS",
            context={"path": path, "authorized": True, "status_code": status_code},
        )
        return payload
    except BusinessProbeFailure as exc:
        reporter.event(
            check,
            "FAIL",
            error_code=exc.error_code,
            message=str(exc),
            context={"path": path},
        )
    except Exception as exc:  # noqa: BLE001 - probe must always reach a terminal report
        reporter.event(
            check,
            "FAIL",
            error_code="request_exception",
            message=str(exc),
            context={"path": path, "exception_type": type(exc).__name__},
        )
    return None


def _resolve_token(
    client: _HttpClient,
    config: BusinessProbeConfig,
    reporter: ProbeReporter,
) -> str:
    token = str(config.token or "").strip()
    username = str(config.username or "").strip()
    password = str(config.password or "")
    if token:
        if username or password:
            raise BusinessProbeFailure(
                "use either token or username/password",
                error_code="ambiguous_credentials",
            )
        reporter.event("authentication", "PASS", context={"mode": "bearer_token"})
        return token
    if not username or not password:
        raise BusinessProbeFailure(
            "authentication credentials are missing",
            error_code="credentials_missing",
        )
    try:
        response = client.post(
            "/api/auth/login",
            json={"account_id": username, "password": password},
        )
        if int(response.status_code) < 200 or int(response.status_code) >= 300:
            raise BusinessProbeFailure(
                f"login returned HTTP {response.status_code}",
                error_code="login_failed",
            )
        payload = _json_response(response, operation="login")
        issued = payload.get("token") if isinstance(payload, Mapping) else None
        if not isinstance(issued, str) or not issued.strip():
            raise BusinessProbeFailure(
                "login response did not contain a token",
                error_code="login_token_missing",
            )
        reporter.event("authentication", "PASS", context={"mode": "username_password"})
        return issued.strip()
    except BusinessProbeFailure:
        raise
    except Exception as exc:  # noqa: BLE001 - converted into a stable probe failure
        raise BusinessProbeFailure(
            "login request failed",
            error_code="login_request_exception",
        ) from exc


def _check_health(
    client: _HttpClient,
    reporter: ProbeReporter,
) -> None:
    check = "system_health"
    try:
        response = client.get("/api/system/health")
        if int(response.status_code) < 200 or int(response.status_code) >= 300:
            raise BusinessProbeFailure(
                f"health returned HTTP {response.status_code}",
                error_code="health_request_failed",
            )
        payload = _json_response(response, operation="system health")
        if not isinstance(payload, Mapping):
            raise BusinessProbeFailure(
                "health response must be an object",
                error_code="health_contract_invalid",
            )
        issues: list[str] = []
        if payload.get("ready") is not True:
            issues.append("api_not_ready")
        if payload.get("storage_writable") is not True:
            issues.append("storage_not_writable")
        if payload.get("worker_alive") is not True:
            issues.append("worker_not_alive")
        worker_count = payload.get("worker_count")
        if not isinstance(worker_count, int) or worker_count <= 0:
            issues.append("worker_count_invalid")
        if issues:
            raise BusinessProbeFailure(
                "system health requirements failed: " + ", ".join(issues),
                error_code=issues[0],
            )
        reporter.event(
            check,
            "PASS",
            context={"worker_count": worker_count},
        )
    except BusinessProbeFailure as exc:
        reporter.event(
            check,
            "FAIL",
            error_code=exc.error_code,
            message=str(exc),
            context={
                "issues": [
                    code
                    for code in (
                        "api_not_ready",
                        "storage_not_writable",
                        "worker_not_alive",
                        "worker_count_invalid",
                    )
                    if code in str(exc)
                ],
            },
        )
    except Exception as exc:  # noqa: BLE001 - terminal report is required
        reporter.event(
            check,
            "FAIL",
            error_code="health_request_exception",
            message=str(exc),
            context={"exception_type": type(exc).__name__},
        )


def run_business_probe(
    config: BusinessProbeConfig,
    *,
    transport: httpx.BaseTransport | None = None,
    client: _HttpClient | None = None,
) -> ProbeSummary:
    reporter = ProbeReporter(
        config.output_dir,
        session_id=f"business-{uuid.uuid4().hex[:12]}",
        probe_name="account-workload",
        required_checks=(
            "system_health",
            "authentication",
            "auth_me",
            "workload_me",
            "task_groups",
            "workflow_monitor",
        ),
    )
    owned_client: httpx.Client | None = None
    if client is None:
        owned_client = httpx.Client(
            base_url=config.api_base_url.rstrip("/"),
            timeout=config.request_timeout_sec,
            transport=transport,
        )
        client = owned_client
    try:
        _check_health(client, reporter)
        try:
            token = _resolve_token(client, config, reporter)
        except BusinessProbeFailure as exc:
            reporter.event(
                "authentication",
                "FAIL",
                error_code=exc.error_code,
                message=str(exc),
            )
            return reporter.finish()

        headers = {"Authorization": f"Bearer {token}"}
        account = _request_check(
            client,
            reporter,
            check="auth_me",
            path="/api/auth/me",
            headers=headers,
        )
        role = str(account.get("role", "")) if isinstance(account, Mapping) else ""

        _request_check(
            client,
            reporter,
            check="accounts",
            path="/api/accounts",
            headers=headers,
            allow_forbidden=role != "管理员",
        )
        _request_check(
            client,
            reporter,
            check="account_invalid_rows",
            path="/api/accounts/invalid-rows",
            headers=headers,
            allow_forbidden=role != "管理员",
        )
        for scope in ("me", "office", "institute", "admin"):
            _request_check(
                client,
                reporter,
                check=f"workload_{scope}",
                path=f"/api/workload/{scope}",
                headers=headers,
                allow_forbidden=scope != "me",
            )
        _request_check(
            client,
            reporter,
            check="task_groups",
            path="/api/task-groups",
            headers=headers,
        )
        _request_check(
            client,
            reporter,
            check="workflow_monitor",
            path="/api/workflow/monitor",
            headers=headers,
        )
        if config.allow_synthetic_mutation:
            reporter.event(
                "synthetic_mutation",
                "SKIPPED",
                error_code="safe_cleanup_api_unavailable",
                message="synthetic mutation was not run because no reversible cleanup API is available",
            )
        return reporter.finish()
    finally:
        if owned_client is not None:
            owned_client.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe account and workload business health.")
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--token")
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--request-timeout-sec", type=float, default=15.0)
    parser.add_argument("--allow-synthetic-mutation", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_business_probe(
        BusinessProbeConfig(
            api_base_url=args.api_base_url,
            output_dir=args.output_dir,
            token=args.token or os.getenv("FANBAN_PROBE_TOKEN", ""),
            username=args.username or os.getenv("FANBAN_PROBE_USERNAME", ""),
            password=args.password or os.getenv("FANBAN_PROBE_PASSWORD", ""),
            request_timeout_sec=args.request_timeout_sec,
            allow_synthetic_mutation=args.allow_synthetic_mutation,
        )
    )
    print(result.summary_path)
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
