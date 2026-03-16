from __future__ import annotations

import json
from pathlib import Path

from ..cad.accoreconsole_runner import AcCoreConsoleRunner
from ..config import get_config
from .models import ScanTextItem


class AuditDotNetScanner:
    def __init__(self) -> None:
        self.config = get_config()
        self.runner = AcCoreConsoleRunner(config=self.config)

    def scan(
        self,
        *,
        job_id: str,
        source_dwg: Path,
        workspace_dir: Path,
        slot_runtime: dict[str, str] | None = None,
    ) -> list[ScanTextItem]:
        task_dir = workspace_dir / "audit_scan"
        task_dir.mkdir(parents=True, exist_ok=True)
        task_json = task_dir / "task.json"
        result_json = task_dir / "result.json"
        task_payload = {
            "schema_version": "audit-check-task@1.0",
            "workflow_stage": "audit_check_scan",
            "job_id": job_id,
            "source_dxf": str(source_dwg),
            "output_dir": str(task_dir),
            "engines": {
                "selection_engine": "dotnet",
                "plot_engine": "dotnet",
                "dotnet_bridge": {
                    "enabled": bool(self.config.module5_export.dotnet_bridge.enabled),
                    "dll_path": str(self.config.module5_export.dotnet_bridge.dll_path),
                    "command_name": str(self.config.module5_export.dotnet_bridge.command_name),
                    "netload_each_run": bool(self.config.module5_export.dotnet_bridge.netload_each_run),
                    "fallback_to_lisp_on_error": False,
                },
            },
        }
        if slot_runtime:
            task_payload["runtime"] = dict(slot_runtime)
        task_json.write_text(json.dumps(task_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.runner.run(
            source_dxf=source_dwg,
            task_json=task_json,
            result_json=result_json,
            workspace_dir=task_dir,
        )
        payload = json.loads(result_json.read_text(encoding="utf-8-sig"))
        items: list[ScanTextItem] = []
        for row in payload.get("texts", []):
            if not isinstance(row, dict):
                continue
            items.append(
                ScanTextItem(
                    raw_text=str(row.get("raw_text", "")),
                    entity_type=str(row.get("entity_type", "")),
                    layout_name=row.get("layout_name"),
                    entity_handle=row.get("entity_handle"),
                    block_path=row.get("block_path"),
                    position_x=_to_float(row.get("position_x")),
                    position_y=_to_float(row.get("position_y")),
                )
            )
        return items


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
