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
import os
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from ..config import RuntimeConfig, get_config, load_spec
from ..models import BBox, FrameMeta, SheetSet
from .accoreconsole_runner import AcCoreConsoleRunner
from .autocad_path_resolver import resolve_autocad_paths
from .plot_resource_manager import PlotResourceContext, ensure_plot_resources

if TYPE_CHECKING:
    from ..config.spec_loader import BusinessSpec


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
        self.spec: BusinessSpec = spec or load_spec()
        self.runner = runner or AcCoreConsoleRunner(config=self.config)
        self._paper_variant_cache: list[tuple[str, float, float]] | None = None
        self._plot_resource_context: PlotResourceContext | None = None

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

        self._ensure_plot_resources_ready()

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
        self._enrich_dotnet_result_metadata(split_result)
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
        pc3_resolved_path, pc3_search_dirs = self._resolve_pc3_runtime_context(plot_cfg.pc3_name)
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
                "pc3_resolved_path": pc3_resolved_path,
                "pc3_search_dirs": pc3_search_dirs,
                "ctb_name": plot_cfg.ctb_name,
                "use_monochrome": bool(plot_cfg.use_monochrome),
                "center_plot": bool(getattr(plot_cfg, "center_plot", False)),
                "plot_offset_mm": dict(getattr(plot_cfg, "plot_offset_mm", {"x": 0.0, "y": 0.0})),
                "scale_mode": str(
                    getattr(plot_cfg, "scale_mode", "manual_integer_from_geometry"),
                ),
                "scale_integer_rounding": str(
                    getattr(plot_cfg, "scale_integer_rounding", "round"),
                ),
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

    def _resolve_pc3_runtime_context(self, pc3_name: str) -> tuple[str | None, list[str]]:
        pc3_token = str(pc3_name or "").strip()
        if not pc3_token:
            return None, []

        path_info = resolve_autocad_paths(configured_install_dir=self.config.autocad.install_dir)
        search_dirs: list[Path] = []

        def add_dir(path: Path | None) -> None:
            if path is None:
                return
            try:
                resolved = path.resolve()
            except Exception:  # noqa: BLE001
                return
            if not resolved.exists() or not resolved.is_dir():
                return
            if resolved not in search_dirs:
                search_dirs.append(resolved)

        if self._plot_resource_context is not None:
            add_dir(self._plot_resource_context.plotters_dir)
        add_dir(path_info.plotters_dir)
        if path_info.install_dir is not None:
            add_dir(path_info.install_dir / "Plotters")

        appdata = os.getenv("APPDATA")
        if appdata:
            autodesk_root = Path(appdata) / "Autodesk"
            if autodesk_root.exists() and autodesk_root.is_dir():
                for plotters_dir in autodesk_root.rglob("Plotters"):
                    if plotters_dir.is_dir():
                        add_dir(plotters_dir)

        resolved_path: str | None = None
        candidate = Path(pc3_token)
        if candidate.is_absolute():
            try:
                resolved_path = str(candidate.resolve())
            except Exception:  # noqa: BLE001
                resolved_path = str(candidate)
        else:
            if (
                self._plot_resource_context is not None
                and self._plot_resource_context.pc3_path.name == pc3_token
            ):
                resolved_path = str(self._plot_resource_context.pc3_path.resolve())
            for base_dir in search_dirs:
                if resolved_path is not None:
                    break
                pc3_path = base_dir / pc3_token
                if pc3_path.exists() and pc3_path.is_file():
                    resolved_path = str(pc3_path.resolve())
                    break

        return resolved_path, [str(path) for path in search_dirs]

    def _ensure_plot_resources_ready(self) -> PlotResourceContext:
        if self._plot_resource_context is not None:
            return self._plot_resource_context
        path_info = resolve_autocad_paths(configured_install_dir=self.config.autocad.install_dir)
        self._plot_resource_context = ensure_plot_resources(path_info=path_info)
        return self._plot_resource_context

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

        window_frame_items_by_id: dict[str, dict] = {}
        window_sheet_items_by_id: dict[str, dict] = {}
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
                window_result = {
                    "frames": [],
                    "sheet_sets": [],
                    "errors": [f"WINDOW_BATCH_FAILED:{exc}"],
                }
            for item in window_result.get("frames", []):
                if not isinstance(item, dict):
                    continue
                fid = str(item.get("frame_id", ""))
                if fid:
                    window_frame_items_by_id[fid] = item
            for item in window_result.get("sheet_sets", []):
                if not isinstance(item, dict):
                    continue
                cluster_id = str(item.get("cluster_id", ""))
                if cluster_id:
                    window_sheet_items_by_id[cluster_id] = item
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
                        window_plot_item=window_frame_items_by_id.get(frame_id),
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
                        window_plot_item=window_sheet_items_by_id.get(cluster_id),
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
        sheet_set_entries: list[dict] = [
            self._build_sheet_set_entry(sheet_set) for sheet_set in sheet_sets
        ]
        if not frame_entries and not sheet_set_entries:
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
            sheet_set_entries=sheet_set_entries,
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
                    else:
                        page_ok, page_reason = self._validate_pdf_page_count(
                            pdf_path=window_pdf,
                            expected_pages=1,
                        )
                        if not page_ok:
                            is_valid_pdf = False
                            self._append_flag(flags, f"PDF_PAGE_CHECK_FAILED:{page_reason}")
                if is_valid_pdf:
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
        window_plot_item: dict | None,
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

        if window_plot_item and isinstance(window_plot_item, dict):
            for flag in self._normalize_flag_list(window_plot_item.get("flags")):
                self._append_flag(flags, flag)
            self._append_flag(flags, "PLOT_FROM_SOURCE_WINDOW")
            window_pdf = self._resolve_existing_path(
                window_plot_item.get("pdf_path"), staged_output_dir
            )
            if (
                str(window_plot_item.get("status", "failed")).lower() == "ok"
                and window_pdf is not None
                and window_pdf.exists()
            ):
                valid_pdf, reason = self._validate_pdf_output(window_pdf)
                if valid_pdf:
                    size_ok, size_reason = self._validate_pdf_page_count(
                        pdf_path=window_pdf,
                        expected_pages=expected_pages,
                    )
                    if size_ok:
                        result_item["status"] = "ok"
                        result_item["pdf_path"] = str(window_pdf)
                        return result_item
                    self._append_flag(flags, f"PDF_PAGE_CHECK_FAILED:{size_reason}")
                else:
                    self._append_flag(flags, f"PLOT_WINDOW_INVALID_PDF:{reason}")
            else:
                self._append_flag(flags, "PLOT_WINDOW_FAILED")
        else:
            self._append_flag(flags, "PLOT_WINDOW_RESULT_MISSING")

        if use_split_fallback:
            fallback_result = self._plot_sheet_set_from_split_dwgs(
                job_id=job_id,
                runtime_task_dir=runtime_task_dir,
                staged_output_dir=staged_output_dir,
                split_item=split_item,
                sheet_set=sheet_set,
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
            if not is_valid_pdf:
                self._append_flag(flags, f"PLOT_INVALID_PDF:{invalid_reason}")
            else:
                page_ok, page_reason = self._validate_pdf_page_count(
                    pdf_path=pdf_path,
                    expected_pages=1,
                )
                if page_ok:
                    result_item["status"] = "ok"
                    result_item["pdf_path"] = str(pdf_path)
                    return result_item

                self._append_flag(flags, f"PDF_PAGE_CHECK_FAILED:{page_reason}")

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
        if dwg_path is None or not dwg_path.exists():
            self._append_flag(flags, "WBLOCK_FAILED")
            return result_item
        result_item["dwg_path"] = str(dwg_path)

        pages_sorted = sorted(sheet_set.pages, key=lambda p: p.page_index)
        expected_pages = len(pages_sorted)
        result_item["page_count"] = expected_pages
        if expected_pages == 0:
            self._append_flag(flags, "A4_MULTI_NO_PAGES")
            return result_item

        plot_task = self._build_task_json_from_entries(
            job_id=job_id,
            source_dxf=dwg_path,
            output_dir=staged_output_dir,
            workflow_stage="plot_from_split_dwg",
            frame_entries=[],
            sheet_set_entries=[self._build_sheet_set_entry(sheet_set)],
            output_override={"plot_preferred_area": "window", "plot_fallback_area": "none"},
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
            (
                i
                for i in plot_result.get("sheet_sets", [])
                if isinstance(i, dict) and str(i.get("cluster_id", "")) == cluster_id
            ),
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
            if not is_valid_pdf:
                self._append_flag(flags, f"PLOT_INVALID_PDF:{invalid_reason}")
                self._append_flag(flags, "PLOT_FAILED")
                return result_item

            size_ok, size_reason = self._validate_pdf_page_count(
                pdf_path=pdf_path,
                expected_pages=expected_pages,
            )
            if not size_ok:
                self._append_flag(flags, f"PDF_PAGE_CHECK_FAILED:{size_reason}")
                self._append_flag(flags, "PLOT_FAILED")
                return result_item

            result_item["status"] = "ok"
            result_item["pdf_path"] = str(pdf_path)
            result_item["page_pdf_paths"] = []
            return result_item

        self._append_flag(flags, "PLOT_FAILED")
        if pdf_path is not None:
            result_item["pdf_path"] = str(pdf_path)
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
        self._enrich_dotnet_result_metadata(result)
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
            "paper_variant_id": frame.runtime.paper_variant_id,
            "paper_media_name": self._paper_media_name_for_variant(
                frame.runtime.paper_variant_id,
            ),
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
                "paper_variant_id": self._a4_variant_id(page.outer_bbox),
                "paper_media_name": self._paper_media_name_for_variant(
                    self._a4_variant_id(page.outer_bbox),
                ),
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

    @staticmethod
    def _a4_variant_id(bbox: BBox) -> str:
        # 约定：A4 横向按 CNPE_A4H，竖向按 CNPE_A4
        if bbox.width >= bbox.height:
            return "CNPE_A4H"
        return "CNPE_A4"

    def _paper_media_name_for_variant(self, variant_id: str | None) -> str | None:
        if not variant_id:
            return None
        titleblock_extract = getattr(self.spec, "titleblock_extract", {})
        if not isinstance(titleblock_extract, dict):
            return None
        raw_variants = titleblock_extract.get("paper_variants", {})
        if not isinstance(raw_variants, dict):
            return None
        variant = raw_variants.get(variant_id)
        if variant is None and variant_id.upper().endswith("H"):
            variant = raw_variants.get(variant_id[:-1])
        if not isinstance(variant, dict):
            return None
        media_hint = variant.get("打印PDF2.pc3文件中对应纸张")
        if not isinstance(media_hint, str):
            return None
        normalized = media_hint.strip()
        if not normalized:
            return None

        normalized = normalized.replace("竖向打印", "").replace("横向打印", "")
        normalized = normalized.replace("（", "(").replace("）", ")")
        normalized = normalized.replace("，", ",")
        normalized = normalized.split(",", 1)[0].strip()
        return normalized or None

    def _enrich_dotnet_result_metadata(self, result: dict) -> None:
        errors = result.get("errors")
        if isinstance(errors, list):
            enriched_errors: list[str] = []
            for item in errors:
                if isinstance(item, str) and item:
                    enriched_errors.append(self._annotate_precheck_error_with_variant(item))
            result["errors"] = enriched_errors

        for section in ("frames", "sheet_sets"):
            entries = result.get(section)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                flags = entry.get("flags")
                if not isinstance(flags, list):
                    continue
                enriched_flags: list[str] = []
                for flag in flags:
                    if not isinstance(flag, str) or not flag:
                        continue
                    enriched = self._annotate_media_not_matched_flag(flag)
                    if enriched not in enriched_flags:
                        enriched_flags.append(enriched)
                entry["flags"] = enriched_flags

    def _annotate_precheck_error_with_variant(self, err: str) -> str:
        marker = "PLOT_MEDIA_PRECHECK_MISSING:"
        if not err.startswith(marker) or ":variants=" in err:
            return err
        size_token = err[len(marker) :].split(":", 1)[0]
        variant_names = self._variant_names_for_size_token(size_token)
        if not variant_names:
            return err
        return f"{err}:variants={','.join(variant_names)}"

    def _annotate_media_not_matched_flag(self, flag: str) -> str:
        marker = "MEDIA_NOT_MATCHED_"
        idx = flag.find(marker)
        if idx < 0 or "(variants=" in flag:
            return flag
        size_token = flag[idx + len(marker) :].strip()
        variant_names = self._variant_names_for_size_token(size_token)
        if not variant_names:
            return flag
        return f"{flag}(variants={','.join(variant_names)})"

    def _variant_names_for_size_token(self, size_token: str) -> list[str]:
        parts = size_token.split("x", 1)
        if len(parts) != 2:
            return []
        try:
            width = float(parts[0].strip())
            height = float(parts[1].strip())
        except ValueError:
            return []
        return self._variant_names_for_size(width, height)

    def _variant_names_for_size(self, width_mm: float, height_mm: float) -> list[str]:
        tolerance = 0.5
        exact: list[str] = []
        swapped: list[str] = []
        for name, variant_w, variant_h in self._paper_variants_cache():
            if abs(variant_w - width_mm) <= tolerance and abs(variant_h - height_mm) <= tolerance:
                exact.append(name)
                continue
            if abs(variant_w - height_mm) <= tolerance and abs(variant_h - width_mm) <= tolerance:
                swapped.append(name)
        if exact:
            return sorted(exact)
        if swapped:
            return sorted(swapped)
        return []

    def _paper_variants_cache(self) -> list[tuple[str, float, float]]:
        if self._paper_variant_cache is not None:
            return self._paper_variant_cache
        variants = self.spec.get_paper_variants()
        cache: list[tuple[str, float, float]] = []
        for name, variant in variants.items():
            try:
                cache.append((name, float(variant.W), float(variant.H)))
            except Exception:  # noqa: BLE001
                continue
        self._paper_variant_cache = cache
        return cache

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
            ("top", 0.0),
            ("bottom", 0.0),
            ("left", 0.0),
            ("right", 0.0),
        ):
            # 业务规范优先；缺失时回退到运行期配置。
            merged[k] = spec_margins.get(k, runtime_margins.get(k, default_value))

        return {k: float(v) for k, v in merged.items()}

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

    def _validate_pdf_dimensions(
        self,
        *,
        pdf_path: Path,
        expected_pages_mm: list[tuple[float, float]],
        tolerance_mm: float = 1.0,
    ) -> tuple[bool, str]:
        if not expected_pages_mm:
            return False, "EXPECTED_PAGES_EMPTY"
        try:
            from pypdf import PdfReader
        except Exception:  # noqa: BLE001
            # 运行环境无 pypdf 时跳过尺寸校验，保留结构门禁结果。
            return True, "SKIP_SIZE_CHECK_NO_PYPDF"

        try:
            reader = PdfReader(str(pdf_path))
        except Exception as exc:  # noqa: BLE001
            return False, f"PDF_UNREADABLE:{exc}"

        if len(reader.pages) != len(expected_pages_mm):
            return (
                False,
                f"PAGE_COUNT_MISMATCH:{len(reader.pages)}!={len(expected_pages_mm)}",
            )

        for idx, page in enumerate(reader.pages, start=1):
            expected_w, expected_h = expected_pages_mm[idx - 1]
            actual_w_mm = float(page.mediabox.width) * 25.4 / 72.0
            actual_h_mm = float(page.mediabox.height) * 25.4 / 72.0
            if (
                abs(actual_w_mm - expected_w) > tolerance_mm
                or abs(actual_h_mm - expected_h) > tolerance_mm
            ):
                return (
                    False,
                    "PAGE_SIZE_MISMATCH:"
                    f"{idx}:"
                    f"{actual_w_mm:.3f}x{actual_h_mm:.3f}"
                    f"!="
                    f"{expected_w:.3f}x{expected_h:.3f}",
                )

        return True, "OK"

    def _validate_pdf_page_count(
        self,
        *,
        pdf_path: Path,
        expected_pages: int,
    ) -> tuple[bool, str]:
        if expected_pages <= 0:
            return False, "EXPECTED_PAGES_INVALID"
        try:
            from pypdf import PdfReader
        except Exception:  # noqa: BLE001
            return True, "SKIP_PAGE_COUNT_CHECK_NO_PYPDF"

        try:
            reader = PdfReader(str(pdf_path))
        except Exception as exc:  # noqa: BLE001
            return False, f"PDF_UNREADABLE:{exc}"

        if len(reader.pages) != expected_pages:
            return False, f"PAGE_COUNT_MISMATCH:{len(reader.pages)}!={expected_pages}"
        return True, "OK"
