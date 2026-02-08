"""
锚点优先定位器单元测试（模块2）
"""

from __future__ import annotations

from pathlib import Path

import ezdxf

from src.cad.detection.anchor_first_locator import AnchorFirstLocator
from src.config import BusinessSpec
from src.models import BBox


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


def _make_spec() -> BusinessSpec:
    return BusinessSpec(
        schema_version="2.0",
        titleblock_extract={
            "paper_variants": {"A1": {"W": 100.0, "H": 50.0, "profile": "BASE10"}},
            "roi_profiles": {
                "BASE10": {
                    "description": "test",
                    "tolerance": 0.5,
                    "outer_frame": [0, 100, 0, 50],
                    "fields": {"锚点": [0, 100, 0, 50]},
                }
            },
            "anchor": {
                "search_text": ["ANCHOR"],
                "roi_field_name": "锚点",
                "match_policy": "single_hit_same_roi",
            },
            "tolerances": {"roi_margin_percent": 0.0},
        },
        a4_multipage={},
        doc_generation={},
        enums={},
    )


def test_locate_frames_returns_match() -> None:
    spec = _make_spec()
    bbox = BBox(xmin=0, ymin=0, xmax=100, ymax=50)
    finder = DummyFinder([bbox])
    fitter = DummyFitter()
    locator = AnchorFirstLocator(spec, finder, fitter)

    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_text("ANCHOR", dxfattribs={"insert": (10, 10), "height": 2.5})

    frames = locator.locate_frames(msp, Path("dummy.dxf"))
    assert len(frames) == 1


def test_locate_frames_no_roi_match_returns_empty() -> None:
    spec = _make_spec()
    bbox = BBox(xmin=0, ymin=0, xmax=100, ymax=50)
    finder = DummyFinder([bbox])
    fitter = DummyFitter()
    locator = AnchorFirstLocator(spec, finder, fitter)

    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_text("ANCHOR", dxfattribs={"insert": (200, 200), "height": 2.5})

    frames = locator.locate_frames(msp, Path("dummy.dxf"))
    assert frames == []


def test_build_candidates_ignores_scale_filter() -> None:
    spec = _make_spec()
    bbox = BBox(xmin=0, ymin=0, xmax=100, ymax=50)
    finder = DummyFinder([bbox])
    fitter = DummyFitter()
    locator = AnchorFirstLocator(spec, finder, fitter)

    locator._anchor_scale_range = (0.1, 0.2)
    candidates = locator._build_candidates(None)

    assert len(candidates) == 1
