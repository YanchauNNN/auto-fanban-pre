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


def test_mechanism_spec_reads_audit_replace_factory_codes(tmp_path: Path) -> None:
    spec_path = _write_mechanism_spec(
        tmp_path / "documents" / "参数规范-3.yaml",
        {
            "schema_version": "1.0",
            "backend_mechanism": {
                "audit_replace": {
                    "unit_factory_codes": ["RC", "HL"],
                },
            },
        },
    )
    MechanismSpecLoader.clear_cache()

    spec = MechanismSpecLoader.load(spec_path)

    assert spec.audit_replace.unit_factory_codes == ["RC", "HL"]


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
    assert spec.api_runtime.jobs_activity_stream_poll_interval_sec == 2.0
    assert spec.api_runtime.jobs_activity_stream_keepalive_sec == 15.0


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
