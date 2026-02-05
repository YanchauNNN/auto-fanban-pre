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


def _effective_layer(insert_layer: str, entity_layer: str | None) -> str:
    if not entity_layer or entity_layer == "0":
        return insert_layer
    return entity_layer


def _polyline_vertices(entity, tp: str) -> list[tuple[float, float]]:
    vertices: list[tuple[float, float]] = []
    if tp == "LWPOLYLINE":
        for p in entity.get_points():
            vertices.append((float(p[0]), float(p[1])))
    elif tp == "POLYLINE":
        for v in entity.vertices:
            loc = v.dxf.location
            vertices.append((float(loc.x), float(loc.y)))
    return vertices


def _is_polyline_closed(entity, tp: str) -> bool:
    if tp == "LWPOLYLINE":
        return bool(
            getattr(entity, "closed", False) or getattr(entity, "is_closed", False)
        )
    if tp == "POLYLINE":
        return bool(
            getattr(entity, "is_closed", False) or getattr(entity, "closed", False)
        )
    return False


def _collect_block_geometry(msp, layers: list[str]):
    block_segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    block_polylines: list[dict] = []
    insert_count = 0

    for insert in msp.query("INSERT"):
        insert_count += 1
        insert_layer = str(getattr(insert.dxf, "layer", "0"))
        try:
            virtuals = list(insert.virtual_entities())
        except Exception:
            virtuals = []
        for ve in virtuals:
            tp = ve.dxftype()
            if tp not in {"LINE", "LWPOLYLINE", "POLYLINE"}:
                continue
            ve_layer = str(getattr(ve.dxf, "layer", "0"))
            effective_layer = _effective_layer(insert_layer, ve_layer)
            if effective_layer not in layers:
                continue
            if tp == "LINE":
                start = ve.dxf.start
                end = ve.dxf.end
                p1 = (float(start.x), float(start.y))
                p2 = (float(end.x), float(end.y))
                if p1 != p2:
                    block_segments.append((p1, p2))
                continue
            vertices = _polyline_vertices(ve, tp)
            if len(vertices) < 2:
                continue
            is_closed = _is_polyline_closed(ve, tp)
            if is_closed:
                block_polylines.append(
                    {"vertices": vertices, "layer": effective_layer, "tp": tp}
                )
            for idx in range(len(vertices) - 1):
                p1 = vertices[idx]
                p2 = vertices[idx + 1]
                if p1 != p2:
                    block_segments.append((p1, p2))
            if is_closed and vertices[0] != vertices[-1]:
                block_segments.append((vertices[-1], vertices[0]))

    return insert_count, block_segments, block_polylines


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check block-contained geometry against RB targets."
    )
    parser.add_argument("files", nargs="*", help="DXF文件路径（可选）")
    parser.add_argument(
        "--project-no",
        default="1818",
        help="项目号（用于字高/偏移覆盖）",
    )
    parser.add_argument(
        "--dxf-dir",
        default="",
        help="可选：DXF目录（配合--glob使用）",
    )
    parser.add_argument(
        "--glob",
        default="",
        help="可选：glob模式（如 1818-A1*.dxf）",
    )
    parser.add_argument(
        "--layers",
        default="",
        help="覆盖扫描图层（逗号分隔，默认取layer_priority）",
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
    if args.layers:
        layers = [v.strip() for v in args.layers.split(",") if v.strip()]
    else:
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
        spec, finder, PaperFitter(), project_no=args.project_no
    )

    anchor_cfg = spec.titleblock_extract.get("anchor", {})
    search_texts = anchor_cfg.get("search_text", [])
    if isinstance(search_texts, str):
        search_texts = [search_texts]

    files = [Path(p) for p in args.files]
    if not files and args.dxf_dir and args.glob:
        files = sorted(Path(args.dxf_dir).glob(args.glob))
    if not files:
        print("ERROR: 未提供文件或未匹配到文件")
        return 2

    for dxf_path in files:
        if not dxf_path.exists():
            print(f"{dxf_path.name}: ERROR 文件不存在")
            continue

        doc = ezdxf.readfile(str(dxf_path))
        msp = doc.modelspace()
        text_items = list(AnchorFirstLocator._iter_text_items(msp))  # noqa: SLF001
        anchor_items = [
            t
            for t in text_items
            if locator._match_any_text(t.text, search_texts)  # noqa: SLF001
        ]
        rb_targets = locator._build_rb_targets(anchor_items)  # noqa: SLF001
        if not rb_targets:
            print(f"{dxf_path.name}: ERROR 未找到锚点/RB")
            continue

        insert_count, block_segments, block_polylines = _collect_block_geometry(
            msp, layers
        )
        print(
            f"{dxf_path.name}: inserts={insert_count} "
            f"block_segments={len(block_segments)} block_polylines={len(block_polylines)}"
        )

        for target in rb_targets:
            rb_x = float(target["rb_x"])
            rb_y = float(target["rb_y"])
            profile = target["profile_id"]
            scale = float(target["scale"])
            matches_line = locator._match_lines(  # noqa: SLF001
                block_segments, rb_x, rb_y, scale, profile, "BLOCK"
            )
            matches_poly = []
            if block_polylines:
                poly_items = []
                for poly in block_polylines:
                    vertices = poly["vertices"]
                    if not locator._is_axis_aligned(vertices):  # noqa: SLF001
                        continue
                    bbox = locator._bbox_from_vertices(vertices)  # noqa: SLF001
                    poly_items.append({"bbox": bbox, "vertices": vertices})
                if poly_items:
                    matches_poly = locator._match_polylines(  # noqa: SLF001
                        poly_items, rb_x, rb_y, scale, profile, "BLOCK"
                    )
            if matches_line or matches_poly:
                print(
                    f"  RB profile={profile} scale={scale:.6f}: "
                    f"line_matches={len(matches_line)} poly_matches={len(matches_poly)}"
                )
            else:
                print(f"  RB profile={profile} scale={scale:.6f}: no matches")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
