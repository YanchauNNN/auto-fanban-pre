from __future__ import annotations

import json
from pathlib import Path

import pytest


class _FakeRunner:
    def __init__(self) -> None:
        self.task_payload: dict | None = None

    def run(
        self,
        *,
        source_dxf: Path,
        task_json: Path,
        result_json: Path,
        workspace_dir: Path,
    ) -> None:
        self.task_payload = json.loads(task_json.read_text(encoding="utf-8"))
        result_json.write_text(
            json.dumps({"errors": [], "factory_index_map": {"applied_count": 2}}),
            encoding="utf-8",
        )


def _first_dxf(folder: Path, pattern: str = "*.dxf") -> Path:
    matches = sorted(folder.glob(pattern))
    if not matches:
        pytest.skip(f"factory index map fixture missing: {folder}")
    return matches[0]


def test_bridge_writes_factory_index_map_replace_task(tmp_path: Path) -> None:
    from src.audit_replace.factory_index_bridge import FactoryIndexMapBridge
    from src.audit_replace.factory_index_maps import build_factory_index_replacement_plan

    repo_root = Path(__file__).resolve().parents[3]
    source_dxf = _first_dxf(
        repo_root
        / "test"
        / "block_replace_validation"
        / "20162PR-JGS01-B"
        / "dxf"
    )
    target_dxf = _first_dxf(
        repo_root / "test" / "\u5382\u623f\u7d22\u5f15\u56fe-20260508" / "dxf",
        "2026*.dxf",
    )
    plan = build_factory_index_replacement_plan(
        source_project_no="2016",
        target_project_no="2026",
        source_dxf=source_dxf,
        target_template_dxf=target_dxf,
        target_template_dwg=repo_root / "documents_bin" / "factory_index_maps" / "2026.dwg",
    )

    fake_runner = _FakeRunner()
    bridge = FactoryIndexMapBridge(runner=fake_runner)
    result = bridge.apply(
        job_id="job-factory-index",
        source_dwg=tmp_path / "input.dwg",
        output_dwg=tmp_path / "output.dwg",
        plan=plan,
        workspace_dir=tmp_path / "bridge",
        slot_runtime={"profile_root": "slot-a"},
    )

    assert result["factory_index_map"]["applied_count"] == 2
    assert fake_runner.task_payload is not None
    assert fake_runner.task_payload["workflow_stage"] == "factory_index_map_replace"
    assert fake_runner.task_payload["factory_index_map"]["target_project_no"] == "2026"
    assert len(fake_runner.task_payload["factory_index_map"]["actions"]) == 2
    assert fake_runner.task_payload["runtime"] == {"profile_root": "slot-a"}
