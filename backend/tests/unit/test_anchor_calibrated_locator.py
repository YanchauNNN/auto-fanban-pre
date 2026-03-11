"""
锚点校准定位器单元测试（模块2）
"""

from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest

from src.cad.detection import AnchorCalibratedLocator, CandidateFinder, PaperFitter
from src.config import BusinessSpec
from tests.conftest import add_rect_polyline


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
