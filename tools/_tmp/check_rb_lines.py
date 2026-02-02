from __future__ import annotations

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


def _iter_line_endpoints(
    locator, msp, layer: str
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    lines: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for entity in locator._iter_layer_entities(msp, layer, "LINE"):  # noqa: SLF001
        start = entity.dxf.start
        end = entity.dxf.end
        p1 = (float(start.x), float(start.y))
        p2 = (float(end.x), float(end.y))
        lines.append((p1, p2))
    return lines


def _iter_polylines(locator, msp, layer: str) -> list[dict[str, object]]:
    polylines: list[dict[str, object]] = []
    for entity_type in ("LWPOLYLINE", "POLYLINE"):
        for entity in locator._iter_layer_entities(msp, layer, entity_type):  # noqa: SLF001
            if not locator._is_polyline_closed(entity, entity_type):  # noqa: SLF001
                continue
            vertices = locator._polyline_vertices(entity, entity_type)  # noqa: SLF001
            if not vertices:
                continue
            bbox = locator._bbox_from_vertices(vertices)  # noqa: SLF001
            is_axis = locator._is_axis_aligned(vertices)  # noqa: SLF001
            polylines.append(
                {
                    "entity_type": entity_type,
                    "vertices": vertices,
                    "bbox": bbox,
                    "is_axis": is_axis,
                }
            )
    return polylines


def _analyze_rb_for_layer(
    *,
    locator,
    msp,
    layer: str,
    rb_x: float,
    rb_y: float,
    radius: float = 0.1,
) -> dict[str, object]:
    lines = _iter_line_endpoints(locator, msp, layer)
    rb_point = (rb_x, rb_y)
    exact_tol = 1e-6

    exact_hits: list[tuple[tuple[float, float], tuple[float, float], float]] = []
    radius_hits: list[tuple[tuple[float, float], tuple[float, float], float]] = []
    nearest: list[tuple[float, tuple[float, float], tuple[float, float]]] = []

    for p1, p2 in lines:
        for p in (p1, p2):
            d = _dist(p, rb_point)
            if d <= exact_tol:
                exact_hits.append((p1, p2, d))
            if d <= radius:
                radius_hits.append((p1, p2, d))
            nearest.append((d, p1, p2))

    nearest.sort(key=lambda x: x[0])

    max_w = 0.0
    max_h = 0.0
    rb_tol = locator.rb_tol
    for p1, p2 in lines:
        p_near, p_other = locator._pick_rb_endpoint(p1, p2, rb_x, rb_y)  # noqa: SLF001
        if p_near is None:
            continue
        x1, y1 = p_near
        x2, y2 = p_other
        dx = x2 - x1
        dy = y2 - y1
        if abs(dy) <= rb_tol and x2 <= rb_x + rb_tol:
            max_w = max(max_w, rb_x - x2)
        elif abs(dx) <= rb_tol and y2 >= rb_y - rb_tol:
            max_h = max(max_h, y2 - rb_y)

    return {
        "line_count": len(lines),
        "exact_hits": exact_hits,
        "radius_hits": radius_hits,
        "nearest": nearest[:10],
        "rb_tol": rb_tol,
        "max_w": max_w,
        "max_h": max_h,
    }


def _analyze_rb_polylines(
    *,
    locator,
    msp,
    layer: str,
    rb_x: float,
    rb_y: float,
    radius: float = 0.1,
) -> dict[str, object]:
    polylines = _iter_polylines(locator, msp, layer)
    rb_point = (rb_x, rb_y)
    rb_tol = locator.rb_tol

    exact_hits: list[dict[str, object]] = []
    radius_hits: list[dict[str, object]] = []
    rb_tol_hits: list[dict[str, object]] = []
    bbox_rb_hits: list[dict[str, object]] = []
    nearest: list[tuple[float, tuple[float, float], dict[str, object]]] = []

    for poly in polylines:
        vertices = poly["vertices"]
        bbox = poly["bbox"]
        hit_exact = False
        hit_radius = False
        hit_rb_tol = False
        best_d = None
        best_p = None
        for vx, vy in vertices:
            d = _dist((vx, vy), rb_point)
            if best_d is None or d < best_d:
                best_d = d
                best_p = (vx, vy)
            if d <= 1e-6:
                hit_exact = True
            if d <= radius:
                hit_radius = True
            if abs(vx - rb_x) <= rb_tol and abs(vy - rb_y) <= rb_tol:
                hit_rb_tol = True
        if best_d is not None and best_p is not None:
            nearest.append((best_d, best_p, poly))

        if hit_exact:
            exact_hits.append(poly)
        if hit_radius:
            radius_hits.append(poly)
        if hit_rb_tol:
            rb_tol_hits.append(poly)
        if abs(bbox.xmax - rb_x) <= rb_tol and abs(bbox.ymin - rb_y) <= rb_tol:
            bbox_rb_hits.append(poly)

    nearest.sort(key=lambda x: x[0])
    return {
        "poly_count": len(polylines),
        "axis_count": sum(1 for p in polylines if p["is_axis"]),
        "exact_hits": exact_hits,
        "radius_hits": radius_hits,
        "rb_tol_hits": rb_tol_hits,
        "bbox_rb_hits": bbox_rb_hits,
        "nearest": nearest[:10],
        "rb_tol": rb_tol,
    }


def main() -> int:
    _add_backend_to_path()
    from src.cad.detection import (  # type: ignore
        AnchorCalibratedLocator,
        CandidateFinder,
        PaperFitter,
    )
    from src.cad.detection.anchor_first_locator import (
        AnchorFirstLocator,  # type: ignore
    )
    from src.config import load_spec  # type: ignore

    if len(sys.argv) < 2:
        print("Usage: python tools/_tmp/check_rb_lines.py <dxf-path>")
        return 2

    dxf_path = Path(sys.argv[1])
    if not dxf_path.exists():
        print(f"DXF not found: {dxf_path}")
        return 2

    spec = load_spec()
    locator = AnchorCalibratedLocator(spec, CandidateFinder(), PaperFitter())

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
        f"dxf={dxf_path.name} anchor_items={len(anchor_items)} rb_targets={len(rb_targets)}"
    )
    if not rb_targets:
        return 0

    layer = "0"
    for t in rb_targets:
        rb_x = float(t["rb_x"])
        rb_y = float(t["rb_y"])
        profile_id = t["profile_id"]
        scale = t["scale"]
        print(
            f"- rb profile={profile_id} scale={scale:.6f} rb=({_format_point((rb_x, rb_y))})"
        )
        report = _analyze_rb_for_layer(
            locator=locator,
            msp=msp,
            layer=layer,
            rb_x=rb_x,
            rb_y=rb_y,
            radius=0.1,
        )
        print(
            f"  layer={layer} lines={report['line_count']} rb_tol={report['rb_tol']} "
            f"max_w={report['max_w']:.3f} max_h={report['max_h']:.3f}"
        )
        exact_hits = report["exact_hits"]
        radius_hits = report["radius_hits"]
        print(f"  exact_hits={len(exact_hits)} radius_hits(<=0.1)={len(radius_hits)}")
        if exact_hits:
            for p1, p2, d in exact_hits[:4]:
                print(
                    f"    exact line: {_format_point(p1)} -> {_format_point(p2)} d={d:.6f}"
                )
        if not exact_hits and radius_hits:
            for p1, p2, d in radius_hits[:4]:
                print(
                    f"    radius line: {_format_point(p1)} -> {_format_point(p2)} d={d:.6f}"
                )
        if not exact_hits and not radius_hits:
            nearest = report["nearest"]
            if nearest:
                d, p1, p2 = nearest[0]
                print(
                    f"  nearest: d={d:.6f} line {_format_point(p1)} -> {_format_point(p2)}"
                )

        poly_report = _analyze_rb_polylines(
            locator=locator,
            msp=msp,
            layer=layer,
            rb_x=rb_x,
            rb_y=rb_y,
            radius=0.1,
        )
        print(
            f"  polylines={poly_report['poly_count']} axis_aligned={poly_report['axis_count']} "
            f"bbox_rb_hits={len(poly_report['bbox_rb_hits'])}"
        )
        print(
            f"  vertex_exact={len(poly_report['exact_hits'])} "
            f"vertex_radius(<=0.1)={len(poly_report['radius_hits'])} "
            f"vertex_rb_tol(<=1.0)={len(poly_report['rb_tol_hits'])}"
        )
        if poly_report["exact_hits"]:
            sample = poly_report["exact_hits"][0]
            bbox = sample["bbox"]
            print(
                "    sample_exact_bbox="
                f"({bbox.xmin:.3f},{bbox.ymin:.3f},{bbox.xmax:.3f},{bbox.ymax:.3f}) "
                f"type={sample['entity_type']} axis={sample['is_axis']}"
            )
        elif poly_report["radius_hits"]:
            sample = poly_report["radius_hits"][0]
            bbox = sample["bbox"]
            print(
                "    sample_radius_bbox="
                f"({bbox.xmin:.3f},{bbox.ymin:.3f},{bbox.xmax:.3f},{bbox.ymax:.3f}) "
                f"type={sample['entity_type']} axis={sample['is_axis']}"
            )
        else:
            nearest = poly_report["nearest"]
            if nearest:
                d, p, poly = nearest[0]
                bbox = poly["bbox"]
                print(
                    "  nearest_vertex: "
                    f"d={d:.6f} p={_format_point(p)} "
                    f"bbox=({bbox.xmin:.3f},{bbox.ymin:.3f},{bbox.xmax:.3f},{bbox.ymax:.3f}) "
                    f"type={poly['entity_type']} axis={poly['is_axis']}"
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
