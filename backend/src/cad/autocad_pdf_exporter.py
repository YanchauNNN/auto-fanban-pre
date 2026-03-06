"""
AutoCAD COM PDF 导出器 — 原生打印链路

策略：
- 通过 AutoCAD ActiveX COM 接口打开裁切后的 DXF
- 使用 打印PDF2.pc3 配合 monochrome.ctb 打印为 PDF
- 相比纯 Python 渲染（ezdxf+matplotlib），字体/线宽/图层与 CAD 原图一致
- ProgID 按版本回退：24.1(2022) → 24.0(2021) → AutoCAD.Application(通用)
- 超时保护：打印线程超时后强制 Quit AutoCAD
- 多页 PDF：逐页打印后用 pypdf 合并

限制：
- 仅 Windows 可用（需 pywin32）
- 需要目标机安装并授权的 AutoCAD

用法（通过 FrameSplitter 的 pdf_engine 配置开关）：
    runtime_config.autocad.pdf_engine = "autocad_com"
    # 或
    runtime_config.autocad.pdf_engine = "both"   # 双路对比
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ..models import BBox

logger = logging.getLogger(__name__)

# AutoCAD ActiveX PlotType 枚举
_ACAD_PLOT_EXTENTS = 1  # acExtents — 打印可见实体范围（用于已裁切的 DXF）
_ACAD_PLOT_DISPLAY = 2  # acDisplay — 打印当前显示窗口
_ACAD_PLOT_WINDOW = 4  # acWindow  — 窗口打印（指定模型坐标范围）
# AutoCAD ActiveX StandardScale 枚举
_ACAD_SCALE_TO_FIT = 16  # acScaleToFit — 充满纸张
_ACAD_MODEL_SPACE = 1  # acModelSpace
_BM_CLICK = 0x00F5  # Button click message
_RPC_CALL_REJECTED = -2147418111


# ISO / ANSI 纸张规格名（打印PDF2.pc3 可用格式）
_MEDIA_MAP: list[tuple[tuple[float, float], str]] = [
    ((1189, 841), "ISO_A0_(1189.00_x_841.00_MM)"),
    ((841, 1189), "ISO_A0_(841.00_x_1189.00_MM)"),
    ((841, 594), "ISO_A1_(841.00_x_594.00_MM)"),
    ((594, 841), "ISO_A1_(594.00_x_841.00_MM)"),
    ((594, 420), "ISO_A2_(594.00_x_420.00_MM)"),
    ((420, 594), "ISO_A2_(420.00_x_594.00_MM)"),
    ((420, 297), "ISO_A3_(420.00_x_297.00_MM)"),
    ((297, 420), "ISO_A3_(297.00_x_420.00_MM)"),
    ((297, 210), "ISO_A4_(297.00_x_210.00_MM)"),
    ((210, 297), "ISO_A4_(210.00_x_297.00_MM)"),
]


@dataclass(slots=True)
class _PlotJob:
    """单页出图任务。"""

    dxf_path: Path
    pdf_path: Path
    clip_bbox: BBox | None
    paper_size_mm: tuple[float, float] | None


def _pick_media_name(paper_size_mm: tuple[float, float] | None) -> str:
    """根据图幅尺寸选择 PC3 标准纸张格式名。"""
    if paper_size_mm is None:
        return "ISO_A1_(841.00_x_594.00_MM)"
    w, h = paper_size_mm
    for (mw, mh), name in _MEDIA_MAP:
        if abs(w - mw) <= 10 and abs(h - mh) <= 10:
            return name
    # 找不到精确匹配时返回 A1 横向作为安全兜底
    return "ISO_A1_(841.00_x_594.00_MM)"


class AutoCADPdfExporter:
    """AutoCAD COM PDF 导出器（原生打印链路）。

    接口与 DxfPdfExporter 相同，可在 FrameSplitter 中直接替换。
    每次导出独立创建/销毁 AutoCAD 实例，避免实例状态污染。
    """

    def __init__(
        self,
        prog_id_candidates: list[str] | None = None,
        visible: bool = False,
        plot_timeout_sec: int = 180,
        ctb_name: str = "monochrome.ctb",
        pc3_name: str = "打印PDF2.pc3",
        retry: int = 1,
        margins: dict[str, float] | None = None,
    ):
        self.prog_id_candidates = prog_id_candidates or [
            "AutoCAD.Application.24.1",
            "AutoCAD.Application.24.0",
            "AutoCAD.Application",
        ]
        self.visible = visible
        self.plot_timeout_sec = plot_timeout_sec
        self.ctb_name = ctb_name
        self.pc3_name = pc3_name
        self.retry = max(0, retry)
        self.margins = margins or {"top": 20, "bottom": 10, "left": 20, "right": 10}

    # ------------------------------------------------------------------
    # Public API（与 DxfPdfExporter 保持一致）
    # ------------------------------------------------------------------

    def export_single_page(
        self,
        dxf_path: Path,
        pdf_path: Path,
        *,
        clip_bbox: BBox | None = None,
        paper_size_mm: tuple[float, float] | None = None,
    ) -> Path:
        """单页 PDF（AutoCAD COM 打印）。

        clip_bbox: 使用图框识别得到的矩形窗口（四顶点）坐标定义打印范围。
                   这是模块4/5提供的关键定位数据，必须优先使用。
        """
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        last_exc: Exception | None = None
        for attempt in range(self.retry + 1):
            try:
                job = _PlotJob(
                    dxf_path=dxf_path,
                    pdf_path=pdf_path,
                    clip_bbox=clip_bbox,
                    paper_size_mm=paper_size_mm,
                )
                self._run_plot_jobs([job], timeout_sec=self.plot_timeout_sec)
                logger.info(
                    "AutoCAD COM 出图成功 (attempt %d): %s",
                    attempt + 1,
                    pdf_path.name,
                )
                return pdf_path
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "AutoCAD COM 出图失败 (attempt %d/%d): %s: %s",
                    attempt + 1,
                    self.retry + 1,
                    pdf_path.name,
                    exc,
                )
        raise RuntimeError(
            f"AutoCAD COM 出图失败（共 {self.retry + 1} 次）: {last_exc}"
        ) from last_exc

    def export_single_page_batch(
        self,
        jobs: list[tuple[Path, Path, BBox | None, tuple[float, float] | None]],
    ) -> None:
        """批量单页出图（同一批任务仅启动一次 AutoCAD）。"""
        if not jobs:
            return
        normalized_jobs = [
            _PlotJob(
                dxf_path=dxf_path,
                pdf_path=pdf_path,
                clip_bbox=clip_bbox,
                paper_size_mm=paper_size_mm,
            )
            for dxf_path, pdf_path, clip_bbox, paper_size_mm in jobs
        ]
        for job in normalized_jobs:
            job.pdf_path.parent.mkdir(parents=True, exist_ok=True)

        timeout = max(1, len(normalized_jobs)) * self.plot_timeout_sec
        last_exc: Exception | None = None
        for attempt in range(self.retry + 1):
            try:
                self._run_plot_jobs(normalized_jobs, timeout_sec=timeout)
                logger.info(
                    "AutoCAD COM 批量出图成功: %d 张（attempt %d）",
                    len(normalized_jobs),
                    attempt + 1,
                )
                return
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "AutoCAD COM 批量出图失败 (attempt %d/%d): %s",
                    attempt + 1,
                    self.retry + 1,
                    exc,
                )
        raise RuntimeError(
            f"AutoCAD COM 批量出图失败（共 {self.retry + 1} 次）: {last_exc}"
        ) from last_exc

    def export_multipage(
        self,
        dxf_path: Path,
        pdf_path: Path,
        page_bboxes: list[BBox],
        paper_size_mm: tuple[float, float] | None = None,
    ) -> tuple[Path, bool]:
        """多页 PDF：逐页打印 → pypdf 合并。

        对 A4 多页成组，每个 bbox 对应一页。
        """
        import tempfile

        try:
            from pypdf import PdfWriter
        except ImportError as e:
            raise RuntimeError("pypdf 未安装，无法合并多页 PDF") from e

        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            page_pdfs: list[Path] = []
            page_jobs: list[tuple[Path, Path, BBox | None, tuple[float, float] | None]] = []
            for i, _bbox in enumerate(page_bboxes):
                page_pdf = Path(tmpdir) / f"page_{i:03d}.pdf"
                page_jobs.append(
                    (
                        dxf_path,
                        page_pdf,
                        _bbox,
                        paper_size_mm,
                    )
                )
                page_pdfs.append(page_pdf)
            self.export_single_page_batch(page_jobs)

            writer = PdfWriter()
            for p in page_pdfs:
                writer.append(str(p))
            with open(pdf_path, "wb") as f:
                writer.write(f)

        logger.info("AutoCAD COM 多页PDF合并成功: %s (%d页)", pdf_path.name, len(page_bboxes))
        return pdf_path, False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    # _connect / _wait_documents_ready 已重构为模块级函数（线程内复用）

    def _plot_window_to_pdf(
        self,
        dxf_path: Path,
        pdf_path: Path,
        *,
        clip_bbox: BBox | None,
        paper_size_mm: tuple[float, float] | None,
    ) -> None:
        """单任务包装器（兼容旧调用）。"""
        job = _PlotJob(
            dxf_path=dxf_path,
            pdf_path=pdf_path,
            clip_bbox=clip_bbox,
            paper_size_mm=paper_size_mm,
        )
        self._run_plot_jobs([job], timeout_sec=self.plot_timeout_sec)

    def _run_plot_jobs(self, jobs: list[_PlotJob], *, timeout_sec: int) -> None:
        """核心打印流程（单线程 COM + 可批量任务）。"""
        if not jobs:
            return

        exc_holder: list[Exception] = []
        done_evt = threading.Event()
        visible = self.visible
        pc3_name = self.pc3_name
        ctb_name = self.ctb_name
        prog_id_candidates = self.prog_id_candidates
        margins = self.margins
        popup_stop_evt = threading.Event()
        popup_stats: dict[str, int] = {"closed": 0}

        def _worker() -> None:
            import pythoncom  # type: ignore[import]
            import win32com.client  # type: ignore[import]

            pythoncom.CoInitialize()
            app = None
            try:
                # ── 1. 连接 AutoCAD ──────────────────────────────────────
                app = _dispatch_autocad(win32com, prog_id_candidates)
                _wait_docs_ready(app)
                app.Visible = True  # Documents.Open 在某些版本要求窗口可见

                # ── 2. 抑制 UI 弹窗（打开文件前设置）─────────────────────
                # SAVEFIDELITY=0 : 关闭 DXF 时不弹"是否保存 DWG 副本"对话框
                # FILEDIA=0       : 关闭文件选择对话框
                # CMDDIA=0        : 关闭命令行对话框
                _suppress_autocad_dialogs(app)

                for idx, job in enumerate(jobs, start=1):
                    _plot_job_with_opened_app(
                        app,
                        dxf_path=job.dxf_path,
                        pdf_path=job.pdf_path,
                        clip_bbox=job.clip_bbox,
                        paper_size_mm=job.paper_size_mm,
                        pc3_name=pc3_name,
                        ctb_name=ctb_name,
                        margins=margins,
                    )
                    logger.info(
                        "AutoCAD COM 任务完成 %d/%d: %s",
                        idx,
                        len(jobs),
                        job.pdf_path.name,
                    )

                if not visible:
                    with contextlib.suppress(Exception):
                        app.Visible = False

            except Exception as exc:
                exc_holder.append(exc)
            finally:
                if app is not None:
                    with contextlib.suppress(Exception):
                        app.Quit()
                pythoncom.CoUninitialize()
                done_evt.set()

        # 弹窗监控：遇到“是否保存改动”自动点击“否”
        popup_thread = threading.Thread(
            target=_popup_watchdog,
            args=(popup_stop_evt, popup_stats),
            daemon=True,
        )
        popup_thread.start()

        worker_thread = threading.Thread(target=_worker, daemon=True)
        worker_thread.start()
        timed_out = not done_evt.wait(timeout=timeout_sec)
        popup_stop_evt.set()
        popup_thread.join(timeout=2.0)

        if timed_out:
            raise TimeoutError(f"AutoCAD COM 打印超时（{timeout_sec}s）: {jobs[0].dxf_path.name}")
        if exc_holder:
            raise exc_holder[0]
        if popup_stats["closed"] > 0:
            logger.warning("本次导出自动处理了 %d 次 AutoCAD 保存弹窗", popup_stats["closed"])


# ======================================================================
# 模块级辅助函数（在工作线程内调用，避免跨线程 COM 对象传递）
# ======================================================================


def _dispatch_autocad(win32com_module, prog_id_candidates: list[str]):
    """在当前线程中连接 AutoCAD COM 实例（优先新建独立实例）。"""
    # 依次尝试创建新实例（避免复用已卡住实例）
    last_exc: Exception | None = None
    for prog_id in prog_id_candidates:
        try:
            app = win32com_module.client.DispatchEx(prog_id)
            logger.debug("AutoCAD COM 新实例 ProgID=%s ver=%s", prog_id, app.Version)
            return app
        except Exception as exc:
            last_exc = exc
            logger.debug("AutoCAD COM ProgID=%s 失败: %s", prog_id, exc)

    # 新建失败时，再尝试复用已有实例
    with contextlib.suppress(Exception):
        app = win32com_module.client.GetActiveObject("AutoCAD.Application")
        logger.debug("回退复用已运行 AutoCAD ver=%s", app.Version)
        return app

    raise RuntimeError(f"AutoCAD COM 无法连接，已尝试: {prog_id_candidates}") from last_exc


def _wait_docs_ready(app, timeout_sec: float = 45.0, poll_interval: float = 1.0) -> None:
    """等待 AutoCAD COM Documents 集合就绪（新实例启动时需要时间）。
    通过访问 Count 属性来确认集合已完全初始化。
    """
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            docs = app.Documents
            _ = docs.Count  # Count 可访问说明集合已就绪
            return
        except Exception:
            time.sleep(poll_interval)
    raise TimeoutError(f"AutoCAD COM Documents 初始化超时（{timeout_sec}s）")


def _wait_active_document(
    app, expected_stem: str, timeout_sec: float = 60.0, poll_interval: float = 0.8
):
    """等待 app.ActiveDocument 就绪且文件名与期望匹配，并验证 ActiveLayout 可访问。

    late-binding 下 Documents.Open() 的返回值不可靠；
    通过轮询 app.ActiveDocument 并校验 ActiveLayout 属性来确认文档完全就绪。
    """
    stem_lower = expected_stem.lower()
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            doc = app.ActiveDocument
            if doc is None:
                time.sleep(poll_interval)
                continue
            # 验证文件名（允许 .dxf / .dwg 差异）
            doc_name = doc.Name.lower()
            doc_stem = doc_name.rsplit(".", 1)[0]
            if doc_stem != stem_lower:
                time.sleep(poll_interval)
                continue
            # 验证 ActiveLayout 可访问（文档内容已就绪的关键指标）
            _ = doc.ActiveLayout
            logger.debug("ActiveDocument 就绪: %s", doc.Name)
            return doc
        except Exception:
            pass
        time.sleep(poll_interval)

    raise TimeoutError(f"等待 ActiveDocument({expected_stem}) 完全就绪超时（{timeout_sec}s）")


def _suppress_autocad_dialogs(app, doc=None) -> None:
    """在 app 和 doc 层面设置系统变量，全面抑制 AutoCAD 自动化中的 UI 弹窗。

    关键变量说明：
      SAVEFIDELITY=0  关闭 DXF 时不弹"是否保存 DWG 副本"对话框（本次弹窗的根因）
      FILEDIA=0       关闭文件选择对话框
      CMDDIA=0        关闭命令输入对话框
      BACKGROUNDPLOT=0 强制 PlotToFile 同步执行（不走后台打印队列）
    """
    _VARS = {
        "SAVEFIDELITY": 0,  # 关闭 DXF→DWG 副本保存提示 ← 修复本次弹窗的核心
        "FILEDIA": 0,  # 关闭文件对话框
        "CMDDIA": 0,  # 关闭命令行对话框
        "BACKGROUNDPLOT": 0,  # 同步打印
    }
    targets = [t for t in (app, doc) if t is not None]
    for var, val in _VARS.items():
        set_ok = False
        for target in targets:
            if _set_sysvar(target, var, val):
                set_ok = True
        if (not set_ok) and doc is not None:
            # SetVariable 不可用时，退回命令行设置
            with contextlib.suppress(Exception):
                doc.SendCommand(f"_.{var} {val}\n")


def _mark_document_clean(app, doc) -> None:
    """将文档标记为"未修改"，使 doc.Close(False) 不弹保存确认框。

    DBMOD=0 告知 AutoCAD 自上次保存后未作任何修改。
    """
    if doc is None:
        return
    # COM 标准属性：直接声明已保存，抑制关闭时保存询问
    with contextlib.suppress(Exception):
        doc.Saved = True
    for target in (doc, app):
        if _set_sysvar(target, "DBMOD", 0):
            return
    # 最后兜底：命令行设置 DBMOD
    with contextlib.suppress(Exception):
        doc.SendCommand("_.DBMOD 0\n")


def _plot_job_with_opened_app(
    app,
    *,
    dxf_path: Path,
    pdf_path: Path,
    clip_bbox: BBox | None,
    paper_size_mm: tuple[float, float] | None,
    pc3_name: str,
    ctb_name: str,
    margins: dict[str, float] | None,
) -> None:
    """在已打开的 AutoCAD 进程内处理单个 DXF→PDF 任务。"""
    doc = None
    try:
        _suppress_autocad_dialogs(app)
        app.Documents.Open(str(dxf_path.resolve()))
        doc = _wait_active_document(app, dxf_path.stem)
        _suppress_autocad_dialogs(app, doc)

        layout = _activate_model_layout(doc)
        _set_layout_attr(layout, "ConfigName", pc3_name, strict=True)
        with contextlib.suppress(Exception):
            layout.RefreshPlotDeviceInfo()
        with contextlib.suppress(Exception):
            layout.CanonicalMediaName = _pick_media_name(paper_size_mm)
        _set_layout_attr(layout, "StyleSheet", ctb_name)
        _set_layout_attr(layout, "PlotWithPlotStyles", True)
        _set_layout_attr(layout, "ScaleLineweights", True)
        _set_layout_attr(layout, "UseStandardScale", True)
        _set_layout_attr(layout, "StandardScale", _ACAD_SCALE_TO_FIT)
        _set_layout_attr(layout, "CenterPlot", True)

        window_bbox = _build_plot_window_bbox(
            clip_bbox=clip_bbox,
            paper_size_mm=paper_size_mm,
            margins=margins,
        )
        window_set = False
        if window_bbox is not None:
            try:
                ll, ur = _bbox_to_window_points(window_bbox)
                _set_plot_window(layout, ll, ur)
                window_set = True
            except Exception as exc:
                logger.warning("Window 打印范围设置失败，尝试 ZoomWindow+Display: %s", exc)
                with contextlib.suppress(Exception):
                    ll, ur = _bbox_to_window_points(window_bbox)
                    _zoom_to_bbox(app, doc, ll, ur)
                    _set_layout_attr(layout, "PlotType", _ACAD_PLOT_DISPLAY, strict=True)
                    window_set = True

        if not window_set:
            with contextlib.suppress(Exception):
                app.ZoomExtents()
            with contextlib.suppress(Exception):
                doc.Regen(0)  # acAllViewports = 0
            # 最后回退：Display / Extents
            if not _set_layout_attr(layout, "PlotType", _ACAD_PLOT_DISPLAY):
                _set_layout_attr(layout, "PlotType", _ACAD_PLOT_EXTENTS, strict=True)

        result = _plot_to_file_with_retry(doc, pdf_path.resolve())
        if not result:
            raise RuntimeError("PlotToFile 返回 False（打印已取消或失败）")
        _wait_file_stable(pdf_path, timeout_sec=30.0)
    finally:
        if doc is not None:
            _mark_document_clean(app, doc)
            with contextlib.suppress(Exception):
                doc.Close(False)


def _activate_model_layout(doc):
    """切到 Model 布局，避免在空白纸空间布局中打印。"""
    with contextlib.suppress(Exception):
        _set_sysvar(doc, "TILEMODE", 1)

    model_layout = None
    with contextlib.suppress(Exception):
        model_layout = _com_get_with_retry(lambda: doc.Layouts.Item("Model"), "Layouts.Item(Model)")

    if model_layout is not None:
        with contextlib.suppress(Exception):
            doc.ActiveLayout = model_layout

    with contextlib.suppress(Exception):
        doc.ActiveSpace = _ACAD_MODEL_SPACE
    with contextlib.suppress(Exception):
        doc.MSpace = True

    active_layout = _com_get_with_retry(lambda: doc.ActiveLayout, "ActiveLayout")
    layout_name = _com_get_with_retry(lambda: str(active_layout.Name), "ActiveLayout.Name")
    if model_layout is not None and layout_name.lower() != "model":
        with contextlib.suppress(Exception):
            doc.ActiveLayout = model_layout
        active_layout = _com_get_with_retry(lambda: doc.ActiveLayout, "ActiveLayout(Model)")
    return active_layout


def _com_get_with_retry(getter, desc: str, retries: int = 10):
    """读取 COM 属性（处理 RPC_E_CALL_REJECTED）。"""
    last_exc: Exception | None = None
    for _ in range(retries):
        try:
            return getter()
        except Exception as exc:
            last_exc = exc
            time.sleep(0.8 if _is_call_rejected(exc) else 0.3)
    raise RuntimeError(f"读取 COM 属性失败: {desc}: {last_exc}") from last_exc


def _is_call_rejected(exc: Exception) -> bool:
    """判断是否为 AutoCAD COM 忙导致的拒绝调用。"""
    with contextlib.suppress(Exception):
        hresult = getattr(exc, "hresult", None)
        if hresult == _RPC_CALL_REJECTED:
            return True
    msg = str(exc).lower()
    return ("被呼叫方拒绝接收呼叫" in msg) or ("call was rejected by callee" in msg)


def _build_plot_window_bbox(
    *,
    clip_bbox: BBox | None,
    paper_size_mm: tuple[float, float] | None,
    margins: dict[str, float] | None,
) -> BBox | None:
    """将图框 bbox 扩展为打印窗口（叠加页边距）。"""
    if clip_bbox is None:
        return None

    m = margins or {}
    left_mm = float(m.get("left", 20))
    right_mm = float(m.get("right", 10))
    top_mm = float(m.get("top", 20))
    bottom_mm = float(m.get("bottom", 10))

    # 默认按 1:1（图纸单位≈mm）处理
    sx = sy = 1.0
    if paper_size_mm:
        pw, ph = paper_size_mm
        if pw > 1e-6 and ph > 1e-6 and clip_bbox.width > 1e-6 and clip_bbox.height > 1e-6:
            # 用图框宽高与标准图幅推导“每毫米对应的图纸单位”
            sx = clip_bbox.width / pw
            sy = clip_bbox.height / ph

    return BBox(
        xmin=clip_bbox.xmin - left_mm * sx,
        ymin=clip_bbox.ymin - bottom_mm * sy,
        xmax=clip_bbox.xmax + right_mm * sx,
        ymax=clip_bbox.ymax + top_mm * sy,
    )


def _set_plot_window(layout, ll: tuple[float, float], ur: tuple[float, float]) -> None:
    """设置 Window 打印范围与 PlotType（带重试，处理 AutoCAD 忙状态）。"""
    last_exc: Exception | None = None
    ll_pt = _to_com_point2d(ll)
    ur_pt = _to_com_point2d(ur)
    for _ in range(8):
        try:
            # 某些 AutoCAD 版本要求先切到 Window 模式，再设置窗口坐标
            with contextlib.suppress(Exception):
                layout.PlotType = _ACAD_PLOT_WINDOW
            layout.SetWindowToPlot(ll_pt, ur_pt)
            layout.PlotType = _ACAD_PLOT_WINDOW
            return
        except Exception as exc:
            last_exc = exc
            # AutoCAD 忙状态（RPC_E_CALL_REJECTED）给更长回退时间
            time.sleep(0.8 if _is_call_rejected(exc) else 0.35)
    raise RuntimeError(f"设置 Window 打印范围失败: {last_exc}") from last_exc


def _zoom_to_bbox(app, doc, ll: tuple[float, float], ur: tuple[float, float]) -> None:
    """用视图窗口定位打印区域（SetWindowToPlot 失败时兜底）。"""
    last_exc: Exception | None = None
    ll_pt = _to_com_point2d(ll)
    ur_pt = _to_com_point2d(ur)
    for _ in range(6):
        try:
            app.ZoomWindow(ll_pt, ur_pt)
            with contextlib.suppress(Exception):
                doc.Regen(0)
            return
        except Exception as exc:
            last_exc = exc
            time.sleep(0.8 if _is_call_rejected(exc) else 0.35)
    raise RuntimeError(f"ZoomWindow 定位失败: {last_exc}") from last_exc


def _set_layout_attr(layout, attr_name: str, value, *, strict: bool = False) -> bool:
    """设置布局属性（处理 AutoCAD COM 忙状态/属性不支持）。"""
    last_exc: Exception | None = None
    for _ in range(6):
        try:
            setattr(layout, attr_name, value)
            return True
        except Exception as exc:
            last_exc = exc
            time.sleep(0.35)
    if strict:
        raise RuntimeError(f"设置布局属性失败: {attr_name}={value} ({last_exc})") from last_exc
    logger.debug("忽略布局属性写入失败: %s=%s, err=%s", attr_name, value, last_exc)
    return False


def _plot_to_file_with_retry(doc, pdf_path: Path, retries: int = 6) -> bool:
    """调用 PlotToFile（处理 COM '被呼叫方拒绝接收呼叫'）。"""
    last_exc: Exception | None = None
    for _ in range(retries):
        try:
            return bool(doc.Plot.PlotToFile(str(pdf_path)))
        except Exception as exc:
            last_exc = exc
            time.sleep(0.8 if _is_call_rejected(exc) else 0.4)
    raise RuntimeError(f"PlotToFile 调用失败: {last_exc}") from last_exc


def _bbox_to_window_points(bbox: BBox) -> tuple[tuple[float, float], tuple[float, float]]:
    """将 BBox 转为 AutoCAD SetWindowToPlot 需要的左下/右上点。"""
    ll = (float(bbox.xmin), float(bbox.ymin))
    ur = (float(bbox.xmax), float(bbox.ymax))
    return ll, ur


def _to_com_point2d(point: tuple[float, float]):
    """构造 COM 2D 点参数（SAFEARRAY[Double, Double]）。"""
    try:
        import pythoncom  # type: ignore[import]
        import win32com.client  # type: ignore[import]

        return win32com.client.VARIANT(
            pythoncom.VT_ARRAY | pythoncom.VT_R8,
            [float(point[0]), float(point[1])],
        )
    except Exception:
        return [float(point[0]), float(point[1])]


def _set_sysvar(target, var_name: str, value) -> bool:
    """尝试调用 SetVariable，成功返回 True。"""
    with contextlib.suppress(Exception):
        target.SetVariable(var_name, value)
        return True
    return False


def _popup_watchdog(stop_evt: threading.Event, stats: dict[str, int]) -> None:
    """检测 AutoCAD 保存询问弹窗并自动点击“否”。"""
    try:
        import win32con  # type: ignore[import]
        import win32gui  # type: ignore[import]
    except Exception:
        return

    deny_keywords = ("否", "No", "不保存", "Don't Save", "&No", "N)")
    prompt_keywords = (
        "是否将改动保存到",
        "是否保存",
        "save changes",
        "do you want to save",
    )

    while not stop_evt.is_set():
        try:
            dialogs: list[int] = []

            def _enum_windows(hwnd, _, _dialogs=dialogs):
                if not win32gui.IsWindowVisible(hwnd):
                    return
                cls = win32gui.GetClassName(hwnd)
                title = (win32gui.GetWindowText(hwnd) or "").strip()
                if cls == "#32770" or "AutoCAD" in title:
                    _dialogs.append(hwnd)

            win32gui.EnumWindows(_enum_windows, None)

            for dlg in dialogs:
                text_blob = _collect_window_text(win32gui, dlg).lower()
                if not any(k in text_blob for k in prompt_keywords):
                    continue
                btn = _find_dialog_button(win32gui, dlg, deny_keywords)
                if btn:
                    win32gui.SendMessage(btn, _BM_CLICK, 0, 0)
                    stats["closed"] = int(stats.get("closed", 0)) + 1
                    logger.warning("检测到保存弹窗，已自动点击“否”")
                else:
                    # 无法定位按钮时发送 ESC 兜底
                    win32gui.PostMessage(dlg, win32con.WM_KEYDOWN, win32con.VK_ESCAPE, 0)
                    win32gui.PostMessage(dlg, win32con.WM_KEYUP, win32con.VK_ESCAPE, 0)
                    stats["closed"] = int(stats.get("closed", 0)) + 1
                    logger.warning("检测到保存弹窗，已自动发送 ESC")
        except Exception:
            pass
        time.sleep(0.35)


def _collect_window_text(win32gui_mod, hwnd: int) -> str:
    """收集窗口及子控件文本。"""
    texts: list[str] = []
    with contextlib.suppress(Exception):
        title = win32gui_mod.GetWindowText(hwnd)
        if title:
            texts.append(title)

    def _enum_child(ch, _):
        with contextlib.suppress(Exception):
            t = win32gui_mod.GetWindowText(ch)
            if t:
                texts.append(t)

    with contextlib.suppress(Exception):
        win32gui_mod.EnumChildWindows(hwnd, _enum_child, None)

    return "\n".join(texts)


def _find_dialog_button(win32gui_mod, hwnd: int, keywords: tuple[str, ...]) -> int | None:
    """在弹窗中查找“否/No”按钮。"""
    result: list[int] = []

    def _enum_child(ch, _):
        with contextlib.suppress(Exception):
            cls = win32gui_mod.GetClassName(ch)
            txt = (win32gui_mod.GetWindowText(ch) or "").strip()
            if cls == "Button" and any(k.lower() in txt.lower() for k in keywords):
                result.append(ch)

    with contextlib.suppress(Exception):
        win32gui_mod.EnumChildWindows(hwnd, _enum_child, None)
    return result[0] if result else None


def _wait_file_stable(path: Path, timeout_sec: float = 30.0, interval: float = 0.5) -> None:
    """等待 PDF 文件写入完成（大小稳定），避免后续打开时文件不完整。"""
    deadline = time.monotonic() + timeout_sec
    prev_size = -1
    while time.monotonic() < deadline:
        try:
            cur_size = path.stat().st_size
            if cur_size > 0 and cur_size == prev_size:
                return
            prev_size = cur_size
        except OSError:
            pass
        time.sleep(interval)
    # 超时时不报错，仅记录警告，让调用方决定是否可用
    logger.warning("PDF 文件写入稳定性等待超时: %s (size=%d)", path.name, prev_size)
