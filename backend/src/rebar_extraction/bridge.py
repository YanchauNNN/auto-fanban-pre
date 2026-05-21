from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..cad.accoreconsole_runner import AcCoreConsoleRunner
from ..config import RuntimeConfig, get_config
from .models import CircleFeature, LineFeature, Point2D, TextFeature


@dataclass(frozen=True)
class RebarBridgeScanResult:
    summary: dict[str, Any]
    circles: list[CircleFeature]
    lines: list[LineFeature]
    texts: list[TextFeature]
    debug_symbols: list[dict[str, Any]]


class RebarBridgeScanner:
    """Run the AutoCAD .NET rebar scan stage and parse the feature payload."""

    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        runner: AcCoreConsoleRunner | None = None,
    ) -> None:
        self.config = config or get_config()
        self.runner = runner or AcCoreConsoleRunner(config=self.config)

    def scan(
        self,
        *,
        job_id: str,
        source_dwg: Path,
        workspace_dir: Path,
        slot_runtime: dict[str, str] | None = None,
    ) -> RebarBridgeScanResult:
        task_dir = workspace_dir / "rebar_scan"
        task_dir.mkdir(parents=True, exist_ok=True)
        task_json = task_dir / "task.json"
        result_json = task_dir / "result.json"
        task_payload: dict[str, Any] = {
            "schema_version": "rebar-scan-task@1.0",
            "workflow_stage": "rebar_scan",
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
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            raise RuntimeError("rebar scan failed: " + "; ".join(str(error) for error in errors))
        return RebarBridgeScanResult(
            summary=payload.get("rebar_scan") if isinstance(payload.get("rebar_scan"), dict) else {},
            circles=[_circle_from_payload(row) for row in _iter_dicts(payload.get("rebar_circles"))],
            lines=[_line_from_payload(row) for row in _iter_dicts(payload.get("rebar_lines"))],
            texts=[_text_from_payload(row) for row in _iter_dicts(payload.get("rebar_texts"))],
            debug_symbols=list(_iter_dicts(payload.get("rebar_debug_symbols"))),
        )


def _iter_dicts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _circle_from_payload(row: dict[str, Any]) -> CircleFeature:
    center = _point_from_payload(row.get("center"))
    return CircleFeature(
        handle=str(row.get("handle", "")),
        layout_name=str(row.get("layout_name", "Model") or "Model"),
        block_path=str(row.get("block_path", "")),
        center=center,
        radius=_to_float(row.get("radius")) or 0.0,
    )


def _line_from_payload(row: dict[str, Any]) -> LineFeature:
    return LineFeature(
        handle=str(row.get("handle", "")),
        layout_name=str(row.get("layout_name", "Model") or "Model"),
        block_path=str(row.get("block_path", "")),
        start=_point_from_payload(row.get("start")),
        end=_point_from_payload(row.get("end")),
    )


def _text_from_payload(row: dict[str, Any]) -> TextFeature:
    codepoints = row.get("codepoints")
    return TextFeature(
        handle=str(row.get("handle", "")),
        raw_text=str(row.get("raw_text", "")),
        entity_type=str(row.get("entity_type", "")),
        layout_name=str(row.get("layout_name", "Model") or "Model"),
        block_path=str(row.get("block_path", "")),
        position=_point_from_payload(row.get("position")),
        bbox=row.get("bbox") if isinstance(row.get("bbox"), dict) else None,
        text_style=str(row.get("text_style", "")),
        font=str(row.get("font", "")),
        bigfont=str(row.get("bigfont", "")),
        codepoints=tuple(str(item) for item in codepoints) if isinstance(codepoints, list) else (),
    )


def _point_from_payload(value: object) -> Point2D:
    if not isinstance(value, dict):
        return Point2D(0.0, 0.0)
    return Point2D(_to_float(value.get("x")) or 0.0, _to_float(value.get("y")) or 0.0)


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
