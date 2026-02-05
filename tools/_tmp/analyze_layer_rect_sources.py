from __future__ import annotations

import argparse
import sys
from pathlib import Path

import ezdxf  # type: ignore


def _add_backend_to_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    backend_root = repo_root / "backend"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze rectangle sources per layer in layer_priority."
    )
    parser.add_argument("--dxf", required=True, help="DXF路径")
    parser.add_argument("--project-no", default="", help="项目号")
    parser.add_argument("--max-segments", type=int, default=5000, help="线段上限")
    parser.add_argument("--max-combos", type=int, default=50000, help="坐标组合上限")
    args = parser.parse_args()

    _add_backend_to_path()
    from src.cad.detection import (  # type: ignore
        AnchorCalibratedLocator,
        CandidateFinder,
        PaperFitter,
    )
    from src.config import load_spec  # type: ignore

    spec = load_spec()
    finder = CandidateFinder()
    locator = AnchorCalibratedLocator(
        spec, finder, PaperFitter(), project_no=args.project_no or None
    )

    dxf_path = Path(args.dxf)
    if not dxf_path.exists():
        print("ERROR: DXF文件不存在")
        return 2
    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()

    print(f"{dxf_path.name}: layers={locator.layer_order}")
    for layer in locator.layer_order:
        closed_count = 0
        open_axis4 = 0
        for entity_type in ("LWPOLYLINE", "POLYLINE"):
            for entity in locator._iter_layer_entities(msp, layer, entity_type):  # noqa: SLF001
                vertices = locator._polyline_vertices(entity, entity_type)  # noqa: SLF001
                if not vertices:
                    continue
                is_closed = locator._is_polyline_closed(entity, entity_type)  # noqa: SLF001
                if is_closed and locator._is_axis_aligned(vertices):  # noqa: SLF001
                    closed_count += 1
                if (
                    (not is_closed)
                    and len(vertices) == 4
                    and locator._is_axis_aligned(vertices)
                ):  # noqa: SLF001
                    open_axis4 += 1

        segments = locator._query_lines(msp, layer)  # noqa: SLF001
        horizontal = []
        vertical = []
        if len(segments) > args.max_segments:
            print(
                f"  layer={layer} closed_poly={closed_count} open_axis4={open_axis4} "
                f"line_rects=SKIP lines={len(segments)}"
            )
            continue
        for (x1, y1), (x2, y2) in segments:
            dx = x2 - x1
            dy = y2 - y1
            length = (dx * dx + dy * dy) ** 0.5
            if length <= 0:
                continue
            if abs(dy) <= finder.coord_tol or abs(dy) / length <= finder._sin_tol:  # noqa: SLF001
                y = (y1 + y2) / 2.0
                horizontal.append((y, min(x1, x2), max(x1, x2)))
            elif abs(dx) <= finder.coord_tol or abs(dx) / length <= finder._sin_tol:  # noqa: SLF001
                x = (x1 + x2) / 2.0
                vertical.append((x, min(y1, y2), max(y1, y2)))

        h_segments = finder._cluster_segments(horizontal)  # noqa: SLF001
        v_segments = finder._cluster_segments(vertical)  # noqa: SLF001
        rects = 0
        ys = sorted(h_segments.keys())
        xs = sorted(v_segments.keys())
        if len(xs) * len(ys) > args.max_combos:
            print(
                f"  layer={layer} closed_poly={closed_count} open_axis4={open_axis4} "
                f"line_rects=SKIP lines={len(segments)}"
            )
            continue
        for yi, y1 in enumerate(ys):
            for y2 in ys[yi + 1 :]:
                if (y2 - y1) < finder.min_dim:
                    continue
                for xi, x1 in enumerate(xs):
                    for x2 in xs[xi + 1 :]:
                        if (x2 - x1) < finder.min_dim:
                            continue
                        if not finder._has_edge(h_segments[y1], x1, x2):  # noqa: SLF001
                            continue
                        if not finder._has_edge(h_segments[y2], x1, x2):  # noqa: SLF001
                            continue
                        if not finder._has_edge(v_segments[x1], y1, y2):  # noqa: SLF001
                            continue
                        if not finder._has_edge(v_segments[x2], y1, y2):  # noqa: SLF001
                            continue
                        rects += 1

        print(
            f"  layer={layer} closed_poly={closed_count} "
            f"open_axis4={open_axis4} line_rects={rects} lines={len(segments)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
