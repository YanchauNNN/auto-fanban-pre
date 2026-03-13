from __future__ import annotations

import json
from pathlib import Path

from src.audit_check.bridge import AuditDotNetScanner
from src.config import SpecLoader, reload_config


def _configure_env(monkeypatch, tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    monkeypatch.setenv("FANBAN_SPEC_PATH", str(repo_root / "documents" / "参数规范.yaml"))
    monkeypatch.setenv("FANBAN_RUNTIME_SPEC_PATH", str(repo_root / "documents" / "参数规范_运行期.yaml"))
    monkeypatch.setenv("FANBAN_STORAGE_DIR", str(tmp_path / "storage"))
    SpecLoader.clear_cache()
    reload_config()


def test_audit_dotnet_scanner_reads_utf8_bom_result_json(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)

    scanner = AuditDotNetScanner()
    source_dwg = tmp_path / "2026-A01.dwg"
    source_dwg.write_bytes(b"dwg")
    workspace_dir = tmp_path / "work"

    def fake_run(*, result_json: Path, **_: object) -> None:
        payload = {
            "texts": [
                {
                    "raw_text": "示例文本",
                    "entity_type": "DBText",
                    "layout_name": "Model",
                    "position_x": 12.5,
                    "position_y": 35.0,
                }
            ]
        }
        result_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig")

    monkeypatch.setattr(scanner.runner, "run", fake_run)

    items = scanner.scan(job_id="job-audit-bom", source_dwg=source_dwg, workspace_dir=workspace_dir)

    assert len(items) == 1
    assert items[0].raw_text == "示例文本"
    assert items[0].position_x == 12.5
