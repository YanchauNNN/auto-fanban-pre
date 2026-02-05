import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path


def _add_backend_to_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    backend_root = repo_root / "backend"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))


def _collect_inputs(dwg_dir: Path, dxf_dir: Path | None) -> list[Path]:
    if dxf_dir:
        if dxf_dir.is_file():
            return [dxf_dir]
        return sorted(dxf_dir.glob("*.dxf"))
    return sorted(dwg_dir.glob("*.dwg"))


def _collect_anchor_items(msp, detector) -> list[object]:
    from src.cad.detection.anchor_first_locator import AnchorFirstLocator  # type: ignore

    text_items = list(AnchorFirstLocator._iter_text_items(msp))
    locator = getattr(detector, "anchor_locator", detector.anchor_calibrated_locator)
    return [t for t in text_items if locator._match_any_text(t.text, locator.anchor_texts)]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run frame detector on DWG/DXF samples."
    )
    parser.add_argument(
        "--dwg-dir",
        default="test/dwg",
        help="DWG目录（默认：test/dwg）",
    )
    parser.add_argument(
        "--dxf-dir",
        default="",
        help="可选：直接使用DXF目录（绕过ODA）",
    )
    parser.add_argument(
        "--biaozhun",
        action="store_true",
        help="快捷模式：使用 test/dxf-biaozhun 作为DXF输入目录",
    )
    parser.add_argument(
        "--out-dir",
        default="test/dwg/_dxf_out",
        help="DWG->DXF输出目录（默认：test/dwg/_dxf_out）",
    )
    parser.add_argument(
        "--json-out",
        default="",
        help="可选：输出JSON汇总文件路径",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="最多处理文件数（0表示不限制）",
    )
    parser.add_argument(
        "--skip-line-rebuild",
        action="store_true",
        help="跳过LINE重建矩形（仅使用polyline候选）",
    )
    parser.add_argument(
        "--anchor-mode",
        default="auto",
        choices=["auto", "calibrated", "fallback"],
        help="锚点定位模式：auto(直推优先+回退)/calibrated(仅直推)/fallback(仅旧逻辑)",
    )
    parser.add_argument(
        "--project-no",
        default="",
        help="项目号（如1818），用于锚点字高等项目差异化配置",
    )
    args = parser.parse_args()

    _add_backend_to_path()
    from src.cad import FrameDetector, ODAConverter  # type: ignore

    dwg_dir = Path(args.dwg_dir)
    if args.biaozhun:
        dxf_dir = Path("test/dxf-biaozhun")
    else:
        dxf_dir = Path(args.dxf_dir) if args.dxf_dir else None
    out_dir = Path(args.out_dir)

    detector = FrameDetector(project_no=args.project_no or None)
    oda = ODAConverter()

    if args.skip_line_rebuild:
        detector.candidate_finder._rebuild_from_lines = (  # type: ignore[attr-defined]
            lambda _msp: []
        )

    inputs = _collect_inputs(dwg_dir, dxf_dir)
    if args.max_files and args.max_files > 0:
        inputs = inputs[: args.max_files]
    if not inputs:
        print("未找到可处理文件")
        return 1

    results: list[dict] = []

    for path in inputs:
        try:
            print(f"start {path.name}")
            sys.stdout.flush()
            started_at = time.perf_counter()
            if path.suffix.lower() == ".dwg":
                dxf_path = oda.dwg_to_dxf(path, out_dir)
            else:
                dxf_path = path
            anchor_texts_count = None
            anchor_items: list[object] = []
            try:
                import ezdxf  # type: ignore

                doc = ezdxf.readfile(str(dxf_path))
                msp = doc.modelspace()
                anchor_items = _collect_anchor_items(msp, detector)
                anchor_texts_count = len(anchor_items)
            except Exception:
                anchor_texts_count = None
            if args.anchor_mode == "auto":
                frames = detector.detect_frames(dxf_path)
            else:
                import ezdxf  # type: ignore

                doc = ezdxf.readfile(str(dxf_path))
                msp = doc.modelspace()
                if args.anchor_mode == "calibrated":
                    frames = detector.anchor_calibrated_locator.locate_frames(
                        msp, dxf_path
                    )
                else:
                    frames = detector.anchor_locator.locate_frames(msp, dxf_path)
            variants = [f.runtime.paper_variant_id for f in frames]
            profile_counts = Counter(f.runtime.roi_profile_id for f in frames)
            base10_count = profile_counts.get("BASE10", 0)
            small5_count = profile_counts.get("SMALL5", 0)
            scales = [
                {
                    "paper_variant_id": f.runtime.paper_variant_id,
                    "sx": f.runtime.sx,
                    "sy": f.runtime.sy,
                    "geom_scale_factor": f.runtime.geom_scale_factor,
                }
                for f in frames
            ]
            rb_points = [
                {"x": f.runtime.outer_bbox.xmax, "y": f.runtime.outer_bbox.ymin}
                for f in frames
            ]
            print(
                f"{path.name}: frames={len(frames)} base10={base10_count} small5={small5_count} "
                f"anchors={anchor_texts_count} variants={variants} scales={scales} rb={rb_points}"
            )
            elapsed_s = round(time.perf_counter() - started_at, 3)
            results.append(
                {
                    "file": path.name,
                    "source_suffix": path.suffix.lower(),
                    "dxf_path": str(dxf_path),
                    "frame_count": len(frames),
                    "base10_count": base10_count,
                    "small5_count": small5_count,
                    "anchor_texts": anchor_texts_count,
                    "variants": variants,
                    "scales": scales,
                    "rb_points": rb_points,
                    "frames": [f.model_dump(mode="json") for f in frames],
                    "elapsed_s": elapsed_s,
                    "error": None,
                }
            )
        except Exception as exc:  # noqa: BLE001
            rb_points: list[dict[str, float]] = []
            anchor_texts_count = None
            if "dxf_path" in locals():
                try:
                    import ezdxf  # type: ignore

                    doc = ezdxf.readfile(str(dxf_path))
                    msp = doc.modelspace()
                    anchor_items = _collect_anchor_items(msp, detector)
                    anchor_texts_count = len(anchor_items)
                    rb_targets = detector.anchor_calibrated_locator._build_rb_targets(  # noqa: SLF001
                        anchor_items
                    )
                    rb_points = []
                    seen_anchors: set[int] = set()
                    for t in rb_targets:
                        anchor_id = t["anchor_id"]
                        if anchor_id in seen_anchors:
                            continue
                        seen_anchors.add(anchor_id)
                        rb_points.append(
                            {
                                "x": t["rb_x"],
                                "y": t["rb_y"],
                                "profile_id": t["profile_id"],
                                "scale": t["scale"],
                            }
                        )
                except Exception:
                    rb_points = []
            print(f"{path.name}: ERROR {exc} rb={rb_points}")
            results.append(
                {
                    "file": path.name,
                    "source_suffix": path.suffix.lower(),
                    "dxf_path": None,
                    "frame_count": 0,
                    "base10_count": 0,
                    "small5_count": 0,
                    "anchor_texts": anchor_texts_count,
                    "variants": [],
                    "scales": [],
                    "rb_points": rb_points,
                    "frames": [],
                    "elapsed_s": None,
                    "error": str(exc),
                }
            )

    if args.json_out:
        json_path = Path(args.json_out)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "dxf_dir": str(dxf_dir) if dxf_dir else None,
            "dwg_dir": str(dwg_dir),
            "out_dir": str(out_dir),
            "options": {"skip_line_rebuild": bool(args.skip_line_rebuild)},
            "items": results,
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
