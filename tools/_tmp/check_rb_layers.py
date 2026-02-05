from __future__ import annotations

import argparse
import importlib
import math
import sys
from pathlib import Path

import ezdxf  # type: ignore


def _add_backend_to_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    backend_root = repo_root / "backend"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))


def _dist(p: tuple[float, float], q: tuple[float, float]) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _format_point(p: tuple[float, float]) -> str:
    return f"({p[0]:.3f}, {p[1]:.3f})"


def _dist_point_to_segment(
    p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float:
    px, py = p
    ax, ay = a
    bx, by = b
    dx = bx - ax
    dy = by - ay
    if dx == 0 and dy == 0:
        return _dist(p, a)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx = ax + t * dx
    cy = ay + t * dy
    return _dist(p, (cx, cy))


def _override_text_height(calibration: dict, base_h: float) -> None:
    for key, calib in calibration.items():
        if key == "reference_point":
            continue
        if isinstance(calib, dict):
            calib["text_height_1to1_mm"] = base_h


def _count_endpoint_hits(
    lines: list[tuple[tuple[float, float], tuple[float, float]]],
    rb: tuple[float, float],
    radius: float,
) -> int:
    hits = 0
    for p1, p2 in lines:
        if _dist(p1, rb) <= radius or _dist(p2, rb) <= radius:
            hits += 1
    return hits


def _nearest_endpoint(
    lines: list[tuple[tuple[float, float], tuple[float, float]]],
    rb: tuple[float, float],
) -> tuple[float | None, tuple[float, float] | None]:
    best_d = None
    best_p = None
    best_seg = None
    for p1, p2 in lines:
        for p in (p1, p2):
            d = _dist(p, rb)
            if best_d is None or d < best_d:
                best_d = d
                best_p = p
                best_seg = (p1, p2)
    return best_d, best_p, best_seg


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan RB matches across layers (LINE + open polylines)."
    )
    parser.add_argument(
        "--dxf",
        default="test/dxf-1818/1818-A0.dxf",
        help="DXF文件路径",
    )
    parser.add_argument(
        "--base-h",
        type=float,
        default=None,
        help="覆盖校准字高(如1818使用2.5)",
    )
    parser.add_argument(
        "--radius",
        type=float,
        default=0.1,
        help="端点靠近RB的半径(输出统计)",
    )
    parser.add_argument(
        "--rb-tol",
        type=float,
        default=None,
        help="覆盖RB端点容差(默认使用代码中的rb_tol)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="输出每个图层的线段数量与最近端点距离",
    )
    args = parser.parse_args()

    _add_backend_to_path()
    from src.cad.detection import (  # type: ignore
        AnchorCalibratedLocator,
        CandidateFinder,
        PaperFitter,
    )
    from src.config import load_spec  # type: ignore

    anchor_module = importlib.import_module("src.cad.detection.anchor_first_locator")
    AnchorFirstLocator = anchor_module.AnchorFirstLocator

    spec = load_spec()
    anchor_cfg = spec.titleblock_extract.get("anchor", {})
    calibration = anchor_cfg.get("calibration", {})
    if args.base_h is not None:
        _override_text_height(calibration, args.base_h)

    locator = AnchorCalibratedLocator(spec, CandidateFinder(), PaperFitter())
    if args.rb_tol is not None:
        locator.rb_tol = float(args.rb_tol)
    dxf_path = Path(args.dxf)
    if not dxf_path.exists():
        print(f"DXF not found: {dxf_path}")
        return 2

    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()
    text_items = list(AnchorFirstLocator._iter_text_items(msp))  # noqa: SLF001
    anchor_items = [
        t
        for t in text_items
        if locator._match_any_text(t.text, locator.anchor_texts)  # noqa: SLF001
    ]
    rb_targets = locator._build_rb_targets(anchor_items)  # noqa: SLF001

    print(
        f"dxf={dxf_path.name} anchors={len(anchor_items)} rb_targets={len(rb_targets)} "
        f"base_h={args.base_h}"
    )
    if not rb_targets:
        return 0

    for target in rb_targets:
        rb = (float(target["rb_x"]), float(target["rb_y"]))
        profile = target["profile_id"]
        scale = float(target["scale"])
        print(f"\nRB profile={profile} scale={scale:.6f} rb={_format_point(rb)}")

        for layer in locator.layer_order:
            lines = locator._query_lines(msp, layer)  # noqa: SLF001
            if not lines:
                if args.verbose:
                    print(f"  layer={layer} lines=0")
                continue
            hits_r = _count_endpoint_hits(lines, rb, args.radius)
            hits_tol = _count_endpoint_hits(lines, rb, locator.rb_tol)
            matches = locator._match_lines(  # noqa: SLF001
                lines,
                rb[0],
                rb[1],
                scale,
                profile,
                layer,
            )
            if hits_r or hits_tol or matches or args.verbose:
                nearest_d, nearest_p, nearest_seg = _nearest_endpoint(lines, rb)
                nearest_seg_dist = min(
                    (_dist_point_to_segment(rb, seg[0], seg[1]) for seg in lines),
                    default=None,
                )
                xs = [p[0] for seg in lines for p in seg]
                ys = [p[1] for seg in lines for p in seg]
                bbox_info = None
                if xs and ys:
                    bbox_info = f"bbox=({min(xs):.3f},{min(ys):.3f},{max(xs):.3f},{max(ys):.3f})"
                print(
                    f"  layer={layer} lines={len(lines)} "
                    f"hits<=r({args.radius})={hits_r} hits<=rb_tol({locator.rb_tol})={hits_tol} "
                    f"matches={len(matches)} nearest_d={nearest_d} seg_d={nearest_seg_dist} "
                    f"nearest_p={_format_point(nearest_p) if nearest_p else None} {bbox_info or ''}"
                )
                if nearest_seg:
                    print(
                        f"    nearest_seg: {_format_point(nearest_seg[0])} -> {_format_point(nearest_seg[1])}"
                    )
                if matches:
                    best = min(matches, key=lambda c: (c.fit_error, c.area))
                    bbox = best.bbox
                    print(
                        "    best_bbox="
                        f"({bbox.xmin:.3f},{bbox.ymin:.3f},{bbox.xmax:.3f},{bbox.ymax:.3f}) "
                        f"variant={best.paper_variant_id} sx={best.sx:.6f} sy={best.sy:.6f}"
                    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
