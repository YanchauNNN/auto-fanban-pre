"""
FrameDetector 路由逻辑单元测试（模块2）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.cad import FrameDetector
from src.interfaces import DetectionError


def test_detect_frames_uses_anchor_locator(sample_dxf_path: Path, monkeypatch: pytest.MonkeyPatch):
    detector = FrameDetector(frame_detect_mode="geometry_first")
    called = {"anchor": False}

    def fake_anchor(_msp, _path):
        called["anchor"] = True
        return []

    def fake_calibrated(_msp, _path):
        raise AssertionError("anchor_calibrated_locator should not be called")

    monkeypatch.setattr(detector.anchor_locator, "locate_frames", fake_anchor)
    monkeypatch.setattr(detector.anchor_calibrated_locator, "locate_frames", fake_calibrated)

    detector.detect_frames(sample_dxf_path)
    assert called["anchor"]


def test_detect_frames_uses_anchor_calibrated(sample_dxf_path: Path, monkeypatch: pytest.MonkeyPatch):
    detector = FrameDetector(frame_detect_mode="rb_anchor")
    called = {"calibrated": False}

    def fake_calibrated(_msp, _path):
        called["calibrated"] = True
        return []

    def fake_anchor(_msp, _path):
        raise AssertionError("anchor_locator should not be called")

    monkeypatch.setattr(detector.anchor_calibrated_locator, "locate_frames", fake_calibrated)
    monkeypatch.setattr(detector.anchor_locator, "locate_frames", fake_anchor)

    detector.detect_frames(sample_dxf_path)
    assert called["calibrated"]


def test_detect_frames_missing_file_raises() -> None:
    detector = FrameDetector()
    with pytest.raises(DetectionError):
        detector.detect_frames(Path("missing-file.dxf"))
