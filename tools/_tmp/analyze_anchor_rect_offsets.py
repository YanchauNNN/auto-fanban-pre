from __future__ import annotations

import argparse
import math
import sys
from collections import Counter
from pathlib import Path

import ezdxf  # type: ignore


def _add_backend_to_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    backend_root = repo_root / "backend"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))


def _bbox_key(bbox) -> tuple[float, float, float, float]:
    return (
        round(bbox.xmin, 3),
        round(bbox.ymin, 3),
        round(bbox.xmax, 3),
        round(bbox.ymax, 3),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze anchor RB vs rectangles within layer_priority."
    )
    parser.add_argument("--dxf", required=True, help="DXF路径")
    parser.add_argument("--project-no", default="", help="项目号")
    parser.add_argument(
        "--max-anchors",
        type=int,
        default=0,
        help="仅分析前N个锚点（0=全部）",
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
    locator = AnchorCalibratedLocator(
        spec, CandidateFinder(), PaperFitter(), project_no=args.project_no or None
    )

    dxf_path = Path(args.dxf)
    if not dxf_path.exists():
        print("ERROR: DXF文件不存在")
        return 2
    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()

    anchor_cfg = spec.titleblock_extract.get("anchor", {})
    search_texts = anchor_cfg.get("search_text", [])
    if isinstance(search_texts, str):
        search_texts = [search_texts]
    text_items = list(AnchorFirstLocator._iter_text_items(msp))  # noqa: SLF001
    anchor_items = [
        t
        for t in text_items
        if locator._match_any_text(t.text, search_texts)  # noqa: SLF001
    ]
    if args.max_anchors > 0:
        anchor_items = anchor_items[: args.max_anchors]

    rects = []
    seen = set()
    for layer in locator.layer_order:
        for entity_type in ("LWPOLYLINE", "POLYLINE"):
            for poly in locator._query_polylines(msp, layer, entity_type):  # noqa: SLF001
                bbox = poly["bbox"]
                key = _bbox_key(bbox)
                if key in seen:
                    continue
                seen.add(key)
                rects.append(bbox)
    for bbox in locator._build_line_rectangles(msp):  # noqa: SLF001
        key = _bbox_key(bbox)
        if key in seen:
            continue
        seen.add(key)
        rects.append(bbox)

    print(
        f"{dxf_path.name}: anchors={len(anchor_items)} rects={len(rects)} "
        f"layers={len(locator.layer_order)}"
    )
    if not rects or not anchor_items:
        return 0

    delta_pairs = []
    delta_pairs_1to1 = []
    nearest_dist = []
    for idx, anchor_item in enumerate(anchor_items, start=1):
        best = None
        best_dist = None
        for profile_id, calib in locator._iter_calibrations():  # noqa: SLF001
            candidates = locator._iter_scale_candidates(anchor_item, calib)  # noqa: SLF001
            if not candidates:
                continue
            candidate = candidates[0]
            scale = candidate["scale"]
            rb_x, rb_y = locator._outer_rb_from_anchor(  # noqa: SLF001
                anchor_item, scale, calib, candidate["use_project_override"]
            )
            for bbox in rects:
                dx = bbox.xmax - rb_x
                dy = bbox.ymin - rb_y
                dist = math.hypot(dx, dy)
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best = (dx, dy, scale)
        if best is None:
            continue
        dx, dy, scale = best
        nearest_dist.append(best_dist)
        delta_pairs.append((round(dx, 3), round(dy, 3)))
        delta_pairs_1to1.append((round(dx / scale, 3), round(dy / scale, 3)))

    if not delta_pairs:
        print("no_offset_samples")
        return 0

    pair_counts = Counter(delta_pairs).most_common(5)
    pair_counts_1to1 = Counter(delta_pairs_1to1).most_common(5)
    print("top_offset_pairs", pair_counts)
    print("top_offset_pairs_1to1", pair_counts_1to1)
    if nearest_dist:
        nearest_dist.sort()
        print(
            "nearest_dist_sample",
            [round(d, 3) for d in nearest_dist[:5]],
            [round(d, 3) for d in nearest_dist[-5:]],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
