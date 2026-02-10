# -*- coding: utf-8 -*-
"""
诊断裁切 + external_code 提取问题

分析内容:
1. 裁切后 DXF (002) 的实体类型与数量
2. 原始 DXF 中 002 图框 outer_bbox 范围内的实体类型与数量
3. 两者差异（丢失了哪些实体类型）
4. external_code 提取结果：为什么全是 "DOCUMENTFCRFCNDENCI"
"""

import json
import sys
from collections import Counter
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "backend"))

import ezdxf
from ezdxf import bbox as ezdxf_bbox

from src.cad import FrameDetector, TitleblockExtractor
from src.models import BBox

# ── 路径 ──
ORIGINAL_DXF = PROJECT / "test" / "dwg" / "_dxf_out" / "1818仿真图.dxf"
CLIPPED_DXF = (
    PROJECT
    / "test"
    / "_module5_output"
    / "work"
    / "split"
    / "DOCUMENTFCRFCNDENCI(18185NX-JGS61-002).dxf"
)

SEPARATOR = "=" * 70


def count_entities(msp, label: str) -> Counter:
    """统计 modelspace 中的实体类型"""
    types = Counter(e.dxftype() for e in msp)
    print(f"\n{label}")
    print(f"  Total entities: {sum(types.values())}")
    for t, c in types.most_common():
        print(f"    {t:<20s} {c:>6d}")
    return types


def count_entities_in_bbox(msp, clip_bbox: BBox, label: str) -> Counter:
    """统计 bbox 范围内的实体类型（模拟裁切逻辑）"""
    cache = ezdxf_bbox.Cache()
    inside = Counter()
    outside = Counter()
    no_bbox_count = 0

    for entity in msp:
        tp = entity.dxftype()
        try:
            ext = ezdxf_bbox.extents([entity], cache=cache)
            if ext.has_data:
                eb = BBox(
                    xmin=ext.extmin.x,
                    ymin=ext.extmin.y,
                    xmax=ext.extmax.x,
                    ymax=ext.extmax.y,
                )
                if clip_bbox.intersects(eb):
                    inside[tp] += 1
                else:
                    outside[tp] += 1
            else:
                # No bbox → splitter keeps these (conservative)
                inside[tp] += 1
                no_bbox_count += 1
        except Exception:
            inside[tp] += 1
            no_bbox_count += 1

    print(f"\n{label}")
    print(f"  Entities inside bbox:  {sum(inside.values())}  (no_bbox kept: {no_bbox_count})")
    print(f"  Entities outside bbox: {sum(outside.values())}")
    for t, c in inside.most_common():
        print(f"    {t:<20s} {c:>6d}")
    return inside


