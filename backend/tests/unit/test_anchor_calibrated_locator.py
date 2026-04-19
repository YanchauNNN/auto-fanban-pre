"""
锚点校准定位器单元测试（模块2）
"""

from __future__ import annotations

from pathlib import Path

import ezdxf

from src.cad.detection import AnchorCalibratedLocator, CandidateFinder, PaperFitter
from src.config import BusinessSpec
from src.models import BBox
from tests.conftest import add_rect_polyline


class FixedScaleFitter:
    def __init__(
        self,
        *,
        paper_variant_id: str = "A1",
        profile_id: str = "BASE10",
        sx: float = 98.0,
        sy: float = 97.6,
        fit_error: float = 0.002,
    ) -> None:
        self.paper_variant_id = paper_variant_id
        self.profile_id = profile_id
        self.sx = sx
        self.sy = sy
        self.fit_error = fit_error

    def fit_all(self, _bbox, _variants):
        return [(self.paper_variant_id, self.sx, self.sy, self.profile_id, self.fit_error)]


def _calibrated_spec() -> BusinessSpec:
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
            "outer_frame": {
                "layer_priority": {
                    "global_layers": ["HIGH"],
                    "local_only_layers": ["LOW"],
                    "entity_order": ["LWPOLYLINE", "POLYLINE", "LINE"],
                }
            },
            "anchor": {
                "search_text": ["ANCHOR"],
                "profile_priority": ["BASE10"],
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
                    },
                },
            },
            "tolerances": {"roi_margin_percent": 0.0},
        },
        a4_multipage={},
        doc_generation={},
        enums={},
    )


def test_calibrated_locator_without_anchor_falls_back_to_geometry() -> None:
    locator = AnchorCalibratedLocator(
        _calibrated_spec(),
        CandidateFinder(layer_order=["HIGH"], min_dim=10.0),
        PaperFitter(),
    )
    doc = ezdxf.new()
    doc.layers.new("HIGH")
    msp = doc.modelspace()
    add_rect_polyline(msp, "HIGH", 0, 0, 100, 50)

    frames = locator.locate_frames(msp, Path("dummy.dxf"))

    assert len(frames) == 1


def test_calibrated_locator_falls_back_to_non_priority_insert_layer_for_unresolved_anchor() -> None:
    locator = AnchorCalibratedLocator(
        _calibrated_spec(),
        CandidateFinder(
            layer_order=["HIGH", "LOW"],
            entity_order=["LWPOLYLINE"],
            min_dim=1.0,
        ),
        PaperFitter(),
    )
    doc = ezdxf.new()
    doc.layers.new("123")
    block = doc.blocks.new(name="FRAME_IN_BLOCK")
    add_rect_polyline(block, "0", 0, 0, 100, 50)

    msp = doc.modelspace()
    # Calibrated locator uses the anchor text bbox right-bottom as reference.
    # Place the text so bbox.xmax/ymin aligns with the frame right-bottom (100, 0).
    msp.add_text("ANCHOR", dxfattribs={"insert": (91, 0), "height": 2.5})
    msp.add_blockref("FRAME_IN_BLOCK", (0, 0), dxfattribs={"layer": "123"})

    frames = locator.locate_frames(msp, Path("dummy.dxf"))

    assert len(frames) == 1


class GlobalThenLocalDummyFinder:
    def __init__(self, *, global_by_layer: dict[str, list[BBox]], local_by_layer: dict[str, list[BBox]]) -> None:
        self.global_by_layer = global_by_layer
        self.local_by_layer = local_by_layer
        self.min_dim = 1.0
        self.coord_tol = 0.5
        self._sin_tol = 0.0
        self.calls: list[tuple[tuple[str, ...], BBox | None, bool]] = []

    def find_rectangles(self, _msp):
        return []

    def find_rectangles_in_layers(self, _msp, layers, *, window=None, localize_line_rebuild=False):
        key = tuple(str(layer) for layer in layers)
        self.calls.append((key, window, localize_line_rebuild))
        source = self.local_by_layer if localize_line_rebuild else self.global_by_layer
        bboxes: list[BBox] = []
        for layer in key:
            bboxes.extend(source.get(layer, []))
        if window is None:
            return list(bboxes)
        return [bbox for bbox in bboxes if bbox.intersects(window)]


def test_calibrated_locator_retries_global_layers_with_localized_line_rebuild_for_unresolved_anchor() -> None:
    locator = AnchorCalibratedLocator(
        _calibrated_spec(),
        GlobalThenLocalDummyFinder(
            global_by_layer={"HIGH": []},
            local_by_layer={"HIGH": [BBox(xmin=0, ymin=0, xmax=100, ymax=50)]},
        ),
        PaperFitter(),
    )

    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_text("ANCHOR", dxfattribs={"insert": (91, 0), "height": 2.5})

    frames = locator.locate_frames(msp, Path("dummy.dxf"))

    assert len(frames) == 1
    assert (("HIGH",), None, False) in locator.candidate_finder.calls
    assert any(
        call[0] == ("HIGH",) and call[1] is not None and call[2]
        for call in locator.candidate_finder.calls
    )


def test_calibrated_localized_candidate_build_keeps_integer_scale_gate() -> None:
    locator = AnchorCalibratedLocator(
        _calibrated_spec(),
        CandidateFinder(min_dim=1.0),
        FixedScaleFitter(),
    )
    bbox = BBox(xmin=0, ymin=0, xmax=100, ymax=50)

    assert locator._build_candidates_for_bbox(bbox, "0") == []

    localized = locator._build_candidates_for_bbox(
        bbox,
        "0",
        relax_scale_candidate_gate=True,
    )

    assert localized == []
