from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.config.mechanism_spec import (
    MechanismSpecLoader,
    append_audit_replace_factory_codes,
    load_mechanism_spec,
)


def _write_mechanism_spec(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_mechanism_spec_loader_reads_default_path(tmp_path: Path, monkeypatch) -> None:
    spec_path = _write_mechanism_spec(
        tmp_path / "documents" / "参数规范-3.yaml",
        {
            "schema_version": "1.0",
            "backend_mechanism": {
                "archive_defaults": {
                    "engineering_no": "ENG_UNKNOWN",
                    "subitem_no": "SUB_UNKNOWN",
                    "album_internal_code": "ALBUM_UNKNOWN",
                    "revision": "Z",
                },
            },
        },
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FANBAN_MECHANISM_SPEC_PATH", raising=False)
    MechanismSpecLoader.clear_cache()

    spec = load_mechanism_spec()

    assert spec.source_path == spec_path.resolve()
    assert spec.archive_defaults.engineering_no == "ENG_UNKNOWN"
    assert spec.archive_defaults.revision == "Z"


def test_mechanism_spec_loader_uses_env_override(tmp_path: Path, monkeypatch) -> None:
    spec_path = _write_mechanism_spec(
        tmp_path / "custom" / "mechanism.yaml",
        {
            "schema_version": "1.0",
            "backend_mechanism": {
                "project_inference": {
                    "default_project_no": "2026",
                },
            },
        },
    )
    monkeypatch.setenv("FANBAN_MECHANISM_SPEC_PATH", str(spec_path))
    MechanismSpecLoader.clear_cache()

    spec = load_mechanism_spec()

    assert spec.source_path == spec_path.resolve()
    assert spec.project_inference.default_project_no == "2026"


def test_repo_mechanism_spec_whitelists_connected_han_forbidden_term() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    MechanismSpecLoader.clear_cache()

    spec = MechanismSpecLoader.load(repo_root / "documents" / "参数规范-3.yaml")

    assert spec.audit_display.forbidden_term_connected_han_whitelist == ["工种"]


def test_repo_mechanism_spec_exposes_typed_task_group_submission_rules() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    MechanismSpecLoader.clear_cache()

    spec = MechanismSpecLoader.load(repo_root / "documents" / "参数规范-3.yaml")
    submission = spec.task_group_submission

    assert submission.shared_prep.required_json_files == ["frames.json", "sheet_sets.json"]
    assert submission.shared_prep.invalid_error == "shared_prep_invalid"
    assert submission.shared_prep.source_missing_error == "shared_prep_source_missing"
    deliverable = submission.required_task_roles[0]
    assert deliverable.task_role == "deliverable_main"
    assert [artifact.field for artifact in deliverable.artifacts] == ["package_zip", "ied_xlsx"]
    assert deliverable.artifacts[1].required_when is not None
    assert deliverable.artifacts[1].required_when.field == "include_ied_plan"


def test_mechanism_spec_reads_audit_replace_factory_codes(tmp_path: Path) -> None:
    spec_path = _write_mechanism_spec(
        tmp_path / "documents" / "参数规范-3.yaml",
        {
            "schema_version": "1.0",
            "backend_mechanism": {
                "audit_replace": {
                    "unit_factory_codes": ["RC", "HL"],
                    "batch_filename_identity_regex": (
                        r"(\d{4})([0-9])([A-Z0-9]{2,4})-?[A-Z]{3}\d{2}"
                    ),
                },
            },
        },
    )
    MechanismSpecLoader.clear_cache()

    spec = MechanismSpecLoader.load(spec_path)

    assert spec.audit_replace.unit_factory_codes == ["RC", "HL"]
    assert spec.audit_replace.batch_filename_identity_regex == (
        r"(\d{4})([0-9])([A-Z0-9]{2,4})-?[A-Z]{3}\d{2}"
    )


def test_mechanism_spec_exposes_job_activity_timing_defaults(tmp_path: Path) -> None:
    spec_path = _write_mechanism_spec(
        tmp_path / "documents" / "鍙傛暟瑙勮寖-3.yaml",
        {
            "schema_version": "1.0",
            "backend_mechanism": {
                "api_runtime": {},
            },
        },
    )
    MechanismSpecLoader.clear_cache()

    spec = MechanismSpecLoader.load(spec_path)

    assert spec.api_runtime.job_summary_sync_interval_sec == 3.0
    assert spec.api_runtime.worker_heartbeat_interval_sec == 10.0
    assert spec.api_runtime.worker_claim_timeout_sec == 90.0
    assert spec.api_runtime.jobs_activity_stream_poll_interval_sec == 2.0
    assert spec.api_runtime.jobs_activity_stream_keepalive_sec == 15.0
    assert spec.api_runtime.jobs_activity_stream_max_duration_sec == 60.0
    assert spec.api_runtime.jobs_activity_stream_retry_ms == 5000


@pytest.mark.parametrize("invalid_timeout", [0, -1])
def test_mechanism_spec_rejects_nonpositive_worker_claim_timeout(
    tmp_path: Path,
    invalid_timeout: int,
) -> None:
    spec_path = _write_mechanism_spec(
        tmp_path / "documents" / "mechanism.yaml",
        {
            "schema_version": "1.0",
            "backend_mechanism": {
                "api_runtime": {
                    "worker_claim_timeout_sec": invalid_timeout,
                },
            },
        },
    )
    MechanismSpecLoader.clear_cache()

    with pytest.raises(ValueError, match="worker_claim_timeout_sec"):
        MechanismSpecLoader.load(spec_path)


def test_mechanism_spec_rejects_claim_timeout_shorter_than_three_heartbeats(
    tmp_path: Path,
) -> None:
    spec_path = _write_mechanism_spec(
        tmp_path / "documents" / "mechanism.yaml",
        {
            "schema_version": "1.0",
            "backend_mechanism": {
                "api_runtime": {
                    "worker_heartbeat_interval_sec": 10,
                    "worker_claim_timeout_sec": 1,
                },
            },
        },
    )
    MechanismSpecLoader.clear_cache()

    with pytest.raises(ValueError, match="three times worker_heartbeat_interval_sec"):
        MechanismSpecLoader.load(spec_path)


def test_mechanism_spec_accepts_claim_timeout_at_three_heartbeat_boundary(
    tmp_path: Path,
) -> None:
    spec_path = _write_mechanism_spec(
        tmp_path / "documents" / "mechanism.yaml",
        {
            "schema_version": "1.0",
            "backend_mechanism": {
                "api_runtime": {
                    "worker_heartbeat_interval_sec": 10,
                    "worker_claim_timeout_sec": 30,
                },
            },
        },
    )
    MechanismSpecLoader.clear_cache()

    spec = MechanismSpecLoader.load(spec_path)

    assert spec.api_runtime.worker_claim_timeout_sec == 30.0


def test_append_audit_replace_factory_codes_updates_yaml_and_cache(tmp_path: Path) -> None:
    spec_path = _write_mechanism_spec(
        tmp_path / "documents" / "参数规范-3.yaml",
        {
            "schema_version": "1.0",
            "backend_mechanism": {
                "audit_replace": {
                    "unit_factory_codes": ["RC"],
                },
            },
        },
    )
    MechanismSpecLoader.clear_cache()

    updated = append_audit_replace_factory_codes(["hl", "RC", "16mm"], spec_path=spec_path)

    assert updated == ["RC", "HL"]
    assert "HL" in spec_path.read_text(encoding="utf-8")
    assert MechanismSpecLoader.load(spec_path).audit_replace.unit_factory_codes == ["RC", "HL"]


def test_mechanism_spec_rejects_existing_yaml_roots(tmp_path: Path) -> None:
    spec_path = _write_mechanism_spec(
        tmp_path / "documents" / "参数规范-3.yaml",
        {
            "schema_version": "1.0",
            "management_features": {},
            "backend_mechanism": {},
        },
    )
    MechanismSpecLoader.clear_cache()

    with pytest.raises(ValueError, match="management_features"):
        MechanismSpecLoader.load(spec_path)


def test_mechanism_spec_validates_permission_roles_against_business_spec(
    tmp_path: Path,
    monkeypatch,
) -> None:
    business_spec = tmp_path / "business.yaml"
    business_spec.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "management_features": {
                    "account": {
                        "valid_roles": ["设计人员", "室主任", "所领导", "管理员"],
                    },
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    mechanism_spec = _write_mechanism_spec(
        tmp_path / "mechanism.yaml",
        {
            "schema_version": "1.0",
            "backend_mechanism": {
                "permissions": {
                    "account_admin_roles": ["管理员", "外部管理员"],
                },
            },
        },
    )
    monkeypatch.setenv("FANBAN_SPEC_PATH", str(business_spec))
    MechanismSpecLoader.clear_cache()

    with pytest.raises(ValueError, match="外部管理员"):
        MechanismSpecLoader.load(mechanism_spec)
