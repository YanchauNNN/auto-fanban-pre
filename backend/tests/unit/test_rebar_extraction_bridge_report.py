from __future__ import annotations

import csv
import json
from pathlib import Path

from src.rebar_extraction.bridge import RebarBridgeScanner
from src.rebar_extraction.models import CircleFeature, LineFeature, Point2D, RebarRow, TextFeature
from src.rebar_extraction.reporting import write_rebar_debug_json, write_rebar_summary_csv


class _FakeRunner:
    def __init__(self) -> None:
        self.task_payload: dict | None = None

    def run(
        self,
        *,
        source_dxf: Path,
        task_json: Path,
        result_json: Path,
        workspace_dir: Path,
    ) -> None:
        self.task_payload = json.loads(task_json.read_text(encoding="utf-8"))
        assert source_dxf.name == "新块.dwg"
        payload = {
            "errors": [],
            "rebar_scan": {"circle_count": 1, "text_count": 2, "line_count": 1},
            "rebar_circles": [
                {
                    "handle": "C1",
                    "layout_name": "Model",
                    "center": {"x": 100.0, "y": 200.0},
                    "radius": 15.0,
                }
            ],
            "rebar_lines": [
                {
                    "handle": "L1",
                    "layout_name": "Model",
                    "start": {"x": 80.0, "y": 200.0},
                    "end": {"x": 180.0, "y": 200.0},
                }
            ],
            "rebar_texts": [
                {
                    "handle": "T1",
                    "raw_text": "105",
                    "entity_type": "DBText",
                    "layout_name": "Model",
                    "position": {"x": 100.0, "y": 200.0},
                    "text_style": "STANDARD",
                    "font": "tssdeng.shx",
                    "codepoints": ["U+0031", "U+0030", "U+0035"],
                },
                {
                    "handle": "T2",
                    "raw_text": "8\u008520@200",
                    "entity_type": "DBText",
                    "layout_name": "Model",
                    "position": {"x": 130.0, "y": 220.0},
                    "text_style": "STANDARD",
                    "font": "tssdeng.shx",
                    "codepoints": ["U+0038", "U+0085"],
                },
            ],
            "rebar_debug_symbols": [{"raw_text": "8\u008520@200", "codepoints": ["U+0085"]}],
        }
        result_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig")


def test_rebar_bridge_writes_scan_task_and_reads_features(tmp_path: Path) -> None:
    source_dwg = tmp_path / "新块.dwg"
    source_dwg.write_bytes(b"dwg")
    fake_runner = _FakeRunner()
    scanner = RebarBridgeScanner(runner=fake_runner)

    result = scanner.scan(
        job_id="job-rebar",
        source_dwg=source_dwg,
        workspace_dir=tmp_path / "work",
        slot_runtime={"temp_dir": str(tmp_path / "temp")},
    )

    assert fake_runner.task_payload is not None
    assert fake_runner.task_payload["workflow_stage"] == "rebar_scan"
    assert fake_runner.task_payload["source_dxf"] == str(source_dwg)
    assert fake_runner.task_payload["runtime"]["temp_dir"] == str(tmp_path / "temp")
    assert result.summary["circle_count"] == 1
    assert result.circles == [CircleFeature(handle="C1", layout_name="Model", center=Point2D(100.0, 200.0), radius=15.0)]
    assert result.lines == [LineFeature(handle="L1", layout_name="Model", start=Point2D(80.0, 200.0), end=Point2D(180.0, 200.0))]
    assert result.texts[1] == TextFeature(
        handle="T2",
        raw_text="8\u008520@200",
        entity_type="DBText",
        layout_name="Model",
        position=Point2D(130.0, 220.0),
        text_style="STANDARD",
        font="tssdeng.shx",
        codepoints=("U+0038", "U+0085"),
    )
    assert result.debug_symbols[0]["codepoints"] == ["U+0085"]


def test_write_rebar_summary_csv_and_debug_json(tmp_path: Path) -> None:
    row = RebarRow(
        source_filename="新块.dwg",
        internal_code="TEST-002",
        layout_name="Model",
        bar_no="105",
        quantity=8,
        grade_symbol_raw="\u0085",
        grade_symbol_normalized="REBAR_GRADE",
        diameter=20,
        spacing=200,
        radius=5800,
        formula_text="",
        note_text="半径R=5800处间距为250mm",
        input_kind="horizontal",
        confidence="high",
        circle_handle="C1",
        line_handle="L1",
        text_handles="T2;T3",
        position_x=100.0,
        position_y=200.0,
    )

    csv_path = tmp_path / "rebar_summary.csv"
    debug_path = tmp_path / "rebar_debug.json"
    write_rebar_summary_csv([row], csv_path)
    write_rebar_debug_json({"unknown_symbols": [{"raw_text": "?", "codepoints": ["U+FFFF"]}]}, debug_path)

    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["source_filename"] == "新块.dwg"
    assert rows[0]["bar_no"] == "105"
    assert rows[0]["grade_symbol_normalized"] == "REBAR_GRADE"
    assert rows[0]["spacing"] == "200"
    assert rows[0]["text_handles"] == "T2;T3"

    payload = json.loads(debug_path.read_text(encoding="utf-8"))
    assert payload["unknown_symbols"][0]["codepoints"] == ["U+FFFF"]