def main():
    print(SEPARATOR)
    print("DIAGNOSE: Clip + External Code Issue")
    print(SEPARATOR)

    # ── 1. 读取裁切后 DXF ──
    print(f"\n[1] Clipped DXF: {CLIPPED_DXF.name}")
    print(f"    Exists: {CLIPPED_DXF.exists()}")
    if not CLIPPED_DXF.exists():
        print("    ERROR: Clipped DXF not found!")
        return
    print(f"    Size: {CLIPPED_DXF.stat().st_size / 1024:.1f} KB")

    clipped_doc = ezdxf.readfile(str(CLIPPED_DXF))
    clipped_msp = clipped_doc.modelspace()
    clipped_types = count_entities(clipped_msp, "Clipped DXF (002) entity types:")

    # ── 2. 读取原始 DXF, 找到 002 图框 ──
    print(f"\n{SEPARATOR}")
    print(f"\n[2] Original DXF: {ORIGINAL_DXF.name}")
    print(f"    Exists: {ORIGINAL_DXF.exists()}")
    if not ORIGINAL_DXF.exists():
        print("    ERROR: Original DXF not found!")
        return
    print(f"    Size: {ORIGINAL_DXF.stat().st_size / 1024:.1f} KB")

    orig_doc = ezdxf.readfile(str(ORIGINAL_DXF))
    orig_msp = orig_doc.modelspace()
    orig_types = count_entities(orig_msp, "Original DXF (full) entity types:")

    # 运行 FrameDetector
    print("\n  Running FrameDetector...")
    detector = FrameDetector()
    frames = detector.detect_frames(ORIGINAL_DXF)
    print(f"  Detected {len(frames)} frames")

    # 运行 TitleblockExtractor
    print("  Running TitleblockExtractor...")
    extractor = TitleblockExtractor()
    for f in frames:
        try:
            extractor.extract_fields(ORIGINAL_DXF, f)
        except Exception as e:
            print(f"    Extract failed for {f.frame_id[:8]}: {e}")

    # 打印所有帧的信息
    print(f"\n  All frames summary:")
    frame_002 = None
    for i, f in enumerate(frames):
        ic = f.titleblock.internal_code or "(none)"
        ec = f.titleblock.external_code or "(none)"
        paper = f.runtime.paper_variant_id or "?"
        ob = f.runtime.outer_bbox
        bbox_str = f"({ob.xmin:.0f},{ob.ymin:.0f})-({ob.xmax:.0f},{ob.ymax:.0f})"
        print(f"    [{i + 1:2d}] ic={ic:<25s} ec={ec:<25s} paper={paper:<15s} bbox={bbox_str}")

        # 找到 002 图框（通过 internal_code 匹配）
        if ic.endswith("-002"):
            frame_002 = f

    if frame_002 is None:
        print("\n    WARNING: Could not find frame with internal_code ending in '-002'")
        print("    Trying to match by filename pattern...")
        # 备选：如果internal_code不匹配，用排序后的第二个non-A4帧
        non_a4 = [f for f in frames if "A4" not in (f.runtime.paper_variant_id or "").upper()]
        if len(non_a4) >= 2:
            # 按bbox位置排序找到第二帧
            non_a4_sorted = sorted(non_a4, key=lambda f: (
                f.titleblock.internal_code or "", f.runtime.outer_bbox.xmin
            ))
            frame_002 = non_a4_sorted[1] if len(non_a4_sorted) > 1 else non_a4_sorted[0]
            print(f"    Using fallback frame: ic={frame_002.titleblock.internal_code}")

    if frame_002:
        ob = frame_002.runtime.outer_bbox
        margin = 0.015
        clip_bbox = BBox(
            xmin=ob.xmin - ob.width * margin,
            ymin=ob.ymin - ob.height * margin,
            xmax=ob.xmax + ob.width * margin,
            ymax=ob.ymax + ob.height * margin,
        )
        print(f"\n  002 Frame outer_bbox: ({ob.xmin:.1f}, {ob.ymin:.1f}) -> ({ob.xmax:.1f}, {ob.ymax:.1f})")
        print(f"  002 Frame clip_bbox:  ({clip_bbox.xmin:.1f}, {clip_bbox.ymin:.1f}) -> ({clip_bbox.xmax:.1f}, {clip_bbox.ymax:.1f})")
        print(f"  002 Frame size: {ob.width:.1f} x {ob.height:.1f}")

        orig_inside_types = count_entities_in_bbox(
            orig_msp, clip_bbox,
            "Original DXF entities inside 002 clip_bbox:",
        )

        # ── 3. 对比差异 ──
        print(f"\n{SEPARATOR}")
        print("\n[3] Comparison: Clipped vs Original-in-bbox")
        all_types = sorted(set(list(clipped_types.keys()) + list(orig_inside_types.keys())))
        print(f"\n  {'Entity Type':<20s} {'Clipped':>10s} {'Orig-in-bbox':>14s} {'Diff':>10s}")
        print(f"  {'-' * 20} {'-' * 10} {'-' * 14} {'-' * 10}")
        total_clipped = 0
        total_orig = 0
        for tp in all_types:
            c = clipped_types.get(tp, 0)
            o = orig_inside_types.get(tp, 0)
            diff = c - o
            diff_str = f"{diff:+d}" if diff != 0 else "="
            marker = " <<<" if diff < 0 else ""
            print(f"  {tp:<20s} {c:>10d} {o:>14d} {diff_str:>10s}{marker}")
            total_clipped += c
            total_orig += o
        diff_total = total_clipped - total_orig
        print(f"  {'TOTAL':<20s} {total_clipped:>10d} {total_orig:>14d} {diff_total:+d}")

        # 找出丢失最多的类型
        lost_types = {}
        for tp in all_types:
            c = clipped_types.get(tp, 0)
            o = orig_inside_types.get(tp, 0)
            if c < o:
                lost_types[tp] = o - c
        if lost_types:
            print(f"\n  LOST entity types (clipped < original-in-bbox):")
            for tp, lost in sorted(lost_types.items(), key=lambda x: -x[1]):
                print(f"    {tp}: lost {lost} entities")
        else:
            print(f"\n  No entity types lost (clipped >= original for all types)")

    # ── 4. 检查 external_code 提取结果 ──
    print(f"\n{SEPARATOR}")
    print("\n[4] External Code Extraction Diagnosis")

    for i, f in enumerate(frames):
        ec = f.titleblock.external_code
        ic = f.titleblock.internal_code
        paper = f.runtime.paper_variant_id or "?"
        print(f"\n  Frame [{i + 1:2d}] paper={paper}")
        print(f"    internal_code = {ic}")
        print(f"    external_code = {ec}")

        # 检查 raw_extracts 中与 external_code 相关的内容
        if f.raw_extracts:
            for key, items in f.raw_extracts.items():
                if "外部" in key or "external" in key.lower() or "DOC" in key.upper():
                    print(f"    raw_extracts['{key}']:")
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, dict):
                                text = item.get("text", "")
                                x = item.get("x", "?")
                                y = item.get("y", "?")
                                src = item.get("source", "?")
                                print(f"      text='{text}' at ({x}, {y}) src={src}")
                            else:
                                print(f"      {item}")
                    else:
                        print(f"      {items}")

            # 也打印所有 raw_extracts 的 keys，帮助理解
            all_keys = list(f.raw_extracts.keys())
            print(f"    raw_extracts keys: {all_keys}")

            # 专门查找外部编码的 raw data
            for key in all_keys:
                items = f.raw_extracts[key]
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    text = str(item.get("text", ""))
                    # 检查是否包含类似外部编码的文本（19位字母数字）
                    cleaned = "".join(
                        ch for ch in text.upper() if ch.isalnum()
                    )
                    if len(cleaned) >= 15:
                        print(f"    ** Long alnum in '{key}': text='{text}' cleaned='{cleaned}' (len={len(cleaned)})")

    # ── 5. 深入诊断: 在 002 图框的外部编码 ROI 区域内有什么文本 ──
    print(f"\n{SEPARATOR}")
    print("\n[5] Deep dive: Text in 002 frame's external_code ROI region")

    if frame_002:
        profile_id = frame_002.runtime.roi_profile_id or "BASE10"
        profile = extractor.spec.get_roi_profile(profile_id)
        if profile:
            field_defs = extractor.spec.get_field_definitions()
            ec_def = field_defs.get("external_code")
            if ec_def and ec_def.roi:
                roi_name = ec_def.roi
                rb_offset = profile.fields.get(roi_name)
                if rb_offset:
                    ob = frame_002.runtime.outer_bbox
                    sx = frame_002.runtime.sx or 1.0
                    sy = frame_002.runtime.sy or 1.0

                    # Restore ROI
                    roi = extractor._restore_roi(ob, rb_offset, sx, sy)
                    print(f"    ROI '{roi_name}' rb_offset={rb_offset}")
                    print(f"    Restored ROI: ({roi.xmin:.1f}, {roi.ymin:.1f}) -> ({roi.xmax:.1f}, {roi.ymax:.1f})")
                    print(f"    ROI size: {roi.width:.1f} x {roi.height:.1f}")
                    print(f"    sx={sx}, sy={sy}")

                    # Find all text items in the original DXF
                    all_text = list(extractor._iter_text_items(orig_msp))
                    print(f"    Total text items in original DXF: {len(all_text)}")

                    # Filter items in ROI (with margin)
                    expanded_roi = extractor._expand_roi(roi, extractor.roi_margin_percent)
                    in_roi = [
                        t for t in all_text
                        if extractor._item_in_roi(t, expanded_roi, use_bbox=True)
                    ]
                    print(f"    Text items in ROI (margin={extractor.roi_margin_percent}): {len(in_roi)}")
                    for t in in_roi:
                        print(f"      text='{t.text}' at ({t.x:.1f}, {t.y:.1f}) src={t.source} h={t.text_height}")

                    # Also check: what does _parse_external_code produce?
                    parse_cfg = (ec_def.parse or {})
                    print(f"\n    Parse config: {parse_cfg}")
                    joined = extractor._join_text(in_roi)
                    print(f"    Joined text: '{joined}'")
                    cleaned = extractor._clean_alnum(joined.upper())
                    print(f"    Cleaned alnum: '{cleaned}' (len={len(cleaned)})")

                    # Check header stripping
                    header_hint = str(parse_cfg.get("header", "DOC.NO"))
                    header_clean = extractor._clean_alnum(header_hint.upper())
                    print(f"    Header hint: '{header_hint}' -> cleaned: '{header_clean}'")
                    if header_clean and cleaned.startswith(header_clean):
                        stripped = cleaned[len(header_clean):]
                        print(f"    After header strip: '{stripped}' (len={len(stripped)})")
                    else:
                        print(f"    Header not found at start of cleaned text")

                    fixed_len = int(parse_cfg.get("length", parse_cfg.get("fixed_len", 19)))
                    print(f"    Expected fixed_len: {fixed_len}")

                    # Try rebuild from single chars
                    rebuilt = extractor._rebuild_fixed19_from_single_chars(
                        in_roi, fixed_len, header_hint
                    )
                    print(f"    Rebuild from single chars: '{rebuilt}'")

                    # Show what the ROI text looks like for all frames
                    print(f"\n    --- Checking external_code ROI text for ALL frames ---")
                    for i, f in enumerate(frames):
                        if "A4" in (f.runtime.paper_variant_id or "").upper():
                            continue
                        fob = f.runtime.outer_bbox
                        fsx = f.runtime.sx or 1.0
                        fsy = f.runtime.sy or 1.0
                        froi = extractor._restore_roi(fob, rb_offset, fsx, fsy)
                        froi_exp = extractor._expand_roi(froi, extractor.roi_margin_percent)
                        f_in_roi = [
                            t for t in all_text
                            if extractor._item_in_roi(t, froi_exp, use_bbox=True)
                        ]
                        fjoined = extractor._join_text(f_in_roi)
                        fcleaned = extractor._clean_alnum(fjoined.upper())
                        print(
                            f"      Frame [{i + 1:2d}] ic={f.titleblock.internal_code or '?':<25s} "
                            f"ec_roi_text='{fjoined[:60]}' cleaned='{fcleaned}' (len={len(fcleaned)})"
                        )
                else:
                    print(f"    ROI field '{roi_name}' not found in profile '{profile_id}'")
            else:
                print(f"    external_code field definition not found or no ROI")
        else:
            print(f"    Profile '{profile_id}' not found")

    print(f"\n{SEPARATOR}")
    print("DIAGNOSIS COMPLETE")
    print(SEPARATOR)


if __name__ == "__main__":
    main()
