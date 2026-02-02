from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

import ezdxf  # type: ignore


def _add_backend_to_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    backend_root = repo_root / "backend"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))


def _safe_stat(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "median": None, "min": None, "max": None}
    return {
        "mean": sum(values) / len(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


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


def _iter_layers(doc) -> list[str]:
    layers = []
    for layer in doc.layers:
        try:
            name = layer.dxf.name
        except Exception:
            continue
        if name:
            layers.append(str(name))
    return layers


def _collect_polylines(locator, msp, layer: str) -> list[dict[str, object]]:
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
                    "bbox": bbox,
                    "is_axis": is_axis,
                }
            )
    return polylines


def _collect_lines(locator, msp, layer: str):
    lines: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for entity in locator._iter_layer_entities(msp, layer, "LINE"):  # noqa: SLF001
        start = entity.dxf.start
        end = entity.dxf.end
        p1 = (float(start.x), float(start.y))
        p2 = (float(end.x), float(end.y))
        lines.append((p1, p2))
    return lines


def _overlap_len(a0: float, a1: float, b0: float, b1: float) -> float:
    lo = max(min(a0, a1), min(b0, b1))
    hi = min(max(a0, a1), max(b0, b1))
    return max(0.0, hi - lo)


def _line_edge_coverage(lines, outer, tol: float) -> dict[str, float]:
    xmin, ymin, xmax, ymax = outer.xmin, outer.ymin, outer.xmax, outer.ymax
    width = max(1e-9, xmax - xmin)
    height = max(1e-9, ymax - ymin)
    cov = {"bottom": 0.0, "top": 0.0, "left": 0.0, "right": 0.0}

    for (x1, y1), (x2, y2) in lines:
        dx = x2 - x1
        dy = y2 - y1
        if abs(dy) <= tol:
            y = (y1 + y2) / 2.0
            overlap = _overlap_len(x1, x2, xmin, xmax)
            if abs(y - ymin) <= tol and overlap > 0:
                cov["bottom"] += overlap
            elif abs(y - ymax) <= tol and overlap > 0:
                cov["top"] += overlap
        elif abs(dx) <= tol:
            x = (x1 + x2) / 2.0
            overlap = _overlap_len(y1, y2, ymin, ymax)
            if abs(x - xmin) <= tol and overlap > 0:
                cov["left"] += overlap
            elif abs(x - xmax) <= tol and overlap > 0:
                cov["right"] += overlap

    return {
        "bottom": cov["bottom"] / width,
        "top": cov["top"] / width,
        "left": cov["left"] / height,
        "right": cov["right"] / height,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find layers whose geometry overlaps outer frame."
    )
    parser.add_argument(
        "--dxf-dir",
        default="test/dxf-biaozhun",
        help="DXF目录（默认：test/dxf-biaozhun）",
    )
    parser.add_argument(
        "--outer-layer",
        default="外层矩形",
        help='外框图层名（默认："外层矩形"）',
    )
    parser.add_argument("--tol", type=float, default=1.0, help="坐标容差")
    parser.add_argument(
        "--edge-cover",
        type=float,
        default=0.9,
        help="边覆盖比例阈值（用于LINE矩形判定）",
    )
    args = parser.parse_args()

    _add_backend_to_path()
    from src.cad.detection import (  # type: ignore
        AnchorCalibratedLocator,
        CandidateFinder,
        PaperFitter,
    )
    from src.config import load_spec  # type: ignore

    locator = AnchorCalibratedLocator(load_spec(), CandidateFinder(), PaperFitter())  # type: ignore

    dxf_dir = Path(args.dxf_dir)
    dxfs = sorted(dxf_dir.glob("*.dxf"))
    if not dxfs:
        print("未找到DXF文件")
        return 1

    poly_layer_counts: dict[str, int] = {}
    line_layer_counts: dict[str, int] = {}
    poly_offsets: dict[str, list[tuple[float, float, float, float]]] = {}

    for dxf_path in dxfs:
        doc = ezdxf.readfile(str(dxf_path))
        msp = doc.modelspace()
        outer = _find_outer_bbox_in_layer(locator, msp, args.outer_layer)
        if outer is None:
            print(f"{dxf_path.name}: ERROR 未找到外层矩形图层外框")
            continue

        layers = _iter_layers(doc)
        matched_poly_layers: list[str] = []
        matched_line_layers: list[str] = []

        for layer in layers:
            if layer == args.outer_layer:
                continue

            polylines = _collect_polylines(locator, msp, layer)
            for poly in polylines:
                if not poly["is_axis"]:
                    continue
                bbox = poly["bbox"]
                if (
                    abs(bbox.xmin - outer.xmin) <= args.tol
                    and abs(bbox.ymin - outer.ymin) <= args.tol
                    and abs(bbox.xmax - outer.xmax) <= args.tol
                    and abs(bbox.ymax - outer.ymax) <= args.tol
                ):
                    matched_poly_layers.append(layer)
                    poly_layer_counts[layer] = poly_layer_counts.get(layer, 0) + 1
                    offsets = (
                        bbox.xmin - outer.xmin,
                        bbox.ymin - outer.ymin,
                        bbox.xmax - outer.xmax,
                        bbox.ymax - outer.ymax,
                    )
                    poly_offsets.setdefault(layer, []).append(offsets)
                    break

            lines = _collect_lines(locator, msp, layer)
            if lines:
                coverage = _line_edge_coverage(lines, outer, args.tol)
                if (
                    coverage["bottom"] >= args.edge_cover
                    and coverage["top"] >= args.edge_cover
                    and coverage["left"] >= args.edge_cover
                    and coverage["right"] >= args.edge_cover
                ):
                    matched_line_layers.append(layer)
                    line_layer_counts[layer] = line_layer_counts.get(layer, 0) + 1

        poly_layers_str = ", ".join(sorted(set(matched_poly_layers))) or "-"
        line_layers_str = ", ".join(sorted(set(matched_line_layers))) or "-"
        print(
            f"{dxf_path.name}: poly_layers={poly_layers_str} line_layers={line_layers_str}"
        )

    print("\n== 汇总 ==")
    if not poly_layer_counts and not line_layer_counts:
        print("未发现与外层矩形重合的其它图层")
        return 0

    if poly_layer_counts:
        print("[Polyline]")
        for layer, count in sorted(
            poly_layer_counts.items(), key=lambda x: (-x[1], x[0])
        ):
            offsets = poly_offsets.get(layer, [])
            xs = [o[0] for o in offsets]
            ys = [o[1] for o in offsets]
            xe = [o[2] for o in offsets]
            ye = [o[3] for o in offsets]
            print(
                f"  {layer}: files={count} "
                f"dxmin={_safe_stat(xs)} dymin={_safe_stat(ys)} "
                f"dxmax={_safe_stat(xe)} dymax={_safe_stat(ye)}"
            )
    if line_layer_counts:
        print("[Line]")
        for layer, count in sorted(
            line_layer_counts.items(), key=lambda x: (-x[1], x[0])
        ):
            print(f"  {layer}: files={count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
