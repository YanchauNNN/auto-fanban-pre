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
    parser = argparse.ArgumentParser(description="Count RB targets after filtering.")
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
    unique_rb = {
        (round(t["rb_x"], 3), round(t["rb_y"], 3), t["profile_id"]) for t in rb_targets
    }
    print(
        f"{dxf_path.name}: anchors_raw={len(anchor_items)} "
        f"rb_targets={len(rb_targets)} unique_rb={len(unique_rb)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
