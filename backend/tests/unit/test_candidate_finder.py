"""
候选矩形查找器单元测试（模块2）
"""

from __future__ import annotations

import logging

import ezdxf
import pytest

from src.cad.detection.candidate_finder import CandidateFinder


def _add_rect_polyline(msp, layer: str, x0: float, y0: float, x1: float, y1: float) -> None:
    msp.add_lwpolyline(
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
        close=True,
        dxfattribs={"layer": layer},
    )


def _add_rect_lines(msp, layer: str, x0: float, y0: float, x1: float, y1: float) -> None:
    msp.add_line((x0, y0), (x1, y0), dxfattribs={"layer": layer})
    msp.add_line((x1, y0), (x1, y1), dxfattribs={"layer": layer})
    msp.add_line((x1, y1), (x0, y1), dxfattribs={"layer": layer})
    msp.add_line((x0, y1), (x0, y0), dxfattribs={"layer": layer})


def test_line_rebuild_only_when_no_polyline(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = ezdxf.new()
    doc.layers.new("L1")
    doc.layers.new("L2")
    msp = doc.modelspace()

    _add_rect_polyline(msp, "L1", 0, 0, 200, 100)
    _add_rect_lines(msp, "L1", 300, 0, 500, 100)
    _add_rect_lines(msp, "L2", 0, 200, 200, 300)

    finder = CandidateFinder(layer_order=["L1", "L2"], entity_order=["LWPOLYLINE", "POLYLINE", "LINE"])
    contexts: list[str | None] = []

    original = finder._rebuild_from_segments

    def wrapped(segments, *, context=None):
        contexts.append(context)
        return original(segments, context=context)

    monkeypatch.setattr(finder, "_rebuild_from_segments", wrapped)

    bboxes = finder.find_rectangles(msp)

    assert any(abs(b.width - 200) < 1e-6 and abs(b.height - 100) < 1e-6 for b in bboxes)
    assert "layer=L1" not in contexts
    assert "layer=L2" in contexts


def test_global_skips_line_rebuild_when_poly_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = ezdxf.new()
    msp = doc.modelspace()

    _add_rect_polyline(msp, "0", 0, 0, 200, 100)
    _add_rect_lines(msp, "0", 300, 0, 500, 100)

    finder = CandidateFinder(layer_order=None)
    called = {"rebuild": False}

    def fake_rebuild(msp):
        called["rebuild"] = True
        return []

    monkeypatch.setattr(finder, "_rebuild_from_lines", fake_rebuild)

    bboxes = finder.find_rectangles(msp)

    assert bboxes
    assert not called["rebuild"]


def test_line_rebuild_logs_when_segments_exceed(caplog: pytest.LogCaptureFixture) -> None:
    finder = CandidateFinder(line_rebuild_limits={"max_segments": 2})
    segments = [
        ((0.0, 0.0), (10.0, 0.0)),
        ((0.0, 0.0), (0.0, 10.0)),
        ((10.0, 0.0), (10.0, 10.0)),
    ]

    with caplog.at_level(logging.WARNING):
        rects = finder._rebuild_from_segments(segments, context="layer=LX")

    assert rects == []
    assert "LINE重建跳过" in caplog.text
