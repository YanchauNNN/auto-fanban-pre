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


def _infer_anchor_rb_offset(
    locator, item, calib: dict, outer_xmax: float, outer_ymin: float
):
    scales = locator._iter_scales_from_text(item, calib)  # noqa: SLF001
    if not scales:
        return None
    scale = scales[0]
    ref_x, ref_y = locator._anchor_ref_point(item)  # noqa: SLF001
    ref_cfg = calib.get("text_ref_in_anchor_roi_1to1", {})
    dx_right = float(ref_cfg.get("dx_right", 0.0))
    dy_bottom = float(ref_cfg.get("dy_bottom", 0.0))
    roi_xmax = ref_x + dx_right * scale
    roi_ymin = ref_y - dy_bottom * scale
    inferred_dx_right = (outer_xmax - roi_xmax) / scale
    inferred_dy_bottom = (roi_ymin - outer_ymin) / scale
    return inferred_dx_right, inferred_dy_bottom, scale


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Infer anchor RB offset by project using open lines."
    )
    parser.add_argument(
        "--dxf-dir",
        default="test/dxf-1818",
        help="DXF目录（默认：test/dxf-1818）",
    )
    parser.add_argument(
        "--project-no",
        default="1818",
        help="项目号（用于字高覆盖）",
    )
    args = parser.parse_args()

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
    from src.models import BBox  # type: ignore

    spec = load_spec()
    outer_cfg = spec.titleblock_extract.get("outer_frame", {})
    layers = outer_cfg.get("layer_priority", {}).get("layers") or []
    if not layers:
        layers = ["_TSZ-PLOT_MARK", "TK", "图框", "ttkk", "0"]

    acceptance_cfg = outer_cfg.get("acceptance", {})
    orth_tol = float(acceptance_cfg.get("orthogonality_tol_deg", 1.0))
    base_profile = spec.get_roi_profile("BASE10")
    coord_tol = base_profile.tolerance if base_profile else 0.5

    scale_fit_cfg = spec.titleblock_extract.get("scale_fit", {})
    paper_fitter = PaperFitter(
        allow_rotation=bool(scale_fit_cfg.get("allow_rotation", True)),
        uniform_scale_required=bool(scale_fit_cfg.get("uniform_scale_required", True)),
        uniform_scale_tol=float(scale_fit_cfg.get("uniform_scale_tol", 0.02)),
        error_metric=str(scale_fit_cfg.get("fit_error_metric", "max_rel_error(W,H)")),
    )
    finder = CandidateFinder(
        min_dim=100.0, coord_tol=coord_tol, orthogonality_tol_deg=orth_tol
    )
    locator = AnchorCalibratedLocator(
        spec, finder, paper_fitter, project_no=args.project_no
    )
    paper_variants = spec.get_paper_variants()

    anchor_cfg = spec.titleblock_extract.get("anchor", {})
    search_texts = anchor_cfg.get("search_text", [])
    if isinstance(search_texts, str):
        search_texts = [search_texts]

    calibration = anchor_cfg.get("calibration", {})
    profiles = [
        k
        for k, v in calibration.items()
        if k != "reference_point" and isinstance(v, dict)
    ]

    dxf_dir = Path(args.dxf_dir)
    dxfs = sorted(dxf_dir.glob("*.dxf"))
    if not dxfs:
        print("未找到DXF文件")
        return 1

    profile_stats: dict[str, dict[str, list[float]]] = {
        p: {"dx": [], "dy": [], "delta_x": [], "delta_y": []} for p in profiles
    }

    print(f"dxf_dir={dxf_dir} project_no={args.project_no} layers={layers}")

    for dxf_path in dxfs:
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
        bbox = BBox(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax)
        fit = paper_fitter.fit(bbox, paper_variants)
        expected_profile = fit[3] if fit else None
        name_upper = dxf_path.stem.upper()
        if "A3" in name_upper or "A4" in name_upper:
            expected_profile = "SMALL5"
        elif any(tag in name_upper for tag in ("A0", "A1", "A2")):
            expected_profile = "BASE10"

        text_items = list(AnchorFirstLocator._iter_text_items(msp))  # noqa: SLF001
        anchor_items = [
            t
            for t in text_items
            if locator._match_any_text(t.text, search_texts)  # noqa: SLF001
        ]
        if not anchor_items:
            print(f"{dxf_path.name}: ERROR 未找到锚点文本")
            continue

        print(
            f"{dxf_path.name}: outer_rb=({xmax:.3f},{ymin:.3f}) "
            f"anchors={len(anchor_items)} profile={expected_profile}"
        )

        for profile_id in profiles:
            if expected_profile and profile_id != expected_profile:
                continue
            calib = calibration.get(profile_id)
            if not isinstance(calib, dict):
                continue
            current_rb = calib.get("anchor_roi_rb_offset_1to1", [0.0, 0.0, 0.0, 0.0])
            current_dx = float(current_rb[0])
            current_dy = float(current_rb[2])

            best = None
            for item in anchor_items:
                inferred = _infer_anchor_rb_offset(
                    locator, item, calib, outer_xmax=xmax, outer_ymin=ymin
                )
                if inferred is None:
                    continue
                inferred_dx, inferred_dy, scale = inferred
                pred_x = xmax - (inferred_dx - current_dx) * scale
                pred_y = ymin + (inferred_dy - current_dy) * scale
                dx = pred_x - xmax
                dy = pred_y - ymin
                abs_max = max(abs(dx), abs(dy))
                if best is None or abs_max < best["abs_max"]:
                    best = {
                        "inferred_dx": inferred_dx,
                        "inferred_dy": inferred_dy,
                        "scale": scale,
                        "dx": dx,
                        "dy": dy,
                        "abs_max": abs_max,
                    }

            if best is None:
                print(f"  {profile_id}: 无可用锚点/字高")
                continue

            delta_x = best["inferred_dx"] - current_dx
            delta_y = best["inferred_dy"] - current_dy

            profile_stats[profile_id]["dx"].append(best["inferred_dx"])
            profile_stats[profile_id]["dy"].append(best["inferred_dy"])
            profile_stats[profile_id]["delta_x"].append(delta_x)
            profile_stats[profile_id]["delta_y"].append(delta_y)

            print(
                f"  {profile_id}: inferred_dx/dy=({best['inferred_dx']:.3f},{best['inferred_dy']:.3f}) "
                f"delta_dx/dy=({delta_x:.3f},{delta_y:.3f}) scale={best['scale']:.6f}"
            )

    print("\n== 汇总统计 ==")
    for profile_id in profiles:
        print(f"[{profile_id}]")
        dx_stats = _safe_stat(profile_stats[profile_id]["dx"])
        dy_stats = _safe_stat(profile_stats[profile_id]["dy"])
        delta_x_stats = _safe_stat(profile_stats[profile_id]["delta_x"])
        delta_y_stats = _safe_stat(profile_stats[profile_id]["delta_y"])
        print(
            "  inferred_dx_right: "
            f"mean={dx_stats['mean']}, median={dx_stats['median']}, "
            f"min={dx_stats['min']}, max={dx_stats['max']}"
        )
        print(
            "  inferred_dy_bottom: "
            f"mean={dy_stats['mean']}, median={dy_stats['median']}, "
            f"min={dy_stats['min']}, max={dy_stats['max']}"
        )
        print(
            "  delta_dx_right: "
            f"mean={delta_x_stats['mean']}, median={delta_x_stats['median']}, "
            f"min={delta_x_stats['min']}, max={delta_x_stats['max']}"
        )
        print(
            "  delta_dy_bottom: "
            f"mean={delta_y_stats['mean']}, median={delta_y_stats['median']}, "
            f"min={delta_y_stats['min']}, max={delta_y_stats['max']}"
        )

        current = calibration.get(profile_id, {}).get("anchor_roi_rb_offset_1to1", [])
        if (
            len(current) == 4
            and delta_x_stats["mean"] is not None
            and delta_y_stats["mean"] is not None
        ):
            cur_dx = float(current[0])
            cur_dy = float(current[2])
            shift_x = delta_x_stats["mean"] or 0.0
            shift_y = delta_y_stats["mean"] or 0.0
            suggested = [
                round(cur_dx + shift_x, 4),
                round(float(current[1]) + shift_x, 4),
                round(cur_dy + shift_y, 4),
                round(float(current[3]) + shift_y, 4),
            ]
            print(f"  suggested_anchor_roi_rb_offset_1to1: {suggested}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
