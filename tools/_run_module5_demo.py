"""运行模块5全链路演示 — 1818仿真图.dxf"""

import shutil
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "backend"))

DXF = PROJECT / "test" / "dwg" / "_dxf_out" / "1818仿真图.dxf"
OUT = PROJECT / "test" / "_module5_output_v3"

# 清理旧输出
if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True)

print(f"DXF: {DXF}")
print(f"DXF exists: {DXF.exists()}, size: {DXF.stat().st_size / 1024:.0f} KB")
print(f"Output dir: {OUT}")

from src.cad import A4MultipageGrouper, FrameDetector, TitleblockExtractor
from src.cad.dxf_pdf_exporter import DxfPdfExporter
from src.cad.splitter import (
    FrameSplitter,
    output_name_for_frame,
    output_name_for_sheet_set,
)

# ── Module 2 ──
print("\n=== Module 2: Frame Detection ===")
detector = FrameDetector()
frames = detector.detect_frames(DXF)
print(f"Detected {len(frames)} frames")

# ── Module 3 ──
print("\n=== Module 3: Titleblock Extraction ===")
extractor = TitleblockExtractor()
for i, f in enumerate(frames):
    try:
        extractor.extract_fields(DXF, f)
        ic = f.titleblock.internal_code or "(none)"
        ec = f.titleblock.external_code or "(none)"
        paper = f.runtime.paper_variant_id or "?"
        print(f"  [{i + 1:2d}] ic={ic}  ec={ec}  paper={paper}")
    except Exception as e:
        print(f"  [{i + 1:2d}] extract failed: {e}")

# ── Module 4 ──
print("\n=== Module 4: A4 Grouping ===")
grouper = A4MultipageGrouper()
remaining, sheet_sets = grouper.group_a4_pages(frames)
print(f"Remaining (non-A4): {len(remaining)}")
print(f"Sheet sets (A4 groups): {len(sheet_sets)}")
for ss in sheet_sets:
    tb = ss.get_inherited_titleblock()
    master_ic = tb.get("internal_code", "?")
    print(f"  SheetSet pages={ss.page_total}, master_ic={master_ic}, flags={ss.flags}")

# ── Module 5 ──
print("\n=== Module 5: Split + Export ===")
split_dir = OUT / "work" / "split"
drawings_dir = OUT / "drawings"
split_dir.mkdir(parents=True)
drawings_dir.mkdir(parents=True)


class MockODA:
    def dxf_to_dwg(self, dxf_path, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / f"{dxf_path.stem}.dwg"
        out.touch()
        return out


splitter = object.__new__(FrameSplitter)
splitter.spec = None
splitter.config = None
splitter.oda = MockODA()
splitter.margins = {"top": 20, "bottom": 10, "left": 20, "right": 10}
splitter.pdf_exporter = DxfPdfExporter(margins=splitter.margins)
splitter._margin_percent = 0.015

# Clip frames
print(f"\n--- Clipping {len(remaining)} single frames ---")
frame_splits = []
for f in remaining:
    try:
        name = output_name_for_frame(f)
        split_dxf = splitter.clip_frame(DXF, f, split_dir)
        frame_splits.append((f, split_dxf, name))
        print(f"  CLIP OK: {name}")
    except Exception as e:
        print(f"  CLIP FAIL: {f.frame_id[:8]} -> {e}")

# Clip sheet sets
print(f"\n--- Clipping {len(sheet_sets)} sheet sets ---")
ss_splits = []
for ss in sheet_sets:
    try:
        name = output_name_for_sheet_set(ss)
        split_dxf = splitter.clip_sheet_set(DXF, ss, split_dir)
        ss_splits.append((ss, split_dxf, name))
        print(f"  CLIP OK: {name} ({ss.page_total} pages)")
    except Exception as e:
        print(f"  CLIP FAIL: {ss.cluster_id[:8]} -> {e}")

# Export
print("\n--- Exporting PDFs + DWGs ---")
pdf_count = 0
dwg_count = 0

for f, split_dxf, name in frame_splits:
    try:
        pdf_path = drawings_dir / f"{name}.pdf"
        splitter.pdf_exporter.export_single_page(split_dxf, pdf_path)
        dwg_path = splitter.oda.dxf_to_dwg(split_dxf, drawings_dir)
        pdf_count += 1
        dwg_count += 1
        sz = pdf_path.stat().st_size / 1024
        print(f"  PDF+DWG: {name}.pdf ({sz:.1f} KB)")
    except Exception as e:
        print(f"  EXPORT FAIL: {name} -> {e}")

for ss, split_dxf, name in ss_splits:
    try:
        pdf_path = drawings_dir / f"{name}.pdf"
        page_bboxes = [p.outer_bbox for p in ss.pages]
        _, is_fallback = splitter.pdf_exporter.export_multipage(
            split_dxf, pdf_path, page_bboxes,
        )
        fb_mark = " [FALLBACK]" if is_fallback else ""
        dwg_path = splitter.oda.dxf_to_dwg(split_dxf, drawings_dir)
        pdf_count += 1
        dwg_count += 1
        sz = pdf_path.stat().st_size / 1024
        # PDF page count
        pg = "?"
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(pdf_path))
            pg = len(reader.pages)
        except Exception:
            pass
        print(f"  PDF+DWG: {name}.pdf ({sz:.1f} KB, {pg} pages){fb_mark}")
    except Exception as e:
        print(f"  EXPORT FAIL: {name} -> {e}")

# Summary
print(f"\n{'=' * 60}")
print(f"SUMMARY")
print(f"  Total PDF: {pdf_count}")
print(f"  Total DWG: {dwg_count}")
print(f"  Expected:  11 PDF + 11 DWG")
print(f"{'=' * 60}")

print(f"\nOutput directory: {OUT}")
print(f"\n--- drawings/ ---")
for p in sorted(drawings_dir.iterdir()):
    print(f"  {p.name:<70s}  {p.stat().st_size / 1024:>8.1f} KB")

print(f"\n--- work/split/ (intermediate DXFs) ---")
for p in sorted(split_dir.iterdir()):
    print(f"  {p.name:<70s}  {p.stat().st_size / 1024:>8.1f} KB")
