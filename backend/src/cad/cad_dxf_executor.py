"""
CAD-DXF 执行器

职责：
- 按 source_dxf 分组
- 构建 task.json（模块2/3/4 -> 模块5执行契约）
- 调用 AcCoreConsoleRunner 执行
- 解析 result.json 并回填模型路径/flags
"""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
from pathlib import Path

from ..config import RuntimeConfig, get_config, load_spec
from ..models import BBox, FrameMeta, SheetSet
from .accoreconsole_runner import AcCoreConsoleRunner


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
        """执行单个 CAD 源文件分组任务（固定两阶段：先切图，再从切图DWG打印）。"""
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

        split_task = self.build_task_json(
            job_id=job_id,
            source_dxf=staged_source_dxf,
            frames=frames,
            sheet_sets=sheet_sets,
            output_dir=staged_output_dir,
            workflow_stage="split_only",
        )
        split_run_meta = self._run_runner_with_engine_fallback(
            source_dxf=staged_source_dxf,
            task_payload=split_task,
            task_json=task_json,
            result_json=result_json,
            workspace_dir=runtime_task_dir,
        )
        split_result = self.load_result_json(result_json)
        if split_run_meta["fallback_used"]:
            split_result.setdefault("errors", []).append(
                f"DOTNET_TO_LISP_FALLBACK:{split_run_meta['reason']}",
            )

        final_result = self._run_plot_stage_from_split_dwg(
            job_id=job_id,
            source_dxf=staged_source_dxf,
            runtime_task_dir=runtime_task_dir,
            staged_output_dir=staged_output_dir,
            split_result=split_result,
            frames=frames,
            sheet_sets=sheet_sets,
        )
        self._write_task_json(result_json, final_result)

        self._materialize_stage_outputs(
            result=final_result,
            staged_output_dir=staged_output_dir,
            final_output_dir=output_dir,
        )
        self._sync_runtime_artifacts(
            runtime_task_dir=runtime_task_dir,
            task_dir=requested_task_dir,
        )
        return final_result

    def build_task_json(
        self,
        *,
        job_id: str,
        source_dxf: Path,
        frames: list[FrameMeta],
        sheet_sets: list[SheetSet],
        output_dir: Path,
        workflow_stage: str = "split_only",
    ) -> dict:
        """构建 task.json（Python -> CAD）。"""
        self._validate_duplicate_codes(frames)
        return self._build_task_json_from_entries(
            job_id=job_id,
            source_dxf=source_dxf,
            output_dir=output_dir,
            workflow_stage=workflow_stage,
            frame_entries=[self._build_frame_entry(frame) for frame in frames],
            sheet_set_entries=[self._build_sheet_set_entry(sheet_set) for sheet_set in sheet_sets],
        )

    def _build_task_json_from_entries(
        self,
        *,
        job_id: str,
        source_dxf: Path,
        output_dir: Path,
        workflow_stage: str,
        frame_entries: list[dict],
        sheet_set_entries: list[dict],
        output_override: dict[str, str | bool] | None = None,
    ) -> dict:
        plot_cfg = self.config.module5_export.plot
        selection_cfg = self.config.module5_export.selection
        margins_mm = self._resolve_plot_margins_mm()
        output_entry = self._build_output_entry()
        if output_override:
            output_entry.update(output_override)
        return {
            "schema_version": "cad-dxf-task@1.0",
            "workflow_stage": workflow_stage,
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
                "hard_retry_margin_percent": float(selection_cfg.hard_retry_margin_percent),
                "db_unknown_bbox_policy": str(selection_cfg.db_unknown_bbox_policy),
                "db_fallback_to_crossing": bool(selection_cfg.db_fallback_to_crossing),
            },
            "output": output_entry,
            "engines": self._build_engines_entry(),
            "frames": frame_entries,
            "sheet_sets": sheet_set_entries,
        }

    def _build_output_entry(self) -> dict[str, str | bool | int]:
        output_cfg = self.config.module5_export.output
        return {
            "a4_multipage_pdf": str(output_cfg.a4_multipage_pdf),
            "on_frame_fail": str(output_cfg.on_frame_fail),
            "pdf_from_split_dwg_mode": str(output_cfg.pdf_from_split_dwg_mode),
            "split_stage_plot_enabled": bool(output_cfg.split_stage_plot_enabled),
            "plot_preferred_area": str(output_cfg.plot_preferred_area),
            "plot_fallback_area": str(output_cfg.plot_fallback_area),
            "plot_session_mode": str(output_cfg.plot_session_mode),
            "plot_from_source_window_enabled": bool(output_cfg.plot_from_source_window_enabled),
            "plot_fallback_to_split_on_failure": bool(output_cfg.plot_fallback_to_split_on_failure),
            "pdf_validation_min_size_bytes": int(output_cfg.pdf_validation_min_size_bytes),
            "pdf_validation_min_stream_bytes": int(output_cfg.pdf_validation_min_stream_bytes),
        }

    def _build_engines_entry(self) -> dict:
        selection_cfg = self.config.module5_export.selection
        output_cfg = self.config.module5_export.output
        bridge_cfg = self.config.module5_export.dotnet_bridge
        return {
            "selection_engine": str(selection_cfg.engine).strip().lower(),
            "plot_engine": str(output_cfg.plot_engine).strip().lower(),
            "dotnet_bridge": {
                "enabled": bool(bridge_cfg.enabled),
                "dll_path": str(bridge_cfg.dll_path),
                "command_name": str(bridge_cfg.command_name),
                "netload_each_run": bool(bridge_cfg.netload_each_run),
                "fallback_to_lisp_on_error": bool(bridge_cfg.fallback_to_lisp_on_error),
            },
        }

    @staticmethod
    def _write_task_json(path: Path, data: dict) -> None:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _run_plot_stage_from_split_dwg(
        self,
        *,
        job_id: str,
        source_dxf: Path,
        runtime_task_dir: Path,
        staged_output_dir: Path,
        split_result: dict,
        frames: list[FrameMeta],
        sheet_sets: list[SheetSet],
    ) -> dict:
        frames_by_id = {frame.frame_id: frame for frame in frames}
        sheet_sets_by_id = {sheet_set.cluster_id: sheet_set for sheet_set in sheet_sets}
        output_cfg = self.config.module5_export.output
        use_window_batch = bool(output_cfg.plot_from_source_window_enabled)
        use_split_fallback = bool(output_cfg.plot_fallback_to_split_on_failure)
        session_mode = str(output_cfg.plot_session_mode).strip().lower()

        window_items_by_id: dict[str, dict] = {}
        errors: list[str] = []

        if use_window_batch and session_mode == "per_source_batch":
            try:
                window_result = self._run_source_window_plot_batch(
                    job_id=job_id,
                    source_dxf=source_dxf,
                    runtime_task_dir=runtime_task_dir,
                    staged_output_dir=staged_output_dir,
                    frames=frames,
                    sheet_sets=sheet_sets,
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"WINDOW_BATCH_FAILED:{exc}")
                window_result = {"frames": [], "errors": [f"WINDOW_BATCH_FAILED:{exc}"]}
            for item in window_result.get("frames", []):
                if not isinstance(item, dict):
                    continue
                fid = str(item.get("frame_id", ""))
                if fid:
                    window_items_by_id[fid] = item
            for err in window_result.get("errors", []):
                if isinstance(err, str) and err:
                    errors.append(err)

        final_frames: list[dict] = []
        for item in split_result.get("frames", []):
            if not isinstance(item, dict):
                continue
            frame_id = str(item.get("frame_id", ""))
            frame = frames_by_id.get(frame_id)
            if use_window_batch and session_mode == "per_source_batch":
                final_frames.append(
                    self._finalize_frame_with_window_then_fallback(
                        job_id=job_id,
                        runtime_task_dir=runtime_task_dir,
                        staged_output_dir=staged_output_dir,
                        split_item=item,
                        frame=frame,
                        window_plot_item=window_items_by_id.get(frame_id),
                        use_split_fallback=use_split_fallback,
                    ),
                )
            else:
                final_frames.append(
                    self._plot_single_frame_from_split_dwg(
                        job_id=job_id,
                        runtime_task_dir=runtime_task_dir,
                        staged_output_dir=staged_output_dir,
                        split_item=item,
                        frame=frame,
                    ),
                )

        final_sheet_sets: list[dict] = []
        for item in split_result.get("sheet_sets", []):
            if not isinstance(item, dict):
                continue
            cluster_id = str(item.get("cluster_id", ""))
            sheet_set = sheet_sets_by_id.get(cluster_id)
            if use_window_batch and session_mode == "per_source_batch":
                final_sheet_sets.append(
                    self._finalize_sheet_set_with_window_then_fallback(
                        job_id=job_id,
                        runtime_task_dir=runtime_task_dir,
                        staged_output_dir=staged_output_dir,
                        split_item=item,
                        sheet_set=sheet_set,
                        window_items_by_id=window_items_by_id,
                        use_split_fallback=use_split_fallback,
                    ),
                )
            else:
                final_sheet_sets.append(
                    self._plot_sheet_set_from_split_dwgs(
                        job_id=job_id,
                        runtime_task_dir=runtime_task_dir,
                        staged_output_dir=staged_output_dir,
                        split_item=item,
                        sheet_set=sheet_set,
                    ),
                )

        for err in split_result.get("errors", []):
            if isinstance(err, str) and err:
                errors.append(err)

        return {
            "schema_version": "cad-dxf-result@1.0",
            "job_id": job_id,
            "source_dxf": str(source_dxf),
            "frames": final_frames,
            "sheet_sets": final_sheet_sets,
            "errors": errors,
        }

    def _run_source_window_plot_batch(
        self,
        *,
        job_id: str,
        source_dxf: Path,
        runtime_task_dir: Path,
        staged_output_dir: Path,
        frames: list[FrameMeta],
        sheet_sets: list[SheetSet],
    ) -> dict:
        frame_entries: list[dict] = [self._build_frame_entry(frame) for frame in frames]
        for sheet_set in sheet_sets:
            sheet_name = self._name_for_sheet_set(sheet_set)
            for page in sorted(sheet_set.pages, key=lambda p: p.page_index):
                frame_entries.append(
                    self._build_plot_frame_entry_from_page(
                        frame_id=f"{sheet_set.cluster_id}__p{page.page_index}",
                        name=f"{sheet_name}__p{page.page_index}",
                        page=page,
                    ),
                )
        if not frame_entries:
            return {
                "schema_version": "cad-dxf-result@1.0",
                "job_id": job_id,
                "source_dxf": str(source_dxf),
                "frames": [],
                "sheet_sets": [],
                "errors": [],
            }

        plot_task = self._build_task_json_from_entries(
            job_id=job_id,
            source_dxf=source_dxf,
            output_dir=staged_output_dir,
            workflow_stage="plot_window_only",
            frame_entries=frame_entries,
            sheet_set_entries=[],
            output_override={"plot_preferred_area": "window", "plot_fallback_area": "none"},
        )
        return self._run_plot_task_from_dwg(
            source_dwg=source_dxf,
            runtime_task_dir=runtime_task_dir,
            task_data=plot_task,
        )

    def _finalize_frame_with_window_then_fallback(
        self,
        *,
        job_id: str,
        runtime_task_dir: Path,
        staged_output_dir: Path,
        split_item: dict,
        frame: FrameMeta | None,
        window_plot_item: dict | None,
        use_split_fallback: bool,
    ) -> dict:
        frame_id = str(split_item.get("frame_id", ""))
        flags = self._normalize_flag_list(split_item.get("flags"))
        result_item = {
            "frame_id": frame_id,
            "status": "failed",
            "pdf_path": "",
            "dwg_path": "",
            "selection_count": int(split_item.get("selection_count", 0) or 0),
            "flags": flags,
        }
        if frame is None:
            self._append_flag(flags, "FRAME_NOT_FOUND")
            return result_item

        dwg_path = self._resolve_existing_path(split_item.get("dwg_path"), staged_output_dir)
        if dwg_path is not None and dwg_path.exists():
            result_item["dwg_path"] = str(dwg_path)
        else:
            self._append_flag(flags, "DWG_MISSING_FOR_PLOT")

        if str(split_item.get("status", "failed")).lower() != "ok":
            self._append_flag(flags, "WBLOCK_STATUS_MISMATCH")

        if window_plot_item and isinstance(window_plot_item, dict):
            for flag in self._normalize_flag_list(window_plot_item.get("flags")):
                self._append_flag(flags, flag)
            self._append_flag(flags, "PLOT_FROM_SOURCE_WINDOW")
            window_pdf = self._resolve_existing_path(
                window_plot_item.get("pdf_path"), staged_output_dir
            )
            if str(window_plot_item.get("status", "failed")).lower() == "ok":
                is_valid_pdf = False
                if window_pdf is not None and window_pdf.exists():
                    is_valid_pdf, invalid_reason = self._validate_pdf_output(window_pdf)
                    if not is_valid_pdf:
                        self._append_flag(flags, f"PLOT_WINDOW_INVALID_PDF:{invalid_reason}")
                if is_valid_pdf:
                    if self._normalize_cad_pdf_canvas_if_needed(frame=frame, pdf_path=window_pdf):
                        self._append_flag(flags, "PDF_CAD_CANVAS_ADJUSTED")
                    result_item["status"] = "ok"
                    result_item["pdf_path"] = str(window_pdf)
                    return result_item
            self._append_flag(flags, "PLOT_WINDOW_FAILED")
        else:
            self._append_flag(flags, "PLOT_WINDOW_RESULT_MISSING")

        if use_split_fallback:
            fallback_result = self._plot_single_frame_from_split_dwg(
                job_id=job_id,
                runtime_task_dir=runtime_task_dir,
                staged_output_dir=staged_output_dir,
                split_item=split_item,
                frame=frame,
            )
            for flag in self._normalize_flag_list(fallback_result.get("flags")):
                self._append_flag(flags, flag)
            if str(fallback_result.get("status", "failed")).lower() == "ok":
                result_item["status"] = "ok"
                result_item["pdf_path"] = str(fallback_result.get("pdf_path", ""))
                if not result_item["dwg_path"]:
                    result_item["dwg_path"] = str(fallback_result.get("dwg_path", ""))
                self._append_flag(flags, "PLOT_FROM_SPLIT_FALLBACK")
                return result_item

        self._append_flag(flags, "PLOT_FAILED")
        return result_item

    def _finalize_sheet_set_with_window_then_fallback(
        self,
        *,
        job_id: str,
        runtime_task_dir: Path,
        staged_output_dir: Path,
        split_item: dict,
        sheet_set: SheetSet | None,
        window_items_by_id: dict[str, dict],
        use_split_fallback: bool,
    ) -> dict:
        cluster_id = str(split_item.get("cluster_id", ""))
        flags = self._normalize_flag_list(split_item.get("flags"))
        result_item = {
            "cluster_id": cluster_id,
            "status": "failed",
            "pdf_path": "",
            "dwg_path": "",
            "page_count": int(split_item.get("page_count", 0) or 0),
            "flags": flags,
            "page_pdf_paths": [],
        }
        if sheet_set is None:
            self._append_flag(flags, "SHEET_SET_NOT_FOUND")
            return result_item

        dwg_path = self._resolve_existing_path(split_item.get("dwg_path"), staged_output_dir)
        if dwg_path is not None and dwg_path.exists():
            result_item["dwg_path"] = str(dwg_path)
        else:
            self._append_flag(flags, "WBLOCK_FAILED")

        pages_sorted = sorted(sheet_set.pages, key=lambda p: p.page_index)
        expected_pages = len(pages_sorted)
        result_item["page_count"] = expected_pages
        if expected_pages == 0:
            self._append_flag(flags, "A4_MULTI_NO_PAGES")
            return result_item

        sheet_name = self._name_for_sheet_set(sheet_set)
        page_pdf_by_index: dict[int, Path] = {}
        failed_page_indexes: list[int] = []
        for page in pages_sorted:
            page_id = f"{cluster_id}__p{page.page_index}"
            plot_item = window_items_by_id.get(page_id)
            if not plot_item:
                failed_page_indexes.append(page.page_index)
                continue
            for flag in self._normalize_flag_list(plot_item.get("flags")):
                self._append_flag(flags, flag)
            self._append_flag(flags, "PLOT_FROM_SOURCE_WINDOW")
            page_pdf = self._resolve_existing_path(plot_item.get("pdf_path"), staged_output_dir)
            if (
                str(plot_item.get("status", "failed")).lower() == "ok"
                and page_pdf is not None
                and page_pdf.exists()
            ):
                is_valid_pdf, invalid_reason = self._validate_pdf_output(page_pdf)
                if is_valid_pdf:
                    paper = self._a4_paper_size(page.outer_bbox)
                    self._normalize_cad_pdf_canvas_for_paper(
                        pdf_path=page_pdf,
                        paper_size_mm=(float(paper[0]), float(paper[1])),
                    )
                    page_pdf_by_index[page.page_index] = page_pdf
                else:
                    self._append_flag(
                        flags,
                        f"PLOT_WINDOW_INVALID_PDF:{page.page_index}:{invalid_reason}",
                    )
                    failed_page_indexes.append(page.page_index)
            else:
                failed_page_indexes.append(page.page_index)

        if failed_page_indexes and use_split_fallback:
            fallback_pages = self._plot_sheet_pages_from_split_fallback(
                job_id=job_id,
                runtime_task_dir=runtime_task_dir,
                staged_output_dir=staged_output_dir,
                split_item=split_item,
                sheet_set=sheet_set,
                failed_page_indexes=failed_page_indexes,
                flags=flags,
            )
            for idx, pdf in fallback_pages.items():
                page_pdf_by_index[idx] = pdf

        ordered_pdf_paths: list[Path] = []
        for page in pages_sorted:
            page_pdf = page_pdf_by_index.get(page.page_index)
            if page_pdf is None:
                self._append_flag(flags, "PLOT_FAILED")
                result_item["page_pdf_paths"] = [str(p) for p in ordered_pdf_paths]
                return result_item
            ordered_pdf_paths.append(page_pdf)

        output_pdf = self._resolve_existing_path(split_item.get("pdf_path"), staged_output_dir)
        if output_pdf is None:
            output_pdf = staged_output_dir / f"{sheet_name}.pdf"
        self._merge_pdf_pages(ordered_pdf_paths, output_pdf)
        result_item["status"] = "ok"
        result_item["pdf_path"] = str(output_pdf)
        result_item["page_pdf_paths"] = []
        self._append_flag(flags, "PDF_CAD_SPLIT_MERGED")
        return result_item

    def _plot_sheet_pages_from_split_fallback(
        self,
        *,
        job_id: str,
        runtime_task_dir: Path,
        staged_output_dir: Path,
        split_item: dict,
        sheet_set: SheetSet,
        failed_page_indexes: list[int],
        flags: list[str],
    ) -> dict[int, Path]:
        pages_by_index = {p.page_index: p for p in sheet_set.pages}
        page_dwg_by_index: dict[int, Path] = {}
        raw_page_dwg_paths = split_item.get("page_dwg_paths", [])
        if isinstance(raw_page_dwg_paths, list):
            for raw in raw_page_dwg_paths:
                p = self._resolve_existing_path(raw, staged_output_dir)
                if p is None or not p.exists():
                    continue
                idx = self._extract_page_index(p)
                if idx is not None:
                    page_dwg_by_index[idx] = p

        union_dwg = self._resolve_existing_path(split_item.get("dwg_path"), staged_output_dir)
        sheet_name = self._name_for_sheet_set(sheet_set)
        page_pdf_by_index: dict[int, Path] = {}
        for page_index in failed_page_indexes:
            page = pages_by_index.get(page_index)
            if page is None:
                continue
            source_dwg = page_dwg_by_index.get(page_index)
            output_override: dict[str, str] | None = None
            if source_dwg is None:
                if union_dwg is None or not union_dwg.exists():
                    self._append_flag(flags, f"PLOT_FALLBACK_PAGE_MISSING:{page_index}")
                    continue
                source_dwg = union_dwg
                output_override = {"plot_preferred_area": "window", "plot_fallback_area": "none"}
                self._append_flag(flags, "A4_PLOT_FROM_UNION_DWG")

            frame_entry = self._build_plot_frame_entry_from_page(
                frame_id=f"{sheet_set.cluster_id}__p{page_index}",
                name=f"{sheet_name}__p{page_index}",
                page=page,
            )
            plot_task = self._build_task_json_from_entries(
                job_id=job_id,
                source_dxf=source_dwg,
                output_dir=staged_output_dir,
                workflow_stage="plot_from_split_dwg",
                frame_entries=[frame_entry],
                sheet_set_entries=[],
                output_override=output_override,
            )
            try:
                plot_result = self._run_plot_task_from_dwg(
                    source_dwg=source_dwg,
                    runtime_task_dir=runtime_task_dir,
                    task_data=plot_task,
                )
            except Exception as exc:  # noqa: BLE001
                self._append_flag(flags, "PLOT_FAILED")
                self._append_flag(flags, f"PLOT_EXCEPTION:{exc}")
                continue

            plot_item = next(
                (i for i in plot_result.get("frames", []) if isinstance(i, dict)),
                None,
            )
            if plot_item is None:
                self._append_flag(flags, "PLOT_RESULT_MISSING")
                continue
            for flag in self._normalize_flag_list(plot_item.get("flags")):
                self._append_flag(flags, flag)
            self._append_flag(flags, "PLOT_FROM_SPLIT_DWG")

            page_pdf = self._resolve_existing_path(plot_item.get("pdf_path"), staged_output_dir)
            if (
                str(plot_item.get("status", "failed")).lower() == "ok"
                and page_pdf is not None
                and page_pdf.exists()
            ):
                is_valid_pdf, invalid_reason = self._validate_pdf_output(page_pdf)
                if is_valid_pdf:
                    paper = self._a4_paper_size(page.outer_bbox)
                    self._normalize_cad_pdf_canvas_for_paper(
                        pdf_path=page_pdf,
                        paper_size_mm=(float(paper[0]), float(paper[1])),
                    )
                    page_pdf_by_index[page_index] = page_pdf
                    self._append_flag(flags, f"PLOT_FALLBACK_PAGE_OK:{page_index}")
                else:
                    self._append_flag(
                        flags,
                        f"PLOT_FALLBACK_PAGE_INVALID:{page_index}:{invalid_reason}",
                    )
            else:
                self._append_flag(flags, "PLOT_FAILED")
        return page_pdf_by_index

    def _plot_single_frame_from_split_dwg(
        self,
        *,
        job_id: str,
        runtime_task_dir: Path,
        staged_output_dir: Path,
        split_item: dict,
        frame: FrameMeta | None,
    ) -> dict:
        frame_id = str(split_item.get("frame_id", ""))
        flags = self._normalize_flag_list(split_item.get("flags"))
        result_item = {
            "frame_id": frame_id,
            "status": "failed",
            "pdf_path": "",
            "dwg_path": "",
            "selection_count": int(split_item.get("selection_count", 0) or 0),
            "flags": flags,
        }
        if frame is None:
            self._append_flag(flags, "FRAME_NOT_FOUND")
            return result_item

        dwg_path = self._resolve_existing_path(split_item.get("dwg_path"), staged_output_dir)
        if dwg_path is None or not dwg_path.exists():
            self._append_flag(flags, "DWG_MISSING_FOR_PLOT")
            return result_item
        result_item["dwg_path"] = str(dwg_path)

        if str(split_item.get("status", "failed")).lower() != "ok":
            self._append_flag(flags, "WBLOCK_STATUS_MISMATCH")

        frame_entry = self._build_frame_entry(frame)
        plot_task = self._build_task_json_from_entries(
            job_id=job_id,
            source_dxf=dwg_path,
            output_dir=staged_output_dir,
            workflow_stage="plot_from_split_dwg",
            frame_entries=[frame_entry],
            sheet_set_entries=[],
        )

        try:
            plot_result = self._run_plot_task_from_dwg(
                source_dwg=dwg_path,
                runtime_task_dir=runtime_task_dir,
                task_data=plot_task,
            )
        except Exception as exc:  # noqa: BLE001
            self._append_flag(flags, "PLOT_FAILED")
            self._append_flag(flags, f"PLOT_EXCEPTION:{exc}")
            return result_item

        plot_item = next(
            (i for i in plot_result.get("frames", []) if isinstance(i, dict)),
            None,
        )
        if plot_item is None:
            self._append_flag(flags, "PLOT_RESULT_MISSING")
            return result_item

        for flag in self._normalize_flag_list(plot_item.get("flags")):
            self._append_flag(flags, flag)
        self._append_flag(flags, "PLOT_FROM_SPLIT_DWG")

        pdf_path = self._resolve_existing_path(plot_item.get("pdf_path"), staged_output_dir)
        if (
            str(plot_item.get("status", "failed")).lower() == "ok"
            and pdf_path is not None
            and pdf_path.exists()
        ):
            is_valid_pdf, invalid_reason = self._validate_pdf_output(pdf_path)
            if is_valid_pdf:
                if self._normalize_cad_pdf_canvas_if_needed(frame=frame, pdf_path=pdf_path):
                    self._append_flag(flags, "PDF_CAD_CANVAS_ADJUSTED")
                result_item["status"] = "ok"
                result_item["pdf_path"] = str(pdf_path)
                return result_item
            self._append_flag(flags, f"PLOT_INVALID_PDF:{invalid_reason}")

        self._append_flag(flags, "PLOT_FAILED")
        if pdf_path is not None:
            result_item["pdf_path"] = str(pdf_path)
        return result_item

    def _plot_sheet_set_from_split_dwgs(
        self,
        *,
        job_id: str,
        runtime_task_dir: Path,
        staged_output_dir: Path,
        split_item: dict,
        sheet_set: SheetSet | None,
    ) -> dict:
        cluster_id = str(split_item.get("cluster_id", ""))
        flags = self._normalize_flag_list(split_item.get("flags"))
        result_item = {
            "cluster_id": cluster_id,
            "status": "failed",
            "pdf_path": "",
            "dwg_path": "",
            "page_count": int(split_item.get("page_count", 0) or 0),
            "flags": flags,
            "page_pdf_paths": [],
        }
        if sheet_set is None:
            self._append_flag(flags, "SHEET_SET_NOT_FOUND")
            return result_item

        dwg_path = self._resolve_existing_path(split_item.get("dwg_path"), staged_output_dir)
        if dwg_path is not None and dwg_path.exists():
            result_item["dwg_path"] = str(dwg_path)
            if "WBLOCK_FAILED" in flags:
                flags.remove("WBLOCK_FAILED")

        if str(split_item.get("status", "failed")).lower() != "ok" and (
            dwg_path is None or not dwg_path.exists()
        ):
            if "WBLOCK_FAILED" not in flags:
                self._append_flag(flags, "WBLOCK_FAILED")
            return result_item

        raw_page_dwg_paths = split_item.get("page_dwg_paths", [])
        page_dwg_paths: list[Path] = []
        if isinstance(raw_page_dwg_paths, list):
            for raw in raw_page_dwg_paths:
                p = self._resolve_existing_path(raw, staged_output_dir)
                if p is not None and p.exists():
                    page_dwg_paths.append(p)
        page_dwg_paths.sort(key=self._page_index_sort_key)

        pages_sorted = sorted(sheet_set.pages, key=lambda p: p.page_index)
        expected_pages = len(pages_sorted)
        result_item["page_count"] = expected_pages
        if expected_pages == 0:
            self._append_flag(flags, "A4_MULTI_NO_PAGES")
            return result_item
        use_union_window_fallback = False
        if len(page_dwg_paths) != expected_pages:
            self._append_flag(flags, "A4_PAGE_WBLOCK_PARTIAL")
            if dwg_path is None or not dwg_path.exists():
                return result_item
            page_dwg_paths = [dwg_path for _ in pages_sorted]
            use_union_window_fallback = True
            self._append_flag(flags, "A4_PLOT_FROM_UNION_DWG")

        sheet_name = self._name_for_sheet_set(sheet_set)
        page_pdf_paths: list[Path] = []
        for page, page_dwg in zip(pages_sorted, page_dwg_paths, strict=False):
            frame_entry = self._build_plot_frame_entry_from_page(
                frame_id=f"{cluster_id}__p{page.page_index}",
                name=f"{sheet_name}__p{page.page_index}",
                page=page,
            )
            plot_task = self._build_task_json_from_entries(
                job_id=job_id,
                source_dxf=page_dwg,
                output_dir=staged_output_dir,
                workflow_stage="plot_from_split_dwg",
                frame_entries=[frame_entry],
                sheet_set_entries=[],
                output_override=(
                    {"plot_preferred_area": "window", "plot_fallback_area": "none"}
                    if use_union_window_fallback
                    else None
                ),
            )
            try:
                plot_result = self._run_plot_task_from_dwg(
                    source_dwg=page_dwg,
                    runtime_task_dir=runtime_task_dir,
                    task_data=plot_task,
                )
            except Exception as exc:  # noqa: BLE001
                self._append_flag(flags, "PLOT_FAILED")
                self._append_flag(flags, f"PLOT_EXCEPTION:{exc}")
                continue

            plot_item = next(
                (i for i in plot_result.get("frames", []) if isinstance(i, dict)),
                None,
            )
            if plot_item is None:
                self._append_flag(flags, "PLOT_RESULT_MISSING")
                continue
            for flag in self._normalize_flag_list(plot_item.get("flags")):
                self._append_flag(flags, flag)

            page_pdf = self._resolve_existing_path(plot_item.get("pdf_path"), staged_output_dir)
            if (
                str(plot_item.get("status", "failed")).lower() == "ok"
                and page_pdf is not None
                and page_pdf.exists()
            ):
                is_valid_pdf, invalid_reason = self._validate_pdf_output(page_pdf)
                if is_valid_pdf:
                    paper = self._a4_paper_size(page.outer_bbox)
                    self._normalize_cad_pdf_canvas_for_paper(
                        pdf_path=page_pdf,
                        paper_size_mm=(float(paper[0]), float(paper[1])),
                    )
                    page_pdf_paths.append(page_pdf)
                else:
                    self._append_flag(
                        flags,
                        f"PLOT_INVALID_PDF:{page.page_index}:{invalid_reason}",
                    )
                    self._append_flag(flags, "PLOT_FAILED")
            else:
                self._append_flag(flags, "PLOT_FAILED")

        if len(page_pdf_paths) != expected_pages:
            self._append_flag(flags, "PLOT_FAILED")
            result_item["page_pdf_paths"] = [str(p) for p in page_pdf_paths]
            return result_item

        output_pdf = self._resolve_existing_path(split_item.get("pdf_path"), staged_output_dir)
        if output_pdf is None:
            output_pdf = staged_output_dir / f"{sheet_name}.pdf"
        self._merge_pdf_pages(page_pdf_paths, output_pdf)
        result_item["status"] = "ok"
        result_item["pdf_path"] = str(output_pdf)
        result_item["page_pdf_paths"] = []
        self._append_flag(flags, "PDF_CAD_SPLIT_MERGED")
        self._append_flag(flags, "PLOT_FROM_SPLIT_DWG")
        return result_item

    @staticmethod
    def _resolve_existing_path(raw: object, staged_output_dir: Path) -> Path | None:
        if not isinstance(raw, str) or not raw:
            return None
        path = Path(raw)
        if not path.is_absolute():
            path = staged_output_dir / path
        return path

    @staticmethod
    def _normalize_flag_list(raw: object) -> list[str]:
        if not isinstance(raw, list):
            return []
        flags: list[str] = []
        for item in raw:
            if isinstance(item, str) and item and item not in flags:
                flags.append(item)
        return flags

    @staticmethod
    def _append_flag(flags: list[str], flag: str) -> None:
        if flag and flag not in flags:
            flags.append(flag)

    @staticmethod
    def _page_index_sort_key(path: Path) -> tuple[int, str]:
        page_index = CADDXFExecutor._extract_page_index(path)
        if page_index is not None:
            return (page_index, path.stem)
        return (10_000_000, path.stem)

    @staticmethod
    def _extract_page_index(path: Path) -> int | None:
        stem = path.stem
        marker = "__p"
        idx = stem.rfind(marker)
        if idx < 0:
            return None
        suffix = stem[idx + len(marker) :]
        if suffix.isdigit():
            return int(suffix)
        return None

    def _run_plot_task_from_dwg(
        self,
        *,
        source_dwg: Path,
        runtime_task_dir: Path,
        task_data: dict,
    ) -> dict:
        plot_root = runtime_task_dir / "plot_tasks"
        plot_root.mkdir(parents=True, exist_ok=True)
        task_dir = Path(
            tempfile.mkdtemp(
                prefix=f"{self._safe_task_dir_name(source_dwg)}_",
                dir=plot_root,
            ),
        )
        source_suffix = source_dwg.suffix if source_dwg.suffix else ".dwg"
        staged_source = task_dir / f"source_input{source_suffix}"
        shutil.copy2(source_dwg, staged_source)

        task_payload = dict(task_data)
        task_payload["source_dxf"] = str(staged_source)
        task_json = task_dir / "task.json"
        result_json = task_dir / "result.json"
        run_meta = self._run_runner_with_engine_fallback(
            source_dxf=staged_source,
            task_payload=task_payload,
            task_json=task_json,
            result_json=result_json,
            workspace_dir=task_dir,
        )
        result = self.load_result_json(result_json)
        if run_meta["fallback_used"]:
            result.setdefault("errors", []).append(
                f"DOTNET_TO_LISP_FALLBACK:{run_meta['reason']}",
            )
        return result

    def _run_runner_with_engine_fallback(
        self,
        *,
        source_dxf: Path,
        task_payload: dict,
        task_json: Path,
        result_json: Path,
        workspace_dir: Path,
    ) -> dict[str, str | bool]:
        self._write_task_json(task_json, task_payload)
        try:
            self.runner.run(
                source_dxf=source_dxf,
                task_json=task_json,
                result_json=result_json,
                workspace_dir=workspace_dir,
            )
            return {"fallback_used": False, "reason": ""}
        except Exception as exc:  # noqa: BLE001
            if not self._task_can_fallback_to_lisp(task_payload):
                raise
            fallback_payload = self._build_lisp_fallback_task_payload(
                task_payload=task_payload,
                reason=str(exc),
            )
            self._write_task_json(task_json, fallback_payload)
            self.runner.run(
                source_dxf=source_dxf,
                task_json=task_json,
                result_json=result_json,
                workspace_dir=workspace_dir,
            )
            return {"fallback_used": True, "reason": str(exc)}

    def _task_can_fallback_to_lisp(self, task_payload: dict) -> bool:
        engines = task_payload.get("engines", {})
        if not isinstance(engines, dict):
            return False
        dotnet_bridge = engines.get("dotnet_bridge", {})
        if not isinstance(dotnet_bridge, dict):
            return False
        if not bool(dotnet_bridge.get("enabled", False)):
            return False
        if not bool(dotnet_bridge.get("fallback_to_lisp_on_error", True)):
            return False
        return self._task_prefers_dotnet(task_payload)

    @staticmethod
    def _task_prefers_dotnet(task_payload: dict) -> bool:
        stage = str(task_payload.get("workflow_stage", "split_only")).strip().lower()
        engines = task_payload.get("engines", {})
        if not isinstance(engines, dict):
            return False
        selection_engine = str(engines.get("selection_engine", "lisp")).strip().lower()
        plot_engine = str(engines.get("plot_engine", "lisp")).strip().lower()
        if stage == "split_only":
            return selection_engine == "dotnet"
        if stage in {"plot_window_only", "plot_from_split_dwg"}:
            return plot_engine == "dotnet"
        return False

    @staticmethod
    def _build_lisp_fallback_task_payload(*, task_payload: dict, reason: str) -> dict:
        fallback_payload = copy.deepcopy(task_payload)
        engines = fallback_payload.setdefault("engines", {})
        if not isinstance(engines, dict):
            engines = {}
            fallback_payload["engines"] = engines
        engines["selection_engine"] = "lisp"
        engines["plot_engine"] = "lisp"
        dotnet_bridge = engines.get("dotnet_bridge", {})
        if not isinstance(dotnet_bridge, dict):
            dotnet_bridge = {}
        dotnet_bridge["enabled"] = False
        dotnet_bridge["fallback_reason"] = reason
        engines["dotnet_bridge"] = dotnet_bridge
        return fallback_payload

    def _build_plot_frame_entry_from_page(
        self,
        *,
        frame_id: str,
        name: str,
        page,
    ) -> dict:
        return {
            "frame_id": frame_id,
            "name": name,
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
            "kind": "single",
        }

    @staticmethod
    def load_result_json(result_json: Path) -> dict:
        """解析 result.json。"""
        if not result_json.exists():
            raise FileNotFoundError(f"result.json 不存在: {result_json}")
        # .NET File.WriteAllText(Encoding.UTF8) 默认会写入 BOM，这里统一兼容。
        return json.loads(result_json.read_text(encoding="utf-8-sig"))

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

    def _validate_pdf_output(self, pdf_path: Path) -> tuple[bool, str]:
        if not pdf_path.exists():
            return False, "PDF_MISSING"

        output_cfg = self.config.module5_export.output
        min_size = max(int(getattr(output_cfg, "pdf_validation_min_size_bytes", 1024)), 1)
        min_stream = max(int(getattr(output_cfg, "pdf_validation_min_stream_bytes", 64)), 1)
        if pdf_path.stat().st_size < min_size:
            return False, "PDF_TOO_SMALL"

        try:
            from pypdf import PdfReader
        except Exception:  # noqa: BLE001
            # 环境缺少 pypdf 时仅保留最小字节门禁。
            return True, "OK"

        try:
            reader = PdfReader(str(pdf_path))
        except Exception as exc:  # noqa: BLE001
            return False, f"PDF_UNREADABLE:{exc}"

        if len(reader.pages) <= 0:
            return False, "PDF_NO_PAGES"

        has_non_empty_stream = False
        for page in reader.pages:
            try:
                content_obj = page.get_contents()
            except Exception:  # noqa: BLE001
                content_obj = None
            if content_obj is None:
                continue

            total_bytes = 0
            if isinstance(content_obj, list):
                for item in content_obj:
                    if item is None:
                        continue
                    try:
                        data = item.get_data() if hasattr(item, "get_data") else b""
                    except Exception:  # noqa: BLE001
                        data = b""
                    total_bytes += len(data)
            else:
                try:
                    data = content_obj.get_data() if hasattr(content_obj, "get_data") else b""
                except Exception:  # noqa: BLE001
                    data = b""
                total_bytes = len(data)

            if total_bytes >= min_stream:
                has_non_empty_stream = True
                break

        if not has_non_empty_stream:
            # CAD PDF 存在“可视内容在外部对象流中”的情况，page.get_contents() 可能为空。
            # 为避免误判，此处仅保留结构/体积门禁，不将空内容流作为硬失败条件。
            return True, "OK_EMPTY_CONTENT_STREAM"
        return True, "OK"

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
