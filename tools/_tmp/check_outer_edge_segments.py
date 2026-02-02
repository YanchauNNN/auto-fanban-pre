from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import ezdxf  # type: ignore


def _add_backend_to_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    backend_root = repo_root / "backend"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))


def _find_outer_bbox_in_layer(locator, msp, layer: str):
    best = None
    best_area = -1.0
    for entity_type in ("LWPOLYLINE", "POLYLINE"):
        for entity in locator._iter_layer_entities(msp, layer, entity_type):  # noqa: SLF001
            if not locator._is_polyline_closed(entity, entity_type):  # noqa: SLF001
                continue
            vertices = locator._polyline_vertices(entity, entity_type)  # noqa: SLF001
            if not vertices:
                continue
            bbox = locator._bbox_from_vertices(vertices)  # noqa: SLF001
            area = bbox.width * bbox.height
            if area > best_area:
                best = bbox
                best_area = area
    return best


def _iter_entities(msp):
    for ent in msp:
        tp = ent.dxftype()
        layer = getattr(ent.dxf, "layer", "0")
        if tp in {"LWPOLYLINE", "POLYLINE", "LINE"}:
            yield ent, layer, tp
            continue
        if tp == "INSERT":
            try:
                for ve in ent.virtual_entities():
                    vtp = ve.dxftype()
                    if vtp not in {"LWPOLYLINE", "POLYLINE", "LINE"}:
                        continue
                    try:
                        ve_layer = ve.dxf.layer
                    except Exception:
                        ve_layer = "0"
                    effective_layer = layer if ve_layer == "0" else ve_layer
                    yield ve, effective_layer, vtp
            except Exception:
                continue


def _polyline_vertices(entity, tp: str) -> list[tuple[float, float]]:
    vertices: list[tuple[float, float]] = []
    if tp == "LWPOLYLINE":
        for p in entity.get_points():
            vertices.append((float(p[0]), float(p[1])))
    elif tp == "POLYLINE":
        for v in entity.vertices:
            loc = v.dxf.location
            vertices.append((float(loc.x), float(loc.y)))
    return vertices


def _overlap_len(a0: float, a1: float, b0: float, b1: float) -> float:
    lo = max(min(a0, a1), min(b0, b1))
    hi = min(max(a0, a1), max(b0, b1))
    return max(0.0, hi - lo)


def _segment_from_vertices(vertices, tol: float):
    xs = [p[0] for p in vertices]
    ys = [p[1] for p in vertices]
    if not xs or not ys:
        return None
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    dx = max_x - min_x
    dy = max_y - min_y
    if dy <= tol and dx > tol:
        return {
            "orientation": "H",
            "coord": (min_y + max_y) / 2.0,
            "a0": min_x,
            "a1": max_x,
        }
    if dx <= tol and dy > tol:
        return {
            "orientation": "V",
            "coord": (min_x + max_x) / 2.0,
            "a0": min_y,
            "a1": max_y,
        }
    return None


def _segment_from_line(p1, p2, tol: float):
    x1, y1 = p1
    x2, y2 = p2
    dx = abs(x2 - x1)
    dy = abs(y2 - y1)
    if dy <= tol and dx > tol:
        return {
            "orientation": "H",
            "coord": (y1 + y2) / 2.0,
            "a0": min(x1, x2),
            "a1": max(x1, x2),
        }
    if dx <= tol and dy > tol:
        return {
            "orientation": "V",
            "coord": (x1 + x2) / 2.0,
            "a0": min(y1, y2),
            "a1": max(y1, y2),
        }
    return None


def _edge_name(orientation: str, coord: float, outer, tol: float) -> str | None:
    if orientation == "H":
        if abs(coord - outer.ymin) <= tol:
            return "bottom"
        if abs(coord - outer.ymax) <= tol:
            return "top"
    if orientation == "V":
        if abs(coord - outer.xmin) <= tol:
            return "left"
        if abs(coord - outer.xmax) <= tol:
            return "right"
    return None


