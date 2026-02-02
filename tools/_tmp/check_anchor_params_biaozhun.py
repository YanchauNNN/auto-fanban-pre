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


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _safe_stat(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "median": None, "min": None, "max": None}
    return {
        "mean": _mean(values),
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


def _scale_from_text(locator, item, calib: dict) -> float | None:
    text_h = item.text_height
    if text_h is None and item.bbox is not None:
        text_h = item.bbox.height / 1.2
    if text_h is None:
        return None
    base_h = calib.get("text_height_1to1_mm")
    if not base_h:
        return None
    return float(text_h) / float(base_h)


def _ref_point(locator, item) -> tuple[float, float]:
    return locator._anchor_ref_point(item)  # noqa: SLF001


def _predict_outer_rb(
    *,
    locator,
    item,
    calib: dict,
) -> tuple[float, float, float] | None:
    scale = _scale_from_text(locator, item, calib)
    if scale is None:
        return None
    ref_x, ref_y = _ref_point(locator, item)
    ref_cfg = calib.get("text_ref_in_anchor_roi_1to1", {})
    dx_right = float(ref_cfg.get("dx_right", 0.0))
    dy_bottom = float(ref_cfg.get("dy_bottom", 0.0))
    roi_xmax = ref_x + dx_right * scale
    roi_ymin = ref_y - dy_bottom * scale

    anchor_rb = calib.get("anchor_roi_rb_offset_1to1", [0.0, 0.0, 0.0, 0.0])
    outer_xmax = roi_xmax + float(anchor_rb[0]) * scale
    outer_ymin = roi_ymin - float(anchor_rb[2]) * scale
    return outer_xmax, outer_ymin, scale


def _infer_anchor_rb_offset(
    *,
    locator,
    item,
    calib: dict,
    outer_xmax: float,
    outer_ymin: float,
) -> tuple[float, float] | None:
    scale = _scale_from_text(locator, item, calib)
    if scale is None:
        return None
    ref_x, ref_y = _ref_point(locator, item)
    ref_cfg = calib.get("text_ref_in_anchor_roi_1to1", {})
    dx_right = float(ref_cfg.get("dx_right", 0.0))
    dy_bottom = float(ref_cfg.get("dy_bottom", 0.0))
    roi_xmax = ref_x + dx_right * scale
    roi_ymin = ref_y - dy_bottom * scale
    inferred_dx_right = (outer_xmax - roi_xmax) / scale
    inferred_dy_bottom = (roi_ymin - outer_ymin) / scale
    return inferred_dx_right, inferred_dy_bottom


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check anchor RB params using dxf-biaozhun folder."
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

    spec = load_spec()
    locator = AnchorCalibratedLocator(spec, CandidateFinder(), PaperFitter())

    anchor_cfg = spec.titleblock_extract.get("anchor", {})
    texts = anchor_cfg.get("search_text", [])
    if isinstance(texts, str):
        texts = [texts]
    search_texts = [t for t in texts if t]
    calibration = anchor_cfg.get("calibration", {})
    profiles = [
        k
        for k, v in calibration.items()
        if k != "reference_point" and isinstance(v, dict)
    ]
    if not profiles:
        print("未找到校准档")
        return 1

    dxf_dir = Path(args.dxf_dir)
    dxfs = sorted(dxf_dir.glob("*.dxf"))
    if not dxfs:
        print("未找到DXF文件")
        return 1

    profile_stats: dict[str, dict[str, list[float]]] = {
        p: {"dx": [], "dy": [], "delta_x": [], "delta_y": []} for p in profiles
    }

    print(f"dxf_dir={dxf_dir} outer_layer={args.outer_layer} profiles={profiles}")

    for dxf_path in dxfs:
        doc = ezdxf.readfile(str(dxf_path))
        msp = doc.modelspace()
        outer_bbox = _find_outer_bbox_in_layer(locator, msp, args.outer_layer)
        if outer_bbox is None:
            print(f"{dxf_path.name}: ERROR 未找到外层矩形图层外框")
            continue
        outer_xmax = float(outer_bbox.xmax)
        outer_ymin = float(outer_bbox.ymin)

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
            f"{dxf_path.name}: outer_rb=({outer_xmax:.3f},{outer_ymin:.3f}) "
            f"anchors={len(anchor_items)}"
        )

        for profile_id in profiles:
            calib = calibration.get(profile_id)
            if not isinstance(calib, dict):
                continue
            current_rb = calib.get("anchor_roi_rb_offset_1to1", [0.0, 0.0, 0.0, 0.0])
            current_dx = float(current_rb[0])
            current_dy = float(current_rb[2])

            best = None
            for item in anchor_items:
                pred = _predict_outer_rb(locator=locator, item=item, calib=calib)
                if pred is None:
                    continue
                pred_x, pred_y, scale = pred
                dx = pred_x - outer_xmax
                dy = pred_y - outer_ymin
                abs_max = max(abs(dx), abs(dy))
                if best is None or abs_max < best["abs_max"]:
                    best = {
                        "item": item,
                        "pred_x": pred_x,
                        "pred_y": pred_y,
                        "scale": scale,
                        "dx": dx,
                        "dy": dy,
                        "abs_max": abs_max,
                    }

            if best is None:
                print(f"  {profile_id}: 无可用锚点/字高")
                continue

            inferred = _infer_anchor_rb_offset(
                locator=locator,
                item=best["item"],
                calib=calib,
                outer_xmax=outer_xmax,
                outer_ymin=outer_ymin,
            )
            if inferred is None:
                print(f"  {profile_id}: 无法反解参数")
                continue
            inferred_dx, inferred_dy = inferred
            delta_x = inferred_dx - current_dx
            delta_y = inferred_dy - current_dy

            profile_stats[profile_id]["dx"].append(inferred_dx)
            profile_stats[profile_id]["dy"].append(inferred_dy)
            profile_stats[profile_id]["delta_x"].append(delta_x)
            profile_stats[profile_id]["delta_y"].append(delta_y)

            print(
                f"  {profile_id}: pred_rb=({best['pred_x']:.3f},{best['pred_y']:.3f}) "
                f"delta=({best['dx']:.3f},{best['dy']:.3f}) scale={best['scale']:.6f} "
                f"inferred_dx/dy=({inferred_dx:.3f},{inferred_dy:.3f}) "
                f"delta_dx/dy=({delta_x:.3f},{delta_y:.3f})"
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
            and dx_stats["mean"] is not None
            and dy_stats["mean"] is not None
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
