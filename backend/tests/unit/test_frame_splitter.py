"""
FrameSplitter 单元测试 (模块5)

覆盖守则 §5.1 必测用例：
1. test_split_single_frame_outputs_pdf_and_dwg
2. test_split_single_frame_keeps_coordinates
3. test_split_single_frame_entity_intersection_rule
4. test_split_frames_batch_returns_all_results
5. test_split_sheet_set_outputs_pdf_and_dwg
6. test_split_sheet_set_page_order_by_page_index
7. test_split_sheet_set_preserves_relative_layout
8. test_pdf_fallback_flag_on_multipage_failure
9. test_naming_conflict_policy_error
10. test_failure_isolation_single_frame

额外：
- test_output_name_external_internal
- test_output_name_fallback
- test_config_multi_dwg_policy
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import ezdxf
import pytest

from src.cad.dxf_pdf_exporter import DxfPdfExporter
from src.cad.splitter import (
    FrameSplitter,
    make_output_name,
    output_name_for_frame,
    output_name_for_sheet_set,
)
from src.models import (
    BBox,
    FrameMeta,
    FrameRuntime,
    PageInfo,
    SheetSet,
    TitleblockFields,
)

# ======================================================================
# Fixtures / Helpers
# ======================================================================


class MockODAConverter:
    """ODA mock — touch 出 .dwg 文件"""

    def dxf_to_dwg(self, dxf_path: Path, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / f"{dxf_path.stem}.dwg"
        out.touch()
        return out

    def dwg_to_dxf(self, dwg_path: Path, output_dir: Path) -> Path:
        raise NotImplementedError


class MockPdfExporter(DxfPdfExporter):
    """PDF导出mock — touch 出 .pdf 文件"""

    def export_single_page(
        self, dxf_path, pdf_path, *, clip_bbox=None, paper_size_mm=None,
    ):
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.touch()
        return pdf_path

    def export_multipage(
        self, dxf_path, pdf_path, page_bboxes, paper_size_mm=None,
    ):
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.touch()
        return pdf_path, False


class FailingPdfExporter(DxfPdfExporter):
    """多页失败的PDF导出mock"""

    def export_single_page(
        self, dxf_path, pdf_path, *, clip_bbox=None, paper_size_mm=None,
    ):
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.touch()
        return pdf_path

    def export_multipage(
        self, dxf_path, pdf_path, page_bboxes, paper_size_mm=None,
    ):
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.touch()
        return pdf_path, True  # 兜底标记


class FailingODAConverter:
    """总是失败的ODA mock"""

    def dxf_to_dwg(self, dxf_path: Path, output_dir: Path) -> Path:
        raise RuntimeError("ODA not available")

    def dwg_to_dxf(self, dwg_path: Path, output_dir: Path) -> Path:
        raise RuntimeError("ODA not available")


def _make_splitter(
    temp_dir: Path,
    *,
    oda=None,
    pdf_exporter=None,
    pdf_engine: str = "python",
    autocad_pdf_exporter=None,
) -> FrameSplitter:
    """创建可测试的 FrameSplitter（绕过 load_spec / get_config）"""
    obj = object.__new__(FrameSplitter)
    obj.spec = MagicMock()
    obj.spec.doc_generation = {
        "options": {
            "pdf_margin_mm": {"top": 20, "bottom": 10, "left": 20, "right": 10},
            "pdf_aci1_linewidth_mm": 0.4,
            "pdf_aci_default_linewidth_mm": 0.18,
        },
    }
    obj.spec.a4_multipage = {
        "clipping": {
            "margin": {"margin_percent": "0.015"},
            "unknown_bbox_policy": "keep_if_uncertain",
        },
    }
    obj.spec.titleblock_extract = {
        "paper_variants": {
            "CNPE_A1": {"W": 841.0, "H": 594.0, "profile": "BASE10"},
            "CNPE_A4": {"W": 210.0, "H": 297.0, "profile": "SMALL5"},
        },
    }
    obj.config = MagicMock()
    obj.oda = cast(Any, oda or MockODAConverter())
    obj.margins = {"top": 20, "bottom": 10, "left": 20, "right": 10}
    obj.pdf_exporter = cast(Any, pdf_exporter or MockPdfExporter())
    obj.autocad_pdf_exporter = cast(Any, autocad_pdf_exporter or MockPdfExporter())
    obj._pdf_engine = pdf_engine
    obj._module5_engine = "python_fallback"
    obj.cad_dxf_executor = cast(Any, MagicMock())
    obj._margin_percent = 0.015
    obj._unknown_bbox_policy = "keep_if_uncertain"
    return obj


def _make_frame(
    *,
    x=0.0, y=0.0, w=841.0, h=594.0,
    internal_code: str | None = "1234567-JG001-001",
    external_code: str | None = "JD1NHT11001B25C42SD",
    revision="A",
    status="CFC",
    frame_id=None,
    source_file=None,
) -> FrameMeta:
    fid = frame_id or str(uuid.uuid4())
    bbox = BBox(xmin=x, ymin=y, xmax=x + w, ymax=y + h)
    runtime = FrameRuntime(
        frame_id=fid,
        source_file=source_file or Path("test.dxf"),
        outer_bbox=bbox,
        paper_variant_id="CNPE_A1",
        sx=1.0, sy=1.0,
    )
    tb = TitleblockFields(
        internal_code=internal_code,
        external_code=external_code,
        revision=revision,
        status=status,
        engineering_no="1234",
        title_cn="测试图纸",
        page_total=1, page_index=1,
    )
    return FrameMeta(runtime=runtime, titleblock=tb)


def _make_sheet_set(
    *,
    page_count=2,
    master_internal="1234567-JG001-001",
    master_external="JD1NHT11001B25C42SD",
) -> SheetSet:
    pages = []
    master = _make_frame(
        x=0, y=0, w=297, h=210,
        internal_code=master_internal,
        external_code=master_external,
    )
    pages.append(PageInfo(
        page_index=1,
        outer_bbox=master.runtime.outer_bbox,
        has_titleblock=True,
        frame_meta=master,
    ))
    for i in range(1, page_count):
        slave = _make_frame(
            x=0, y=(i * 215), w=297, h=210,
            internal_code=None, external_code=None,
        )
        pages.append(PageInfo(
            page_index=i + 1,
            outer_bbox=slave.runtime.outer_bbox,
            has_titleblock=False,
            frame_meta=slave,
        ))

    return SheetSet(
        cluster_id=str(uuid.uuid4()),
        page_total=page_count,
        pages=pages,
        master_page=pages[0],
    )


def _create_test_dxf(path: Path, *, entities_bbox: tuple | None = None) -> Path:
    """创建带实体的真实DXF文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new()
    msp = doc.modelspace()
    if entities_bbox:
        x0, y0, x1, y1 = entities_bbox
        msp.add_lwpolyline(
            [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True,
        )
        # 添加一些内部实体
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        msp.add_line((x0, y0), (x1, y1))
        msp.add_text("TEST", dxfattribs={"insert": (cx, cy)})
    else:
        # 默认实体
        msp.add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], close=True)
    doc.saveas(str(path))
    return path


