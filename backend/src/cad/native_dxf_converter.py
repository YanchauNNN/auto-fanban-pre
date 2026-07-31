"""AutoCAD/.NET 原生 DWG -> DXF 回退转换。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import RuntimeConfig, get_config
from ..interfaces import ConversionError
from .accoreconsole_runner import AcCoreConsoleRunner


class AutoCadDwgToDxfConverter:
    """通过现有 AcCoreConsole/.NET bridge 对任务副本执行 DxfOut。"""

    def __init__(
        self,
        *,
        config: RuntimeConfig | Any | None = None,
        runner: AcCoreConsoleRunner | Any | None = None,
    ) -> None:
        self.config = config or get_config()
        self.runner = runner or AcCoreConsoleRunner(config=self.config)

    def dwg_to_dxf(self, dwg_path: Path, output_dir: Path) -> Path:
        source = dwg_path.resolve()
        if not source.is_file():
            raise ConversionError(f"AutoCAD 原生转换源文件不存在: {source}")

        target_dir = output_dir.resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        output_dxf = target_dir / f"{source.stem}.dxf"
        runtime_dir = target_dir / "_native_dxf_fallback"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        task_json = runtime_dir / "task.json"
        result_json = runtime_dir / "result.json"
        result_json.unlink(missing_ok=True)

        oda_cfg = self.config.oda
        bridge_cfg = self.config.module5_export.dotnet_bridge
        payload = {
            "schema_version": "cad-dxf-task@1.0",
            "workflow_stage": "dwg_to_dxf",
            "job_id": f"native-dxf-{source.stem}",
            "source_dxf": str(source),
            "output_dir": str(target_dir),
            "output_dxf": str(output_dxf),
            "dxf_version": str(oda_cfg.native_dxf_fallback_version),
            "dxf_precision": int(oda_cfg.native_dxf_fallback_precision),
            "engines": {
                "selection_engine": "dotnet",
                "plot_engine": "dotnet",
                "dotnet_bridge": {
                    "enabled": bool(bridge_cfg.enabled),
                    "dll_path": str(bridge_cfg.dll_path),
                    "command_name": str(bridge_cfg.command_name),
                    "netload_each_run": bool(bridge_cfg.netload_each_run),
                },
            },
            "frames": [],
            "sheet_sets": [],
        }
        task_json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self.runner.run(
            source_dxf=source,
            task_json=task_json,
            result_json=result_json,
            workspace_dir=runtime_dir,
        )

        if not result_json.is_file():
            raise ConversionError("AutoCAD 原生转换未生成 result.json")
        result = json.loads(result_json.read_text(encoding="utf-8-sig"))
        errors = [str(item) for item in result.get("errors", []) if str(item).strip()]
        if errors:
            raise ConversionError(f"AutoCAD 原生转换失败: {'; '.join(errors)}")
        if not output_dxf.is_file():
            raise ConversionError(f"AutoCAD 原生转换后文件不存在: {output_dxf}")
        return output_dxf
