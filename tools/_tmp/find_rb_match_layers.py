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
        description="Find layers that can match RB targets."
    )
    parser.add_argument("--dxf", required=True, help="DXF路径")
    parser.add_argument(
        "--project-no",
        default="",
        help="项目号（用于字高/偏移覆盖）",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="输出每个RB命中层",
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
    outer_cfg = spec.titleblock_extract.get("outer_frame", {})
    acceptance_cfg = outer_cfg.get("acceptance", {})
    orth_tol = float(acceptance_cfg.get("orthogonality_tol_deg", 1.0))
    base_profile = spec.get_roi_profile("BASE10")
    coord_tol = base_profile.tolerance if base_profile else 0.5

    finder = CandidateFinder(
        min_dim=100.0, coord_tol=coord_tol, orthogonality_tol_deg=orth_tol
    )
    locator = AnchorCalibratedLocator(
        spec, finder, PaperFitter(), project_no=args.project_no or None
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
    if not rb_targets:
        print("ERROR: 未找到锚点/RB")
        return 1

    layers = [str(layer.dxf.name) for layer in doc.layers]
    layer_matches: dict[str, set[int]] = {}
    rb_matches: dict[int, list[str]] = {i: [] for i in range(len(rb_targets))}

    for layer in layers:
        polylines = locator._query_polylines(msp, layer, "LWPOLYLINE")  # noqa: SLF001
        polylines += locator._query_polylines(msp, layer, "POLYLINE")  # noqa: SLF001
        lines = locator._query_lines(msp, layer)  # noqa: SLF001
        if not polylines and not lines:
            continue
        for idx, target in enumerate(rb_targets):
            rb_x = float(target["rb_x"])
            rb_y = float(target["rb_y"])
            scale = float(target["scale"])
            profile = target["profile_id"]
            matched = False
            if polylines:
                matches_poly = locator._match_polylines(  # noqa: SLF001
                    polylines, rb_x, rb_y, scale, profile, layer
                )
                if matches_poly:
                    matched = True
            if not matched and lines:
                matches_line = locator._match_lines(  # noqa: SLF001
                    lines, rb_x, rb_y, scale, profile, layer
                )
                if matches_line:
                    matched = True
            if matched:
                layer_matches.setdefault(layer, set()).add(idx)
                rb_matches[idx].append(layer)

    print(
        f"{dxf_path.name}: anchors={len(anchor_items)} rb_targets={len(rb_targets)} "
        f"matched_layers={len(layer_matches)}"
    )
    for layer, idxs in sorted(layer_matches.items(), key=lambda x: (-len(x[1]), x[0])):
        print(f"  layer={layer} rb_hits={len(idxs)}")
    if args.verbose:
        for idx, layers in rb_matches.items():
            print(f"  rb[{idx}] layers={layers}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