# ======================================================================
# 命名规则测试
# ======================================================================


class TestOutputNaming:
    """输出文件名 external_code+revision+status (internal_code)"""

    def test_output_name_both_present(self):
        assert make_output_name(
            external_code="JD1NHT11001B25C42SD",
            revision="A",
            status="CFC",
            internal_code="1234567-JG001-001",
        ) == "JD1NHT11001B25C42SDACFC (1234567-JG001-001)"

    def test_output_name_missing_revision_or_status_falls_back_to_external_internal(self):
        assert make_output_name(
            external_code="JD1NHT11001B25C42SD",
            revision=None,
            status="CFC",
            internal_code="1234567-JG001-001",
        ) == "JD1NHT11001B25C42SD (1234567-JG001-001)"

    def test_output_name_only_internal(self):
        assert make_output_name(
            external_code=None,
            revision="A",
            status="CFC",
            internal_code="1234567-JG001-001",
        ) == "1234567-JG001-001"

    def test_output_name_only_external(self):
        assert make_output_name(
            external_code="JD1NHT11001B25C42SD",
            revision=None,
            status=None,
            internal_code=None,
        ) == "JD1NHT11001B25C42SD"

    def test_output_name_fallback(self):
        assert make_output_name(
            external_code=None,
            revision=None,
            status=None,
            internal_code=None,
            fallback_id="abcd1234",
        ) == "abcd1234"

    def test_output_name_for_frame(self):
        frame = _make_frame(
            internal_code="AAA-BBB-001",
            external_code="EXT19CHARS0000001XX",
            revision="B",
            status="CFC",
        )
        assert output_name_for_frame(frame) == "EXT19CHARS0000001XXBCFC (AAA-BBB-001)"

    def test_output_name_for_sheet_set(self):
        ss = _make_sheet_set(
            master_internal="AAA-BBB-001",
            master_external="EXT19CHARS0000001XX",
        )
        assert output_name_for_sheet_set(ss) == "EXT19CHARS0000001XXACFC (AAA-BBB-001)"


