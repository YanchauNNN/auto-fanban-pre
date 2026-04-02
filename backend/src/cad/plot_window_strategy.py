from __future__ import annotations

from dataclasses import dataclass

from ..models import BBox


@dataclass(frozen=True, slots=True)
class PlotWindowResolution:
    use_selection_extents: bool
    plot_window_bbox: BBox
    mismatch_sides_mm: dict[str, float]
    width_ratio_delta: float
    height_ratio_delta: float
    reason: str


def bbox_from_mapping(raw: object) -> BBox | None:
    if not isinstance(raw, dict):
        return None
    try:
        return BBox(
            xmin=float(raw["xmin"]),
            ymin=float(raw["ymin"]),
            xmax=float(raw["xmax"]),
            ymax=float(raw["ymax"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def bbox_to_mapping(bbox: BBox) -> dict[str, float]:
    return {
        "xmin": float(bbox.xmin),
        "ymin": float(bbox.ymin),
        "xmax": float(bbox.xmax),
        "ymax": float(bbox.ymax),
    }


def resolve_plot_window_bbox(
    *,
    frame_bbox: BBox,
    selection_extents: BBox | None,
    enabled: bool,
    mismatch_trigger_mm: float,
    mismatch_trigger_ratio: float,
) -> PlotWindowResolution:
    if not enabled or selection_extents is None:
        return PlotWindowResolution(
            use_selection_extents=False,
            plot_window_bbox=frame_bbox,
            mismatch_sides_mm=_zero_sides(),
            width_ratio_delta=0.0,
            height_ratio_delta=0.0,
            reason="disabled_or_missing",
        )

    mismatch_sides = _compute_mismatch_sides(frame_bbox, selection_extents)
    width_ratio_delta = _ratio_delta(frame_bbox.width, selection_extents.width)
    height_ratio_delta = _ratio_delta(frame_bbox.height, selection_extents.height)

    if any(value > mismatch_trigger_mm for value in mismatch_sides.values()):
        return PlotWindowResolution(
            use_selection_extents=True,
            plot_window_bbox=selection_extents,
            mismatch_sides_mm=mismatch_sides,
            width_ratio_delta=width_ratio_delta,
            height_ratio_delta=height_ratio_delta,
            reason="side_overflow",
        )

    if width_ratio_delta > mismatch_trigger_ratio or height_ratio_delta > mismatch_trigger_ratio:
        return PlotWindowResolution(
            use_selection_extents=True,
            plot_window_bbox=selection_extents,
            mismatch_sides_mm=mismatch_sides,
            width_ratio_delta=width_ratio_delta,
            height_ratio_delta=height_ratio_delta,
            reason="ratio_overflow",
        )

    return PlotWindowResolution(
        use_selection_extents=False,
        plot_window_bbox=frame_bbox,
        mismatch_sides_mm=mismatch_sides,
        width_ratio_delta=width_ratio_delta,
        height_ratio_delta=height_ratio_delta,
        reason="within_threshold",
    )


def _compute_mismatch_sides(frame_bbox: BBox, selection_extents: BBox) -> dict[str, float]:
    return {
        "left": max(0.0, frame_bbox.xmin - selection_extents.xmin),
        "bottom": max(0.0, frame_bbox.ymin - selection_extents.ymin),
        "right": max(0.0, selection_extents.xmax - frame_bbox.xmax),
        "top": max(0.0, selection_extents.ymax - frame_bbox.ymax),
    }


def _ratio_delta(base: float, candidate: float) -> float:
    safe_base = max(float(base), 1e-9)
    return max(0.0, float(candidate) - float(base)) / safe_base


def _zero_sides() -> dict[str, float]:
    return {"left": 0.0, "bottom": 0.0, "right": 0.0, "top": 0.0}
