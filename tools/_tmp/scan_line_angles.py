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


def _angle_deg(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    ang = math.degrees(math.atan2(dy, dx))
    ang = abs(ang) % 180.0
    if ang > 90.0:
        ang = 180.0 - ang
    return ang


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan line angles.")
    parser.add_argument("--dxf", required=True, help="DXF路径")
    parser.add_argument("--project-no", default="", help="项目号")
    parser.add_argument("--all-layers", action="store_true", help="扫描所有图层")
    parser.add_argument("--min-length", type=float, default=100.0, help="最小线段长度")
    args = parser.parse_args()

    _add_backend_to_path()
    from src.cad.detection import (  # type: ignore
        AnchorCalibratedLocator,
        CandidateFinder,
        PaperFitter,
    )
    from src.config import load_spec  # type: ignore

    spec = load_spec()
    outer_cfg = spec.titleblock_extract.get("outer_frame", {})
    layer_priority = outer_cfg.get("layer_priority", {})
    layers = layer_priority.get("layers") or []
    if not layers:
        layers = ["_TSZ-PLOT_MARK", "TK", "图框", "ttkk", "0"]

    finder = CandidateFinder()
    locator = AnchorCalibratedLocator(
        spec, finder, PaperFitter(), project_no=args.project_no or None
    )

    dxf_path = Path(args.dxf)
    if not dxf_path.exists():
        print("ERROR: DXF文件不存在")
        return 2

    doc = ezdxf.readfile(str(dxf_path))
    if args.all_layers:
        layers = [str(layer.dxf.name) for layer in doc.layers]

    angles = Counter()
    total = 0
    for layer in layers:
        for p1, p2 in locator._query_lines(doc.modelspace(), layer):  # noqa: SLF001
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            length = (dx * dx + dy * dy) ** 0.5
            if length < args.min_length:
                continue
            ang = _angle_deg(p1, p2)
            bucket = round(ang, 1)
            angles[bucket] += 1
            total += 1

    print(f"{dxf_path.name}: segments={total} unique_angles={len(angles)}")
    for ang, count in angles.most_common(10):
        print(f"  angle={ang} count={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
