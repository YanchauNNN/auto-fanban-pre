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
        description="Scan nearest horizontal/vertical lines to RB."
    )
    parser.add_argument("--dxf", required=True, help="DXF路径")
    parser.add_argument("--project-no", default="", help="项目号")
    parser.add_argument(
        "--all-layers",
        action="store_true",
        help="扫描所有图层（默认仅layer_priority）",
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
    layer_priority = outer_cfg.get("layer_priority", {})
    layers = layer_priority.get("layers") or []
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

    horizontal: list[tuple[float, float, float]] = []
    vertical: list[tuple[float, float, float]] = []
    if args.all_layers:
        layers = [str(layer.dxf.name) for layer in doc.layers]

    for layer in layers:
        for (x1, y1), (x2, y2) in locator._query_lines(msp, layer):  # noqa: SLF001
            dx = x2 - x1
            dy = y2 - y1
            length = (dx * dx + dy * dy) ** 0.5
            if length <= 0:
                continue
            if abs(dy) <= locator.rb_tol or abs(dy) / length <= finder._sin_tol:  # noqa: SLF001
                y = (y1 + y2) / 2.0
                horizontal.append((y, min(x1, x2), max(x1, x2)))
            elif abs(dx) <= locator.rb_tol or abs(dx) / length <= finder._sin_tol:  # noqa: SLF001
                x = (x1 + x2) / 2.0
                vertical.append((x, min(y1, y2), max(y1, y2)))

    print(
        f"{dxf_path.name}: anchors={len(anchor_items)} rb_targets={len(rb_targets)} "
        f"h_segments={len(horizontal)} v_segments={len(vertical)}"
    )

    for idx, target in enumerate(rb_targets):
        rb_x = float(target["rb_x"])
        rb_y = float(target["rb_y"])
        best_h = None
        best_v = None
        best_h_any = None
        best_v_any = None
        for y, x0, x1 in horizontal:
            dy = abs(y - rb_y)
            if best_h_any is None or dy < best_h_any[0]:
                best_h_any = (dy, y, x0, x1)
            if x0 - locator.rb_tol <= rb_x <= x1 + locator.rb_tol:
                if best_h is None or dy < best_h[0]:
                    best_h = (dy, y, x0, x1)
        for x, y0, y1 in vertical:
            dx = abs(x - rb_x)
            if best_v_any is None or dx < best_v_any[0]:
                best_v_any = (dx, x, y0, y1)
            if y0 - locator.rb_tol <= rb_y <= y1 + locator.rb_tol:
                if best_v is None or dx < best_v[0]:
                    best_v = (dx, x, y0, y1)
        dy = best_h[0] if best_h else None
        dx = best_v[0] if best_v else None
        dy_any = best_h_any[0] if best_h_any else None
        dx_any = best_v_any[0] if best_v_any else None
        print(f"  rb[{idx}] dx={dx} dy={dy} dx_any={dx_any} dy_any={dy_any}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
