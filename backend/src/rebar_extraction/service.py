from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from ..models import BBox, FrameMeta, SheetSet
from .bridge import RebarBridgeScanner, RebarBridgeScanResult
from .models import RebarRow
from .parser import associate_rebar_marks
from .reporting import write_rebar_debug_json, write_rebar_summary_csv


class RebarScannerProtocol(Protocol):
    def scan(
        self,
        *,
        job_id: str,
        source_dwg: Path,
        workspace_dir: Path,
        slot_runtime: dict[str, str] | None = None,
    ) -> RebarBridgeScanResult:
        ...


@dataclass(frozen=True)
class RebarScanRunResult:
    csv_path: Path
    debug_path: Path
    rows_count: int
    bridge_summary: dict[str, object]


def run_rebar_scan(
    *,
    job_id: str,
    source_dwg: Path,
    output_dir: Path,
    scanner: RebarScannerProtocol | None = None,
    slot_runtime: dict[str, str] | None = None,
    layout_internal_codes: dict[str, str] | None = None,
    frames: list[FrameMeta] | None = None,
    sheet_sets: list[SheetSet] | None = None,
) -> RebarScanRunResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    scanner = scanner or RebarBridgeScanner()
    bridge_result = scanner.scan(
        job_id=job_id,
        source_dwg=source_dwg,
        workspace_dir=output_dir / "bridge",
        slot_runtime=slot_runtime,
    )

    layout_internal_codes = layout_internal_codes or {}
    rows: list[RebarRow] = []
    association_debug: dict[str, object] = {}
    for layout_name in sorted(_collect_layouts(bridge_result)):
        layout_circles = [item for item in bridge_result.circles if item.layout_name == layout_name]
        layout_lines = [item for item in bridge_result.lines if item.layout_name == layout_name]
        layout_texts = [item for item in bridge_result.texts if item.layout_name == layout_name]
        if not layout_circles and not layout_texts:
            continue
        layout_rows, debug = associate_rebar_marks(
            source_filename=source_dwg.name,
            internal_code=layout_internal_codes.get(layout_name, "未归属"),
            layout_name=layout_name,
            circles=layout_circles,
            lines=layout_lines,
            texts=layout_texts,
        )
        rows.extend(
            _apply_frame_internal_codes(
                layout_rows,
                frames=frames or [],
                sheet_sets=sheet_sets or [],
            )
        )
        association_debug[layout_name] = debug

    csv_path = output_dir / "rebar_summary.csv"
    debug_path = output_dir / "rebar_debug.json"
    write_rebar_summary_csv(rows, csv_path)
    write_rebar_debug_json(
        {
            "source_filename": source_dwg.name,
            "bridge_summary": bridge_result.summary,
            "association": association_debug,
            "debug_symbols": bridge_result.debug_symbols,
            "rows_count": len(rows),
        },
        debug_path,
    )
    return RebarScanRunResult(
        csv_path=csv_path,
        debug_path=debug_path,
        rows_count=len(rows),
        bridge_summary=bridge_result.summary,
    )


def _apply_frame_internal_codes(
    rows: list[RebarRow],
    *,
    frames: list[FrameMeta],
    sheet_sets: list[SheetSet],
) -> list[RebarRow]:
    regions = _build_frame_regions(frames, sheet_sets)
    if not regions:
        return rows
    mapped: list[RebarRow] = []
    for row in rows:
        internal_code = _resolve_internal_code(row.position_x, row.position_y, regions)
        mapped.append(replace(row, internal_code=internal_code or row.internal_code))
    return mapped


def _build_frame_regions(
    frames: list[FrameMeta],
    sheet_sets: list[SheetSet],
) -> list[tuple[BBox, str | None, float]]:
    regions: list[tuple[BBox, str | None, float]] = []
    for frame in frames:
        bbox = frame.runtime.outer_bbox
        regions.append((bbox, frame.titleblock.internal_code, bbox.width * bbox.height))
    for sheet_set in sheet_sets:
        inherited = sheet_set.get_inherited_titleblock()
        inherited_internal_code = str(inherited.get("internal_code") or "") or None
        for page in sheet_set.pages:
            bbox = page.outer_bbox
            regions.append((bbox, inherited_internal_code, bbox.width * bbox.height))
    return regions


def _resolve_internal_code(
    x: float,
    y: float,
    regions: list[tuple[BBox, str | None, float]],
) -> str | None:
    matches = [
        (bbox, internal_code, area)
        for bbox, internal_code, area in regions
        if bbox.xmin <= x <= bbox.xmax and bbox.ymin <= y <= bbox.ymax
    ]
    if not matches:
        return None
    matches.sort(key=lambda item: item[2])
    return matches[0][1]


def _collect_layouts(result: RebarBridgeScanResult) -> set[str]:
    layouts: defaultdict[str, int] = defaultdict(int)
    for group in (result.circles, result.lines, result.texts):
        for item in group:
            layouts[item.layout_name or "Model"] += 1
    return set(layouts)