def _edge_length(outer, edge: str) -> float:
    if edge in {"bottom", "top"}:
        return max(1e-9, outer.xmax - outer.xmin)
    return max(1e-9, outer.ymax - outer.ymin)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find open polylines/lines overlapping outer frame edges."
    )
    parser.add_argument(
        "--dxf",
        default="test/dxf-biaozhun/2016-A0.dxf",
        help="DXF文件路径",
    )
    parser.add_argument(
        "--outer-layer",
        default="外层矩形",
        help='外框图层名（默认："外层矩形"）',
    )
    parser.add_argument("--tol", type=float, default=1.0, help="坐标容差")
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=0.2,
        help="最低覆盖比例（用于过滤输出）",
    )
    args = parser.parse_args()

    _add_backend_to_path()
    from src.cad.detection import (  # type: ignore
        AnchorCalibratedLocator,
        CandidateFinder,
        PaperFitter,
    )
    from src.config import load_spec  # type: ignore

    locator = AnchorCalibratedLocator(load_spec(), CandidateFinder(), PaperFitter())
    dxf_path = Path(args.dxf)
    if not dxf_path.exists():
        print(f"DXF not found: {dxf_path}")
        return 2

    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()
    outer = _find_outer_bbox_in_layer(locator, msp, args.outer_layer)
    if outer is None:
        print(f"{dxf_path.name}: ERROR 未找到外层矩形图层外框")
        return 1

    print(
        f"outer_bbox=({outer.xmin:.3f},{outer.ymin:.3f},{outer.xmax:.3f},{outer.ymax:.3f})"
    )

    per_edge: dict[str, list[dict[str, object]]] = defaultdict(list)

    for ent, layer, tp in _iter_entities(msp):
        if tp in {"LWPOLYLINE", "POLYLINE"}:
            vertices = _polyline_vertices(ent, tp)
            seg = _segment_from_vertices(vertices, args.tol)
            if not seg:
                continue
            edge = _edge_name(seg["orientation"], seg["coord"], outer, args.tol)
            if not edge:
                continue
            length = _edge_length(outer, edge)
            if seg["orientation"] == "H":
                overlap = _overlap_len(seg["a0"], seg["a1"], outer.xmin, outer.xmax)
            else:
                overlap = _overlap_len(seg["a0"], seg["a1"], outer.ymin, outer.ymax)
            coverage = overlap / length
            if coverage < args.min_coverage:
                continue
            per_edge[edge].append(
                {
                    "layer": layer,
                    "type": tp,
                    "coverage": coverage,
                    "coord": seg["coord"],
                    "a0": seg["a0"],
                    "a1": seg["a1"],
                }
            )
        elif tp == "LINE":
            start = ent.dxf.start
            end = ent.dxf.end
            seg = _segment_from_line(
                (float(start.x), float(start.y)),
                (float(end.x), float(end.y)),
                args.tol,
            )
            if not seg:
                continue
            edge = _edge_name(seg["orientation"], seg["coord"], outer, args.tol)
            if not edge:
                continue
            length = _edge_length(outer, edge)
            if seg["orientation"] == "H":
                overlap = _overlap_len(seg["a0"], seg["a1"], outer.xmin, outer.xmax)
            else:
                overlap = _overlap_len(seg["a0"], seg["a1"], outer.ymin, outer.ymax)
            coverage = overlap / length
            if coverage < args.min_coverage:
                continue
            per_edge[edge].append(
                {
                    "layer": layer,
                    "type": tp,
                    "coverage": coverage,
                    "coord": seg["coord"],
                    "a0": seg["a0"],
                    "a1": seg["a1"],
                }
            )

    for edge in ("bottom", "top", "left", "right"):
        items = per_edge.get(edge, [])
        items.sort(key=lambda x: (-x["coverage"], str(x["layer"])))
        print(f"\n[{edge}] candidates={len(items)}")
        for item in items[:10]:
            print(
                "  "
                f"layer={item['layer']} type={item['type']} cov={item['coverage']:.3f} "
                f"coord={item['coord']:.3f} span=({item['a0']:.3f},{item['a1']:.3f})"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
