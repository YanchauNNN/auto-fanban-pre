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
    parser = argparse.ArgumentParser(description="Count anchors with geometry matches.")
    parser.add_argument("--dxf", required=True, help="DXF路径")
    parser.add_argument("--project-no", default="", help="项目号")
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
    rb_targets = locator._build_rb_targets(anchor_items)  # noqa: SLF001
    targets_by_anchor: dict[int, list[dict]] = {}
    for target in rb_targets:
        targets_by_anchor.setdefault(target["anchor_id"], []).append(target)

    matched_anchors: set[int] = set()
    poly_cache: dict[tuple[str, str], list[dict]] = {}
    line_cache: dict[str, list[tuple[tuple[float, float], tuple[float, float]]]] = {}
    for layer in locator.layer_order:
        for entity_type in locator.entity_order:
            if entity_type in {"LWPOLYLINE", "POLYLINE"}:
                cache_key = (layer, entity_type)
                if cache_key not in poly_cache:
                    poly_cache[cache_key] = locator._query_polylines(  # noqa: SLF001
                        msp, layer, entity_type
                    )
                polylines = poly_cache[cache_key]
                if not polylines:
                    continue
            else:
                if layer not in line_cache:
                    line_cache[layer] = locator._query_lines(msp, layer)  # noqa: SLF001
                lines = line_cache[layer]
                if not lines:
                    continue
            for anchor_id, targets in targets_by_anchor.items():
                if anchor_id in matched_anchors:
                    continue
                for target in targets:
                    rb_x = target["rb_x"]
                    rb_y = target["rb_y"]
                    scale = target["scale"]
                    profile = target["profile_id"]
                    if entity_type in {"LWPOLYLINE", "POLYLINE"}:
                        if locator._match_polylines(  # noqa: SLF001
                            polylines, rb_x, rb_y, scale, profile, layer
                        ):
                            matched_anchors.add(anchor_id)
                            break
                    else:
                        if locator._match_lines(  # noqa: SLF001
                            lines, rb_x, rb_y, scale, profile, layer
                        ):
                            matched_anchors.add(anchor_id)
                            break
                if anchor_id in matched_anchors:
                    continue

    print(
        f"{dxf_path.name}: anchors_raw={len(anchor_items)} "
        f"rb_targets={len(rb_targets)} matched_anchors={len(matched_anchors)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
