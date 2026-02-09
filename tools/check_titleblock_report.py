from __future__ import annotations

import sys
from pathlib import Path


def _setup_path() -> Path:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "backend"))
    return root


def _seq_from_internal_code(code: str | None) -> int | None:
    if not code or "-" not in code:
        return None
    suffix = code.rsplit("-", 1)[-1]
    return int(suffix) if suffix.isdigit() else None


def _missing_fields(tb) -> list[str]:
    missing: list[str] = []
    if not tb.engineering_no:
        missing.append("工程号")
    if not tb.subitem_no:
        missing.append("子项号")
    if not tb.internal_code:
        missing.append("内部编码")
    if not tb.external_code:
        missing.append("外部编码")
    if not tb.paper_size_text:
        missing.append("图幅")
    if not tb.discipline:
        missing.append("专业")
    if not tb.scale_text:
        missing.append("比例")
    if tb.page_total is None:
        missing.append("张数(共)")
    if tb.page_index is None:
        missing.append("张数(第)")
    if not (tb.title_cn or tb.title_en):
        missing.append("图纸标题")
    if not tb.revision:
        missing.append("版次")
    if not tb.status:
        missing.append("状态")
    if not tb.date:
        missing.append("日期")
    return missing


def _a4_page_status(tb) -> str:
    if tb.page_index is None:
        return "A4页码缺失"
    if tb.page_total is None:
        return f"A4页码={tb.page_index}"
    return f"A4页码={tb.page_index}/{tb.page_total}"


def main() -> int:
    root = _setup_path()
    from src.cad import FrameDetector, TitleblockExtractor

    dxf_paths = [
        root / "test" / "dwg" / "_dxf_out" / "1818仿真图.dxf",
        root / "test" / "dwg" / "_dxf_out" / "2016仿真图.dxf",
    ]

    detector = FrameDetector()
    extractor = TitleblockExtractor()

    for dxf_path in dxf_paths:
        print(f"\n=== {dxf_path.name} ===")
        frames = detector.detect_frames(dxf_path)
        entries = []
        for frame in frames:
            extractor.extract_fields(dxf_path, frame)
            tb = frame.titleblock
            internal_code = tb.internal_code
            seq = _seq_from_internal_code(internal_code)
            entries.append(
                {
                    "frame": frame,
                    "tb": tb,
                    "internal_code": internal_code,
                    "seq": seq,
                }
            )

        entries.sort(
            key=lambda e: (
                e["seq"] is None,
                e["seq"] if e["seq"] is not None else 10**9,
                e["internal_code"] or e["frame"].frame_id,
            )
        )

        print(f"frames={len(entries)}")
        for idx, entry in enumerate(entries, start=1):
            frame = entry["frame"]
            tb = entry["tb"]
            name = entry["internal_code"] or frame.frame_id
            scale = frame.runtime.geom_scale_factor
            profile = frame.runtime.roi_profile_id or "-"
            paper = frame.runtime.paper_variant_id or "-"

            if "A4" in paper.upper():
                if tb.internal_code or tb.external_code or tb.engineering_no or tb.title_cn or tb.title_en:
                    missing = _missing_fields(tb)
                    status = "A4主: OK" if not missing else "A4主: 缺失: " + ", ".join(missing)
                else:
                    status = _a4_page_status(tb)
            elif "未命中锚点文本" in frame.runtime.flags:
                status = "跳过: 无锚点"
            else:
                missing = _missing_fields(tb)
                status = "OK" if not missing else "缺失: " + ", ".join(missing)

            scale_text = f"{scale:.3f}" if scale is not None else "-"
            print(
                f"[{idx}] name={name} scale={scale_text} "
                f"paper={paper} profile={profile} {status}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
