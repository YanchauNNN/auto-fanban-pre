"""
图框拆分器 - 裁切/导出双阶段

裁切策略（关键）：
  **复制原始DXF → 删除图框外实体**
  不创建新文档、不导入实体，确保字体/样式/块定义/头段完全保持原样。

  实体删除判定（均衡安全，零误删）：
  1. bbox 可算 → 不与任何 clip_bbox 相交则删除
  2. bbox 不可算 → 尝试锚点定位，仅"所有锚点明确在所有 clip_bbox 外"时删除
  3. 无法判定 → 保守保留（硬约束：图框范围内图素零误删）

命名规则（强约束）:
  输出 pdf/dwg 文件名 = external_code+revision+status (internal_code)
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
from .autocad_path_resolver import resolve_autocad_paths
from .autocad_pdf_exporter import AutoCADPdfExporter
from .cad_dxf_executor import CADDXFExecutor
from .dxf_pdf_exporter import DxfPdfExporter
from .oda_converter import ODAConverter

logger = logging.getLogger(__name__)

# 无法可靠获取二维锚点的实体类型 → bbox不可算时一律保留
_ALWAYS_KEEP_TYPES = frozenset({
    "XLINE", "RAY",                    # 无限延伸
    "3DSOLID", "BODY", "REGION",       # 三维实体，无可靠二维锚点
    "ACAD_PROXY_ENTITY",               # 代理实体，结构未知
})


# ======================================================================
# 命名辅助
# ======================================================================


def make_output_name(
    *,
    external_code: str | None = None,
    revision: str | None = None,
    status: str | None = None,
    internal_code: str | None = None,
    fallback_id: str = "unknown",
) -> str:
    external = (external_code or "").strip()
    rev = (revision or "").strip()
    doc_status = (status or "").strip()
    internal = (internal_code or "").strip()

    if external and internal:
        prefix = f"{external}{rev}{doc_status}" if rev and doc_status else external
        return f"{prefix} ({internal})"
    if internal:
        return internal
    if external:
        return external
    return fallback_id


def output_name_for_frame(frame: FrameMeta) -> str:
    tb = frame.titleblock
    return make_output_name(
        external_code=tb.external_code,
        revision=tb.revision,
        status=tb.status,
        internal_code=tb.internal_code,
        fallback_id=frame.frame_id[:8],
    )


def output_name_for_sheet_set(sheet_set: SheetSet) -> str:
    if sheet_set.master_page and sheet_set.master_page.frame_meta:
        tb = sheet_set.master_page.frame_meta.titleblock
        return make_output_name(
            external_code=tb.external_code,
            revision=tb.revision,
            status=tb.status,
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

        options = self.spec.doc_generation.get("options", {})
        margins = options.get("pdf_margin_mm", {})
        if isinstance(margins, dict) and "default" in margins:
            margins = margins["default"]
        self.margins: dict = margins or {
            "top": 20, "bottom": 10, "left": 20, "right": 10,
        }

        # PDF 打印样式参数（ACI 线宽映射，纯 Python 渲染器使用）
        aci1_lw = self._extract_option(options, "pdf_aci1_linewidth_mm", 0.4)
        aci_default_lw = self._extract_option(
            options, "pdf_aci_default_linewidth_mm", 0.18,
        )
        spec_font_dirs = self._as_str_list(
            self._extract_option(options, "pdf_font_dirs", ["fronts/Fonts", "Fonts"]),
        )
        spec_fallback_fonts = self._as_str_list(
            self._extract_option(
                options,
                "pdf_fallback_font_family",
                ["SimSun", "Microsoft YaHei", "SimHei"],
            ),
        )
        runtime_font_dirs = self._as_str_list(
            getattr(self.config.dxf_pdf_export, "font_dirs", []),
        )
        runtime_fallback_fonts = self._as_str_list(
            getattr(self.config.dxf_pdf_export, "fallback_font_family", []),
        )

        # AutoCAD 路径解析（为两个导出器提供字体目录）
        autocad_install_dir = getattr(getattr(self.config, "autocad", None), "install_dir", None)
        self.autocad_paths = resolve_autocad_paths(autocad_install_dir)
        autocad_font_dirs = (
            [str(self.autocad_paths.fonts_dir)]
            if self.autocad_paths.fonts_dir is not None
            else []
        )
        if self.autocad_paths.install_dir is not None:
            logger.info("模块5检测到AutoCAD目录: %s", self.autocad_paths.install_dir)

        runtime_font_dirs = self._merge_unique_lists(autocad_font_dirs, runtime_font_dirs)
        font_dirs = self._merge_unique_lists(runtime_font_dirs, spec_font_dirs)
        fallback_fonts = self._merge_unique_lists(runtime_fallback_fonts, spec_fallback_fonts)

        # 纯 Python 导出器（baseline / 兜底）
        self.pdf_exporter: DxfPdfExporter = pdf_exporter or DxfPdfExporter(
            margins=self.margins,
            aci1_linewidth=float(aci1_lw),
            aci_default_linewidth=float(aci_default_lw),
            font_dirs=font_dirs,
            fallback_font_family=fallback_fonts,
        )

        # AutoCAD COM 导出器（仅在 pdf_engine=autocad_com/both 时使用）
        acad_cfg = getattr(self.config, "autocad", None)
        ctb_name = Path(getattr(acad_cfg, "ctb_path", "monochrome.ctb")).name
        self.autocad_pdf_exporter: AutoCADPdfExporter = AutoCADPdfExporter(
            prog_id_candidates=getattr(acad_cfg, "prog_id_candidates", None),
            visible=getattr(acad_cfg, "visible", False),
            plot_timeout_sec=getattr(acad_cfg, "plot_timeout_sec", 180),
            ctb_name=ctb_name,
            pc3_name=getattr(acad_cfg, "pc3_name", "打印PDF2.pc3"),
            retry=getattr(acad_cfg, "retry", 1),
            margins=self.margins,
        )

        # pdf_engine 开关：python | autocad_com | both
        self._pdf_engine: str = getattr(
            getattr(self.config, "module5_export", None), "pdf_engine", "python"
        )
        logger.info("模块5 PDF引擎: %s", self._pdf_engine)

        clip_cfg = self.spec.a4_multipage.get("clipping", {})
        margin_cfg = clip_cfg.get("margin", {})
        raw = margin_cfg.get("margin_percent", "0.015")
        try:
            self._margin_percent = float(raw)
        except (ValueError, TypeError):
            self._margin_percent = 0.015

        self._unknown_bbox_policy = clip_cfg.get(
            "unknown_bbox_policy", "keep_if_uncertain",
        )
        self._module5_engine: str = getattr(
            getattr(self.config, "module5_export", None),
            "engine",
            "python_fallback",
        )
        self.cad_dxf_executor = CADDXFExecutor(config=self.config, spec=self.spec)

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
        """批量裁切：读一次源文件预算bbox+锚点，每帧复制+删除"""
        if not frames:
            return []
        work_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: 预算每个实体的 handle → (bbox, anchors)
        source = ezdxf.readfile(str(dxf_path))
        source_msp = source.modelspace()

        cache = ezdxf_bbox.Cache()
        handle_info: dict[
            str,
            tuple[BBox | None, list[tuple[float, float]] | None],
        ] = {}
        for idx, entity in enumerate(source_msp, start=1):
            eb = self._get_entity_bbox(entity, cache)
            anchors = self._get_entity_anchors(entity) if eb is None else None
            handle_info[entity.dxf.handle] = (eb, anchors)
            if progress_cb and progress_every > 0 and idx % progress_every == 0:
                progress_cb(idx)
        del source  # 释放内存

        # Step 2: 每帧复制+删除
        results: list[tuple[FrameMeta, Path]] = []
        for frame in frames:
            clip_bbox = self._calc_clip_bbox(frame.runtime.outer_bbox)
            clip_bboxes = [clip_bbox]
            name = output_name_for_frame(frame)
            output_path = work_dir / f"{name}.dxf"

            # 计算该帧需要删除的 handles（均衡安全策略）
            handles_to_delete: set[str] = set()
            for h, (eb, anchors) in handle_info.items():
                if self._should_delete_entity(eb, anchors, clip_bboxes):
                    handles_to_delete.add(h)

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
    # Stage 8: export（含 pdf_engine 路由）
    # ==================================================================

    def export_frame(
        self, split_dxf: Path, frame: FrameMeta, output_dir: Path,
    ) -> tuple[Path, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        name = output_name_for_frame(frame)
        pdf_path = output_dir / f"{name}.pdf"
        clip_bbox = frame.runtime.outer_bbox
        paper_size_mm = self._get_paper_size_mm(frame.runtime.paper_variant_id)

        self._export_single_page_routed(
            split_dxf, pdf_path,
            clip_bbox=clip_bbox,
            paper_size_mm=paper_size_mm,
            name=name,
        )
        dwg_path = self._convert_to_dwg(split_dxf, output_dir, name)
        frame.runtime.pdf_path = pdf_path
        frame.runtime.dwg_path = dwg_path
        return pdf_path, dwg_path

    def export_sheet_set(
        self, split_dxf: Path, sheet_set: SheetSet, output_dir: Path,
    ) -> tuple[Path, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        name = output_name_for_sheet_set(sheet_set)
        pdf_path = output_dir / f"{name}.pdf"
        page_bboxes = [page.outer_bbox for page in sheet_set.pages]
        paper_size_mm = self._get_a4_paper_size(page_bboxes[0]) if page_bboxes else None

        is_fallback = self._export_multipage_routed(
            split_dxf, pdf_path, page_bboxes,
            paper_size_mm=paper_size_mm,
            name=name,
        )
        if is_fallback:
            sheet_set.flags.append("A4多页_PDF兜底为单页大图")
        dwg_path = self._convert_to_dwg(split_dxf, output_dir, name)
        return pdf_path, dwg_path

    # ------------------------------------------------------------------
    # pdf_engine 路由内部方法
    # ------------------------------------------------------------------

    def _export_single_page_routed(
        self,
        split_dxf: Path,
        pdf_path: Path,
        *,
        clip_bbox,
        paper_size_mm,
        name: str,
    ) -> None:
        """根据 pdf_engine 路由单页 PDF 导出。

        python       → DxfPdfExporter（纯 Python）
        autocad_com  → AutoCADPdfExporter，失败时抛出
        both         → 优先 AutoCAD，失败则降级到 Python，并同时保留 Python 结果对比
        """
        if self._pdf_engine == "python":
            self.pdf_exporter.export_single_page(
                split_dxf, pdf_path,
                clip_bbox=clip_bbox,
                paper_size_mm=paper_size_mm,
            )
            return

        if self._pdf_engine == "autocad_com":
            self.autocad_pdf_exporter.export_single_page(
                split_dxf, pdf_path,
                clip_bbox=clip_bbox,
                paper_size_mm=paper_size_mm,
            )
            return

        # pdf_engine == "both"：AutoCAD 为主，Python 为对比，AutoCAD 失败则降级
        py_pdf = pdf_path.with_name(pdf_path.stem + "__py.pdf")
        self.pdf_exporter.export_single_page(
            split_dxf, py_pdf,
            clip_bbox=clip_bbox,
            paper_size_mm=paper_size_mm,
        )
        try:
            self.autocad_pdf_exporter.export_single_page(
                split_dxf, pdf_path,
                clip_bbox=clip_bbox,
                paper_size_mm=paper_size_mm,
            )
            logger.info(
                "both模式: AutoCAD出图成功 %s（Python对比版: %s）", name, py_pdf.name,
            )
        except Exception as exc:
            # AutoCAD 失败时降级到 Python 结果作为最终产物
            logger.warning(
                "both模式: AutoCAD出图失败 %s，降级到Python结果: %s", name, exc,
            )
            import shutil as _shutil
            _shutil.copy2(str(py_pdf), str(pdf_path))

    def _export_multipage_routed(
        self,
        split_dxf: Path,
        pdf_path: Path,
        page_bboxes: list,
        *,
        paper_size_mm,
        name: str,
    ) -> bool:
        """根据 pdf_engine 路由多页 PDF 导出，返回 is_fallback。"""
        if self._pdf_engine == "python":
            _, is_fallback = self.pdf_exporter.export_multipage(
                split_dxf, pdf_path, page_bboxes, paper_size_mm=paper_size_mm,
            )
            return is_fallback

        if self._pdf_engine == "autocad_com":
            _, is_fallback = self.autocad_pdf_exporter.export_multipage(
                split_dxf, pdf_path, page_bboxes, paper_size_mm=paper_size_mm,
            )
            return is_fallback

        # both：AutoCAD 为主，失败降级
        py_pdf = pdf_path.with_name(pdf_path.stem + "__py.pdf")
        _, py_fallback = self.pdf_exporter.export_multipage(
            split_dxf, py_pdf, page_bboxes, paper_size_mm=paper_size_mm,
        )
        try:
            _, acad_fallback = self.autocad_pdf_exporter.export_multipage(
                split_dxf, pdf_path, page_bboxes, paper_size_mm=paper_size_mm,
            )
            logger.info(
                "both模式: AutoCAD多页出图成功 %s（Python对比版: %s）", name, py_pdf.name,
            )
            return acad_fallback
        except Exception as exc:
            logger.warning(
                "both模式: AutoCAD多页出图失败 %s，降级到Python: %s", name, exc,
            )
            import shutil as _shutil
            _shutil.copy2(str(py_pdf), str(pdf_path))
            return py_fallback

    # ==================================================================
    # IFrameSplitter 接口（向后兼容）
    # ==================================================================

    def split_frame(self, dxf_path: Path, frame: FrameMeta, output_dir: Path) -> tuple[Path, Path]:
        if self._module5_engine == "cad_dxf":
            result = self.cad_dxf_executor.execute_source_dxf(
                job_id="adhoc",
                source_dxf=dxf_path,
                frames=[frame],
                sheet_sets=[],
                output_dir=output_dir,
                task_root=output_dir / "_cad_tasks",
            )
            self.cad_dxf_executor.apply_result(
                result=result,
                frames_by_id={frame.frame_id: frame},
                sheet_sets_by_id={},
            )
            if frame.runtime.pdf_path is None or frame.runtime.dwg_path is None:
                raise RuntimeError("cad_dxf 导出失败: 单帧输出路径缺失")
            return frame.runtime.pdf_path, frame.runtime.dwg_path

        split_dxf = self.clip_frame(dxf_path, frame, output_dir)
        return self.export_frame(split_dxf, frame, output_dir)

    def split_sheet_set(
        self, dxf_path: Path, sheet_set: SheetSet, output_dir: Path,
    ) -> tuple[Path, Path]:
        if self._module5_engine == "cad_dxf":
            result = self.cad_dxf_executor.execute_source_dxf(
                job_id="adhoc",
                source_dxf=dxf_path,
                frames=[],
                sheet_sets=[sheet_set],
                output_dir=output_dir,
                task_root=output_dir / "_cad_tasks",
            )
            self.cad_dxf_executor.apply_result(
                result=result,
                frames_by_id={},
                sheet_sets_by_id={sheet_set.cluster_id: sheet_set},
            )
            # sheet_set 路径回填在 pipeline 中按 result 统一处理，这里保持接口兼容返回
            name = output_name_for_sheet_set(sheet_set)
            pdf_path = output_dir / f"{name}.pdf"
            dwg_path = output_dir / f"{name}.dwg"
            if not pdf_path.exists() or not dwg_path.exists():
                raise RuntimeError("cad_dxf 导出失败: A4成组输出路径缺失")
            return pdf_path, dwg_path

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
        """Python fallback 裁切：复制原始DXF，删除框外实体。

        保证字体/样式/块定义/DXF头段完全不变。

        删除判定（零误删）：
        1. bbox 可算 → 不与任何 clip_bbox 相交则删除
        2. bbox 不可算 → 锚点全在框外则删除
        3. 无法判定 → 保留
        """
        # 1. 逐字节复制（保留一切）
        shutil.copy2(str(dxf_path), str(output_path))

        # 2. 打开副本，删除明确在所有 clip_bbox 之外的实体
        doc = ezdxf.readfile(str(output_path))
        msp = doc.modelspace()

        cache = ezdxf_bbox.Cache()
        to_delete: list = []
        for entity in msp:
            eb = self._get_entity_bbox(entity, cache)
            anchors = self._get_entity_anchors(entity) if eb is None else None
            if self._should_delete_entity(eb, anchors, clip_bboxes):
                to_delete.append(entity)

        for entity in to_delete:
            msp.delete_entity(entity)

        if to_delete:
            logger.info("裁切删除 %d 个框外实体", len(to_delete))

        doc.saveas(str(output_path))

    # ==================================================================
    # 删除判定（均衡安全，零误删）
    # ==================================================================

    @staticmethod
    def _should_delete_entity(
        entity_bbox: BBox | None,
        entity_anchors: list[tuple[float, float]] | None,
        clip_bboxes: list[BBox],
    ) -> bool:
        """判定实体是否应被删除（零误删原则）。

        仅在实体**明确**位于所有 clip_bbox 之外时返回 True。
        任何不确定情况返回 False（保留）。
        """
        if entity_bbox is not None:
            # bbox 可算：不与任何 clip_bbox 相交 → 删除
            return not any(cb.intersects(entity_bbox) for cb in clip_bboxes)

        if entity_anchors is not None:
            # bbox 不可算但有锚点：所有锚点都在所有 clip_bbox 之外 → 删除
            return not any(
                FrameSplitter._point_in_bbox(pt, cb)
                for pt in entity_anchors
                for cb in clip_bboxes
            )

        # 无法判定 → 保留（零误删硬约束）
        return False

    @staticmethod
    def _get_entity_anchors(entity) -> list[tuple[float, float]] | None:
        """尝试从实体获取二维锚点（用于 bbox 不可算时的位置判断）。

        返回 None 表示无法获取任何锚点（实体将被保留）。
        """
        if entity.dxftype() in _ALWAYS_KEEP_TYPES:
            return None

        anchors: list[tuple[float, float]] = []
        for attr_name in ("insert", "start", "end", "center", "location"):
            try:
                pt = getattr(entity.dxf, attr_name)
                if pt is not None:
                    anchors.append((float(pt.x), float(pt.y)))
            except Exception:  # noqa: BLE001
                pass

        return anchors if anchors else None

    @staticmethod
    def _point_in_bbox(point: tuple[float, float], bbox: BBox) -> bool:
        """判断二维点是否在边界框内"""
        return (
            bbox.xmin <= point[0] <= bbox.xmax
            and bbox.ymin <= point[1] <= bbox.ymax
        )

    # ==================================================================
    # 辅助
    # ==================================================================

    def _get_paper_size_mm(
        self, paper_variant_id: str | None,
    ) -> tuple[float, float] | None:
        """根据 paper_variant_id 获取标准图幅 1:1 尺寸 (W, H) mm"""
        if not paper_variant_id:
            return None
        variants = self.spec.titleblock_extract.get("paper_variants", {})
        variant = variants.get(paper_variant_id)
        if not variant:
            return None
        try:
            if isinstance(variant, dict):
                w, h = variant.get("W"), variant.get("H")
            else:
                w, h = getattr(variant, "W", None), getattr(variant, "H", None)
            if w and h:
                return (float(w), float(h))
        except Exception:  # noqa: BLE001
            pass
        return None

    @staticmethod
    def _get_a4_paper_size(page_bbox: BBox) -> tuple[float, float]:
        """根据 A4 页面外框判断纸张方向，返回 1:1 尺寸 (mm)"""
        if page_bbox.width > page_bbox.height:
            return (297.0, 210.0)  # 横向
        return (210.0, 297.0)  # 纵向

    @staticmethod
    def _extract_option(options: dict, key: str, default):
        """从 YAML 选项中提取值（处理 {type:..., default:...} 格式）"""
        val = options.get(key, default)
        if isinstance(val, dict) and "default" in val:
            return val["default"]
        return val

    @staticmethod
    def _as_str_list(value) -> list[str]:
        """将配置值归一化为字符串列表"""
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(v) for v in value if v is not None]
        return [str(value)]

    @staticmethod
    def _merge_unique_lists(*values: list[str]) -> list[str]:
        """按入参顺序合并字符串列表（忽略空值与大小写重复）"""
        merged: list[str] = []
        seen: set[str] = set()
        for group in values:
            for item in group:
                normalized = str(item).strip()
                if not normalized:
                    continue
                key = normalized.lower()
                if key in seen:
                    continue
                seen.add(key)
                merged.append(normalized)
        return merged

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