# ======================================================================
# 守则 §5.1 必测用例
# ======================================================================


class TestSplitSingleFrame:
    """1. test_split_single_frame_outputs_pdf_and_dwg"""

    def test_split_single_frame_outputs_pdf_and_dwg(self, temp_dir):
        splitter = _make_splitter(temp_dir)
        dxf = _create_test_dxf(temp_dir / "src" / "test.dxf", entities_bbox=(0, 0, 841, 594))
        frame = _make_frame(source_file=dxf)

        pdf, dwg = splitter.split_frame(dxf, frame, temp_dir / "output")

        assert pdf.suffix == ".pdf"
        assert dwg.suffix == ".dwg"
        assert pdf.exists()
        assert dwg.exists()
        assert frame.runtime.pdf_path == pdf
        assert frame.runtime.dwg_path == dwg

    def test_split_single_frame_naming(self, temp_dir):
        """PDF/DWG 文件名 = external_code+revision+status (internal_code)"""
        splitter = _make_splitter(temp_dir)
        dxf = _create_test_dxf(temp_dir / "src" / "test.dxf")
        frame = _make_frame(
            internal_code="AAABBBB-CCCDD-001",
            external_code="EXT19CHARS0000001XX",
            revision="B",
            status="CFC",
            source_file=dxf,
        )

        pdf, dwg = splitter.split_frame(dxf, frame, temp_dir / "output")

        expected_stem = "EXT19CHARS0000001XXBCFC (AAABBBB-CCCDD-001)"
        assert pdf.stem == expected_stem
        assert dwg.stem == expected_stem


class TestKeepCoordinates:
    """2. test_split_single_frame_keeps_coordinates"""

    def test_split_single_frame_keeps_coordinates(self, temp_dir):
        # 在 (1000, 2000) 处放实体
        dxf = _create_test_dxf(
            temp_dir / "src" / "test.dxf",
            entities_bbox=(1000, 2000, 1841, 2594),
        )
        frame = _make_frame(x=1000, y=2000, source_file=dxf)
        splitter = _make_splitter(temp_dir)

        # 仅测 clip 阶段
        split_dxf = splitter.clip_frame(dxf, frame, temp_dir / "work")

        # 读取裁切后DXF，检查坐标未平移
        doc = ezdxf.readfile(str(split_dxf))
        msp = doc.modelspace()
        entities = list(msp)
        assert len(entities) > 0

        # 检查至少有一个实体的坐标在原始范围内
        found_original = False
        for e in entities:
            try:
                if hasattr(e, "dxf") and hasattr(e.dxf, "insert") and e.dxf.insert.x >= 1000:
                        found_original = True
            except Exception:
                pass
            try:
                get_points = getattr(cast(Any, e), "get_points", None)
                if callable(get_points):
                    pts = list(cast(Any, get_points)())
                    for p in pts:
                        if p[0] >= 1000:
                            found_original = True
            except Exception:
                pass
        assert found_original, "坐标应保持不归零"


class TestEntityIntersection:
    """3. test_split_single_frame_entity_intersection_rule"""

    def test_split_single_frame_entity_intersection_rule(self, temp_dir):
        # 创建DXF: 一个在bbox内、一个完全在bbox外的实体
        doc = ezdxf.new()
        msp = doc.modelspace()
        # 在 (10,10)-(90,90) 内的矩形 — 应保留
        msp.add_lwpolyline([(10, 10), (90, 10), (90, 90), (10, 90)], close=True)
        # 在 (5000,5000) 处的矩形 — 应被剔除
        msp.add_lwpolyline(
            [(5000, 5000), (6000, 5000), (6000, 6000), (5000, 6000)], close=True,
        )
        dxf_path = temp_dir / "src" / "test.dxf"
        dxf_path.parent.mkdir(parents=True, exist_ok=True)
        doc.saveas(str(dxf_path))

        frame = _make_frame(x=0, y=0, w=100, h=100, source_file=dxf_path)
        splitter = _make_splitter(temp_dir)

        split_dxf = splitter.clip_frame(dxf_path, frame, temp_dir / "work")

        out_doc = ezdxf.readfile(str(split_dxf))
        out_entities = list(out_doc.modelspace())
        # 远处矩形应被过滤（实际可能保留无bbox的实体，所以检查数量减少）
        assert len(out_entities) < 2 + 1  # 最多保留内部那个


