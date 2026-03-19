"""
锚点优先定位器单元测试（模块2）
"""

from __future__ import annotations

from pathlib import Path

import ezdxf

from src.cad.detection.anchor_first_locator import AnchorFirstLocator
from src.cad.detection.candidate_finder import CandidateFinder
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
    def __init__(self, paper_variant_id: str = "A1", profile_id: str = "BASE10") -> None:
        self.paper_variant_id = paper_variant_id
        self.profile_id = profile_id

    def fit_all(self, _bbox, _variants):
        return [(self.paper_variant_id, 1.0, 1.0, self.profile_id, 0.0)]


class LayeredDummyFinder:
    def __init__(
        self,
        *,
        by_layer: dict[str, list[BBox]] | None = None,
        global_bboxes: list[BBox] | None = None,
    ) -> None:
        self.by_layer = by_layer or {}
        self.global_bboxes = global_bboxes or []
        self.min_dim = 1.0
        self.calls: list[tuple[tuple[str, ...], BBox | None]] = []

    def find_rectangles(self, _msp):
        return list(self.global_bboxes)

    def find_rectangles_in_layers(self, _msp, layers, *, window=None, localize_line_rebuild=False):
        key = tuple(str(layer) for layer in layers)
        self.calls.append((key, window))
        bboxes: list[BBox] = []
        for layer in key:
            bboxes.extend(self.by_layer.get(layer, []))
        if window is None:
            return list(bboxes)
        return [bbox for bbox in bboxes if bbox.intersects(window)]


def _layered_anchor_spec() -> BusinessSpec:
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
                },
            },
            "outer_frame": {
                "layer_priority": {
                    "global_layers": ["HIGH"],
                    "local_only_layers": ["LOW"],
                    "entity_order": ["LWPOLYLINE", "POLYLINE", "LINE"],
                }
            },
            "anchor": {
                "search_text": ["ANCHOR"],
                "roi_field_name": "锚点",
                "match_policy": "single_hit_same_roi",
                "scale_candidates": [1],
                "scale_match_rel_tol": 0.1,
                "calibration": {
                    "reference_point": "text_bbox_right_bottom",
                    "BASE10": {
                        "text_height_1to1_mm": 2.5,
                        "anchor_roi_rb_offset_1to1": [0.0, 100.0, 0.0, 50.0],
                        "text_ref_in_anchor_roi_1to1": {
                            "dx_right": 0.0,
                            "dy_bottom": 0.0,
                        },
                    }
                },
            },
            "tolerances": {"roi_margin_percent": 0.0},
        },
        a4_multipage={},
        doc_generation={},
        enums={},
    )


def _layered_a4_spec() -> BusinessSpec:
    return BusinessSpec(
        schema_version="2.0",
        titleblock_extract={
            "paper_variants": {
                "CNPE_A4": {"W": 100.0, "H": 50.0, "profile": "SMALL5"}
            },
            "roi_profiles": {
                "SMALL5": {
                    "description": "test-a4",
                    "tolerance": 0.5,
                    "outer_frame": [0, 100, 0, 50],
                    "fields": {"锚点": [0, 100, 0, 50]},
                },
            },
            "outer_frame": {
                "layer_priority": {
                    "global_layers": ["HIGH"],
                    "local_only_layers": ["LOW"],
                    "entity_order": ["LWPOLYLINE", "POLYLINE", "LINE"],
                }
            },
            "anchor": {
                "search_text": ["ANCHOR"],
                "roi_field_name": "锚点",
                "match_policy": "single_hit_same_roi",
                "scale_candidates": [1],
                "scale_match_rel_tol": 0.1,
                "calibration": {
                    "reference_point": "text_bbox_right_bottom",
                    "SMALL5": {
                        "text_height_1to1_mm": 2.5,
                        "anchor_roi_rb_offset_1to1": [0.0, 100.0, 0.0, 50.0],
                        "text_ref_in_anchor_roi_1to1": {
                            "dx_right": 0.0,
                            "dy_bottom": 0.0,
                        },
                    }
                },
            },
            "tolerances": {"roi_margin_percent": 0.0},
            "scale_fit": {"uniform_scale_tol": 0.02, "scale_candidate_match_tol": 0.015},
        },
        a4_multipage={"cluster_building": {"gap_threshold_factor": 0.5}},
        doc_generation={},
        enums={},
    )


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


