from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

import ezdxf  # type: ignore


def _add_backend_to_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    backend_root = repo_root / "backend"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))


def _collect_segments(
    locator, msp, layers: list[str]
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for layer in layers:
        for entity_type in ("LINE", "LWPOLYLINE", "POLYLINE"):
            for entity in locator._iter_layer_entities(msp, layer, entity_type):  # noqa: SLF001
                if entity_type == "LINE":
                    start = entity.dxf.start
                    end = entity.dxf.end
                    p1 = (float(start.x), float(start.y))
                    p2 = (float(end.x), float(end.y))
                    if p1 != p2:
                        segments.append((p1, p2))
                    continue
                vertices = locator._polyline_vertices(entity, entity_type)  # noqa: SLF001
                if len(vertices) < 2:
                    continue
                is_closed = locator._is_polyline_closed(entity, entity_type)  # noqa: SLF001
                for idx in range(len(vertices) - 1):
                    p1 = vertices[idx]
                    p2 = vertices[idx + 1]
                    if p1 != p2:
                        segments.append((p1, p2))
                if is_closed and vertices[0] != vertices[-1]:
                    segments.append((vertices[-1], vertices[0]))
    return segments


def _segments_to_axis(
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
    *,
    coord_tol: float,
    sin_tol: float,
) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]]:
    horizontal: list[tuple[float, float, float]] = []
    vertical: list[tuple[float, float, float]] = []
    for (x1, y1), (x2, y2) in segments:
        dx = x2 - x1
        dy = y2 - y1
        length = (dx * dx + dy * dy) ** 0.5
        if length <= 0:
            continue
        if abs(dy) <= coord_tol or abs(dy) / length <= sin_tol:
            y = (y1 + y2) / 2.0
            horizontal.append((y, min(x1, x2), max(x1, x2)))
        elif abs(dx) <= coord_tol or abs(dx) / length <= sin_tol:
            x = (x1 + x2) / 2.0
            vertical.append((x, min(y1, y2), max(y1, y2)))
    return horizontal, vertical


def _rebuild_outer_bbox(
    finder, segments: list[tuple[tuple[float, float], tuple[float, float]]]
):
    horizontal, vertical = _segments_to_axis(
        segments,
        coord_tol=finder.coord_tol,
        sin_tol=finder._sin_tol,  # noqa: SLF001
    )
    h_segments = finder._cluster_segments(horizontal)  # noqa: SLF001
    v_segments = finder._cluster_segments(vertical)  # noqa: SLF001
    if not h_segments or not v_segments:
        return None
    ys = sorted(h_segments.keys())
    xs = sorted(v_segments.keys())
    best = None
    best_area = -1.0
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
                    area = (x2 - x1) * (y2 - y1)
                    if area > best_area:
                        best_area = area
                        best = (x1, y1, x2, y2)
    return best


def _expected_profile_by_name(name: str) -> str | None:
    upper = name.upper()
    if "A3" in upper or "A4" in upper:
        return "SMALL5"
    if any(tag in upper for tag in ("A0", "A1", "A2")):
        return "BASE10"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check RB offset for specific files (project-aware)."
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="DXF文件路径列表",
    )
    parser.add_argument(
        "--project-no",
        default="1818",
        help="项目号（用于字高/偏移覆盖）",
    )
    parser.add_argument(
        "--layers",
        default="",
        help="可选：覆盖扫描图层（逗号分隔）",
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
    outer_cfg = spec.titleblock_extract.get("outer_frame", {})
    if args.layers:
        layers = [v.strip() for v in args.layers.split(",") if v.strip()]
    else:
        layers = outer_cfg.get("layer_priority", {}).get("layers") or []
        if not layers:
            layers = ["_TSZ-PLOT_MARK", "TK", "图框", "ttkk", "0"]

    acceptance_cfg = outer_cfg.get("acceptance", {})
    orth_tol = float(acceptance_cfg.get("orthogonality_tol_deg", 1.0))
    base_profile = spec.get_roi_profile("BASE10")
    coord_tol = base_profile.tolerance if base_profile else 0.5

    finder = CandidateFinder(
        min_dim=100.0, coord_tol=coord_tol, orthogonality_tol_deg=orth_tol
    )
    locator = AnchorCalibratedLocator(
        spec, finder, PaperFitter(), project_no=args.project_no
    )

    anchor_cfg = spec.titleblock_extract.get("anchor", {})
    search_texts = anchor_cfg.get("search_text", [])
    if isinstance(search_texts, str):
        search_texts = [search_texts]
    calibration = anchor_cfg.get("calibration", {})

    for file_path in args.files:
        dxf_path = Path(file_path)
        if not dxf_path.exists():
            print(f"{dxf_path.name}: ERROR 文件不存在")
            continue
        doc = ezdxf.readfile(str(dxf_path))
        msp = doc.modelspace()
        segments = _collect_segments(locator, msp, layers)
        if not segments:
            print(f"{dxf_path.name}: ERROR 未找到图层内线段")
            continue
        outer = _rebuild_outer_bbox(finder, segments)
        if not outer:
            print(f"{dxf_path.name}: ERROR 无法从线段重建外框")
            continue
        xmin, ymin, xmax, ymax = outer
        outer_rb = (xmax, ymin)

        text_items = list(AnchorFirstLocator._iter_text_items(msp))  # noqa: SLF001
        anchor_items = [
            t
            for t in text_items
            if locator._match_any_text(t.text, search_texts)  # noqa: SLF001
        ]
        if not anchor_items:
            print(f"{dxf_path.name}: ERROR 未找到锚点文本")
            continue

        expected_profile = _expected_profile_by_name(dxf_path.stem)
        if not expected_profile:
            print(f"{dxf_path.name}: ERROR 无法识别图幅类型")
            continue
        calib = calibration.get(expected_profile)
        if not isinstance(calib, dict):
            print(f"{dxf_path.name}: ERROR 未找到{expected_profile}校准配置")
            continue

        best = None
        for item in anchor_items:
            candidates = locator._iter_scale_candidates(item, calib)  # noqa: SLF001
            if not candidates:
                continue
            candidate = candidates[0]
            scale = candidate["scale"]
            rb_x, rb_y = locator._outer_rb_from_anchor(  # noqa: SLF001
                item, scale, calib, candidate["use_project_override"]
            )
            dx = rb_x - outer_rb[0]
            dy = rb_y - outer_rb[1]
            abs_max = max(abs(dx), abs(dy))
            if best is None or abs_max < best["abs_max"]:
                best = {
                    "rb": (rb_x, rb_y),
                    "dx": dx,
                    "dy": dy,
                    "abs_max": abs_max,
                    "scale": scale,
                }

        if not best:
            print(f"{dxf_path.name}: ERROR 无有效锚点/字高")
            continue

        print(
            f"{dxf_path.name}: profile={expected_profile} scale={best['scale']:.6f} "
            f"outer_rb=({outer_rb[0]:.3f},{outer_rb[1]:.3f}) "
            f"pred_rb=({best['rb'][0]:.3f},{best['rb'][1]:.3f}) "
            f"delta=({best['dx']:.3f},{best['dy']:.3f}) abs_max={best['abs_max']:.3f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