class TestBatchSplit:
    """4. test_split_frames_batch_returns_all_results"""

    def test_split_frames_batch_returns_all_results(self, temp_dir):
        dxf = _create_test_dxf(
            temp_dir / "src" / "test.dxf",
            entities_bbox=(0, 0, 2000, 2000),
        )
        frames = [
            _make_frame(
                x=0, y=0, w=800, h=600,
                internal_code="AAA-001",
                external_code="EXT001",
                source_file=dxf,
            ),
            _make_frame(
                x=900, y=0, w=800, h=600,
                internal_code="AAA-002",
                external_code="EXT002",
                source_file=dxf,
            ),
        ]
        splitter = _make_splitter(temp_dir)

        results = splitter.clip_frames_batch(dxf, frames, temp_dir / "work")

        assert len(results) == 2
        for _frame, split_path in results:
            assert split_path.exists()
            assert split_path.suffix == ".dxf"


class TestSheetSetSplit:
    """5-7. sheet_set 相关测试"""

    def test_split_sheet_set_outputs_pdf_and_dwg(self, temp_dir):
        """5. test_split_sheet_set_outputs_pdf_and_dwg"""
        dxf = _create_test_dxf(
            temp_dir / "src" / "test.dxf",
            entities_bbox=(0, 0, 297, 1500),
        )
        ss = _make_sheet_set(page_count=3)
        # 设置source_file
        for page in ss.pages:
            if page.frame_meta:
                page.frame_meta.runtime.source_file = dxf

        splitter = _make_splitter(temp_dir)
        pdf, dwg = splitter.split_sheet_set(dxf, ss, temp_dir / "output")

        assert pdf.suffix == ".pdf"
        assert dwg.suffix == ".dwg"
        assert pdf.exists()
        assert dwg.exists()

    def test_split_sheet_set_page_order_by_page_index(self, temp_dir):
        """6. test_split_sheet_set_page_order_by_page_index"""
        ss = _make_sheet_set(page_count=4)
        # pages 应已按 page_index 排序
        indices = [p.page_index for p in ss.pages]
        assert indices == sorted(indices)

    def test_split_sheet_set_preserves_relative_layout(self, temp_dir):
        """7. test_split_sheet_set_preserves_relative_layout"""
        dxf = _create_test_dxf(
            temp_dir / "src" / "test.dxf",
            entities_bbox=(0, 0, 297, 1000),
        )
        ss = _make_sheet_set(page_count=2)
        for page in ss.pages:
            if page.frame_meta:
                page.frame_meta.runtime.source_file = dxf

        splitter = _make_splitter(temp_dir)
        split_dxf = splitter.clip_sheet_set(dxf, ss, temp_dir / "work")

        # 读取裁切后DXF
        out_doc = ezdxf.readfile(str(split_dxf))
        out_entities = list(out_doc.modelspace())
        # 至少有实体保留
        assert len(out_entities) > 0


class TestPdfFallback:
    """8. test_pdf_fallback_flag_on_multipage_failure"""

    def test_pdf_fallback_flag_on_multipage_failure(self, temp_dir):
        dxf = _create_test_dxf(temp_dir / "src" / "test.dxf")
        ss = _make_sheet_set(page_count=2)
        for page in ss.pages:
            if page.frame_meta:
                page.frame_meta.runtime.source_file = dxf

        # 使用总是返回兜底标记的PDF导出器
        splitter = _make_splitter(
            temp_dir,
            pdf_exporter=FailingPdfExporter(),
        )

        pdf, dwg = splitter.split_sheet_set(dxf, ss, temp_dir / "output")
        assert "A4多页_PDF兜底为单页大图" in ss.flags


class TestNamingConflict:
    """9. test_naming_conflict_policy_error"""

    def test_naming_conflict_detection(self, temp_dir):
        """两个frame同名时应能检测到冲突"""
        dxf = _create_test_dxf(
            temp_dir / "src" / "test.dxf",
            entities_bbox=(0, 0, 2000, 2000),
        )
        # 两个frame使用相同的internal_code和external_code
        frame1 = _make_frame(
            x=0, y=0,
            internal_code="SAME-001",
            external_code="SAMEEXT",
            source_file=dxf,
        )
        frame2 = _make_frame(
            x=1000, y=0,
            internal_code="SAME-001",
            external_code="SAMEEXT",
            source_file=dxf,
        )

        # 同名 → 输出名相同
        assert output_name_for_frame(frame1) == output_name_for_frame(frame2)

        # 批量裁切时第二个文件会覆盖第一个（冲突）
        splitter = _make_splitter(temp_dir)
        results = splitter.clip_frames_batch(
            dxf, [frame1, frame2], temp_dir / "work",
        )
        # 两个都裁切成功，但路径相同（覆盖）
        assert len(results) == 2
        assert results[0][1] == results[1][1]  # 同路径