def test_locate_frames_progressively_queries_global_then_local_layers() -> None:
    spec = _layered_anchor_spec()
    finder = LayeredDummyFinder(
        by_layer={
            "HIGH": [BBox(xmin=0, ymin=0, xmax=100, ymax=50)],
            "LOW": [BBox(xmin=200, ymin=0, xmax=300, ymax=50)],
        }
    )
    locator = AnchorFirstLocator(spec, finder, DummyFitter())

    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_text("ANCHOR", dxfattribs={"insert": (10, 10), "height": 2.5})
    msp.add_text("ANCHOR", dxfattribs={"insert": (210, 10), "height": 2.5})

    frames = locator.locate_frames(msp, Path("dummy.dxf"))

    assert len(frames) == 2
    assert (("HIGH",), None) in finder.calls
    assert any(call[0] == ("LOW",) and call[1] is not None for call in finder.calls)


def test_locate_frames_without_anchor_falls_back_to_geometry_layers() -> None:
    spec = _layered_anchor_spec()
    finder = LayeredDummyFinder(
        by_layer={"HIGH": [BBox(xmin=0, ymin=0, xmax=100, ymax=50)]},
    )
    locator = AnchorFirstLocator(spec, finder, DummyFitter())

    doc = ezdxf.new()
    msp = doc.modelspace()

    frames = locator.locate_frames(msp, Path("dummy.dxf"))

    assert len(frames) == 1
    assert finder.calls[0] == (("HIGH",), None)


def test_locate_frames_expands_a4_neighbors_from_local_layers_without_extra_anchors() -> None:
    spec = _layered_a4_spec()
    finder = LayeredDummyFinder(
        by_layer={
            "HIGH": [
                BBox(xmin=0, ymin=0, xmax=100, ymax=50),
                BBox(xmin=110, ymin=0, xmax=210, ymax=50),
            ],
            "LOW": [
                BBox(xmin=220, ymin=0, xmax=320, ymax=50),
                BBox(xmin=330, ymin=0, xmax=430, ymax=50),
            ],
        }
    )
    locator = AnchorFirstLocator(spec, finder, DummyFitter("CNPE_A4", "SMALL5"))

    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_text("ANCHOR", dxfattribs={"insert": (10, 10), "height": 2.5})
    msp.add_text("ANCHOR", dxfattribs={"insert": (120, 10), "height": 2.5})

    frames = locator.locate_frames(msp, Path("dummy.dxf"))

    assert len(frames) == 4
    assert any(call[0] == ("LOW",) and call[1] is not None for call in finder.calls)


def test_locate_frames_falls_back_to_non_priority_insert_layer_for_unresolved_anchor() -> None:
    spec = _layered_anchor_spec()
    finder = CandidateFinder(
        min_dim=1.0,
        coord_tol=0.5,
        layer_order=["HIGH", "LOW"],
        entity_order=["LWPOLYLINE"],
    )
    locator = AnchorFirstLocator(spec, finder, DummyFitter())

    doc = ezdxf.new()
    doc.layers.new("123")
    block = doc.blocks.new(name="FRAME_IN_BLOCK")
    block.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True, dxfattribs={"layer": "0"})

    msp = doc.modelspace()
    msp.add_text("ANCHOR", dxfattribs={"insert": (10, 10), "height": 2.5})
    msp.add_blockref("FRAME_IN_BLOCK", (0, 0), dxfattribs={"layer": "123"})

    frames = locator.locate_frames(msp, Path("dummy.dxf"))

    assert len(frames) == 1
