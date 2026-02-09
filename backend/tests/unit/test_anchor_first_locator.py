"""
锚点优先定位器单元测试（模块2）
"""

from __future__ import annotations

from pathlib import Path

import ezdxf

from src.cad.detection.anchor_first_locator import AnchorFirstLocator
from src.config import BusinessSpec
from src.models import BBox

# ---------------------------------------------------------------------------
# 本文件专用的 Dummy 依赖（仅此处使用，不上提 conftest）
# ---------------------------------------------------------------------------

class DummyFinder:
    def __init__(self, bboxes: list[BBox]) -> None:
        self._bboxes = bboxes
        self.min_dim = 1.0

    def find_rectangles(self, _msp):
        return self._bboxes


class DummyFitter:
    def __init__(self, paper_variant_id: str = "A1") -> None:
        self.paper_variant_id = paper_variant_id

    def fit_all(self, _bbox, _variants):
        return [(self.paper_variant_id, 1.0, 1.0, "BASE10", 0.0)]


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------

def test_locate_frames_returns_match(anchor_spec: BusinessSpec) -> None:
    bbox = BBox(xmin=0, ymin=0, xmax=100, ymax=50)
    locator = AnchorFirstLocator(anchor_spec, DummyFinder([bbox]), DummyFitter())

    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_text("ANCHOR", dxfattribs={"insert": (10, 10), "height": 2.5})

    frames = locator.locate_frames(msp, Path("dummy.dxf"))
    assert len(frames) == 1


def test_locate_frames_no_roi_match_returns_empty(anchor_spec: BusinessSpec) -> None:
    bbox = BBox(xmin=0, ymin=0, xmax=100, ymax=50)
    locator = AnchorFirstLocator(anchor_spec, DummyFinder([bbox]), DummyFitter())

    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_text("ANCHOR", dxfattribs={"insert": (200, 200), "height": 2.5})

    frames = locator.locate_frames(msp, Path("dummy.dxf"))
    assert frames == []


def test_build_candidates_ignores_scale_filter(anchor_spec: BusinessSpec) -> None:
    bbox = BBox(xmin=0, ymin=0, xmax=100, ymax=50)
    locator = AnchorFirstLocator(anchor_spec, DummyFinder([bbox]), DummyFitter())

    locator._anchor_scale_range = (0.1, 0.2)
    candidates = locator._build_candidates(None)

    assert len(candidates) == 1