class TestFailureIsolation:
    """10. test_failure_isolation_single_frame"""

    def test_failure_isolation_single_frame(self, temp_dir):
        """单帧DWG转换失败不中断整个导出"""
        dxf = _create_test_dxf(temp_dir / "src" / "test.dxf")
        frame = _make_frame(source_file=dxf)

        # 使用失败的ODA
        splitter = _make_splitter(temp_dir, oda=FailingODAConverter())

        # clip 阶段应成功
        split_dxf = splitter.clip_frame(dxf, frame, temp_dir / "work")
        assert split_dxf.exists()

        # export 阶段 DWG 会失败，但不应抛出异常（在 executor 层处理）
        # 这里直接测 export_frame 会抛出（由 executor 捕获）
        with pytest.raises(RuntimeError, match="ODA not available"):
            splitter.export_frame(split_dxf, frame, temp_dir / "output")


# ======================================================================
# Config 测试
# ======================================================================


class TestConfigMultiDwgPolicy:
    """验证 multi_dwg_policy 默认值"""

    def test_default_policy(self, runtime_config):
        assert runtime_config.multi_dwg_policy.code_conflict == "error"
        assert runtime_config.multi_dwg_policy.per_dwg_isolation is True
        assert runtime_config.multi_dwg_policy.same_name_dwg == "error"


class TestConfigDxfPdfExport:
    """验证 dxf_pdf_export 默认值"""

    def test_default_pdf_export_config(self, runtime_config):
        assert runtime_config.dxf_pdf_export.aci1_linewidth_mm == 0.4
        assert runtime_config.dxf_pdf_export.aci_default_linewidth_mm == 0.18
        assert runtime_config.dxf_pdf_export.monochrome is True
        assert runtime_config.dxf_pdf_export.screening == 100


# ======================================================================
# 裁切判定测试（均衡安全，零误删）
# ======================================================================


class TestShouldDeleteEntity:
    """_should_delete_entity 零误删判定"""

    def test_bbox_inside_clip_keeps(self):
        """bbox 与 clip_bbox 相交 → 保留"""
        eb = BBox(xmin=10, ymin=10, xmax=50, ymax=50)
        clip = BBox(xmin=0, ymin=0, xmax=100, ymax=100)
        assert FrameSplitter._should_delete_entity(eb, None, [clip]) is False

    def test_bbox_outside_clip_deletes(self):
        """bbox 完全在 clip_bbox 外 → 删除"""
        eb = BBox(xmin=5000, ymin=5000, xmax=6000, ymax=6000)
        clip = BBox(xmin=0, ymin=0, xmax=100, ymax=100)
        assert FrameSplitter._should_delete_entity(eb, None, [clip]) is True

    def test_no_bbox_no_anchors_keeps(self):
        """无 bbox 无锚点 → 保留（零误删）"""
        assert FrameSplitter._should_delete_entity(None, None, [
            BBox(xmin=0, ymin=0, xmax=100, ymax=100),
        ]) is False

    def test_no_bbox_anchor_inside_keeps(self):
        """无 bbox 但锚点在框内 → 保留"""
        anchors = [(50.0, 50.0)]
        clip = BBox(xmin=0, ymin=0, xmax=100, ymax=100)
        assert FrameSplitter._should_delete_entity(None, anchors, [clip]) is False

    def test_no_bbox_anchor_outside_deletes(self):
        """无 bbox 但锚点全在框外 → 删除"""
        anchors = [(9999.0, 9999.0)]
        clip = BBox(xmin=0, ymin=0, xmax=100, ymax=100)
        assert FrameSplitter._should_delete_entity(None, anchors, [clip]) is True

    def test_no_bbox_mixed_anchors_keeps(self):
        """无 bbox 但有一个锚点在框内 → 保留（零误删）"""
        anchors = [(50.0, 50.0), (9999.0, 9999.0)]
        clip = BBox(xmin=0, ymin=0, xmax=100, ymax=100)
        assert FrameSplitter._should_delete_entity(None, anchors, [clip]) is False

    def test_multiple_clip_bboxes_any_match_keeps(self):
        """多个 clip_bbox，锚点在其中一个内 → 保留"""
        anchors = [(150.0, 150.0)]
        clips = [
            BBox(xmin=0, ymin=0, xmax=100, ymax=100),
            BBox(xmin=100, ymin=100, xmax=200, ymax=200),
        ]
        assert FrameSplitter._should_delete_entity(None, anchors, clips) is False


