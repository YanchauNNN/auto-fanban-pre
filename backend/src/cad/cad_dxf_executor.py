"""
CAD-DXF 执行器

职责：
- 按 source_dxf 分组
- 构建 task.json（模块2/3/4 -> 模块5执行契约）
- 调用 AcCoreConsoleRunner 执行
- 解析 result.json 并回填模型路径/flags
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from ..config import RuntimeConfig, get_config, load_spec
from ..models import BBox, FrameMeta, SheetSet
from .accoreconsole_runner import AcCoreConsoleRunner
from .dxf_pdf_exporter import DxfPdfExporter


class CADDXFExecutor:
    """模块5 CAD-DXF 主执行器。"""

    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        runner: AcCoreConsoleRunner | None = None,
        spec=None,
    ) -> None:
        self.config = config or get_config()
        self.spec = spec or load_spec()
        self.runner = runner or AcCoreConsoleRunner(config=self.config)
        self._pdf_fallback_exporter = self._build_pdf_fallback_exporter()

    def group_by_source_dxf(
        self,
        frames: list[FrameMeta],
        sheet_sets: list[SheetSet],
    ) -> dict[Path, dict[str, list]]:
        """按 CAD 源文件分组，保证同一源文件一次会话执行。"""
        grouped: dict[Path, dict[str, list]] = {}
        for frame in frames:
            source = self._resolve_cad_source_file(frame)
            grouped.setdefault(source, {"frames": [], "sheet_sets": []})["frames"].append(frame)

        for sheet_set in sheet_sets:
            if not sheet_set.master_page or not sheet_set.master_page.frame_meta:
                continue
            source = self._resolve_cad_source_file(sheet_set.master_page.frame_meta)
            grouped.setdefault(source, {"frames": [], "sheet_sets": []})["sheet_sets"].append(
                sheet_set,
            )

        return grouped

    @staticmethod
    def _resolve_cad_source_file(frame: FrameMeta) -> Path:
        cad_source = frame.runtime.cad_source_file or frame.runtime.source_file
        return cad_source.resolve()

    def execute_source_dxf(
        self,
        *,
        job_id: str,
        source_dxf: Path,
        frames: list[FrameMeta],
        sheet_sets: list[SheetSet],
        output_dir: Path,
        task_root: Path,
    ) -> dict:
        """执行单个 CAD 源文件分组任务。"""
        source_dxf = source_dxf.resolve()
        output_dir = output_dir.resolve()
        task_root = task_root.resolve()
        task_root.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        requested_task_dir = task_root / self._safe_task_dir_name(source_dxf)
        requested_task_dir.mkdir(parents=True, exist_ok=True)

        runtime_task_dir = self._make_runtime_task_dir(source_dxf)
        runtime_task_dir.mkdir(parents=True, exist_ok=True)
        task_json = runtime_task_dir / "task.json"
        result_json = runtime_task_dir / "result.json"
        source_suffix = source_dxf.suffix if source_dxf.suffix else ".dwg"
        staged_source_dxf = runtime_task_dir / f"source_input{source_suffix}"
        staged_output_dir = runtime_task_dir / "cad_stage_output"
        staged_output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_dxf, staged_source_dxf)

        task = self.build_task_json(
            job_id=job_id,
            source_dxf=staged_source_dxf,
            frames=frames,
            sheet_sets=sheet_sets,
            output_dir=staged_output_dir,
        )
        task_json.write_text(
            json.dumps(task, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self.runner.run(
            source_dxf=staged_source_dxf,
            task_json=task_json,
            result_json=result_json,
            workspace_dir=runtime_task_dir,
        )
        result = self.load_result_json(result_json)
        self._recover_pdf_with_python_fallback(
            result=result,
            frames=frames,
            sheet_sets=sheet_sets,
            staged_output_dir=staged_output_dir,
        )
        result_json.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._materialize_stage_outputs(
            result=result,
            staged_output_dir=staged_output_dir,
            final_output_dir=output_dir,
        )
        self._sync_runtime_artifacts(
            runtime_task_dir=runtime_task_dir,
            task_dir=requested_task_dir,
        )
        return result

    def build_task_json(
        self,
        *,
        job_id: str,
        source_dxf: Path,
        frames: list[FrameMeta],
        sheet_sets: list[SheetSet],
        output_dir: Path,
    ) -> dict:
        """构建 task.json（Python -> CAD）。"""
        self._validate_duplicate_codes(frames)

        plot_cfg = self.config.module5_export.plot
        selection_cfg = self.config.module5_export.selection
        margins_mm = self._resolve_plot_margins_mm()

        return {
            "schema_version": "cad-dxf-task@1.0",
            "job_id": job_id,
            "source_dxf": str(source_dxf),
            "output_dir": str(output_dir),
            "plot": {
                "pc3_name": plot_cfg.pc3_name,
                "ctb_name": plot_cfg.ctb_name,
                "use_monochrome": bool(plot_cfg.use_monochrome),
                "margins_mm": margins_mm,
            },
            "selection": {
                "mode": selection_cfg.mode,
                "bbox_margin_percent": float(selection_cfg.bbox_margin_percent),
                "empty_selection_retry_margin_percent": float(
                    selection_cfg.empty_selection_retry_margin_percent,
                ),
            },
            "frames": [self._build_frame_entry(frame) for frame in frames],
            "sheet_sets": [self._build_sheet_set_entry(sheet_set) for sheet_set in sheet_sets],
        }

    @staticmethod
    def load_result_json(result_json: Path) -> dict:
        """解析 result.json。"""
        if not result_json.exists():
            raise FileNotFoundError(f"result.json 不存在: {result_json}")
        return json.loads(result_json.read_text(encoding="utf-8"))

    def apply_result(
        self,
        *,
        result: dict,
        frames_by_id: dict[str, FrameMeta],
        sheet_sets_by_id: dict[str, SheetSet],
    ) -> tuple[int, int]:
        """回填 result.json 到内存模型，返回 (frame_count, sheet_set_count)。"""
        frame_count = 0
        for item in result.get("frames", []):
            frame_id = str(item.get("frame_id", ""))
            frame = frames_by_id.get(frame_id)
            if frame is None:
                continue
            frame_count += 1
            self._apply_frame_result(frame, item)

        sheet_count = 0
        for item in result.get("sheet_sets", []):
            cluster_id = str(item.get("cluster_id", ""))
            sheet_set = sheet_sets_by_id.get(cluster_id)
            if sheet_set is None:
                continue
            sheet_count += 1
            self._apply_sheet_set_result(sheet_set, item)

        return frame_count, sheet_count

    @staticmethod
    def _apply_frame_result(frame: FrameMeta, item: dict) -> None:
        status = str(item.get("status", "failed")).lower()
        for flag in item.get("flags", []):
            if isinstance(flag, str):
                frame.add_flag(flag)

        if status != "ok":
            frame.add_flag("导出失败")
            return

        pdf_path_raw = item.get("pdf_path")
        dwg_path_raw = item.get("dwg_path")

        if isinstance(pdf_path_raw, str) and pdf_path_raw:
            frame.runtime.pdf_path = Path(pdf_path_raw)
        else:
            frame.add_flag("PDF缺失")

        if isinstance(dwg_path_raw, str) and dwg_path_raw:
            frame.runtime.dwg_path = Path(dwg_path_raw)
        else:
            frame.add_flag("DWG缺失")

    @staticmethod
    def _apply_sheet_set_result(sheet_set: SheetSet, item: dict) -> None:
        status = str(item.get("status", "failed")).lower()
        for flag in item.get("flags", []):
            if isinstance(flag, str) and flag not in sheet_set.flags:
                sheet_set.flags.append(flag)

        if status != "ok" and "导出失败" not in sheet_set.flags:
            sheet_set.flags.append("导出失败")

    def _build_frame_entry(self, frame: FrameMeta) -> dict:
        return {
            "frame_id": frame.frame_id,
            "name": self._name_for_frame(frame),
            "bbox": self._bbox_to_dict(frame.runtime.outer_bbox),
            "vertices": self._vertices_for_frame(
                frame.runtime.outer_bbox, frame.runtime.outer_vertices
            ),
            "paper_size_mm": self._paper_size_for_frame(frame),
            "sx": float(frame.runtime.sx) if frame.runtime.sx is not None else None,
            "sy": float(frame.runtime.sy) if frame.runtime.sy is not None else None,
            "kind": "single",
        }

    def _build_sheet_set_entry(self, sheet_set: SheetSet) -> dict:
        pages = [
            {
                "page_index": page.page_index,
                "bbox": self._bbox_to_dict(page.outer_bbox),
                "vertices": (
                    self._vertices_for_frame(
                        page.outer_bbox,
                        page.frame_meta.runtime.outer_vertices,
                    )
                    if page.frame_meta
                    else self._vertices_from_bbox(page.outer_bbox)
                ),
                "paper_size_mm": self._a4_paper_size(page.outer_bbox),
                "sx": (
                    float(page.frame_meta.runtime.sx)
                    if page.frame_meta and page.frame_meta.runtime.sx is not None
                    else None
                ),
                "sy": (
                    float(page.frame_meta.runtime.sy)
                    if page.frame_meta and page.frame_meta.runtime.sy is not None
                    else None
                ),
            }
            for page in sheet_set.pages
        ]
        return {
            "cluster_id": sheet_set.cluster_id,
            "name": self._name_for_sheet_set(sheet_set),
            "pages": pages,
        }

    @staticmethod
    def _vertices_for_frame(
        bbox: BBox,
        vertices: list[tuple[float, float]],
    ) -> list[list[float]]:
        if vertices and len(vertices) >= 4:
            return [[float(x), float(y)] for x, y in vertices[:4]]
        return CADDXFExecutor._vertices_from_bbox(bbox)

    @staticmethod
    def _vertices_from_bbox(bbox: BBox) -> list[list[float]]:
        return [
            [float(bbox.xmin), float(bbox.ymin)],
            [float(bbox.xmax), float(bbox.ymin)],
            [float(bbox.xmax), float(bbox.ymax)],
            [float(bbox.xmin), float(bbox.ymax)],
        ]

    @staticmethod
    def _bbox_to_dict(bbox: BBox) -> dict[str, float]:
        return {
            "xmin": float(bbox.xmin),
            "ymin": float(bbox.ymin),
            "xmax": float(bbox.xmax),
            "ymax": float(bbox.ymax),
        }

    def _paper_size_for_frame(self, frame: FrameMeta) -> list[float] | None:
        variant_id = frame.runtime.paper_variant_id
        if not variant_id:
            return None

        variants = self.spec.get_paper_variants()
        variant = variants.get(variant_id)
        if variant is None:
            return None

        try:
            return [float(variant.W), float(variant.H)]
        except AttributeError:
            return None

    @staticmethod
    def _a4_paper_size(bbox: BBox) -> list[float]:
        # 复用现有经验规则：按 bbox 长宽判断横/竖版 A4
        if bbox.width >= bbox.height:
            return [297.0, 210.0]
        return [210.0, 297.0]

    def _validate_duplicate_codes(self, frames: list[FrameMeta]) -> None:
        policy = self.config.multi_dwg_policy.code_conflict
        if policy != "error":
            return

        seen_internal: set[str] = set()
        seen_external: set[str] = set()
        dup_internal: set[str] = set()
        dup_external: set[str] = set()

        for frame in frames:
            internal = (frame.titleblock.internal_code or "").strip()
            external = (frame.titleblock.external_code or "").strip()
            if internal:
                if internal in seen_internal:
                    dup_internal.add(internal)
                seen_internal.add(internal)
            if external:
                if external in seen_external:
                    dup_external.add(external)
                seen_external.add(external)

        if dup_internal or dup_external:
            raise ValueError(
                f"检测到重复编码: internal={sorted(dup_internal)}, external={sorted(dup_external)}",
            )

    @staticmethod
    def _name_for_frame(frame: FrameMeta) -> str:
        external = frame.titleblock.external_code
        internal = frame.titleblock.internal_code
        return CADDXFExecutor._make_output_name(
            external_code=external,
            internal_code=internal,
            fallback_id=frame.frame_id[:8],
        )

    @staticmethod
    def _name_for_sheet_set(sheet_set: SheetSet) -> str:
        if sheet_set.master_page and sheet_set.master_page.frame_meta:
            tb = sheet_set.master_page.frame_meta.titleblock
            return CADDXFExecutor._make_output_name(
                external_code=tb.external_code,
                internal_code=tb.internal_code,
                fallback_id=f"sheet_set_{sheet_set.cluster_id[:8]}",
            )
        return f"sheet_set_{sheet_set.cluster_id[:8]}"

    @staticmethod
    def _make_output_name(
        *,
        external_code: str | None,
        internal_code: str | None,
        fallback_id: str,
    ) -> str:
        if external_code and internal_code:
            return f"{external_code}({internal_code})"
        if internal_code:
            return internal_code
        if external_code:
            return external_code
        return fallback_id

    @staticmethod
    def _safe_task_dir_name(source_dxf: Path) -> str:
        stem = source_dxf.stem
        suffix = abs(hash(str(source_dxf))) % 10000
        safe = "".join(
            ch if (ch.isascii() and (ch.isalnum() or ch in ("-", "_"))) else "_" for ch in stem
        )
        safe = safe.strip("_") or "source"
        safe = safe[:48]
        return f"{safe}_{suffix:04d}"

    def _make_runtime_task_dir(self, source_dxf: Path) -> Path:
        base_dir = Path(tempfile.gettempdir()) / "fanban_module5_cad_tasks"
        base_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"{self._safe_task_dir_name(source_dxf)}_"
        return Path(tempfile.mkdtemp(prefix=prefix, dir=base_dir))

    @staticmethod
    def _sync_runtime_artifacts(*, runtime_task_dir: Path, task_dir: Path) -> None:
        for name in (
            "task.json",
            "result.json",
            "runtime_module5.scr",
            "accoreconsole.log",
            "module5_trace.log",
        ):
            src = runtime_task_dir / name
            if src.exists():
                shutil.copy2(src, task_dir / name)

    @staticmethod
    def _materialize_stage_outputs(
        *,
        result: dict,
        staged_output_dir: Path,
        final_output_dir: Path,
    ) -> None:
        for key in ("frames", "sheet_sets"):
            for item in result.get(key, []):
                if not isinstance(item, dict):
                    continue
                for path_key in ("pdf_path", "dwg_path"):
                    raw = item.get(path_key)
                    if not isinstance(raw, str) or not raw:
                        continue
                    src = Path(raw)
                    if not src.is_absolute():
                        src = staged_output_dir / src
                    dst = final_output_dir / src.name
                    if src.exists():
                        if src.resolve() != dst.resolve():
                            shutil.copy2(src, dst)
                        item[path_key] = str(dst)

    def _resolve_plot_margins_mm(self) -> dict[str, float]:
        """固定映射：doc_generation.options.pdf_margin_mm -> task.plot.margins_mm。"""
        spec_options = self.spec.doc_generation.get("options", {})
        raw = spec_options.get("pdf_margin_mm", {})
        if isinstance(raw, dict) and "default" in raw:
            raw = raw["default"]

        spec_margins = raw if isinstance(raw, dict) else {}
        runtime_margins = self.config.module5_export.plot.margins_mm

        merged = {}
        for k, default_value in (
            ("top", 20.0),
            ("bottom", 10.0),
            ("left", 20.0),
            ("right", 10.0),
        ):
            # 业务规范优先；缺失时回退到运行期配置。
            merged[k] = spec_margins.get(k, runtime_margins.get(k, default_value))

        return {k: float(v) for k, v in merged.items()}

    def _build_pdf_fallback_exporter(self) -> DxfPdfExporter:
        options = self.spec.doc_generation.get("options", {})

        def _opt(key: str, default):
            value = options.get(key, default)
            if isinstance(value, dict) and "default" in value:
                return value["default"]
            return value

        font_dirs = _opt("pdf_font_dirs", ["fronts/Fonts", "Fonts"])
        fallback_fonts = _opt(
            "pdf_fallback_font_family",
            ["SimSun", "Microsoft YaHei", "SimHei"],
        )
        if isinstance(font_dirs, str):
            font_dirs = [font_dirs]
        if isinstance(fallback_fonts, str):
            fallback_fonts = [fallback_fonts]

        return DxfPdfExporter(
            margins=self._resolve_plot_margins_mm(),
            aci1_linewidth=float(_opt("pdf_aci1_linewidth_mm", 0.4)),
            aci_default_linewidth=float(_opt("pdf_aci_default_linewidth_mm", 0.18)),
            font_dirs=font_dirs,
            fallback_font_family=fallback_fonts,
        )

    def _recover_pdf_with_python_fallback(
        self,
        *,
        result: dict,
        frames: list[FrameMeta],
        sheet_sets: list[SheetSet],
        staged_output_dir: Path,
    ) -> None:
        frames_by_id = {f.frame_id: f for f in frames}
        sheet_sets_by_id = {ss.cluster_id: ss for ss in sheet_sets}

        for item in result.get("frames", []):
            frame_id = str(item.get("frame_id", ""))
            frame = frames_by_id.get(frame_id)
            if frame is None:
                continue
            raw_pdf = item.get("pdf_path")
            raw_dwg = item.get("dwg_path")
            pdf_path = Path(raw_pdf) if isinstance(raw_pdf, str) and raw_pdf else None
            dwg_path = Path(raw_dwg) if isinstance(raw_dwg, str) and raw_dwg else None

            has_pdf = bool(pdf_path and pdf_path.exists())
            has_dwg = bool(dwg_path and dwg_path.exists())
            status = str(item.get("status", "failed")).lower()
            flags = item.get("flags", [])
            if not isinstance(flags, list):
                flags = []
            if has_pdf and pdf_path is not None:
                if self._normalize_cad_pdf_canvas_if_needed(frame=frame, pdf_path=pdf_path):
                    item.setdefault("flags", [])
                    if "PDF_CAD_CANVAS_ADJUSTED" not in item["flags"]:
                        item["flags"].append("PDF_CAD_CANVAS_ADJUSTED")
                if has_dwg and status != "ok":
                    item["status"] = "ok"
            if has_pdf or (status == "ok" and "PLOT_FAILED" not in flags):
                continue
            if pdf_path is None:
                name = self._name_for_frame(frame)
                pdf_path = staged_output_dir / f"{name}.pdf"
                item["pdf_path"] = str(pdf_path)

            paper = self._paper_size_for_frame(frame)
            paper_size = (
                (float(paper[0]), float(paper[1]))
                if isinstance(paper, list) and len(paper) == 2
                else None
            )
            self._pdf_fallback_exporter.export_single_page(
                frame.runtime.source_file,
                pdf_path,
                clip_bbox=frame.runtime.outer_bbox,
                paper_size_mm=paper_size,
            )
            item.setdefault("flags", [])
            if "PDF_PYTHON_FALLBACK" not in item["flags"]:
                item["flags"].append("PDF_PYTHON_FALLBACK")
            if has_dwg and pdf_path.exists():
                item["status"] = "ok"

        for item in result.get("sheet_sets", []):
            cluster_id = str(item.get("cluster_id", ""))
            sheet_set = sheet_sets_by_id.get(cluster_id)
            if sheet_set is None:
                continue
            raw_pdf = item.get("pdf_path")
            raw_dwg = item.get("dwg_path")
            pdf_path = Path(raw_pdf) if isinstance(raw_pdf, str) and raw_pdf else None
            dwg_path = Path(raw_dwg) if isinstance(raw_dwg, str) and raw_dwg else None

            has_pdf = bool(pdf_path and pdf_path.exists())
            has_dwg = bool(dwg_path and dwg_path.exists())
            status = str(item.get("status", "failed")).lower()
            flags = item.get("flags", [])
            if not isinstance(flags, list):
                flags = []
            if has_pdf or (status == "ok" and "PLOT_FAILED" not in flags):
                continue
            if pdf_path is None:
                name = self._name_for_sheet_set(sheet_set)
                pdf_path = staged_output_dir / f"{name}.pdf"
                item["pdf_path"] = str(pdf_path)

            # CAD窗口打印（按页输出）成功时，先合并 CAD 页级 PDF，避免错误回退为 Python 渲染。
            page_pdf_paths = item.get("page_pdf_paths")
            if isinstance(page_pdf_paths, list):
                page_paths: list[Path] = []
                for raw in page_pdf_paths:
                    if not isinstance(raw, str) or not raw:
                        continue
                    p = Path(raw)
                    if not p.is_absolute():
                        p = staged_output_dir / p
                    if p.exists():
                        page_paths.append(p)
                expected_page_count = len(sheet_set.pages)
                failure_flags = {
                    "PLOT_FAILED",
                    "WBLOCK_FAILED",
                    "CAD_EMPTY_SELECTION",
                    "A4_MULTI_NO_PAGES",
                }
                has_hard_failure = any(
                    isinstance(flag, str) and flag in failure_flags for flag in flags
                )
                has_complete_pages = (
                    expected_page_count > 0 and len(page_paths) == expected_page_count
                )

                if page_paths and has_complete_pages and not has_hard_failure:
                    first_page_bbox = sheet_set.pages[0].outer_bbox if sheet_set.pages else None
                    sheet_paper = self._a4_paper_size(first_page_bbox) if first_page_bbox else None
                    if isinstance(sheet_paper, list) and len(sheet_paper) == 2:
                        for page_path in page_paths:
                            self._normalize_cad_pdf_canvas_for_paper(
                                pdf_path=page_path,
                                paper_size_mm=(float(sheet_paper[0]), float(sheet_paper[1])),
                            )
                    self._merge_pdf_pages(page_paths, pdf_path)
                    item.setdefault("flags", [])
                    if "PDF_CAD_WINDOW_MERGED" not in item["flags"]:
                        item["flags"].append("PDF_CAD_WINDOW_MERGED")
                    if has_dwg and pdf_path.exists():
                        item["status"] = "ok"
                    continue
                if page_paths and (not has_complete_pages or has_hard_failure):
                    item.setdefault("flags", [])
                    if "PDF_CAD_WINDOW_PARTIAL" not in item["flags"]:
                        item["flags"].append("PDF_CAD_WINDOW_PARTIAL")

            page_bboxes = [page.outer_bbox for page in sheet_set.pages]
            paper_size = self._a4_paper_size(page_bboxes[0]) if page_bboxes else None
            source_dxf = (
                sheet_set.master_page.frame_meta.runtime.source_file
                if sheet_set.master_page and sheet_set.master_page.frame_meta
                else None
            )
            if source_dxf is None:
                continue
            self._pdf_fallback_exporter.export_multipage(
                source_dxf,
                pdf_path,
                page_bboxes,
                paper_size_mm=paper_size,
            )
            item.setdefault("flags", [])
            if "PDF_PYTHON_FALLBACK" not in item["flags"]:
                item["flags"].append("PDF_PYTHON_FALLBACK")
            if has_dwg and pdf_path.exists():
                item["status"] = "ok"

    @staticmethod
    def _merge_pdf_pages(page_paths: list[Path], output_pdf: Path) -> None:
        if not page_paths:
            raise ValueError("无可合并的页级PDF")
        try:
            from pypdf import PdfWriter
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("pypdf 未安装，无法合并页级PDF") from exc

        writer = PdfWriter()
        for path in page_paths:
            writer.append(str(path))
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        with open(output_pdf, "wb") as f:
            writer.write(f)
        for path in page_paths:
            try:
                path.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                continue

    def _normalize_cad_pdf_canvas_if_needed(self, *, frame: FrameMeta, pdf_path: Path) -> bool:
        paper = self._paper_size_for_frame(frame)
        if not isinstance(paper, list) or len(paper) != 2:
            return False
        return self._normalize_cad_pdf_canvas_for_paper(
            pdf_path=pdf_path,
            paper_size_mm=(float(paper[0]), float(paper[1])),
        )

    def _normalize_cad_pdf_canvas_for_paper(
        self,
        *,
        pdf_path: Path,
        paper_size_mm: tuple[float, float],
    ) -> bool:
        try:
            from pypdf import PdfReader, PdfWriter
        except Exception:  # noqa: BLE001
            return False

        margins = self._resolve_plot_margins_mm()
        expected_w_mm = float(paper_size_mm[0]) + float(margins["left"]) + float(margins["right"])
        expected_h_mm = float(paper_size_mm[1]) + float(margins["top"]) + float(margins["bottom"])

        try:
            reader = PdfReader(str(pdf_path))
        except Exception:  # noqa: BLE001
            return False
        if len(reader.pages) != 1:
            return False

        page = reader.pages[0]
        actual_w_mm = float(page.mediabox.width) * 25.4 / 72.0
        actual_h_mm = float(page.mediabox.height) * 25.4 / 72.0
        tol_mm = 1.5

        def _close(a: float, b: float) -> bool:
            return abs(a - b) <= tol_mm

        if _close(actual_w_mm, expected_w_mm) and _close(actual_h_mm, expected_h_mm):
            return False

        # 仅在接近基础图幅（无页边距）时扩展画布，避免误改正常文件。
        base_w_mm = float(paper_size_mm[0])
        base_h_mm = float(paper_size_mm[1])
        is_base_size = (_close(actual_w_mm, base_w_mm) and _close(actual_h_mm, base_h_mm)) or (
            _close(actual_w_mm, base_h_mm) and _close(actual_h_mm, base_w_mm)
        )
        if not is_base_size:
            return False

        rotated_for_orientation = False
        if (actual_h_mm > actual_w_mm and expected_w_mm > expected_h_mm) or (
            actual_w_mm > actual_h_mm and expected_h_mm > expected_w_mm
        ):
            page.rotate(90)
            rotated_for_orientation = True

        target_w_mm = expected_w_mm
        target_h_mm = expected_h_mm
        if rotated_for_orientation:
            # 旋转仅设置页面显示方向，不会改变内容坐标系；需交换画布宽高防止裁切。
            target_w_mm, target_h_mm = target_h_mm, target_w_mm

        target_w_pt = self._mm_to_pt(target_w_mm)
        target_h_pt = self._mm_to_pt(target_h_mm)
        left_pt = self._mm_to_pt(float(margins["left"]))
        bottom_pt = self._mm_to_pt(float(margins["bottom"]))
        page.mediabox.lower_left = (-left_pt, -bottom_pt)
        page.mediabox.upper_right = (target_w_pt - left_pt, target_h_pt - bottom_pt)

        writer = PdfWriter()
        writer.add_page(page)
        with open(pdf_path, "wb") as f:
            writer.write(f)
        return True

    @staticmethod
    def _mm_to_pt(mm: float) -> float:
        return mm * 72.0 / 25.4
