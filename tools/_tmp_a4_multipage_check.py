"""
临时诊断脚本：在 1818仿真图.dxf 上跑 模块2→3→4 全流程，
输出 A4 多页成组结果。

用法:
    python tools/_tmp_a4_multipage_check.py
"""

from __future__ import annotations

import sys
from pathlib import Path


def _setup_path() -> Path:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "backend"))
    return root


def main() -> int:
    root = _setup_path()
    from src.cad import A4MultipageGrouper, FrameDetector, TitleblockExtractor

    dxf_path = root / "test" / "dwg" / "_dxf_out" / "1818仿真图.dxf"
    if not dxf_path.exists():
        print(f"ERROR: DXF 文件不存在: {dxf_path}")
        return 1

    # ── 模块2：图框检测 ──
    print(f"=== 模块2: 图框检测 - {dxf_path.name} ===")
    detector = FrameDetector()
    frames = detector.detect_frames(dxf_path)
    print(f"检测到 {len(frames)} 个图框\n")

    # ── 模块3：图签字段提取 ──
    print("=== 模块3: 图签字段提取 ===")
    extractor = TitleblockExtractor()
    a4_count = 0
    for frame in frames:
        extractor.extract_fields(dxf_path, frame)
        paper = frame.runtime.paper_variant_id or "-"
        is_a4 = "A4" in paper.upper()
        if is_a4:
            a4_count += 1

        tb = frame.titleblock
        ident = tb.internal_code or frame.frame_id[:8]
        page_info = ""
        if tb.page_total is not None or tb.page_index is not None:
            page_info = f" 页码={tb.page_index}/{tb.page_total}"

        role = ""
        if is_a4:
            if tb.internal_code or tb.external_code or tb.engineering_no:
                role = " [A4主帧]"
            else:
                role = " [A4从属帧]"

        flags_str = ""
        if frame.runtime.flags:
            flags_str = f" flags={frame.runtime.flags}"

        print(f"  {ident:30s} paper={paper:15s}{role}{page_info}{flags_str}")

    print(f"\n  共 {len(frames)} 帧, 其中 A4 帧 {a4_count} 个\n")

    # ── 模块4：A4 多页成组 ──
    print("=== 模块4: A4 多页成组 ===")
    grouper = A4MultipageGrouper()
    remaining, sheet_sets = grouper.group_a4_pages(frames)

    print(f"成组结果: {len(sheet_sets)} 个 SheetSet, {len(remaining)} 帧未成组\n")

    for i, ss in enumerate(sheet_sets, 1):
        print(f"── SheetSet #{i} ──")
        print(f"  cluster_id : {ss.cluster_id[:12]}...")
        print(f"  page_total : {ss.page_total}")
        print(f"  pages      : {len(ss.pages)} 页")
        print(f"  flags      : {ss.flags or '(无)'}")

        if ss.master_page and ss.master_page.frame_meta:
            mtb = ss.master_page.frame_meta.titleblock
            print(f"  Master:")
            print(f"    internal_code : {mtb.internal_code}")
            print(f"    external_code : {mtb.external_code}")
            print(f"    engineering_no: {mtb.engineering_no}")
            print(f"    title_cn      : {mtb.title_cn}")
            print(f"    page_total    : {mtb.page_total}")
            print(f"    page_index    : {mtb.page_index}")

        print(f"  Pages (按 page_index 排列):")
        for p in ss.pages:
            role = "Master" if p.has_titleblock else "Slave"
            bbox = p.outer_bbox
            fm_id = p.frame_meta.frame_id[:8] if p.frame_meta else "-"
            slave_pt = ""
            if p.frame_meta and not p.has_titleblock:
                spt = p.frame_meta.titleblock.page_total
                spi = p.frame_meta.titleblock.page_index
                slave_pt = f" slave_page={spi}/{spt}"
            print(
                f"    page_index={p.page_index} [{role:6s}] "
                f"bbox=({bbox.xmin:.0f},{bbox.ymin:.0f},{bbox.xmax:.0f},{bbox.ymax:.0f}) "
                f"frame={fm_id}{slave_pt}"
            )

        # 继承的 titleblock
        inherited = ss.get_inherited_titleblock()
        if inherited:
            print(f"  Inherited titleblock keys: {list(inherited.keys())}")
        print()

    # ── 未成组帧列表 ──
    if remaining:
        print("── 未成组帧 ──")
        for f in remaining:
            paper = f.runtime.paper_variant_id or "-"
            ident = f.titleblock.internal_code or f.frame_id[:8]
            print(f"  {ident:30s} paper={paper}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
