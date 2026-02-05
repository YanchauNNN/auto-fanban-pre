from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path


def _add_backend_to_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    backend_root = repo_root / "backend"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run frame detector and summarize stats."
    )
    parser.add_argument("--dxf", required=True, help="DXF路径")
    parser.add_argument("--project-no", default="", help="项目号")
    args = parser.parse_args()

    _add_backend_to_path()
    from src.cad.frame_detector import FrameDetector  # type: ignore
    from src.interfaces import DetectionError  # type: ignore

    dxf_path = Path(args.dxf)
    detector = FrameDetector(project_no=args.project_no or None)
    try:
        frames = detector.detect_frames(dxf_path)
    except DetectionError as exc:
        print(f"{dxf_path.name}: ERROR {exc}")
        return 1

    profile_counts = Counter(f.runtime.roi_profile_id or "UNKNOWN" for f in frames)
    variant_counts = Counter(f.runtime.paper_variant_id or "UNKNOWN" for f in frames)

    print(f"{dxf_path.name}: frames={len(frames)}")
    print("  roi_profile_counts", dict(profile_counts))
    print("  paper_variant_counts", dict(variant_counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
