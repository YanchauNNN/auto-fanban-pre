from __future__ import annotations

from src.cad.plot_window_strategy import (
    bbox_from_mapping,
    bbox_to_mapping,
    resolve_plot_window_bbox,
)
from src.models import BBox


def test_bbox_mapping_roundtrip() -> None:
    bbox = BBox(xmin=1.0, ymin=2.0, xmax=11.0, ymax=22.0)

    raw = bbox_to_mapping(bbox)

    assert bbox_from_mapping(raw) == bbox


def test_plot_window_keeps_frame_bbox_when_selection_extents_missing() -> None:
    frame_bbox = BBox(xmin=0.0, ymin=0.0, xmax=100.0, ymax=50.0)

    resolved = resolve_plot_window_bbox(
        frame_bbox=frame_bbox,
        selection_extents=None,
        enabled=True,
        mismatch_trigger_mm=2.0,
        mismatch_trigger_ratio=0.01,
    )

    assert resolved.use_selection_extents is False
    assert resolved.plot_window_bbox == frame_bbox
    assert resolved.reason == "disabled_or_missing"


def test_plot_window_keeps_frame_bbox_when_mismatch_below_threshold() -> None:
    frame_bbox = BBox(xmin=0.0, ymin=0.0, xmax=100.0, ymax=50.0)
    selection_extents = BBox(xmin=-0.5, ymin=0.0, xmax=100.4, ymax=50.4)

    resolved = resolve_plot_window_bbox(
        frame_bbox=frame_bbox,
        selection_extents=selection_extents,
        enabled=True,
        mismatch_trigger_mm=2.0,
        mismatch_trigger_ratio=0.01,
    )

    assert resolved.use_selection_extents is False
    assert resolved.plot_window_bbox == frame_bbox
    assert resolved.reason == "within_threshold"


def test_plot_window_switches_when_any_side_overflows_threshold() -> None:
    frame_bbox = BBox(xmin=0.0, ymin=0.0, xmax=100.0, ymax=50.0)
    selection_extents = BBox(xmin=-2.5, ymin=0.0, xmax=100.0, ymax=50.0)

    resolved = resolve_plot_window_bbox(
        frame_bbox=frame_bbox,
        selection_extents=selection_extents,
        enabled=True,
        mismatch_trigger_mm=2.0,
        mismatch_trigger_ratio=0.01,
    )

    assert resolved.use_selection_extents is True
    assert resolved.plot_window_bbox == selection_extents
    assert resolved.reason == "side_overflow"
    assert resolved.mismatch_sides_mm["left"] == 2.5


def test_plot_window_switches_when_size_ratio_exceeds_threshold() -> None:
    frame_bbox = BBox(xmin=0.0, ymin=0.0, xmax=100.0, ymax=50.0)
    selection_extents = BBox(xmin=0.0, ymin=0.0, xmax=101.5, ymax=50.0)

    resolved = resolve_plot_window_bbox(
        frame_bbox=frame_bbox,
        selection_extents=selection_extents,
        enabled=True,
        mismatch_trigger_mm=2.0,
        mismatch_trigger_ratio=0.01,
    )

    assert resolved.use_selection_extents is True
    assert resolved.plot_window_bbox == selection_extents
    assert resolved.reason == "ratio_overflow"
    assert resolved.width_ratio_delta > 0.01
