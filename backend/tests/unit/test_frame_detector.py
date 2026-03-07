"""
FrameDetector 路由逻辑单元测试（模块2）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.cad import FrameDetector
from src.interfaces import DetectionError


@pytest.mark.parametrize(
    ("mode", "expected_attr", "blocked_attr"),
    [
        ("geometry_first", "anchor_locator", "anchor_calibrated_locator"),
        ("rb_anchor", "anchor_calibrated_locator", "anchor_locator"),
    ],
    ids=["geometry_first", "rb_anchor"],
)
def test_detect_frames_routing(
    sample_dxf_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_attr: str,
    blocked_attr: str,
) -> None:
    """验证 frame_detect_mode 正确路由到对应定位器"""
    detector = FrameDetector(frame_detect_mode=mode)
    called = {"hit": False}

    def fake_expected(_msp, _path):
        called["hit"] = True
        return []

    def fake_blocked(_msp, _path):
        raise AssertionError(f"{blocked_attr} should not be called in {mode} mode")

    monkeypatch.setattr(
        getattr(detector, expected_attr),
        "locate_frames",
        fake_expected,
    )
    monkeypatch.setattr(
        getattr(detector, blocked_attr),
        "locate_frames",
        fake_blocked,
    )

    detector.detect_frames(sample_dxf_path)
    assert called["hit"]


def test_detect_frames_missing_file_raises() -> None:
    detector = FrameDetector()
    with pytest.raises(DetectionError):
        detector.detect_frames(Path("missing-file.dxf"))


def test_frame_detector_supports_tsz_plot_mark_aliases() -> None:
    detector = FrameDetector()
    layers = detector.candidate_finder.layer_order

    assert "_TSZ_PLOT_MARK" in layers
    assert "_TSZ-PLOT_MARK" in layers
    assert layers.index("_TSZ_PLOT_MARK") < layers.index("_TSZ-PLOT_MARK")
