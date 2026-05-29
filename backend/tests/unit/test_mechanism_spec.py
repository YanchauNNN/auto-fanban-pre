from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.config.mechanism_spec import MechanismSpecLoader, load_mechanism_spec


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


def test_mechanism_spec_loads_management_runtime_and_ui_config(tmp_path: Path, monkeypatch) -> None:
    spec_path = _write_mechanism_spec(
        tmp_path / "custom" / "mechanism.yaml",
        {
            "schema_version": "1.0",
            "backend_mechanism": {
                "permissions": {
                    "account_admin_roles": [],
                    "workflow_admin_roles": [],
                    "workload_scope_roles": {},
                },
                "workflow_runtime": {
                    "approval_terminal_status": "archived",
                    "archive_trigger_status": "archived",
                    "active_conflict_statuses": ["in_review", "archived"],
                },
                "workload_runtime": {
                    "status_options": [
                        {"label": "All", "value": ""},
                        {"label": "Settled", "value": "settled"},
                    ],
                },
                "management_ui": {
                    "workload_scope_labels": {
                        "me": "Mine",
                        "admin": "Admin",
                    },
                    "workflow_status_labels": {"archived": "Archived"},
                    "archive_status_labels": {"succeeded": "Archived"},
                    "empty_current_node_label": "No active node",
                },
            },
        },
    )
    monkeypatch.setenv("FANBAN_MECHANISM_SPEC_PATH", str(spec_path))
    MechanismSpecLoader.clear_cache()

    spec = load_mechanism_spec()

    assert spec.workflow_runtime.approval_terminal_status == "archived"
    assert spec.workflow_runtime.archive_trigger_status == "archived"
    assert spec.workflow_runtime.active_conflict_statuses == ["in_review", "archived"]
    assert spec.workload_runtime.status_options[1].label == "Settled"
    assert spec.management_ui.workload_scope_labels["admin"] == "Admin"
    assert spec.management_ui.workflow_status_labels["archived"] == "Archived"
    assert spec.management_ui.archive_status_labels["succeeded"] == "Archived"
    assert spec.management_ui.empty_current_node_label == "No active node"


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
