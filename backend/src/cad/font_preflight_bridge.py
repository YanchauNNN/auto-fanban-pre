from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from ..config import get_config
from .accoreconsole_runner import AcCoreConsoleRunner
from .dwg_version import detect_dwg_version_code_or_none


class FontPreflightBridge:
    def __init__(self) -> None:
        self.config = get_config()
        self.runner = AcCoreConsoleRunner(config=self.config)

    def preflight(
        self,
        *,
        job_id: str,
        source_dwg: Path,
        workspace_dir: Path,
        slot_runtime: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._run(
            job_id=job_id,
            source_dwg=source_dwg,
            workspace_dir=workspace_dir,
            slot_runtime=slot_runtime,
            replacement_font=None,
        )

    def replace_missing(
        self,
        *,
        job_id: str,
        source_dwg: Path,
        replacement_font: str | None,
        replacement_fonts: dict[str, str] | None,
        replacement_targets: list[dict[str, Any]] | None,
        workspace_dir: Path,
        slot_runtime: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._run(
            job_id=job_id,
            source_dwg=source_dwg,
            workspace_dir=workspace_dir,
            slot_runtime=slot_runtime,
            replacement_font=replacement_font,
            replacement_fonts=replacement_fonts,
            replacement_targets=replacement_targets,
        )

    def _run(
        self,
        *,
        job_id: str,
        source_dwg: Path,
        workspace_dir: Path,
        slot_runtime: dict[str, str] | None,
        replacement_font: str | None,
        replacement_fonts: dict[str, str] | None = None,
        replacement_targets: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        workspace_dir.mkdir(parents=True, exist_ok=True)
        task_json = workspace_dir / "font_preflight_task.json"
        result_json = workspace_dir / "font_preflight_result.json"
        output_dwg = workspace_dir / f"{source_dwg.stem}.fontfix{source_dwg.suffix}"
        has_replacements = bool(replacement_font) or bool(replacement_fonts)

        payload: dict[str, Any] = {
            "schema_version": "font-preflight-task@1.0",
            "workflow_stage": "font_replace_missing" if has_replacements else "font_preflight",
            "job_id": job_id,
            "source_dxf": str(source_dwg),
            "source_dwg_version": detect_dwg_version_code_or_none(source_dwg),
            "output_dir": str(workspace_dir),
            "output_dwg": str(output_dwg),
            "replacement_font": replacement_font,
            "replacement_fonts": replacement_fonts or {},
            "replacement_targets": replacement_targets or [],
            "engines": {
                "dotnet_bridge": {
                    "enabled": bool(self.config.module5_export.dotnet_bridge.enabled),
                    "dll_path": str(self.config.module5_export.dotnet_bridge.dll_path),
                    "command_name": str(self.config.module5_export.dotnet_bridge.command_name),
                    "netload_each_run": bool(self.config.module5_export.dotnet_bridge.netload_each_run),
                    "fallback_to_lisp_on_error": False,
                }
            },
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
        result = json.loads(result_json.read_text(encoding="utf-8-sig"))
        if has_replacements and output_dwg.exists():
            shutil.copy2(output_dwg, source_dwg)
            result["output_dwg"] = str(source_dwg)
        return result
