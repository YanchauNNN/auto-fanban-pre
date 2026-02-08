"""
纸张尺寸拟合器单元测试（模块2）
"""

from __future__ import annotations

from src.cad.detection.paper_fitter import PaperFitter
from src.models import BBox


def test_fit_all_uniform_scale() -> None:
    fitter = PaperFitter()
    bbox = BBox(xmin=0, ymin=0, xmax=200, ymax=100)
    variants = {"A1": {"W": 200.0, "H": 100.0, "profile": "BASE10"}}

    results = fitter.fit_all(bbox, variants)

    assert len(results) == 1
    variant_id, sx, sy, profile, _error = results[0]
    assert variant_id == "A1"
    assert abs(sx - 1.0) < 1e-9
    assert abs(sy - 1.0) < 1e-9
    assert profile == "BASE10"


def test_fit_all_rotation_behavior() -> None:
    bbox = BBox(xmin=0, ymin=0, xmax=100, ymax=200)
    variants = {"A1": {"W": 200.0, "H": 100.0, "profile": "BASE10"}}

    fitter_no_rot = PaperFitter(allow_rotation=False)
    assert fitter_no_rot.fit_all(bbox, variants) == []

    fitter_rot = PaperFitter(allow_rotation=True)
    results = fitter_rot.fit_all(bbox, variants)
    assert len(results) >= 1


def test_fit_all_rejects_non_uniform_scale() -> None:
    bbox = BBox(xmin=0, ymin=0, xmax=210, ymax=300)
    variants = {"A1": {"W": 200.0, "H": 100.0, "profile": "BASE10"}}

    fitter = PaperFitter(uniform_scale_required=True, uniform_scale_tol=0.01)
    assert fitter.fit_all(bbox, variants) == []
