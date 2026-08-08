from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

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

    assert submission.shared_prep.invalid_error == "shared_prep_invalid"
    assert submission.shared_prep.source_missing_error == "shared_prep_source_missing"
    assert submission.shared_prep.source_outside_error == "shared_prep_source_outside"
    assert not hasattr(submission.shared_prep, "required_json_files")
    deliverable = submission.required_task_roles[0]
    assert deliverable.task_role == "deliverable_main"
    assert deliverable.duplicate_role_error == "deliverable_main_duplicate"
    assert [artifact.field for artifact in deliverable.artifacts] == ["package_zip", "ied_xlsx"]
    assert deliverable.artifacts[1].required_when is not None
    assert deliverable.artifacts[1].required_when.field == "include_ied_plan"


def test_repo_mechanism_spec_exposes_frozen_archive_runtime_supply_chain() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    MechanismSpecLoader.clear_cache()

    runtime = MechanismSpecLoader.load(
        repo_root / "documents" / "参数规范-3.yaml"
    ).deployment_mechanism.archive_runtime

    assert runtime is not None
    assert runtime.version == "26.02"
    assert runtime.architecture == "x64"
    assert runtime.source.filename == "7z2602-x64.exe"
    assert runtime.source.sha256 == (
        "6745fa76dc2ea031596d8678f6f6b99c3c1b435b4164a63485adbbc7b8d82ef0"
    )
    assert runtime.source.size_bytes == 1_657_896
    assert runtime.bootstrap.filename == "7zr.exe"
    assert runtime.bootstrap.sha256 == (
        "56b8cc9f4971cef253644fafe54063ed7fdca551d4dee0f8c6baa81b855acd72"
    )
    assert runtime.bootstrap.size_bytes == 602_112
    assert runtime.cache_dir == "build/runtime-cache/7-Zip"
    assert runtime.destination_dir == "bin/7-Zip"
    assert runtime.required_handlers == ("7z", "zip", "Rar", "Rar5")
    assert runtime.probe.timeout_sec == 30
    assert runtime.probe.max_output_bytes == 1_048_576
    assert runtime.probe.fixture_source_relative_path == (
        "fixtures/archive-runtime-smoke-rar5.rar.b64"
    )
    assert runtime.probe.fixture_encoding == "base64"
    assert runtime.probe.fixture_source_sha256 == (
        "324185d843a8046ad64fbaa434c80c2568e49662c3f16c5c7e24ce7eacc2bc92"
    )
    assert runtime.probe.fixture_source_size_bytes == 173
    assert runtime.probe.fixture_decoded_sha256 == (
        "b0c3ccb16412f5215da3ae12f8bafd6fa4524ff44831283a7963b3afc792a886"
    )
    assert runtime.probe.fixture_decoded_size_bytes == 129
    assert runtime.probe.payload_source_relative_path == (
        "fixtures/archive-runtime-smoke.txt"
    )
    assert runtime.probe.payload_filename == "archive-runtime-smoke.txt"
    assert runtime.probe.payload_sha256 == (
        "6eaab97fc311dcba726775b8aa04165069688caa965df2fde9e12813cb74802f"
    )
    assert runtime.probe.payload_size_bytes == 40
    assert {item.filename: item.sha256 for item in runtime.required_files} == {
        "7z.exe": "83967f1b02b43c4efeda302795722c809e0e81b8307de73558d10484d5676a7d",
        "7z.dll": "69fd4df057985c40e510e2fac182881c7f85e90aa13ec703f763a8fdb2ce61f8",
        "License.txt": "519ac0a4bded9c18ea02e0afb71f663d8c47373bd9facd3ac96a79f51d77765d",
    }
    with pytest.raises(ValidationError, match="frozen"):
        runtime.version = "changed"
    with pytest.raises(ValidationError, match="frozen"):
        runtime.probe.timeout_sec = 1


def test_mechanism_spec_rejects_duplicate_submission_task_roles(tmp_path: Path) -> None:
    role = {
        "task_role": "deliverable_main",
        "missing_role_error": "deliverable_main_missing",
        "duplicate_role_error": "deliverable_main_duplicate",
        "artifacts": [
            {
                "field": "package_zip",
                "not_declared_error": "package_not_declared",
                "not_found_error": "package_not_found",
            }
        ],
    }
    spec_path = _write_mechanism_spec(
        tmp_path / "documents" / "参数规范-3.yaml",
        {
            "schema_version": "1.0",
            "backend_mechanism": {
                "task_group_submission": {"required_task_roles": [role, role]},
            },
        },
    )
    MechanismSpecLoader.clear_cache()

    with pytest.raises(ValueError, match="duplicate task_role"):
        MechanismSpecLoader.load(spec_path)


def test_mechanism_spec_rejects_duplicate_submission_artifact_fields(tmp_path: Path) -> None:
    artifact = {
        "field": "package_zip",
        "not_declared_error": "package_not_declared",
        "not_found_error": "package_not_found",
    }
    spec_path = _write_mechanism_spec(
        tmp_path / "documents" / "参数规范-3.yaml",
        {
            "schema_version": "1.0",
            "backend_mechanism": {
                "task_group_submission": {
                    "required_task_roles": [
                        {
                            "task_role": "deliverable_main",
                            "missing_role_error": "deliverable_main_missing",
                            "duplicate_role_error": "deliverable_main_duplicate",
                            "artifacts": [artifact, artifact],
                        }
                    ],
                },
            },
        },
    )
    MechanismSpecLoader.clear_cache()

    with pytest.raises(ValueError, match="duplicate artifact field"):
        MechanismSpecLoader.load(spec_path)


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
