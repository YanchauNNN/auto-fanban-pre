"""
DXF->PDF 导出器 — 黑白打印，严格窗口+1:1图幅+ACI线宽映射

策略：
- 严格窗口打印：单页/多页均使用 clip_bbox 裁切后渲染
- 1:1 图幅输出：页面尺寸基于标准图幅 paper_variants W/H（mm），
  不跟随放大后 DXF 图素坐标
- ACI 线宽映射：颜色1 → 0.4mm，颜色2~255 → 0.18mm（可配置）
- 全黑输出：所有颜色强制为 #000000，淡显100
- 页边距从配置读取（mm），严格按配置值落地

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


def _make_monochrome_override(
    aci1_linewidth: float = 0.4,
    aci_default_linewidth: float = 0.18,
):
    """构建黑白 + ACI 线宽映射的 override 函数。

    颜色：全部输出 #000000（黑色），等效淡显100
    线宽：ACI 1 → aci1_linewidth，其余 → aci_default_linewidth
    """

    def override(props):
        pen = props.pen  # ACI color index (1-255)
        lw = aci1_linewidth if pen == 1 else aci_default_linewidth
        return Override(
            properties=props._replace(color="#000000", lineweight=lw),
            is_visible=True,
        )

    return override


class DxfPdfExporter:
    """DXF→PDF 黑白导出器（严格窗口 + 1:1 图幅 + ACI 线宽映射）"""

    def __init__(
        self,
        margins: dict[str, float] | None = None,
        aci1_linewidth: float = 0.4,
        aci_default_linewidth: float = 0.18,
        font_dirs: list[str] | None = None,
        fallback_font_family: list[str] | None = None,
    ):
        self.margins = margins or {
            "top": 20, "bottom": 10, "left": 20, "right": 10,
        }
        self._override = _make_monochrome_override(
            aci1_linewidth, aci_default_linewidth,
        )
        self.font_dirs = font_dirs or []
        self.fallback_font_family = fallback_font_family or [
            "SimSun", "Microsoft YaHei", "SimHei", "sans-serif",
        ]
        self._resolved_font_dirs: list[str] = []
        self._font_env_ready = False
        self._matplotlib_fonts_registered = False

    @staticmethod
    def _is_problematic_text_style(
        style_name: str,
        font_name: str,
        bigfont_name: str,
    ) -> bool:
        """判断文字样式是否应强制映射到中文TTF。"""
        font_l = (font_name or "").lower()
        bigfont_l = (bigfont_name or "").lower()
        style_l = (style_name or "").lower()

        # 存在 bigfont 的样式通常是 SHX 体系，matplotlib 难以稳定复刻
        if bigfont_l:
            return True

        # SHX/未扩展名样式名（TXT/ROMANS/COMPLEX/SIMPLEX 等）
        shx_tokens = ("txt", "romans", "romand", "simplex", "complex", "tssdeng")
        if font_l.endswith(".shx") or (
            "." not in font_l and any(tok in font_l for tok in shx_tokens)
        ):
            return True

        # 项目中常见会导致方块的字体名
        fallback_bad = {"txt_____.ttf", "arial.ttf", "romans__.ttf", "romant__.ttf"}
        if font_l in fallback_bad:
            return True

        # 常见中文样式名但字体映射不稳定时，强制走 CJK 字体
        style_tokens = ("hz", "rh", "s1", "chinese", "acp1000", "tssd")
        return bool(any(tok in style_l for tok in style_tokens))

    def _pick_cjk_font_file(self) -> str | None:
        """从兜底字体族中挑一个可用字体文件名（如 simsun.ttc）。"""
        import matplotlib.font_manager as fm

        candidates = list(dict.fromkeys(self.fallback_font_family + [
            "SimSun", "Microsoft YaHei", "SimHei",
        ]))
        for fam in candidates:
            try:
                fp = fm.findfont(
                    fm.FontProperties(family=fam),
                    fallback_to_default=False,
                )
            except Exception:  # noqa: BLE001
                continue
            if fp and Path(fp).exists():
                return Path(fp).name
        return None

    def _normalize_text_styles_for_render(self, doc) -> None:
        """渲染前归一化文字样式，尽量避免中文方块字。"""
        cjk_font_file = self._pick_cjk_font_file()
        if not cjk_font_file:
            logger.warning("未找到可用CJK字体，跳过样式归一化")
            return

        replaced = 0
        for style in doc.styles:
            name = getattr(style.dxf, "name", "")
            font = getattr(style.dxf, "font", "")
            bigfont = getattr(style.dxf, "bigfont", "")
            if self._is_problematic_text_style(name, font, bigfont):
                try:
                    style.dxf.font = cjk_font_file
                    style.dxf.bigfont = ""
                    replaced += 1
                except Exception:  # noqa: BLE001
                    continue
        if replaced:
            logger.info("PDF渲染前已归一化文字样式: %d（字体=%s）", replaced, cjk_font_file)

    def _ensure_font_environment(self) -> None:
        """配置 SHX/TTF 字体搜索路径（只执行一次）"""
        if self._font_env_ready:
            return

        resolved_dirs: list[str] = []
        missing_dirs: list[str] = []
        for raw in self.font_dirs:
            p = Path(raw).expanduser()
            if not p.is_absolute():
                p = (Path.cwd() / p).resolve()
            if p.exists() and p.is_dir():
                resolved_dirs.append(str(p))
            else:
                missing_dirs.append(raw)

        existing = list(getattr(ezdxf.options, "support_dirs", []))
        merged = existing[:]
        for d in resolved_dirs:
            if d not in merged:
                merged.append(d)
        ezdxf.options.support_dirs = merged
        self._resolved_font_dirs = resolved_dirs
        self._font_env_ready = True

        if resolved_dirs:
            logger.info("已配置PDF字体目录: %s", resolved_dirs)
            if missing_dirs:
                logger.info("以下PDF字体目录不存在，已忽略: %s", missing_dirs)
        elif self.font_dirs:
            logger.warning("未找到可用PDF字体目录，仍使用系统默认字体: %s", self.font_dirs)

    def _ensure_matplotlib_fonts(self) -> None:
        """注册字体目录下的 TTF/TTC/OTF 到 matplotlib（只执行一次）"""
        if self._matplotlib_fonts_registered:
            return

        import matplotlib.font_manager as fm

        count = 0
        for d in self._resolved_font_dirs:
            root = Path(d)
            for pattern in ("*.ttf", "*.ttc", "*.otf", "*.otc"):
                for fp in root.rglob(pattern):
                    try:
                        fm.fontManager.addfont(str(fp))
                        count += 1
                    except Exception:  # noqa: BLE001
                        continue

        if count:
            logger.info("已向matplotlib注册字体文件: %d", count)
        self._matplotlib_fonts_registered = True

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------

    def export_single_page(
        self,
        dxf_path: Path,
        pdf_path: Path,
        *,
        clip_bbox: BBox | None = None,
        paper_size_mm: tuple[float, float] | None = None,
    ) -> Path:
        """单页黑白 PDF（严格窗口打印 + 1:1 图幅）。

        Args:
            clip_bbox: 裁切窗口（应为图框 outer_bbox），严格窗口打印。
            paper_size_mm: (W, H) 标准图幅尺寸(mm)，用于 1:1 输出。
                若不提供则回退到 content_bbox 尺寸。
        """
        import matplotlib

        matplotlib.use("agg")
        import matplotlib.pyplot as plt

        self._ensure_font_environment()
        self._ensure_matplotlib_fonts()
        plt.rcParams["font.family"] = self.fallback_font_family
        plt.rcParams["axes.unicode_minus"] = False

        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        doc = ezdxf.readfile(str(dxf_path))
        self._normalize_text_styles_for_render(doc)
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

        self._render_to_pdf(
            player,
            content_bbox,
            pdf_path,
            paper_size_mm=paper_size_mm,
            view_bbox=clip_bbox,
        )
        return pdf_path

    def export_multipage(
        self,
        dxf_path: Path,
        pdf_path: Path,
        page_bboxes: list[BBox],
        paper_size_mm: tuple[float, float] | None = None,
    ) -> tuple[Path, bool]:
        """多页黑白 PDF（A4成组，严格窗口打印 + 1:1 图幅）。

        Args:
            paper_size_mm: 每页的标准图幅尺寸(mm)，如 A4 横向 (297, 210)。
        """
        try:
            return self._multipage(
                dxf_path, pdf_path, page_bboxes,
                paper_size_mm=paper_size_mm,
            ), False
        except Exception:
            logger.warning("多页PDF导出失败，使用union bbox兜底", exc_info=True)
            union = BBox(
                xmin=min(b.xmin for b in page_bboxes),
                ymin=min(b.ymin for b in page_bboxes),
                xmax=max(b.xmax for b in page_bboxes),
                ymax=max(b.ymax for b in page_bboxes),
            )
            return self.export_single_page(
                dxf_path, pdf_path, clip_bbox=union,
                paper_size_mm=paper_size_mm,
            ), True

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _render_to_pdf(
        self,
        player,
        content_bbox,
        pdf_path: Path,
        *,
        paper_size_mm: tuple[float, float] | None = None,
        view_bbox: BBox | None = None,
    ) -> None:
        """将 Player 内容渲染为黑白 PDF，带严格页边距。

        paper_size_mm 为标准图幅 1:1 尺寸(mm)；若不提供则回退到
        content_bbox 尺寸（原始行为，用于无法确定图幅的兜底场景）。
        """
        import matplotlib

        matplotlib.use("agg")
        import matplotlib.pyplot as plt
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

        # 内容区域尺寸 (mm) — 优先使用标准图幅 1:1 尺寸
        if paper_size_mm:
            cw_mm, ch_mm = paper_size_mm
        elif view_bbox:
            cw_mm = view_bbox.width
            ch_mm = view_bbox.height
        else:
            cw_mm = content_bbox.size.x
            ch_mm = content_bbox.size.y

        # 页边距 (mm)
        ml = self.margins.get("left", 20)
        mr = self.margins.get("right", 10)
        mt = self.margins.get("top", 20)
        mb = self.margins.get("bottom", 10)

        # 页面总尺寸 (mm)
        pw_mm = cw_mm + ml + mr
        ph_mm = ch_mm + mt + mb

        # 转 inches
        pw_inch = pw_mm / 25.4
        ph_inch = ph_mm / 25.4

        # 限幅避免超大 figure
        max_inch = 200
        if max(pw_inch, ph_inch) > max_inch:
            ratio = max_inch / max(pw_inch, ph_inch)
            pw_inch *= ratio
            ph_inch *= ratio

        fig = plt.figure(figsize=(pw_inch, ph_inch))

        # axes 占据内容区域（严格按边距比例）
        ax = fig.add_axes((ml / pw_mm, mb / ph_mm, cw_mm / pw_mm, ch_mm / ph_mm))
        ax.set_axis_off()

        backend = MatplotlibBackend(ax, adjust_figure=False)
        player.replay(backend, override=self._override)

        if view_bbox:
            # 严格窗口打印：视图范围锁定在窗口，不让跨框实体撑大视图
            ax.set_xlim(view_bbox.xmin, view_bbox.xmax)
            ax.set_ylim(view_bbox.ymin, view_bbox.ymax)
        else:
            ax.set_xlim(content_bbox.extmin.x, content_bbox.extmax.x)
            ax.set_ylim(content_bbox.extmin.y, content_bbox.extmax.y)
        ax.set_aspect("equal")

        fig.savefig(str(pdf_path), format="pdf", dpi=300, facecolor="white")
        plt.close(fig)

    def _multipage(
        self,
        dxf_path: Path,
        pdf_path: Path,
        page_bboxes: list[BBox],
        *,
        paper_size_mm: tuple[float, float] | None = None,
    ) -> Path:
        """逐页窗口裁切 → 合并为多页 PDF"""
        import matplotlib

        matplotlib.use("agg")
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages

        self._ensure_font_environment()
        self._ensure_matplotlib_fonts()
        plt.rcParams["font.family"] = self.fallback_font_family
        plt.rcParams["axes.unicode_minus"] = False

        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        doc = ezdxf.readfile(str(dxf_path))
        self._normalize_text_styles_for_render(doc)
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
                self._render_to_pdf_page(
                    player, content_bbox, pages,
                    paper_size_mm=paper_size_mm,
                    view_bbox=page_bbox,
                )

        return pdf_path

    def _render_to_pdf_page(
        self,
        player,
        content_bbox,
        pdf_pages,
        *,
        paper_size_mm: tuple[float, float] | None = None,
        view_bbox: BBox | None = None,
    ) -> None:
        """渲染单页到 PdfPages 上下文"""
        import matplotlib

        matplotlib.use("agg")
        import matplotlib.pyplot as plt
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

        # 内容区域尺寸 (mm)
        if paper_size_mm:
            cw_mm, ch_mm = paper_size_mm
        elif view_bbox:
            cw_mm = view_bbox.width
            ch_mm = view_bbox.height
        else:
            cw_mm = content_bbox.size.x
            ch_mm = content_bbox.size.y

        ml = self.margins.get("left", 20)
        mr = self.margins.get("right", 10)
        mt = self.margins.get("top", 20)
        mb = self.margins.get("bottom", 10)
        pw_mm = cw_mm + ml + mr
        ph_mm = ch_mm + mt + mb
        pw_inch = pw_mm / 25.4
        ph_inch = ph_mm / 25.4

        # 限幅
        max_inch = 200
        if max(pw_inch, ph_inch) > max_inch:
            ratio = max_inch / max(pw_inch, ph_inch)
            pw_inch *= ratio
            ph_inch *= ratio

        fig = plt.figure(figsize=(pw_inch, ph_inch))
        ax = fig.add_axes((ml / pw_mm, mb / ph_mm, cw_mm / pw_mm, ch_mm / ph_mm))
        ax.set_axis_off()

        backend = MatplotlibBackend(ax, adjust_figure=False)
        player.replay(backend, override=self._override)

        if view_bbox:
            ax.set_xlim(view_bbox.xmin, view_bbox.xmax)
            ax.set_ylim(view_bbox.ymin, view_bbox.ymax)
        else:
            ax.set_xlim(content_bbox.extmin.x, content_bbox.extmax.x)
            ax.set_ylim(content_bbox.extmin.y, content_bbox.extmax.y)
        ax.set_aspect("equal")

        pdf_pages.savefig(fig, dpi=300, facecolor="white")
        plt.close(fig)
