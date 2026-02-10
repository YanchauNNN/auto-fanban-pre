"""
图框拆分器 - 裁切/导出双阶段

裁切策略（关键）：
  **复制原始DXF → 删除图框外实体**
  不创建新文档、不导入实体，确保字体/样式/块定义/头段完全保持原样。

命名规则（强约束）:
  输出 pdf/dwg 文件名 = external_code(internal_code)
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from pathlib import Path

import ezdxf
from ezdxf import bbox as ezdxf_bbox

from ..config import get_config, load_spec
from ..interfaces import IFrameSplitter
from ..models import BBox, FrameMeta, SheetSet
from .dxf_pdf_exporter import DxfPdfExporter
from .oda_converter import ODAConverter

logger = logging.getLogger(__name__)


# ======================================================================
# 命名辅助
# ======================================================================


def make_output_name(
    *,
    external_code: str | None = None,
    internal_code: str | None = None,
    fallback_id: str = "unknown",
) -> str:
    if external_code and internal_code:
        return f"{external_code}({internal_code})"
    if internal_code:
        return internal_code
    if external_code:
        return external_code
    return fallback_id


def output_name_for_frame(frame: FrameMeta) -> str:
    tb = frame.titleblock
    return make_output_name(
        external_code=tb.external_code,
        internal_code=tb.internal_code,
        fallback_id=frame.frame_id[:8],
    )


def output_name_for_sheet_set(sheet_set: SheetSet) -> str:
    if sheet_set.master_page and sheet_set.master_page.frame_meta:
        tb = sheet_set.master_page.frame_meta.titleblock
        return make_output_name(
            external_code=tb.external_code,
            internal_code=tb.internal_code,
            fallback_id=f"sheet_set_{sheet_set.cluster_id[:8]}",
        )
    return f"sheet_set_{sheet_set.cluster_id[:8]}"


# ======================================================================
# 拆分器
# ======================================================================


class FrameSplitter(IFrameSplitter):
    """图框拆分器 — 复制原文件 + 删除框外实体"""

    def __init__(
        self,
        spec_path: str | None = None,
        oda_converter: ODAConverter | None = None,
        pdf_exporter: DxfPdfExporter | None = None,
    ):
        self.spec = load_spec(spec_path) if spec_path else load_spec()
        self.config = get_config()
        self.oda = oda_converter or ODAConverter()

        margins = self.spec.doc_generation.get("options", {}).get("pdf_margin_mm", {})
        if isinstance(margins, dict) and "default" in margins:
            margins = margins["default"]
        self.margins: dict = margins or {
            "top": 20, "bottom": 10, "left": 20, "right": 10,
        }
        self.pdf_exporter = pdf_exporter or DxfPdfExporter(margins=self.margins)

        clip_cfg = self.spec.a4_multipage.get("clipping", {}).get("margin", {})
        raw = clip_cfg.get("margin_percent", "0.015")
        try:
            self._margin_percent = float(raw)
        except (ValueError, TypeError):
            self._margin_percent = 0.015

    # ==================================================================
    # Stage 7: clip-only
    # ==================================================================

    def clip_frame(self, dxf_path: Path, frame: FrameMeta, work_dir: Path) -> Path:
        work_dir.mkdir(parents=True, exist_ok=True)
        clip_bbox = self._calc_clip_bbox(frame.runtime.outer_bbox)
        name = output_name_for_frame(frame)
        output_path = work_dir / f"{name}.dxf"
        self._clip_by_copy_and_delete(dxf_path, output_path, [clip_bbox])
        return output_path

    def clip_frames_batch(
        self,
        dxf_path: Path,
        frames: list[FrameMeta],
        work_dir: Path,
        progress_cb: Callable[[int], None] | None = None,
        progress_every: int = 5000,
    ) -> list[tuple[FrameMeta, Path]]:
        """批量裁切：读一次源文件算bbox，每帧复制+删除"""
        if not frames:
            return []
        work_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: 读取源文件，预算每个实体的 handle → bbox
        source = ezdxf.readfile(str(dxf_path))
        source_msp = source.modelspace()

        cache = ezdxf_bbox.Cache()
        handle_bbox: dict[str, BBox | None] = {}
        for idx, entity in enumerate(source_msp, start=1):
            handle_bbox[entity.dxf.handle] = self._get_entity_bbox(entity, cache)
            if progress_cb and progress_every > 0 and idx % progress_every == 0:
                progress_cb(idx)
        del source  # 释放内存

        # Step 2: 每帧复制+删除
        results: list[tuple[FrameMeta, Path]] = []
        for frame in frames:
            clip_bbox = self._calc_clip_bbox(frame.runtime.outer_bbox)
            name = output_name_for_frame(frame)
            output_path = work_dir / f"{name}.dxf"

            # 计算该帧需要删除的 handles
            handles_to_delete = {
                h for h, eb in handle_bbox.items()
                if eb is not None and not clip_bbox.intersects(eb)
            }

            # 复制 → 打开 → 删除 → 保存
            shutil.copy2(str(dxf_path), str(output_path))
            doc = ezdxf.readfile(str(output_path))
            msp = doc.modelspace()
            to_del = [e for e in msp if e.dxf.handle in handles_to_delete]
            for e in to_del:
                msp.delete_entity(e)
            doc.saveas(str(output_path))

            results.append((frame, output_path))

        return results

    def clip_sheet_set(self, dxf_path: Path, sheet_set: SheetSet, work_dir: Path) -> Path:
        work_dir.mkdir(parents=True, exist_ok=True)
        clip_bboxes = [self._calc_clip_bbox(p.outer_bbox) for p in sheet_set.pages]
        name = output_name_for_sheet_set(sheet_set)
        output_path = work_dir / f"{name}.dxf"
        self._clip_by_copy_and_delete(dxf_path, output_path, clip_bboxes)
        return output_path

    # ==================================================================
    # Stage 8: export
    # ==================================================================

    def export_frame(self, split_dxf: Path, frame: FrameMeta, output_dir: Path) -> tuple[Path, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        name = output_name_for_frame(frame)
        pdf_path = output_dir / f"{name}.pdf"
        self.pdf_exporter.export_single_page(split_dxf, pdf_path)
        dwg_path = self._convert_to_dwg(split_dxf, output_dir, name)
        frame.runtime.pdf_path = pdf_path
        frame.runtime.dwg_path = dwg_path
        return pdf_path, dwg_path

    def export_sheet_set(self, split_dxf: Path, sheet_set: SheetSet, output_dir: Path) -> tuple[Path, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        name = output_name_for_sheet_set(sheet_set)
        pdf_path = output_dir / f"{name}.pdf"
        page_bboxes = [page.outer_bbox for page in sheet_set.pages]
        _, is_fallback = self.pdf_exporter.export_multipage(split_dxf, pdf_path, page_bboxes)
        if is_fallback:
            sheet_set.flags.append("A4多页_PDF兜底为单页大图")
        dwg_path = self._convert_to_dwg(split_dxf, output_dir, name)
        return pdf_path, dwg_path

    # ==================================================================
    # IFrameSplitter 接口（向后兼容）
    # ==================================================================

    def split_frame(self, dxf_path: Path, frame: FrameMeta, output_dir: Path) -> tuple[Path, Path]:
        split_dxf = self.clip_frame(dxf_path, frame, output_dir)
        return self.export_frame(split_dxf, frame, output_dir)

    def split_sheet_set(self, dxf_path: Path, sheet_set: SheetSet, output_dir: Path) -> tuple[Path, Path]:
        split_dxf = self.clip_sheet_set(dxf_path, sheet_set, output_dir)
        return self.export_sheet_set(split_dxf, sheet_set, output_dir)

    # ==================================================================
    # 核心：复制原文件 + 删除框外实体
    # ==================================================================

    def _clip_by_copy_and_delete(
        self,
        dxf_path: Path,
        output_path: Path,
        clip_bboxes: list[BBox],
    ) -> None:
        """裁切的唯一正确方式：复制原始DXF，删除框外实体。

        保证字体/样式/块定义/DXF头段完全不变。
        """
        # 1. 逐字节复制（保留一切）
        shutil.copy2(str(dxf_path), str(output_path))

        # 2. 打开副本，删除不在任何 clip_bbox 内的实体
        doc = ezdxf.readfile(str(output_path))
        msp = doc.modelspace()

        cache = ezdxf_bbox.Cache()
        to_delete: list = []
        for entity in msp:
            eb = self._get_entity_bbox(entity, cache)
            if eb is None:
                continue  # bbox 未知 → 保守保留
            if not any(cb.intersects(eb) for cb in clip_bboxes):
                to_delete.append(entity)

        for entity in to_delete:
            msp.delete_entity(entity)

        doc.saveas(str(output_path))

    # ==================================================================
    # 辅助
    # ==================================================================

    def _calc_clip_bbox(self, outer_bbox: BBox, margin_percent: float | None = None) -> BBox:
        mp = margin_percent if margin_percent is not None else self._margin_percent
        mx = outer_bbox.width * mp
        my = outer_bbox.height * mp
        return BBox(
            xmin=outer_bbox.xmin - mx, ymin=outer_bbox.ymin - my,
            xmax=outer_bbox.xmax + mx, ymax=outer_bbox.ymax + my,
        )

    def _calc_union_bbox(self, bboxes: list[BBox]) -> BBox:
        return BBox(
            xmin=min(b.xmin for b in bboxes), ymin=min(b.ymin for b in bboxes),
            xmax=max(b.xmax for b in bboxes), ymax=max(b.ymax for b in bboxes),
        )

    @staticmethod
    def _get_entity_bbox(entity, cache: ezdxf_bbox.Cache | None = None) -> BBox | None:
        try:
            ext = ezdxf_bbox.extents([entity], cache=cache)
            if ext.has_data:
                return BBox(
                    xmin=ext.extmin.x, ymin=ext.extmin.y,
                    xmax=ext.extmax.x, ymax=ext.extmax.y,
                )
        except Exception:
            pass
        return None

    def _convert_to_dwg(self, dxf_path: Path, output_dir: Path, target_name: str) -> Path:
        dwg_path = self.oda.dxf_to_dwg(dxf_path, output_dir)
        expected = output_dir / f"{target_name}.dwg"
        if dwg_path != expected and dwg_path.exists():
            dwg_path.rename(expected)
            dwg_path = expected
        return dwg_path
