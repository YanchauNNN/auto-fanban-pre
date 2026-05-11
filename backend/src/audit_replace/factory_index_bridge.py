from __future__ import annotations

import json
import re
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


@dataclass(frozen=True)
class FactoryIndexTemplateSelection:
    project_no: str
    variant: str | None
    path: Path


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
        source_filename: str = "",
        target_variant: str | None = None,
        source_dxf: Path,
        source_dwg: Path,
        output_dwg: Path,
        workspace_dir: Path,
        slot_runtime: dict[str, str] | None = None,
    ) -> FactoryIndexReplacementResult:
        if not self.config.factory_index_maps.enabled:
            return FactoryIndexReplacementResult(
                applied=False,
                output_dwg=source_dwg,
                message="factory_index_map_disabled",
            )
        if source_project_no == target_project_no:
            return FactoryIndexReplacementResult(
                applied=False,
                output_dwg=source_dwg,
                message="factory_index_map_same_project",
            )

        selection = self.select_template(
            source_project_no=source_project_no,
            target_project_no=target_project_no,
            source_filename=source_filename,
            target_variant=target_variant,
        )
        if selection is None:
            return FactoryIndexReplacementResult(
                applied=False,
                output_dwg=source_dwg,
                message=f"factory_index_map_template_not_configured:{target_project_no}",
            )

        template_dwg = selection.path
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

    def select_template(
        self,
        *,
        source_project_no: str,
        target_project_no: str,
        source_filename: str = "",
        target_variant: str | None = None,
    ) -> FactoryIndexTemplateSelection | None:
        config = self.config.factory_index_maps
        target_project_no = str(target_project_no or "").strip()
        source_project_no = str(source_project_no or "").strip()
        if not config.enabled or not target_project_no or source_project_no == target_project_no:
            return None

        variant_templates = config.island_templates.get(target_project_no)
        if variant_templates:
            variant = self._normalize_variant(target_variant) or self._infer_variant(
                source_filename=source_filename,
                source_project_no=source_project_no,
                target_project_no=target_project_no,
            )
            if not variant or variant not in variant_templates:
                return None
            return FactoryIndexTemplateSelection(
                project_no=target_project_no,
                variant=variant,
                path=self._template_path(variant_templates[variant]),
            )

        template_name = config.templates.get(target_project_no)
        if not template_name:
            return None
        return FactoryIndexTemplateSelection(
            project_no=target_project_no,
            variant=None,
            path=self._template_path(template_name),
        )

    def _template_path(self, template_name: str) -> Path:
        template_dir = Path(self.config.factory_index_maps.template_dir)
        if not template_dir.is_absolute():
            template_dir = Path(self.config.base_dir) / template_dir
        return template_dir / template_name

    @staticmethod
    def _normalize_variant(value: str | None) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        match = re.search(r"[1-9]", text)
        return match.group(0) if match else None

    @classmethod
    def _infer_variant(
        cls,
        *,
        source_filename: str,
        source_project_no: str,
        target_project_no: str,
    ) -> str | None:
        text = str(source_filename or "")
        for project_no in (target_project_no, source_project_no):
            if not project_no:
                continue
            match = re.search(rf"(?<!\d){re.escape(project_no)}([1-9])", text)
            if match:
                return match.group(1)
        match = re.search(r"(?<!\d)\d{4}([1-9])", text)
        return match.group(1) if match else None
