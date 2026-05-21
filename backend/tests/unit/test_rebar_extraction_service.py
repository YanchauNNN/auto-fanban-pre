from __future__ import annotations

import csv
from pathlib import Path

from src.models import BBox, FrameMeta, FrameRuntime, TitleblockFields
from src.rebar_extraction.bridge import RebarBridgeScanResult
from src.rebar_extraction.models import CircleFeature, LineFeature, Point2D, TextFeature
from src.rebar_extraction.service import run_rebar_scan


class _FakeScanner:
    def scan(self, *, job_id: str, source_dwg: Path, workspace_dir: Path, slot_runtime=None):
        assert job_id == "job-service"
        assert source_dwg.name == "新块.dwg"
        return RebarBridgeScanResult(
            summary={"circle_count": 1, "text_count": 2, "line_count": 1},
            circles=[CircleFeature(handle="C1", center=Point2D(100, 100), radius=20, layout_name="Model")],
            lines=[LineFeature(handle="L1", start=Point2D(50, 100), end=Point2D(200, 100), layout_name="Model")],
            texts=[
                TextFeature(handle="T1", raw_text="105", position=Point2D(100, 100), layout_name="Model"),
                TextFeature(handle="T2", raw_text="8\u008520@200", position=Point2D(140, 120), layout_name="Model"),
            ],
            debug_symbols=[],
        )


def test_run_rebar_scan_writes_reports_grouped_by_layout(tmp_path: Path) -> None:
    source = tmp_path / "新块.dwg"
    source.write_bytes(b"dwg")

    result = run_rebar_scan(
        job_id="job-service",
        source_dwg=source,
        output_dir=tmp_path / "out",
        scanner=_FakeScanner(),
        layout_internal_codes={"Model": "TEST-002"},
    )

    assert result.rows_count == 1
    assert result.csv_path.name == "rebar_summary.csv"
    with result.csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["internal_code"] == "TEST-002"
    assert rows[0]["bar_no"] == "105"
    assert rows[0]["confidence"] == "high"
    assert result.debug_path.read_text(encoding="utf-8").startswith("{")


def test_run_rebar_scan_maps_internal_code_by_frame_bbox(tmp_path: Path) -> None:
    source = tmp_path / "新块.dwg"
    source.write_bytes(b"dwg")
    frame = FrameMeta(
        runtime=FrameRuntime(
            frame_id="frame-002",
            source_file=source,
            outer_bbox=BBox(xmin=0, ymin=0, xmax=300, ymax=300),
        ),
        titleblock=TitleblockFields(internal_code="TEST-002"),
    )

    result = run_rebar_scan(
        job_id="job-service",
        source_dwg=source,
        output_dir=tmp_path / "out",
        scanner=_FakeScanner(),
        frames=[frame],
    )

    with result.csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["internal_code"] == "TEST-002"
