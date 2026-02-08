from __future__ import annotations

import sys
from pathlib import Path


def _setup_path() -> Path:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "backend"))
    return root


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
        print(f"frames={len(frames)}")
        for idx, frame in enumerate(frames, start=1):
            extractor.extract_fields(dxf_path, frame)
            tb = frame.titleblock
            missing = _missing_fields(tb)
            ident = tb.internal_code or frame.frame_id
            profile = frame.runtime.roi_profile_id or "-"
            if "未命中锚点文本" in frame.runtime.flags:
                status = "SKIP(no anchor)"
            else:
                status = "OK" if not missing else "缺失: " + ", ".join(missing)
            print(f"[{idx}] id={ident} profile={profile} {status}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
