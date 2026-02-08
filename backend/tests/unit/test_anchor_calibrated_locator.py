"""
锚点校准定位器单元测试（模块2）
"""

from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest

from src.cad.detection import AnchorCalibratedLocator, CandidateFinder, PaperFitter
from src.config import BusinessSpec
from src.interfaces import DetectionError


def _make_spec() -> BusinessSpec:
    return BusinessSpec(
        schema_version="2.0",
        titleblock_extract={
            "paper_variants": {"A1": {"W": 100.0, "H": 50.0, "profile": "BASE10"}},
            "anchor": {"search_text": ["ANCHOR"]},
        },
        a4_multipage={},
        doc_generation={},
        enums={},
    )


def test_calibrated_locator_raises_when_no_anchor() -> None:
    spec = _make_spec()
    locator = AnchorCalibratedLocator(spec, CandidateFinder(), PaperFitter())

    doc = ezdxf.new()
    msp = doc.modelspace()

    with pytest.raises(DetectionError):
        locator.locate_frames(msp, Path("dummy.dxf"))
