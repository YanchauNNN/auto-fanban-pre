# -*- coding: utf-8 -*-
"""
模块5 通用测试脚本 — CLI 调用

用法:
    python tools/run_module5_test.py <DXF文件路径>
    python tools/run_module5_test.py test/dwg/_dxf_out/2016仿真图.dxf
    python tools/run_module5_test.py test/dwg/_dxf_out/1818仿真图.dxf

输出:
    test/_module5_out_<stem>/
        work/split/*.dxf   — 中间裁切 DXF
        drawings/*.dwg     — DWG (ODA 真实转换)
        drawings/*.pdf     — PDF (黑白，带页边距)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "backend"))

ODA_EXE = PROJECT / "bin" / "ODAFileConverter 25.12.0" / "ODAFileConverter.exe"


def parse_args():
    parser = argparse.ArgumentParser(description="模块5 裁切/导出 集成测试")
    parser.add_argument("dxf", type=Path, help="输入 DXF 文件路径")
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="输出根目录 (默认: test/_module5_out_<stem>)",
    )
    parser.add_argument(
        "--no-pdf", action="store_true", help="跳过 PDF 导出（仅生成 DXF+DWG）",
    )
    parser.add_argument(
        "--no-dwg", action="store_true", help="跳过 DWG 转换（ODA 不可用时使用）",
    )
    return parser.parse_args()


def batch_dxf_to_dwg(split_dir: Path, drawings_dir: Path) -> int:
    """用 ODA 批量转换 split_dir 下所有 DXF → drawings_dir 下 DWG"""
    if not ODA_EXE.exists():
        print(f"  [WARN] ODA 不存在: {ODA_EXE}，跳过 DWG 转换")
        return 0
    dxf_files = list(split_dir.glob("*.dxf"))
    if not dxf_files:
        return 0

    cmd = [
        str(ODA_EXE),
        str(split_dir),       # 输入目录
        str(drawings_dir),    # 输出目录
        "ACAD2018",           # 输出版本
        "DWG",                # 输出格式
        "0",                  # 不递归
        "1",                  # 审计修复
        "*.dxf",              # 过滤器：转换目录下所有 dxf
    ]
    print(f"  ODA 批量转换: {len(dxf_files)} 个 DXF → DWG ...")
    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    elapsed = time.time() - t0
    dwg_count = len(list(drawings_dir.glob("*.dwg")))
    ok = "OK" if result.returncode == 0 else f"returncode={result.returncode}"
    print(f"  ODA 完成: {ok}, 产出 {dwg_count} 个 DWG, 耗时 {elapsed:.1f}s")
    if result.returncode != 0 and result.stderr:
        print(f"  stderr: {result.stderr[:300]}")
    return dwg_count


def main():
    args = parse_args()

    dxf_path = args.dxf.resolve()
    if not dxf_path.exists():
        print(f"错误: DXF 文件不存在: {dxf_path}")
        sys.exit(1)

    out = args.output or (PROJECT / "test" / f"_module5_out_{dxf_path.stem}")
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)

    split_dir = out / "work" / "split"
    drawings_dir = out / "drawings"
    split_dir.mkdir(parents=True)
    drawings_dir.mkdir(parents=True)

    print(f"输入: {dxf_path} ({dxf_path.stat().st_size / 1024:.0f} KB)")
    print(f"输出: {out}")

    # === Module 2: 图框检测 ===
    from src.cad import A4MultipageGrouper, FrameDetector, TitleblockExtractor

    print("\n[Module 2] 图框检测 ...")
    t0 = time.time()
    detector = FrameDetector()
    frames = detector.detect_frames(dxf_path)
    print(f"  检测到 {len(frames)} 个图框 ({time.time() - t0:.1f}s)")

    # === Module 3: 图签提取 ===
    print("\n[Module 3] 图签提取 ...")
    extractor = TitleblockExtractor()
    for i, f in enumerate(frames):
        try:
            extractor.extract_fields(dxf_path, f)
        except Exception as e:
            print(f"  [{i + 1}] 提取失败: {e}")
    # 汇总
    has_ic = sum(1 for f in frames if f.titleblock.internal_code)
    has_ec = sum(1 for f in frames if f.titleblock.external_code)
    print(f"  internal_code: {has_ic}/{len(frames)}, external_code: {has_ec}/{len(frames)}")

    # === Module 4: A4 成组 ===
    print("\n[Module 4] A4 成组 ...")
    grouper = A4MultipageGrouper()
    remaining, sheet_sets = grouper.group_a4_pages(frames)
    print(f"  单帧: {len(remaining)}, A4成组: {len(sheet_sets)}")
    for ss in sheet_sets:
        tb = ss.get_inherited_titleblock()
        print(f"    SheetSet pages={ss.page_total}, ic={tb.get('internal_code', '?')}")

    # === Module 5a: 裁切 ===
    from src.cad.dxf_pdf_exporter import DxfPdfExporter
    from src.cad.splitter import (
        FrameSplitter,
        output_name_for_frame,
        output_name_for_sheet_set,
    )

    # 构造 splitter（绕过 load_spec，直接注入参数）
    splitter = object.__new__(FrameSplitter)
    splitter.spec = None
    splitter.config = None
    splitter.oda = None
    splitter.margins = {"top": 20, "bottom": 10, "left": 20, "right": 10}
    splitter.pdf_exporter = DxfPdfExporter(margins=splitter.margins)
    splitter._margin_percent = 0.015

    total = len(remaining) + len(sheet_sets)
    print(f"\n[Module 5a] 裁切 {total} 个图框 ...")
    t0 = time.time()

    frame_clips: list[tuple] = []
    for f in remaining:
        try:
            name = output_name_for_frame(f)
            clip_dxf = splitter.clip_frame(dxf_path, f, split_dir)
            frame_clips.append((f, clip_dxf, name))
        except Exception as e:
            print(f"  裁切失败 {f.frame_id[:8]}: {e}")

    ss_clips: list[tuple] = []
    for ss in sheet_sets:
        try:
            name = output_name_for_sheet_set(ss)
            clip_dxf = splitter.clip_sheet_set(dxf_path, ss, split_dir)
            ss_clips.append((ss, clip_dxf, name))
        except Exception as e:
            print(f"  A4裁切失败 {ss.cluster_id[:8]}: {e}")

    dxf_count = len(frame_clips) + len(ss_clips)
    print(f"  产出 {dxf_count} 个中间 DXF ({time.time() - t0:.1f}s)")

    # === Module 5b: DWG 转换（ODA 批量） ===
    dwg_count = 0
    if not args.no_dwg:
        print("\n[Module 5b] DWG 转换 (ODA) ...")
        dwg_count = batch_dxf_to_dwg(split_dir, drawings_dir)
    else:
        print("\n[Module 5b] DWG 转换 — 已跳过 (--no-dwg)")

    # === Module 5c: PDF 导出（黑白） ===
    pdf_count = 0
    if not args.no_pdf:
        print("\n[Module 5c] PDF 导出（黑白）...")
        t0 = time.time()
        for f, clip_dxf, name in frame_clips:
            try:
                pdf_path = drawings_dir / f"{name}.pdf"
                splitter.pdf_exporter.export_single_page(clip_dxf, pdf_path)
                pdf_count += 1
                sz = pdf_path.stat().st_size / 1024
                print(f"  {name}.pdf ({sz:.0f} KB)")
            except Exception as e:
                print(f"  PDF失败 {name}: {e}")

        for ss, clip_dxf, name in ss_clips:
            try:
                pdf_path = drawings_dir / f"{name}.pdf"
                page_bboxes = [p.outer_bbox for p in ss.pages]
                _, fallback = splitter.pdf_exporter.export_multipage(
                    clip_dxf, pdf_path, page_bboxes,
                )
                pdf_count += 1
                sz = pdf_path.stat().st_size / 1024
                pg = "?"
                try:
                    from pypdf import PdfReader

                    pg = len(PdfReader(str(pdf_path)).pages)
                except Exception:
                    pass
                fb = " [兜底]" if fallback else ""
                print(f"  {name}.pdf ({sz:.0f} KB, {pg}页){fb}")
            except Exception as e:
                print(f"  PDF失败 {name}: {e}")
        print(f"  PDF 导出完成 ({time.time() - t0:.1f}s)")
    else:
        print("\n[Module 5c] PDF 导出 — 已跳过 (--no-pdf)")

    # === 汇总 ===
    print(f"\n{'=' * 60}")
    print(f"  DXF 中间产物:  {dxf_count}")
    print(f"  DWG 输出:      {dwg_count}")
    print(f"  PDF 输出:      {pdf_count}")
    print(f"{'=' * 60}")

    print(f"\n输出目录: {out}")
    print("\ndrawings/:")
    for p in sorted(drawings_dir.iterdir()):
        print(f"  {p.name:<65s} {p.stat().st_size / 1024:>8.1f} KB")


if __name__ == "__main__":
    main()