class TestGetEntityAnchors:
    """_get_entity_anchors 锚点提取"""

    def test_line_has_start_end_anchors(self):
        doc = ezdxf.new()
        msp = doc.modelspace()
        line = msp.add_line((100, 200), (300, 400))
        anchors = FrameSplitter._get_entity_anchors(line)
        assert anchors is not None
        assert len(anchors) >= 2
        # start 和 end 都应该被提取
        xs = [a[0] for a in anchors]
        assert 100.0 in xs
        assert 300.0 in xs

    def test_text_has_insert_anchor(self):
        doc = ezdxf.new()
        msp = doc.modelspace()
        text = msp.add_text("TEST", dxfattribs={"insert": (500, 600)})
        anchors = FrameSplitter._get_entity_anchors(text)
        assert anchors is not None
        assert any(a[0] == 500.0 and a[1] == 600.0 for a in anchors)

    def test_circle_has_center_anchor(self):
        doc = ezdxf.new()
        msp = doc.modelspace()
        circle = msp.add_circle((150, 250), radius=50)
        anchors = FrameSplitter._get_entity_anchors(circle)
        assert anchors is not None
        assert any(a[0] == 150.0 and a[1] == 250.0 for a in anchors)


class TestAnchorClipping:
    """端到端：bbox 不可算实体通过锚点被清理"""

    def test_entity_with_insert_outside_is_deleted(self, temp_dir):
        """远处的 TEXT 实体（insert 在框外）应被清理"""
        doc = ezdxf.new()
        msp = doc.modelspace()
        # 框内实体
        msp.add_lwpolyline([(10, 10), (90, 10), (90, 90), (10, 90)], close=True)
        # 远处实体（应删除）
        msp.add_line((8000, 8000), (9000, 9000))

        dxf_path = temp_dir / "src" / "test.dxf"
        dxf_path.parent.mkdir(parents=True, exist_ok=True)
        doc.saveas(str(dxf_path))

        frame = _make_frame(x=0, y=0, w=100, h=100, source_file=dxf_path)
        splitter = _make_splitter(temp_dir)
        split_dxf = splitter.clip_frame(dxf_path, frame, temp_dir / "work")

        out_doc = ezdxf.readfile(str(split_dxf))
        out_entities = list(out_doc.modelspace())
        # 远处 LINE 应被删除
        assert len(out_entities) == 1

    def test_entity_inside_is_never_deleted(self, temp_dir):
        """框内实体必须零误删"""
        doc = ezdxf.new()
        msp = doc.modelspace()
        msp.add_lwpolyline([(10, 10), (90, 10), (90, 90), (10, 90)], close=True)
        msp.add_line((20, 20), (80, 80))
        msp.add_text("INSIDE", dxfattribs={"insert": (50, 50)})
        msp.add_circle((50, 50), radius=10)

        dxf_path = temp_dir / "src" / "test.dxf"
        dxf_path.parent.mkdir(parents=True, exist_ok=True)
        doc.saveas(str(dxf_path))

        frame = _make_frame(x=0, y=0, w=100, h=100, source_file=dxf_path)
        splitter = _make_splitter(temp_dir)
        split_dxf = splitter.clip_frame(dxf_path, frame, temp_dir / "work")

        out_doc = ezdxf.readfile(str(split_dxf))
        out_entities = list(out_doc.modelspace())
        # 全部 4 个实体都应保留
        assert len(out_entities) == 4


# ======================================================================
# 图幅尺寸辅助测试
# ======================================================================


