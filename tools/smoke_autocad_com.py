# -*- coding: utf-8 -*-
"""
AutoCAD COM 出图冒烟测试（短测）
仅测试 001 / 002 两个 split DXF，且同批任务只启动一次 AutoCAD。
用法:
    python tools/smoke_autocad_com.py
"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from src.cad import FrameDetector, TitleblockExtractor  # noqa: E402
from src.cad.autocad_pdf_exporter import AutoCADPdfExporter  # noqa: E402

OUT_DIR = PROJECT_ROOT / "test" / "_acad_smoke_out"
TARGET_FILES = [
    "JD1NHH11001B25C42SD(20161NH-JGS03-001).dxf",
    "JD1NHH11002B25C42SD(20161NH-JGS03-002).dxf",
]


def _resolve_target_paths() -> list[Path]:
    all_candidates = list((PROJECT_ROOT / "test").glob("**/*.dxf"))
    by_name = {p.name: p for p in all_candidates}
    resolved: list[Path] = []
    missing: list[str] = []
    for name in TARGET_FILES:
        path = by_name.get(name)
        if path is None:
            missing.append(name)
        else:
            resolved.append(path)
    if missing:
        print("[SKIP] 缺少目标 split DXF：")
        for n in missing:
            print(f"  - {n}")
        print("请先运行模块5切割流程后再执行本脚本。")
        sys.exit(0)
    return resolved


def _extract_internal_code_from_name(file_name: str) -> str | None:
    match = re.search(r"\(([^()]+)\)\.dxf$", file_name, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1)


def _paper_size_from_variant(variant_id: str | None):
    mapping = {
        "CNPE_A0": (1189.0, 841.0),
        "CNPE_A1": (841.0, 594.0),
        "CNPE_A2": (594.0, 420.0),
        "CNPE_A3": (420.0, 297.0),
        "CNPE_A4": (297.0, 210.0),
    }
    if not variant_id:
        return None
    return mapping.get(variant_id)


def _load_source_frame_info() -> dict[str, tuple[object, tuple[float, float] | None]]:
    source_candidates = [
        p
        for p in (PROJECT_ROOT / "test" / "dwg" / "_dxf_out").glob("*.dxf")
        if "2016" in p.name
    ]
    if not source_candidates:
        raise RuntimeError("未找到 2016 源DXF，无法提取原始图框定位数据")

    source_dxf = source_candidates[0]
    detector = FrameDetector()
    extractor = TitleblockExtractor()
    frames = detector.detect_frames(source_dxf)

    frame_info: dict[str, tuple[object, tuple[float, float] | None]] = {}
    for frame in frames:
        try:
            extractor.extract_fields(source_dxf, frame)
        except Exception:
            continue
        internal_code = frame.titleblock.internal_code
        if internal_code:
            paper_size = _paper_size_from_variant(frame.runtime.paper_variant_id)
            frame_info[internal_code] = (frame.runtime.outer_bbox, paper_size)
    return frame_info


OUT_DIR.mkdir(parents=True, exist_ok=True)
exp = AutoCADPdfExporter(visible=False, plot_timeout_sec=120, retry=1)
dxf_files = _resolve_target_paths()
frame_info_map = _load_source_frame_info()
jobs = []

for dxf in dxf_files:
    out_pdf = OUT_DIR / f"{dxf.stem}.pdf"
    internal_code = _extract_internal_code_from_name(dxf.name)
    if not internal_code:
        print(f"  [FAIL] 无法从文件名解析 internal_code: {dxf.name}")
        sys.exit(1)
    frame_info = frame_info_map.get(internal_code)
    if frame_info is None:
        print(f"  [FAIL] 源DXF未找到对应图框坐标: {internal_code}")
        sys.exit(1)
    bbox, paper_size_mm = frame_info
    print(
        f"  [job] {dxf.name} | ic={internal_code} | bbox=({bbox.xmin:.2f}, {bbox.ymin:.2f},"
        f" {bbox.xmax:.2f}, {bbox.ymax:.2f}) | paper={paper_size_mm}",
    )
    jobs.append((dxf, out_pdf, bbox, paper_size_mm))

try:
    exp.export_single_page_batch(jobs)
except Exception as exc:
    print(f"  [FAIL] 批量出图失败: {exc}")
    sys.exit(1)

for _, out_pdf, _, _ in jobs:
    if not out_pdf.exists():
        print(f"  [FAIL] 未生成: {out_pdf.name}")
        sys.exit(1)
    size_kb = out_pdf.stat().st_size / 1024
    print(f"  [OK]  {out_pdf.name}  {size_kb:.0f} KB")

print(f"\n全部冒烟通过，输出在: {OUT_DIR}")
