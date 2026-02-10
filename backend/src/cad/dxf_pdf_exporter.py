"""
DXF->PDF 导出器 — 黑白打印，带页边距

策略：
- ezdxf Recorder 记录渲染结果（一次读取，多次裁切复用）
- Player.crop_rect 按图框窗口裁切
- matplotlib 后端输出 PDF（黑白：白底黑线）
- 页边距从配置读取（mm），转换为 figure 空间

限制：
- SHX 字体无法在纯 Python 中精确渲染（使用系统替代字体）
- 精度不如 AutoCAD 原生打印
- 生产环境建议 DXF→DWG(ODA)→PDF(AutoCAD COM) 路径
"""

from __future__ import annotations

import logging
from pathlib import Path

import ezdxf
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.recorder import Override, Recorder
from ezdxf.math import Vec2

from ..models import BBox

logger = logging.getLogger(__name__)


def _force_black(props):
    """强制所有实体渲染为黑色"""
    return Override(
        properties=props._replace(color="#000000"),
        is_visible=True,
    )


class DxfPdfExporter:
    """DXF→PDF 黑白导出器"""

    def __init__(self, margins: dict[str, float] | None = None):
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
        """单页黑白 PDF"""
        import matplotlib

        matplotlib.use("agg")
        import matplotlib.pyplot as plt

        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        doc = ezdxf.readfile(str(dxf_path))
        recorder = Recorder()
        ctx = RenderContext(doc)
        Frontend(ctx, recorder).draw_layout(doc.modelspace(), finalize=True)

        player = recorder.player().copy()
        if clip_bbox:
            player.crop_rect(
                Vec2(clip_bbox.xmin, clip_bbox.ymin),
                Vec2(clip_bbox.xmax, clip_bbox.ymax),
                distance=0.5,
            )

        content_bbox = player.bbox()
        if not content_bbox.has_data:
            fig = plt.figure(figsize=(8.27, 11.69))
            fig.savefig(str(pdf_path), format="pdf", facecolor="white")
            plt.close(fig)
            return pdf_path

        self._render_to_pdf(player, content_bbox, pdf_path)
        return pdf_path

    def export_multipage(
        self,
        dxf_path: Path,
        pdf_path: Path,
        page_bboxes: list[BBox],
    ) -> tuple[Path, bool]:
        """多页黑白 PDF（A4成组）"""
        try:
            return self._multipage(dxf_path, pdf_path, page_bboxes), False
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

    def _render_to_pdf(self, player, content_bbox, pdf_path: Path) -> None:
        """将 Player 内容渲染为黑白 PDF，带页边距"""
        import matplotlib

        matplotlib.use("agg")
        import matplotlib.pyplot as plt
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

        # 内容尺寸（DXF 单位，工程图通常为 mm×scale）
        cw = content_bbox.size.x
        ch = content_bbox.size.y

        # 页边距 (mm)
        ml = self.margins.get("left", 20)
        mr = self.margins.get("right", 10)
        mt = self.margins.get("top", 20)
        mb = self.margins.get("bottom", 10)

        # 页面总尺寸 (DXF 单位，含边距)
        pw = cw + ml + mr
        ph = ch + mt + mb

        # 转 inches（假设 DXF 单位 = mm；工程图比例由内容本身决定）
        pw_inch = pw / 25.4
        ph_inch = ph / 25.4

        # 限幅避免超大 figure
        max_inch = 200
        if max(pw_inch, ph_inch) > max_inch:
            scale = max_inch / max(pw_inch, ph_inch)
            pw_inch *= scale
            ph_inch *= scale

        fig = plt.figure(figsize=(pw_inch, ph_inch))

        # axes 占据去掉边距后的区域
        ax = fig.add_axes([ml / pw, mb / ph, cw / pw, ch / ph])
        ax.set_axis_off()

        backend = MatplotlibBackend(ax, adjust_figure=False)
        player.replay(backend, override=_force_black)

        ax.set_xlim(content_bbox.extmin.x, content_bbox.extmax.x)
        ax.set_ylim(content_bbox.extmin.y, content_bbox.extmax.y)
        ax.set_aspect("equal")

        fig.savefig(str(pdf_path), format="pdf", dpi=300, facecolor="white")
        plt.close(fig)

    def _multipage(
        self, dxf_path: Path, pdf_path: Path, page_bboxes: list[BBox],
    ) -> Path:
        """逐页窗口裁切 → 合并为多页 PDF"""
        import matplotlib

        matplotlib.use("agg")
        import matplotlib.pyplot as plt
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
                content_bbox = player.bbox()
                if not content_bbox.has_data:
                    fig = plt.figure(figsize=(8.27, 11.69))
                    pages.savefig(fig, facecolor="white")
                    plt.close(fig)
                    continue
                self._render_to_pdf_page(player, content_bbox, pages)

        return pdf_path

    def _render_to_pdf_page(self, player, content_bbox, pdf_pages) -> None:
        """渲染单页到 PdfPages 上下文"""
        import matplotlib

        matplotlib.use("agg")
        import matplotlib.pyplot as plt
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

        cw = content_bbox.size.x
        ch = content_bbox.size.y
        ml = self.margins.get("left", 20)
        mr = self.margins.get("right", 10)
        mt = self.margins.get("top", 20)
        mb = self.margins.get("bottom", 10)
        pw = cw + ml + mr
        ph = ch + mt + mb
        pw_inch = min(pw / 25.4, 200)
        ph_inch = min(ph / 25.4, 200)

        fig = plt.figure(figsize=(pw_inch, ph_inch))
        ax = fig.add_axes([ml / pw, mb / ph, cw / pw, ch / ph])
        ax.set_axis_off()

        backend = MatplotlibBackend(ax, adjust_figure=False)
        player.replay(backend, override=_force_black)

        ax.set_xlim(content_bbox.extmin.x, content_bbox.extmax.x)
        ax.set_ylim(content_bbox.extmin.y, content_bbox.extmax.y)
        ax.set_aspect("equal")

        pdf_pages.savefig(fig, dpi=300, facecolor="white")
        plt.close(fig)
