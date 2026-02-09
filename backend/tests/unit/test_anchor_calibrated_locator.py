"""
锚点校准定位器单元测试（模块2）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.cad.detection import AnchorCalibratedLocator, CandidateFinder, PaperFitter
from src.config import BusinessSpec
from src.interfaces import DetectionError


def test_calibrated_locator_raises_when_no_anchor(
    anchor_spec: BusinessSpec, dxf_doc: tuple,
) -> None:
    locator = AnchorCalibratedLocator(anchor_spec, CandidateFinder(), PaperFitter())
    _, msp = dxf_doc

    with pytest.raises(DetectionError):
        locator.locate_frames(msp, Path("dummy.dxf"))
