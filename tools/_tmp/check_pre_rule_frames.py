from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

import ezdxf  # type: ignore


def _add_backend_to_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    backend_root = repo_root / "backend"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pre-rule check: geometry candidates within layer_priority."
    )
    parser.add_argument("--dxf", required=True, help="DXF路径")
    parser.add_argument("--project-no", default="", help="项目号")
    parser.add_argument("--max-segments", type=int, default=5000, help="线段上限")
    parser.add_argument("--max-combos", type=int, default=50000, help="坐标组合上限")
    args = parser.parse_args()

    _add_backend_to_path()
    from src.cad.detection import AnchorCalibratedLocator, CandidateFinder, PaperFitter  # type: ignore
    from src.cad.detection.anchor_first_locator import AnchorFirstLocator  # type: ignore
    from src.cad.detection.anchor_calibrated_locator import CandidateFrame  # type: ignore
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

    bboxes: dict[tuple[float, float, float, float], dict] = {}

    def add_bbox(bbox, source: str, layer: str) -> None:
        key = (
            round(bbox.xmin, 3),
            round(bbox.ymin, 3),
            round(bbox.xmax, 3),
            round(bbox.ymax, 3),
        )
        if key not in bboxes:
            bboxes[key] = {"bbox": bbox, "sources": set()}
        bboxes[key]["sources"].add(f"{source}:{layer}")

    for layer in locator.layer_order:
        for entity_type in ("LWPOLYLINE", "POLYLINE"):
            for entity in locator._iter_layer_entities(msp, layer, entity_type):  # noqa: SLF001
                vertices = locator._polyline_vertices(entity, entity_type)  # noqa: SLF001
                if not vertices:
                    continue
                is_closed = locator._is_polyline_closed(entity, entity_type)  # noqa: SLF001
                if locator._is_axis_aligned(vertices):  # noqa: SLF001
                    if is_closed:
                        add_bbox(locator._bbox_from_vertices(vertices), "closed_poly", layer)  # noqa: SLF001
                    elif len(vertices) == 4:
                        add_bbox(locator._bbox_from_vertices(vertices), "open_axis4", layer)  # noqa: SLF001

        segments = locator._query_lines(msp, layer)  # noqa: SLF001
        if len(segments) <= args.max_segments:
            horizontal = []
            vertical = []
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
            ys = sorted(h_segments.keys())
            xs = sorted(v_segments.keys())
            if len(xs) * len(ys) <= args.max_combos:
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
                                add_bbox(
                                    locator._bbox_from_vertices(  # noqa: SLF001
                                        [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
                                    ),
                                    "line_rect",
                                    layer,
                                )

    anchor_cfg = spec.titleblock_extract.get("anchor", {})
    search_texts = anchor_cfg.get("search_text", [])
    if isinstance(search_texts, str):
        search_texts = [search_texts]
    text_items = list(AnchorFirstLocator._iter_text_items(msp))  # noqa: SLF001
    anchor_items = [
        t for t in text_items if locator._match_any_text(t.text, search_texts)  # noqa: SLF001
    ]

    candidates = []
    for item in bboxes.values():
        bbox = item["bbox"]
        for paper_id, sx, sy, profile_id, error in locator.paper_fitter.fit_all(  # noqa: SLF001
            bbox, locator.paper_variants  # noqa: SLF001
        ):
            candidates.append(
                {
                    "bbox": bbox,
                    "paper_id": paper_id,
                    "sx": sx,
                    "sy": sy,
                    "profile_id": profile_id,
                    "error": error,
                }
            )

    best_by_key: dict[tuple[float, float, float, float, str], dict] = {}
    for cand in candidates:
        bbox = cand["bbox"]
        key = (
            round(bbox.xmin, 3),
            round(bbox.ymin, 3),
            round(bbox.xmax, 3),
            round(bbox.ymax, 3),
            cand["profile_id"],
        )
        best = best_by_key.get(key)
        if best is None or cand["error"] < best["error"]:
            best_by_key[key] = cand

    def anchor_rb_offset(profile_id: str) -> list[float] | None:
        calib = (anchor_cfg.get("calibration") or {}).get(profile_id, {})
        if not isinstance(calib, dict):
            return None
        overrides = calib.get("anchor_roi_rb_offset_1to1_by_project", {})
        if args.project_no and isinstance(overrides, dict):
            override = overrides.get(args.project_no)
            if override:
                return [float(v) for v in override]
        base = calib.get("anchor_roi_rb_offset_1to1")
        if base:
            return [float(v) for v in base]
        return None

    roi_margin = float(spec.titleblock_extract.get("tolerances", {}).get("roi_margin_percent", 0.0))
    matched_candidates = set()
    matched_anchors = set()
    best_per_anchor: dict[int, tuple[tuple[float, float, float, float, str], dict]] = {}
    for key, cand in best_by_key.items():
        rb_offset = anchor_rb_offset(cand["profile_id"])
        if not rb_offset:
            continue
        anchor_roi = AnchorFirstLocator._restore_roi(  # noqa: SLF001
            cand["bbox"], rb_offset, cand["sx"], cand["sy"]
        )
        anchor_roi = AnchorFirstLocator._expand_roi(anchor_roi, roi_margin)  # noqa: SLF001
        for idx, item in enumerate(anchor_items):
            if AnchorFirstLocator._text_in_roi(  # noqa: SLF001
                AnchorFirstLocator, item, anchor_roi
            ):
                matched_candidates.add(key)
                matched_anchors.add(idx)
                current = best_per_anchor.get(idx)
                if current is None or cand["error"] < current[1]["error"]:
                    best_per_anchor[idx] = (key, cand)

    profile_counts = Counter(c["profile_id"] for c in best_by_key.values())
    matched_profile_counts = Counter(
        key[4] for key in matched_candidates
    )
    best_anchor_profile_counts = Counter(
        item[0][4] for item in best_per_anchor.values()
    )
    variant_counts = Counter(c["paper_id"] for c in best_by_key.values())

    a4_candidates: list[CandidateFrame] = []
    for key, cand in best_by_key.items():
        if "A4" not in cand["paper_id"]:
            continue
        if cand["profile_id"] != "SMALL5":
            continue
        bbox = cand["bbox"]
        source_layers = bboxes.get(
            (
                round(bbox.xmin, 3),
                round(bbox.ymin, 3),
                round(bbox.xmax, 3),
                round(bbox.ymax, 3),
            ),
            {},
        ).get("sources", set())
        layer = next(iter(source_layers), "unknown").split(":", 1)[-1]
        a4_candidates.append(
            CandidateFrame(
                bbox=bbox,
                paper_variant_id=cand["paper_id"],
                sx=cand["sx"],
                sy=cand["sy"],
                roi_profile_id=cand["profile_id"],
                fit_error=cand["error"],
                layer=layer,
            )
        )

    a4_clusters = locator._build_a4_clusters(a4_candidates)  # noqa: SLF001
    a4_cluster_map = locator._cluster_lookup(a4_clusters)  # noqa: SLF001
    small5_from_anchor: set[tuple[float, float, float, float]] = set()
    for key, cand in best_per_anchor.values():
        if cand["profile_id"] != "SMALL5" or "A4" not in cand["paper_id"]:
            continue
        bbox = cand["bbox"]
        cluster = a4_cluster_map.get(
            (
                round(bbox.xmin, 3),
                round(bbox.ymin, 3),
                round(bbox.xmax, 3),
                round(bbox.ymax, 3),
            ),
            [],
        )
        for item in cluster:
            small5_from_anchor.add(
                (
                    round(item.bbox.xmin, 3),
                    round(item.bbox.ymin, 3),
                    round(item.bbox.xmax, 3),
                    round(item.bbox.ymax, 3),
                )
            )

    base10_from_anchor = [
        item for item in best_per_anchor.values() if item[1]["profile_id"] == "BASE10"
    ]

    print(
        f"{dxf_path.name}: anchors={len(anchor_items)} "
        f"rect_bboxes={len(bboxes)} candidates={len(best_by_key)}"
    )
    print("  profile_counts", dict(profile_counts))
    print("  variant_counts", dict(variant_counts))
    print("  anchor_matched_profiles", dict(matched_profile_counts))
    print("  best_anchor_profiles", dict(best_anchor_profile_counts))
    print(
        f"  a4_clusters={len(a4_clusters)} a4_candidates={len(a4_candidates)} "
        f"small5_from_anchor_cluster={len(small5_from_anchor)}"
    )
    print(
        f"  rule_counts BASE10={len(base10_from_anchor)} "
        f"SMALL5={len(small5_from_anchor)}"
    )
    print(
        f"  matched_anchors={len(matched_anchors)} "
        f"matched_candidates={len(matched_candidates)} "
        f"best_per_anchor={len(best_per_anchor)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
