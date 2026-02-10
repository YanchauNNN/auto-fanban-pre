"""
DXF->PDF 导出器 - 纯Python实现（ezdxf绘制链 + matplotlib后端）

职责：
1. 单页 DXF->PDF 导出
2. 多页 DXF->PDF 导出（A4成组，逐页窗口裁切后合并）
3. 兜底策略：多页失败时输出union bbox单页大图

依赖：
- ezdxf (drawing addon): DXF渲染
- matplotlib: PDF渲染后端

测试要点：
- test_export_single_page_pdf: 单页PDF导出
- test_export_multipage_pdf: 多页PDF导出
- test_multipage_fallback: 多页失败兜底
"""

from __future__ import annotations

import logging
from pathlib import Path

import ezdxf
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.recorder import Recorder
from ezdxf.math import Vec2

from ..models import BBox

logger = logging.getLogger(__name__)


class DxfPdfExporter:
    """DXF->PDF 纯Python导出器"""

    def __init__(self, margins: dict[str, float] | None = None):
        """
        Args:
            margins: PDF页边距 {top, bottom, left, right} 单位mm
        """
        self.margins = margins or {"top": 20, "bottom": 10, "left": 20, "right": 10}

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------

    def export_single_page(
        self,
        dxf_path: Path,
        pdf_path: Path,
        *,
        clip_bbox: BBox | None = None,
    ) -> Path:
        """导出单页PDF

        Args:
            dxf_path: 裁切后的中间DXF
            pdf_path: 输出PDF路径
            clip_bbox: 额外裁切视图（可选，一般不需要因为DXF已裁切）

        Returns:
            pdf_path
        """
        import matplotlib

        matplotlib.use("agg")
        import matplotlib.pyplot as plt
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        doc = ezdxf.readfile(str(dxf_path))
        msp = doc.modelspace()

        recorder = Recorder()
        ctx = RenderContext(doc)
        Frontend(ctx, recorder).draw_layout(msp, finalize=True)

        player = recorder.player().copy()

        if clip_bbox:
            player.crop_rect(
                Vec2(clip_bbox.xmin, clip_bbox.ymin),
                Vec2(clip_bbox.xmax, clip_bbox.ymax),
                distance=0.5,
            )

        content_bbox = player.bbox()
        if not content_bbox.has_data:
            # 空内容 -> 空白A4 PDF
            fig = plt.figure(figsize=(8.27, 11.69))
            fig.savefig(str(pdf_path), format="pdf")
            plt.close(fig)
            return pdf_path

        fig = plt.figure()
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_axis_off()

        backend = MatplotlibBackend(ax)
        player.replay(backend)

        fig.savefig(str(pdf_path), format="pdf", dpi=150, facecolor="white")
        plt.close(fig)
        return pdf_path

    def export_multipage(
        self,
        dxf_path: Path,
        pdf_path: Path,
        page_bboxes: list[BBox],
    ) -> tuple[Path, bool]:
        """导出多页PDF（A4成组）

        Args:
            dxf_path: 含所有页面实体的裁切DXF
            pdf_path: 输出PDF路径
            page_bboxes: 各页裁切边界框列表（已按page_index排序）

        Returns:
            (pdf_path, is_fallback) — is_fallback=True 表示使用了兜底策略
        """
        try:
            return self._multipage_via_recorder(dxf_path, pdf_path, page_bboxes), False
        except Exception:
            logger.warning("多页PDF导出失败，使用union bbox兜底", exc_info=True)
            union = BBox(
                xmin=min(b.xmin for b in page_bboxes),
                ymin=min(b.ymin for b in page_bboxes),
                xmax=max(b.xmax for b in page_bboxes),
                ymax=max(b.ymax for b in page_bboxes),
            )
            return self.export_single_page(dxf_path, pdf_path, clip_bbox=union), True

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _multipage_via_recorder(
        self,
        dxf_path: Path,
        pdf_path: Path,
        page_bboxes: list[BBox],
    ) -> Path:
        """逐页窗口打印后合并为多页PDF"""
        import matplotlib

        matplotlib.use("agg")
        import matplotlib.pyplot as plt
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
        from matplotlib.backends.backend_pdf import PdfPages

        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        doc = ezdxf.readfile(str(dxf_path))
        recorder = Recorder()
        ctx = RenderContext(doc)
        Frontend(ctx, recorder).draw_layout(doc.modelspace(), finalize=True)

        with PdfPages(str(pdf_path)) as pages:
            for page_bbox in page_bboxes:
                player = recorder.player().copy()
                player.crop_rect(
                    Vec2(page_bbox.xmin, page_bbox.ymin),
                    Vec2(page_bbox.xmax, page_bbox.ymax),
                    distance=0.5,
                )

                fig = plt.figure()
                ax = fig.add_axes([0, 0, 1, 1])
                ax.set_axis_off()

                backend = MatplotlibBackend(ax)
                player.replay(backend)

                pages.savefig(fig, dpi=150, facecolor="white")
                plt.close(fig)

        return pdf_path