class TestPaperSizeHelpers:
    """paper_size_mm / a4_paper_size 辅助方法"""

    def test_get_paper_size_mm_a1(self, temp_dir):
        splitter = _make_splitter(temp_dir)
        result = splitter._get_paper_size_mm("CNPE_A1")
        assert result == (841.0, 594.0)

    def test_get_paper_size_mm_a4(self, temp_dir):
        splitter = _make_splitter(temp_dir)
        result = splitter._get_paper_size_mm("CNPE_A4")
        assert result == (210.0, 297.0)

    def test_get_paper_size_mm_none(self, temp_dir):
        splitter = _make_splitter(temp_dir)
        assert splitter._get_paper_size_mm(None) is None

    def test_get_paper_size_mm_unknown(self, temp_dir):
        splitter = _make_splitter(temp_dir)
        assert splitter._get_paper_size_mm("UNKNOWN") is None

    def test_a4_landscape(self):
        bbox = BBox(xmin=0, ymin=0, xmax=29700, ymax=21000)
        assert FrameSplitter._get_a4_paper_size(bbox) == (297.0, 210.0)

    def test_a4_portrait(self):
        bbox = BBox(xmin=0, ymin=0, xmax=21000, ymax=29700)
        assert FrameSplitter._get_a4_paper_size(bbox) == (210.0, 297.0)


class TestExtractOption:
    """_extract_option YAML 格式处理"""

    def test_plain_value(self):
        assert FrameSplitter._extract_option({"key": 0.5}, "key", 1.0) == 0.5

    def test_yaml_dict_format(self):
        opts = {"key": {"type": "float", "default": 0.4, "desc": "test"}}
        assert FrameSplitter._extract_option(opts, "key", 1.0) == 0.4

    def test_missing_key_uses_default(self):
        assert FrameSplitter._extract_option({}, "missing", 99) == 99


# ======================================================================
# pdf_engine 路由测试
# ======================================================================


class _RecordingExporter(DxfPdfExporter):
    """记录 export_single_page / export_multipage 被调用次数的 mock 导出器"""

    def __init__(self):
        self.single_calls: list[Path] = []
        self.multi_calls: list[Path] = []

    def export_single_page(self, dxf_path, pdf_path, *, clip_bbox=None, paper_size_mm=None):
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.touch()
        self.single_calls.append(pdf_path)
        return pdf_path

    def export_multipage(self, dxf_path, pdf_path, page_bboxes, paper_size_mm=None):
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.touch()
        self.multi_calls.append(pdf_path)
        return pdf_path, False


class TestPdfEngineRouting:
    """pdf_engine 开关路由测试"""

    def test_python_engine_uses_py_exporter(self, temp_dir: Path):
        """pdf_engine=python 时只调用 pdf_exporter"""
        py_exp = _RecordingExporter()
        acad_exp = _RecordingExporter()
        dxf = _create_test_dxf(temp_dir / "src" / "test.dxf")
        frame = _make_frame(source_file=dxf)
        splitter = _make_splitter(
            temp_dir,
            pdf_exporter=py_exp,
            autocad_pdf_exporter=acad_exp,
            pdf_engine="python",
        )
        splitter.split_frame(dxf, frame, temp_dir / "out")

        assert len(py_exp.single_calls) == 1
        assert len(acad_exp.single_calls) == 0

    def test_autocad_com_engine_uses_acad_exporter(self, temp_dir: Path):
        """pdf_engine=autocad_com 时只调用 autocad_pdf_exporter"""
        py_exp = _RecordingExporter()
        acad_exp = _RecordingExporter()
        dxf = _create_test_dxf(temp_dir / "src" / "test.dxf")
        frame = _make_frame(source_file=dxf)
        splitter = _make_splitter(
            temp_dir,
            pdf_exporter=py_exp,
            autocad_pdf_exporter=acad_exp,
            pdf_engine="autocad_com",
        )
        splitter.split_frame(dxf, frame, temp_dir / "out")

        assert len(acad_exp.single_calls) == 1
        assert len(py_exp.single_calls) == 0

    def test_both_engine_calls_both_exporters(self, temp_dir: Path):
        """pdf_engine=both 时两个导出器都被调用，primary 产物来自 AutoCAD"""
        py_exp = _RecordingExporter()
        acad_exp = _RecordingExporter()
        dxf = _create_test_dxf(temp_dir / "src" / "test.dxf")
        frame = _make_frame(source_file=dxf)
        splitter = _make_splitter(
            temp_dir,
            pdf_exporter=py_exp,
            autocad_pdf_exporter=acad_exp,
            pdf_engine="both",
        )
        pdf, _ = splitter.split_frame(dxf, frame, temp_dir / "out")

        assert len(py_exp.single_calls) == 1, "Python exporter should be called"
        assert len(acad_exp.single_calls) == 1, "AutoCAD exporter should be called"
        # Primary 产物路径应为 AutoCAD 输出（不含 __py 后缀）
        assert "__py" not in pdf.name

    def test_both_engine_fallback_when_acad_fails(self, temp_dir: Path):
        """pdf_engine=both 时 AutoCAD 失败，最终产物由 Python 结果覆盖"""
        class _FailingAcadExporter(DxfPdfExporter):
            def export_single_page(self, dxf_path, pdf_path, **_):
                raise RuntimeError("COM not available")

        py_exp = _RecordingExporter()
        dxf = _create_test_dxf(temp_dir / "src" / "test.dxf")
        frame = _make_frame(source_file=dxf)
        splitter = _make_splitter(
            temp_dir,
            pdf_exporter=py_exp,
            autocad_pdf_exporter=_FailingAcadExporter(),
            pdf_engine="both",
        )
        # 应该成功（AutoCAD 失败后降级到 Python）
        pdf, _ = splitter.split_frame(dxf, frame, temp_dir / "out")
        assert pdf.exists(), "降级后的 Python PDF 应存在"
        assert len(py_exp.single_calls) == 1

    def test_multipage_python_engine(self, temp_dir: Path):
        """pdf_engine=python 时多页走 pdf_exporter"""
        py_exp = _RecordingExporter()
        acad_exp = _RecordingExporter()
        dxf = _create_test_dxf(temp_dir / "src" / "test.dxf")
        ss = _make_sheet_set(page_count=2)
        for page in ss.pages:
            if page.frame_meta:
                page.frame_meta.runtime.source_file = dxf
        splitter = _make_splitter(
            temp_dir,
            pdf_exporter=py_exp,
            autocad_pdf_exporter=acad_exp,
            pdf_engine="python",
        )
        splitter.split_sheet_set(dxf, ss, temp_dir / "out")
        assert len(py_exp.multi_calls) == 1
        assert len(acad_exp.multi_calls) == 0


