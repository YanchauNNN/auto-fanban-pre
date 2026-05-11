from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..cad.accoreconsole_runner import AcCoreConsoleRunner
from ..cad.dwg_version import detect_dwg_version_code_or_none
from ..cad.oda_converter import ODAConverter
from ..config import RuntimeConfig, get_config
from .factory_index_maps import (
    FactoryIndexReplacementPlan,
    build_factory_index_replacement_plan,
)


@dataclass(frozen=True)
class FactoryIndexReplacementResult:
    applied: bool
    output_dwg: Path
    action_count: int = 0
    report_json: Path | None = None
    message: str = ""

    def to_progress_dict(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "action_count": self.action_count,
            "report_json": str(self.report_json) if self.report_json else None,
            "message": self.message,
        }


class FactoryIndexMapBridge:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        runner: Any | None = None,
    ) -> None:
        self.config = config or get_config()
        self.runner = runner or AcCoreConsoleRunner(config=self.config)

    def apply(
        self,
        *,
        job_id: str,
        source_dwg: Path,
        output_dwg: Path,
        plan: FactoryIndexReplacementPlan,
        workspace_dir: Path,
        slot_runtime: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        workspace_dir.mkdir(parents=True, exist_ok=True)
        task_json = workspace_dir / "factory_index_map_task.json"
        result_json = workspace_dir / "factory_index_map_result.json"
        payload = {
            "schema_version": "factory-index-map-replace-task@1.0",
            "workflow_stage": "factory_index_map_replace",
            "job_id": job_id,
            "source_dxf": str(source_dwg),
            "source_dwg_version": detect_dwg_version_code_or_none(source_dwg),
            "output_dir": str(workspace_dir),
            "output_dwg": str(output_dwg),
            "engines": {
                "selection_engine": "dotnet",
                "plot_engine": "dotnet",
                "dotnet_bridge": {
                    "enabled": bool(self.config.module5_export.dotnet_bridge.enabled),
                    "dll_path": str(self.config.module5_export.dotnet_bridge.dll_path),
                    "command_name": str(self.config.module5_export.dotnet_bridge.command_name),
                    "netload_each_run": bool(
                        self.config.module5_export.dotnet_bridge.netload_each_run,
                    ),
                    "fallback_to_lisp_on_error": False,
                },
            },
            "factory_index_map": plan.to_bridge_payload(),
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


class FactoryIndexMapReplacementService:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        oda: ODAConverter | None = None,
        bridge: FactoryIndexMapBridge | None = None,
    ) -> None:
        self.config = config or get_config()
        self.oda = oda or ODAConverter()
        self.bridge = bridge or FactoryIndexMapBridge(config=self.config)

    def replace_if_configured(
        self,
        *,
        job_id: str,
        source_project_no: str,
        target_project_no: str,
        source_dxf: Path,
        source_dwg: Path,
        output_dwg: Path,
        workspace_dir: Path,
        slot_runtime: dict[str, str] | None = None,
    ) -> FactoryIndexReplacementResult:
        if source_project_no != "2016" or target_project_no != "2026":
            return FactoryIndexReplacementResult(
                applied=False,
                output_dwg=source_dwg,
                message="factory_index_map_pair_not_configured",
            )

        template_dwg = self._template_dwg_for_project(target_project_no)
        if not template_dwg.exists():
            return FactoryIndexReplacementResult(
                applied=False,
                output_dwg=source_dwg,
                message=f"factory_index_map_template_missing:{template_dwg}",
            )

        workspace_dir.mkdir(parents=True, exist_ok=True)
        template_dxf = self.oda.dwg_to_dxf(template_dwg, workspace_dir / "template_dxf")
        plan = build_factory_index_replacement_plan(
            source_project_no=source_project_no,
            target_project_no=target_project_no,
            source_dxf=source_dxf,
            target_template_dxf=template_dxf,
            target_template_dwg=template_dwg,
        )
        report_json = workspace_dir / "factory_index_map_plan.json"
        if not plan.actions:
            report_json.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            return FactoryIndexReplacementResult(
                applied=False,
                output_dwg=source_dwg,
                action_count=0,
                report_json=report_json,
                message="factory_index_map_no_candidates",
            )

        bridge_payload = self.bridge.apply(
            job_id=job_id,
            source_dwg=source_dwg,
            output_dwg=output_dwg,
            plan=plan,
            workspace_dir=workspace_dir / "bridge",
            slot_runtime=slot_runtime,
        )
        report_json.write_text(
            json.dumps(
                {"plan": plan.to_dict(), "bridge_result": bridge_payload},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        errors = bridge_payload.get("errors")
        if isinstance(errors, list) and errors:
            raise RuntimeError(
                "factory index map replace failed: "
                + "; ".join(str(error) for error in errors)
            )
        return FactoryIndexReplacementResult(
            applied=True,
            output_dwg=output_dwg,
            action_count=len(plan.actions),
            report_json=report_json,
        )

    def _template_dwg_for_project(self, project_no: str) -> Path:
        template_name = f"{project_no}\u9879\u76ee\u5382\u623f\u7d22\u5f15\u56fe.dwg"
        return Path(self.config.base_dir) / "documents_bin" / "factory_index_maps" / template_name
