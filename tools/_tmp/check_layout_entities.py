from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import ezdxf  # type: ignore


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect entity types in modelspace/layouts."
    )
    parser.add_argument("--dxf", required=True, help="DXF路径")
    args = parser.parse_args()

    dxf_path = Path(args.dxf)
    if not dxf_path.exists():
        print("ERROR: DXF文件不存在")
        return 2

    doc = ezdxf.readfile(str(dxf_path))

    def summarize(space, name: str) -> None:
        counts = Counter(e.dxftype() for e in space)
        total = sum(counts.values())
        interesting = {
            k: counts.get(k, 0)
            for k in ("LINE", "LWPOLYLINE", "POLYLINE", "INSERT", "SPLINE", "CIRCLE")
        }
        print(f"{name}: total={total} {interesting}")

    summarize(doc.modelspace(), "modelspace")
    for layout in doc.layouts:
        if layout.name.lower() == "model":
            continue
        summarize(layout, f"layout:{layout.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
