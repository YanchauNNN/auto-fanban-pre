from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import get_config
from .accoreconsole_runner import AcCoreConsoleRunner
from .titleblock_consistency import FieldConsistencyPlan


class TitleblockConsistencyBridge:
    def __init__(self) -> None:
        self.config = get_config()
        self.runner = AcCoreConsoleRunner(config=self.config)

    def apply(
        self,
        *,
        job_id: str,
        source_dwg: Path,
        output_dwg: Path,
        plans: list[FieldConsistencyPlan],
        workspace_dir: Path,
        slot_runtime: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        workspace_dir.mkdir(parents=True, exist_ok=True)
        task_json = workspace_dir / "consistency_fix_task.json"
        result_json = workspace_dir / "consistency_fix_result.json"

        payload = {
            "schema_version": "titleblock-consistency-task@1.0",
            "workflow_stage": "titleblock_consistency_fix",
            "job_id": job_id,
            "source_dxf": str(source_dwg),
            "output_dir": str(workspace_dir),
            "output_dwg": str(output_dwg),
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
            "consistency_actions": [self._serialize_plan(plan) for plan in plans],
        }
        if slot_runtime:
            payload["runtime"] = dict(slot_runtime)
        task_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.runner.run(
            source_dxf=source_dwg,
            task_json=task_json,
            result_json=result_json,
            workspace_dir=workspace_dir,
        )
        return json.loads(result_json.read_text(encoding="utf-8-sig"))

    @staticmethod
    def _serialize_plan(plan: FieldConsistencyPlan) -> dict[str, Any]:
        return {
            "frame_id": plan.frame_id,
            "field_name": plan.field_name,
            "expected_text": plan.expected_text,
            "current_text": plan.current_text,
            "roi_bbox": {
                "xmin": plan.roi_bbox.xmin,
                "ymin": plan.roi_bbox.ymin,
                "xmax": plan.roi_bbox.xmax,
                "ymax": plan.roi_bbox.ymax,
            },
            "targets": [
                {
                    "old_text": target.old_text,
                    "new_text": target.new_text,
                    "x": target.x,
                    "y": target.y,
                }
                for target in plan.patch_targets
            ],
        }