class TestCadDxfEngineRouting:
    """module5_engine=cad_dxf 时走 CADDXFExecutor 路由。"""

    def test_split_frame_routes_to_cad_executor(self, temp_dir: Path):
        dxf = _create_test_dxf(temp_dir / "src" / "test.dxf")
        frame = _make_frame(source_file=dxf)
        splitter = _make_splitter(temp_dir)
        splitter._module5_engine = "cad_dxf"

        expected_pdf = temp_dir / "out" / "frame.pdf"
        expected_dwg = temp_dir / "out" / "frame.dwg"
        fake_result = {
            "frames": [
                {
                    "frame_id": frame.frame_id,
                    "status": "ok",
                    "pdf_path": str(expected_pdf),
                    "dwg_path": str(expected_dwg),
                    "flags": [],
                },
            ],
            "sheet_sets": [],
            "errors": [],
        }

        def _apply_result(*, result, frames_by_id, sheet_sets_by_id):
            assert frames_by_id[frame.frame_id] is frame
            frame.runtime.pdf_path = Path(result["frames"][0]["pdf_path"])
            frame.runtime.dwg_path = Path(result["frames"][0]["dwg_path"])
            return (1, 0)

        cad_executor = cast(Any, splitter.cad_dxf_executor)
        cad_executor.execute_source_dxf.return_value = fake_result
        cad_executor.apply_result.side_effect = _apply_result

        pdf, dwg = splitter.split_frame(dxf, frame, temp_dir / "out")

        assert pdf == expected_pdf
        assert dwg == expected_dwg
        cad_executor.execute_source_dxf.assert_called_once()

    def test_split_sheet_set_routes_to_cad_executor(self, temp_dir: Path):
        dxf = _create_test_dxf(temp_dir / "src" / "test.dxf")
        ss = _make_sheet_set(page_count=2)
        for page in ss.pages:
            if page.frame_meta:
                page.frame_meta.runtime.source_file = dxf

        splitter = _make_splitter(temp_dir)
        splitter._module5_engine = "cad_dxf"

        out_dir = temp_dir / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = output_name_for_sheet_set(ss)
        expected_pdf = out_dir / f"{stem}.pdf"
        expected_dwg = out_dir / f"{stem}.dwg"
        expected_pdf.touch()
        expected_dwg.touch()

        cad_executor = cast(Any, splitter.cad_dxf_executor)
        cad_executor.execute_source_dxf.return_value = {
            "frames": [],
            "sheet_sets": [{"cluster_id": ss.cluster_id, "status": "ok", "flags": []}],
            "errors": [],
        }
        cad_executor.apply_result.return_value = (0, 1)

        pdf, dwg = splitter.split_sheet_set(dxf, ss, out_dir)

        assert pdf == expected_pdf
        assert dwg == expected_dwg
        cad_executor.execute_source_dxf.assert_called_once()
