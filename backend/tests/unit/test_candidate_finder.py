"""
候选矩形查找器单元测试（模块2）
"""

from __future__ import annotations

import logging

import ezdxf
import pytest

from src.cad.detection.candidate_finder import CandidateFinder
from tests.conftest import add_rect_lines, add_rect_polyline


def test_line_rebuild_conditionally_with_polyline(monkeypatch: pytest.MonkeyPatch) -> None:
    """闭合多段线全部合法时跳过段重建；存在非法比例时降级段重建。"""
    doc = ezdxf.new()
    doc.layers.new("L1")
    doc.layers.new("L2")
    msp = doc.modelspace()

    # L1: 闭合多段线 + LINE 矩形
    add_rect_polyline(msp, "L1", 0, 0, 200, 100)
    add_rect_lines(msp, "L1", 300, 0, 500, 100)
    # L2: 仅 LINE 矩形
    add_rect_lines(msp, "L2", 0, 200, 200, 300)

    def run_with_validator(validator):
        finder = CandidateFinder(
            layer_order=["L1", "L2"],
            entity_order=["LWPOLYLINE", "POLYLINE", "LINE"],
            bbox_scale_validator=validator,
        )
        contexts: list[str | None] = []
        original = finder._rebuild_from_segments

        def wrapped(segments, *, context=None):
            contexts.append(context)
            return original(segments, context=context)

        monkeypatch.setattr(finder, "_rebuild_from_segments", wrapped)
        bboxes = finder.find_rectangles(msp)
        return contexts, bboxes

    # 1) 全部合法：L1 跳过段重建，L2 仍需重建
    contexts, bboxes = run_with_validator(lambda _bbox: True)
    assert any(abs(b.width - 200) < 1e-6 and abs(b.height - 100) < 1e-6 for b in bboxes)
    assert "layer=L1" not in contexts
    assert "layer=L2" in contexts

    # 2) L1 闭合多段线非法：触发段重建
    def validator(bbox):
        return not (abs(bbox.xmin) < 1e-6 and abs(bbox.ymin) < 1e-6)

    contexts, bboxes = run_with_validator(validator)
    assert any(abs(b.width - 200) < 1e-6 and abs(b.height - 100) < 1e-6 for b in bboxes)
    assert "layer=L1" in contexts
    assert "layer=L2" in contexts


def test_global_skips_line_rebuild_when_poly_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = ezdxf.new()
    msp = doc.modelspace()

    add_rect_polyline(msp, "0", 0, 0, 200, 100)
    add_rect_lines(msp, "0", 300, 0, 500, 100)

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
