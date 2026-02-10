"""
模块5 集成回归测试（1818仿真图.dxf）

运行方式:
    cd backend
    python -m pytest ../tools/run_module5_integration.py -v --tb=short -s

预期：
- 输出 11 个 dwg 与 11 个 pdf
- 文件名匹配 external_code(internal_code) 格式
- 001 图纸对应的 pdf 为 7 页

依赖：
- 需要 test/dwg/_dxf_out/1818仿真图.dxf 存在
- matplotlib 已安装
- ODA 不可用时仅验证 PDF 输出（DWG 跳过）
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import pytest

# 添加项目路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

DXF_PATH = PROJECT_ROOT / "test" / "dwg" / "_dxf_out" / "1818仿真图.dxf"

# 若 DXF 文件不存在则跳过全部测试
pytestmark = pytest.mark.skipif(
    not DXF_PATH.exists(),
    reason=f"测试DXF不存在: {DXF_PATH}",
)


def _run_pipeline_module2_to_5(dxf_path: Path, output_dir: Path):
    """运行模块2→3→4→5（裁切 + PDF导出），跳过DWG转换"""
    from src.cad import A4MultipageGrouper, FrameDetector, TitleblockExtractor
    from src.cad.dxf_pdf_exporter import DxfPdfExporter
    from src.cad.splitter import (
        FrameSplitter,
        output_name_for_frame,
        output_name_for_sheet_set,
    )

    # 模块2: 检测图框
    detector = FrameDetector()
    frames = detector.detect_frames(dxf_path)
    print(f"\n模块2: 检测到 {len(frames)} 个图框")

    # 模块3: 提取字段
    extractor = TitleblockExtractor()
    for frame in frames:
        try:
            extractor.extract_fields(dxf_path, frame)
        except Exception as e:
            print(f"  字段提取失败 {frame.frame_id[:8]}: {e}")

    # 模块4: A4成组
    grouper = A4MultipageGrouper()
    remaining, sheet_sets = grouper.group_a4_pages(frames)
    print(f"模块4: remaining={len(remaining)}, sheet_sets={len(sheet_sets)}")
    for ss in sheet_sets:
        print(f"  SheetSet pages={ss.page_total}, flags={ss.flags}")

    # 模块5: 裁切 + 导出
    split_dir = output_dir / "work" / "split"
    drawings_dir = output_dir / "drawings"
    split_dir.mkdir(parents=True, exist_ok=True)
    drawings_dir.mkdir(parents=True, exist_ok=True)

    # 创建mock ODA（集成测试不依赖ODA）
    class MockODA:
        def dxf_to_dwg(self, dxf_path, output_dir):
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

    # 裁切 remaining frames
    all_results = []  # (name, pdf_path, dwg_path, page_count)

    for frame in remaining:
        try:
            name = output_name_for_frame(frame)
            split_dxf = splitter.clip_frame(dxf_path, frame, split_dir)
            pdf_path = drawings_dir / f"{name}.pdf"
            splitter.pdf_exporter.export_single_page(split_dxf, pdf_path)
            dwg_path = splitter.oda.dxf_to_dwg(split_dxf, drawings_dir)
            all_results.append((name, pdf_path, dwg_path, 1))
            print(f"  单帧导出: {name}")
        except Exception as e:
            print(f"  单帧失败 {frame.frame_id[:8]}: {e}")

    # 裁切 sheet_sets
    for ss in sheet_sets:
        try:
            name = output_name_for_sheet_set(ss)
            split_dxf = splitter.clip_sheet_set(dxf_path, ss, split_dir)
            pdf_path = drawings_dir / f"{name}.pdf"
            page_bboxes = [p.outer_bbox for p in ss.pages]
            splitter.pdf_exporter.export_multipage(split_dxf, pdf_path, page_bboxes)
            dwg_path = splitter.oda.dxf_to_dwg(split_dxf, drawings_dir)
            all_results.append((name, pdf_path, dwg_path, ss.page_total))
            print(f"  A4成组导出: {name} ({ss.page_total}页)")
        except Exception as e:
            print(f"  A4成组失败 {ss.cluster_id[:8]}: {e}")

    return remaining, sheet_sets, all_results


class TestModule5Integration:
    """1818仿真图.dxf 集成回归测试"""

    def test_1818_produces_11_outputs(self):
        """应产出 11 个 dwg + 11 个 pdf"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            remaining, sheet_sets, results = _run_pipeline_module2_to_5(
                DXF_PATH, output_dir,
            )

            # 1818仿真图: 10 remaining + 1 sheet_set = 11
            total_outputs = len(results)
            print(f"\n总输出: {total_outputs}")
            for name, pdf, dwg, pages in results:
                print(f"  {name} (pdf={pdf.exists()}, dwg={dwg.exists()}, pages={pages})")

            assert total_outputs == 11, (
                f"预期11个输出，实际{total_outputs}"
            )

            # 检查所有PDF存在
            pdfs = [r[1] for r in results]
            for p in pdfs:
                assert p.exists(), f"PDF不存在: {p}"
            assert len(pdfs) == 11

            # 检查所有DWG存在
            dwgs = [r[2] for r in results]
            for d in dwgs:
                assert d.exists(), f"DWG不存在: {d}"
            assert len(dwgs) == 11

    def test_1818_naming_format(self):
        """文件名匹配 external_code(internal_code) 格式"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            _, _, results = _run_pipeline_module2_to_5(DXF_PATH, output_dir)

            # 检查至少有一些文件名包含 "(" 和 ")"
            named_with_parens = [
                name for name, _, _, _ in results if "(" in name and ")" in name
            ]
            print(f"\n带括号命名的文件: {len(named_with_parens)}/{len(results)}")
            # 有 titleblock 数据的帧应产出括号命名
            assert len(named_with_parens) > 0, "至少应有部分文件使用 external_code(internal_code) 命名"

    def test_1818_001_pdf_has_7_pages(self):
        """001 图纸的 pdf 应为 7 页"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            _, sheet_sets, results = _run_pipeline_module2_to_5(
                DXF_PATH, output_dir,
            )

            # 找到 001 图纸（A4成组，page_total=7）
            sheet_set_results = [
                (name, pdf, dwg, pages)
                for name, pdf, dwg, pages in results
                if pages > 1
            ]
            assert len(sheet_set_results) >= 1, "应有至少1个A4成组"

            # 检查 001 的页数
            for name, pdf_path, _, pages in sheet_set_results:
                if "-001" in name or pages == 7:
                    # 计算PDF页数
                    try:
                        from pypdf import PdfReader
                        reader = PdfReader(str(pdf_path))
                        actual_pages = len(reader.pages)
                        print(f"\n001 PDF: {name}, 页数={actual_pages}")
                        assert actual_pages == 7, (
                            f"001图纸PDF预期7页，实际{actual_pages}页"
                        )
                        return
                    except ImportError:
                        pytest.skip("pypdf 未安装，无法验证页数")
                    except Exception as e:
                        pytest.fail(f"读取PDF失败: {e}")

            # 如果没找到 001 图纸，检查 sheet_set 的 page_total
            for ss in sheet_sets:
                assert ss.page_total == 7, (
                    f"A4成组预期7页，实际{ss.page_total}页"
                )
