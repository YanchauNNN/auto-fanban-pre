"""
流水线执行器 - 编排各阶段执行

职责：
1. 按顺序执行各阶段
2. 更新任务进度
3. 处理错误和失败隔离
4. 生成manifest

Stage B 设计：
  SPLIT_AND_RENAME — 仅裁切DXF，产出中间产物
  EXPORT_PDF_AND_DWG — 统一导出 PDF + DWG，回填路径

测试要点：
- test_execute_full_pipeline: 完整流水线执行
- test_stage_failure_handling: 阶段失败处理
- test_progress_tracking: 进度跟踪
"""

from __future__ import annotations

import json
import logging
import shutil
import time
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from ..cad import (
    A4MultipageGrouper,
    CADDXFExecutor,
    FontPreflightService,
    FrameDetector,
    ODAConverter,
    SameCodeMultipageGrouper,
    TitleblockConsistencyBridge,
    TitleblockConsistencyService,
    TitleblockExtractor,
)
from ..cad.splitter import output_name_for_frame, output_name_for_sheet_set
from ..config import get_config, load_spec
from ..doc_gen import (
    CatalogGenerator,
    CoverGenerator,
    DerivationEngine,
    DesignFileGenerator,
    IEDGenerator,
)
from ..doc_gen.param_validator import DocParamValidator
from ..models import (
    DocContext,
    FrameMeta,
    GlobalDocParams,
    SheetSet,
    normalize_discipline_label,
    normalize_global_doc_params,
)
from .frame_filtering import split_anchor_valid_frames
from .packager import Packager
from .preview_pdf_service import PreviewPdfService
from .shared_prep import SharedPrepService
from .stages import DELIVERABLE_STAGES, StageEnum
from ..workload.calculator import WorkloadCalculator

if TYPE_CHECKING:
    from ..models import Job

logger = logging.getLogger(__name__)

STEEL_LINER_PLOT_STYLE_KEY = "steel_liner"


class PipelineExecutor:
    """流水线执行器"""

    def __init__(self, *, font_preflight_service: FontPreflightService | None = None):
        self.config = get_config()
        self.spec = load_spec()
        self._last_progress_write = 0.0
        self._progress_interval_sec = 2.0

        # 初始化各模块
        self.oda = ODAConverter()
        self.frame_detector = FrameDetector()
        self.font_preflight_service = font_preflight_service or FontPreflightService()
        self.titleblock_extractor = TitleblockExtractor()
        self.a4_grouper = A4MultipageGrouper()
        self.same_code_multipage_grouper = SameCodeMultipageGrouper()
        self.titleblock_consistency = TitleblockConsistencyService()
        self.titleblock_consistency_bridge = TitleblockConsistencyBridge()
        self.cad_dxf_executor = CADDXFExecutor(config=self.config)
        self.derivation = DerivationEngine()
        self.doc_param_validator = DocParamValidator()
        self.cover_gen = CoverGenerator()
        self.catalog_gen = CatalogGenerator()
        self.design_gen = DesignFileGenerator()
        self.ied_gen = IEDGenerator()
        self.packager = Packager()
        self.preview_pdf_service = PreviewPdfService()
        self.workload_calculator = WorkloadCalculator()

    def execute(self, job: Job) -> None:
        """?????"""
        self._start_execution(job)

        try:
            context, stages = self._prepare_execution_plan(job)
            self._run_stages(job, context, stages)
            self._finalize_success(job, context)
        except Exception as e:
            self._fail_execution(job, e)
            raise

    def execute_slot_bound_phase(self, job: Job) -> Callable[[], None] | None:
        self._start_execution(job)

        try:
            context, stages = self._prepare_execution_plan(job)
            slot_bound_stages, post_slot_stages = self._split_slot_bound_and_post_stages(stages)
            self._run_stages(job, context, slot_bound_stages)
        except Exception as e:
            self._fail_execution(job, e)
            raise

        if not post_slot_stages:
            try:
                self._finalize_success(job, context)
            except Exception as e:
                self._fail_execution(job, e)
                raise
            return None

        def run_post_slot_phase() -> None:
            try:
                self._run_stages(job, context, post_slot_stages)
                self._finalize_success(job, context)
            except Exception as e:
                self._fail_execution(job, e)
                raise

        return run_post_slot_phase

    def _start_execution(self, job: Job) -> None:
        job.mark_running()
        self._update_progress(job, message="????", force=True)

    def _prepare_execution_plan(self, job: Job) -> tuple[dict[str, Any], list[Any]]:
        work_dir = self.config.get_job_dir(job.job_id)
        job.work_dir = work_dir
        work_dir.mkdir(parents=True, exist_ok=True)

        split_only = bool(job.options.get("split_only", False))
        shared_prep_dir = str(job.params.get("shared_prep_dir") or "").strip()
        if shared_prep_dir:
            prep = SharedPrepService.load(Path(shared_prep_dir))
            frames, excluded_frames = split_anchor_valid_frames(prep.frames)
            context: dict[str, Any] = {
                "dxf_files": [prep.source_converted_dxf],
                "dxf_to_dwg": {
                    str(prep.source_converted_dxf.resolve()): prep.source_input_dwg.resolve(),
                },
                "frames": frames,
                "sheet_sets": prep.sheet_sets,
                "same_code_multipage_families": [],
                "cad_dxf_results": {},
                "shared_prep_dir": str(prep.shared_dir),
                "excluded_frames": excluded_frames,
            }
            allowed = {
                StageEnum.FIX_TITLEBLOCK_CONSISTENCY.value,
                StageEnum.SPLIT_AND_RENAME.value,
                StageEnum.EXPORT_PDF_AND_DWG.value,
                StageEnum.PACKAGE_ZIP.value,
            }
            if not split_only:
                allowed.update(
                    {
                        StageEnum.GENERATE_DOCS.value,
                    }
                )
            stages = [stage for stage in DELIVERABLE_STAGES if stage.name in allowed]
            return context, stages

        context = {
            "dxf_files": [],
            "dxf_to_dwg": {},
            "frames": [],
            "sheet_sets": [],
            "same_code_multipage_families": [],
            # Stage 7 (cad_dxf) ??: {source_dxf: result_json_dict}
            "cad_dxf_results": {},
            "stage_timings": [],
        }
        stages = (
            [
                stage
                for stage in DELIVERABLE_STAGES
                if stage.name
                in {
                    StageEnum.INGEST.value,
                    StageEnum.FONT_PREFLIGHT_AND_REPLACE.value,
                    StageEnum.CONVERT_DWG_TO_DXF.value,
                    StageEnum.DETECT_FRAMES.value,
                    StageEnum.VERIFY_FRAMES_BY_ANCHOR.value,
                    StageEnum.SCALE_FIT_AND_CHECK.value,
                    StageEnum.EXTRACT_TITLEBLOCK_FIELDS.value,
                    StageEnum.A4_MULTIPAGE_GROUPING.value,
                    StageEnum.FIX_TITLEBLOCK_CONSISTENCY.value,
                    StageEnum.SPLIT_AND_RENAME.value,
                    StageEnum.EXPORT_PDF_AND_DWG.value,
                    StageEnum.PACKAGE_ZIP.value,
                }
            ]
            if split_only
            else DELIVERABLE_STAGES
        )
        return context, stages

    def _run_stages(self, job: Job, context: dict[str, Any], stages: list[Any]) -> None:
        for stage in stages:
            self._execute_stage(job, stage, context)

    @staticmethod
    def _split_slot_bound_and_post_stages(stages: list[Any]) -> tuple[list[Any], list[Any]]:
        post_stage_names = {
            StageEnum.GENERATE_DOCS.value,
            StageEnum.PACKAGE_ZIP.value,
        }
        slot_bound_stages = [stage for stage in stages if stage.name not in post_stage_names]
        post_slot_stages = [stage for stage in stages if stage.name in post_stage_names]
        return slot_bound_stages, post_slot_stages

    def _finalize_success(self, job: Job, context: dict[str, Any]) -> None:
        self._aggregate_flags(job, context)
        self._raise_if_fatal_export_errors(job)
        job.mark_succeeded()
        self._update_progress(job, message="????", force=True)

    def _fail_execution(self, job: Job, exc: Exception) -> None:
        logger.exception(f"???????: {job.job_id}")
        job.mark_failed(str(exc))
        self._update_progress(job, message=f"????: {exc}", force=True)

    # ==================================================================
    # 阶段分发
    # ==================================================================

    def _execute_stage(self, job: Job, stage, context: dict) -> None:
        job.progress.stage = stage.name
        job.progress.percent = stage.progress_start
        logger.info(f"[{job.job_id}] 开始阶段: {stage.name}")
        self._update_progress(job, message=f"开始阶段: {stage.name}", force=True)
        started_at = datetime.now().isoformat()
        stage_start = time.perf_counter()

        try:
            handler = {
                StageEnum.INGEST.value: self._stage_ingest,
                StageEnum.FONT_PREFLIGHT_AND_REPLACE.value: self._stage_font_preflight_and_replace,
                StageEnum.CONVERT_DWG_TO_DXF.value: self._stage_convert,
                StageEnum.DETECT_FRAMES.value: self._stage_detect_frames,
                StageEnum.VERIFY_FRAMES_BY_ANCHOR.value: self._stage_verify_frames,
                StageEnum.SCALE_FIT_AND_CHECK.value: self._stage_scale_fit,
                StageEnum.EXTRACT_TITLEBLOCK_FIELDS.value: self._stage_extract_fields,
                StageEnum.A4_MULTIPAGE_GROUPING.value: self._stage_a4_grouping,
                StageEnum.FIX_TITLEBLOCK_CONSISTENCY.value: self._stage_fix_titleblock_consistency,
                StageEnum.SPLIT_AND_RENAME.value: self._stage_split,
                StageEnum.EXPORT_PDF_AND_DWG.value: self._stage_export,
                StageEnum.GENERATE_DOCS.value: self._stage_generate_docs,
                StageEnum.PACKAGE_ZIP.value: self._stage_package,
            }.get(stage.name)

            if handler:
                handler(job, context)

        except Exception as e:
            self._record_stage_timing(
                job,
                context,
                stage_name=stage.name,
                started_at=started_at,
                duration_ms=(time.perf_counter() - stage_start) * 1000,
                status="failed",
                error=str(e),
            )
            logger.error(f"[{job.job_id}] 阶段失败 {stage.name}: {e}")
            job.add_flag(f"阶段失败:{stage.name}")
            raise

        self._record_stage_timing(
            job,
            context,
            stage_name=stage.name,
            started_at=started_at,
            duration_ms=(time.perf_counter() - stage_start) * 1000,
            status="succeeded",
        )
        job.progress.percent = stage.progress_end
        self._update_progress(job, message=f"完成阶段: {stage.name}", force=True)

    def _record_stage_timing(
        self,
        job: Job,
        context: dict[str, Any],
        *,
        stage_name: str,
        started_at: str,
        duration_ms: float,
        status: str,
        error: str | None = None,
    ) -> None:
        stage_timings = context.setdefault("stage_timings", [])
        if not isinstance(stage_timings, list):
            stage_timings = []
            context["stage_timings"] = stage_timings

        entry: dict[str, Any] = {
            "stage": stage_name,
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(),
            "duration_ms": round(max(duration_ms, 0.0), 2),
            "status": status,
        }
        if error:
            entry["error"] = error
        stage_timings.append(entry)
        job.progress.details["stage_timings"] = list(stage_timings)
        self._persist_stage_timings(job, stage_timings)

    @staticmethod
    def _persist_stage_timings(job: Job, stage_timings: list[dict[str, Any]]) -> None:
        if job.work_dir is None:
            return
        timings_path = job.work_dir / "stage_timings.json"
        with open(timings_path, "w", encoding="utf-8") as f:
            json.dump(stage_timings, f, ensure_ascii=False, indent=2)

    # ==================================================================
    # 阶段 1-6: 不变（ingest / convert / detect / verify / scale / extract / a4）
    # ==================================================================

    @staticmethod
    def _require_work_dir(job: Job) -> Path:
        work_dir = job.work_dir
        if work_dir is None:
            raise RuntimeError(f"job.work_dir not initialized: {job.job_id}")
        return work_dir

    def _stage_ingest(self, job: Job, context: dict) -> None:
        input_dir = self._require_work_dir(job) / "input"
        input_dir.mkdir(exist_ok=True)
        for f in job.input_files:
            if f.exists():
                import shutil

                shutil.copy(f, input_dir / f.name)

    def _stage_font_preflight_and_replace(self, job: Job, context: dict) -> None:
        input_dir = self._require_work_dir(job) / "input"
        dwg_files = sorted(input_dir.glob("*.dwg"))
        policy = str(job.params.get("font_replace_policy") or "none").strip().lower() or "none"
        font_compatibility_mode = self._coerce_bool(job.params.get("font_compatibility_mode"))
        replacement_font = str(job.params.get("font_replacement_font") or "").strip() or None
        replacement_fonts_raw = job.params.get("font_replacement_fonts")
        replacement_fonts = (
            dict(replacement_fonts_raw)
            if isinstance(replacement_fonts_raw, dict)
            else None
        )
        slot_runtime = job.params.get("cad_slot_runtime")
        if (
            policy == "replace_missing"
            and replacement_font is not None
            and not self.font_preflight_service.validate_replacement_font(replacement_font)
        ):
            raise RuntimeError(f"font_replacement_font unavailable: {replacement_font}")

        results: list[dict[str, Any]] = []
        for dwg_file in dwg_files:
            self._update_progress(
                job,
                current_file=dwg_file.name,
                message="DWG?????",
            )
            target_frames = (
                self._detect_frames_for_font_preflight(job, dwg_file, context)
                if font_compatibility_mode
                else []
            )
            result = self.font_preflight_service.inspect_dwg(
                source_dwg=dwg_file,
                replacement_policy=policy,
                replacement_font=replacement_font,
                replacement_fonts=replacement_fonts,
                font_compatibility_mode=font_compatibility_mode,
                frames=target_frames,
                workspace_dir=input_dir / ".font-preflight",
                slot_runtime=slot_runtime if isinstance(slot_runtime, dict) else None,
            )
            results.append(result)

        errors = [
            str(error)
            for item in results
            for error in list(item.get("errors") or [])
            if str(error).strip()
        ]
        missing_detected = any(bool(list(item.get("missing_fonts") or [])) for item in results)
        replacement_applied = any(bool(item.get("font_replacement_applied")) for item in results)
        replaced_style_count = sum(int(item.get("replaced_style_count", 0) or 0) for item in results)
        summary = {
            "files": results,
            "policy": policy,
            "font_compatibility_mode": font_compatibility_mode,
        }
        job.font_preflight_summary = summary
        job.missing_fonts_detected = missing_detected
        job.font_replacement_applied = replacement_applied
        job.replacement_font = replacement_font
        replacement_fonts_summary: dict[str, str] = {}
        for item in results:
            if isinstance(item.get("replacement_fonts"), dict):
                replacement_fonts_summary.update(
                    {
                        str(key): str(value)
                        for key, value in dict(item["replacement_fonts"]).items()
                        if str(value or "").strip()
                    }
                )
        job.replacement_fonts = replacement_fonts_summary
        job.replaced_style_count = replaced_style_count
        job.progress.details["font_missing_style_count"] = sum(
            int(item.get("missing_style_count", 0) or 0) for item in results
        )
        job.progress.details["font_replaced_style_count"] = replaced_style_count

        if errors:
            raise RuntimeError("font preflight failed: " + "; ".join(errors))
        if missing_detected and policy != "replace_missing":
            raise RuntimeError("missing fonts detected but no replacement policy was confirmed")

    def _detect_frames_for_font_preflight(
        self,
        job: Job,
        dwg_file: Path,
        context: dict[str, Any],
    ) -> list[FrameMeta]:
        try:
            probe_dir = self._require_work_dir(job) / "input" / ".font-preflight-probe"
            probe_dir.mkdir(parents=True, exist_ok=True)
            dxf_path = self.oda.dwg_to_dxf(dwg_file, probe_dir)
            context.setdefault("font_preflight_source_dxf_by_dwg", {})[
                str(dwg_file.resolve())
            ] = dxf_path
            self.frame_detector.set_project_no(job.project_no)
            frames = self.frame_detector.detect_frames(dxf_path)
            for frame in frames:
                frame.runtime.cad_source_file = dwg_file
            return frames
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[%s] font preflight target frame probe failed for %s: %s",
                job.job_id,
                dwg_file,
                exc,
            )
            return []

    def _stage_convert(self, job: Job, context: dict) -> None:
        work_dir = self._require_work_dir(job)
        input_dir = work_dir / "input"
        dxf_dir = work_dir / "work" / "dxf"
        dxf_dir.mkdir(parents=True, exist_ok=True)
        dwg_files = list(input_dir.glob("*.dwg"))
        job.progress.details.update({"dwg_total": len(dwg_files), "dwg_converted": 0})
        for dwg_file in dwg_files:
            try:
                self._update_progress(
                    job,
                    current_file=dwg_file.name,
                    message="DWG转DXF中",
                    details={"dwg_current": dwg_file.name},
                )
                preflight_dxf_by_dwg = context.get("font_preflight_source_dxf_by_dwg")
                preflight_dxf = None
                if isinstance(preflight_dxf_by_dwg, dict):
                    preflight_dxf = preflight_dxf_by_dwg.get(str(dwg_file.resolve()))
                if preflight_dxf is not None and Path(preflight_dxf).exists():
                    dxf_path = dxf_dir / Path(preflight_dxf).name
                    if Path(preflight_dxf).resolve() != dxf_path.resolve():
                        shutil.copy2(preflight_dxf, dxf_path)
                else:
                    dxf_path = self.oda.dwg_to_dxf(dwg_file, dxf_dir)
                context["dxf_files"].append(dxf_path)
                context["dxf_to_dwg"][str(dxf_path.resolve())] = dwg_file.resolve()
                job.progress.details["dwg_converted"] = (
                    job.progress.details.get("dwg_converted", 0) + 1
                )
                self._update_progress(
                    job, details={"dwg_converted": job.progress.details["dwg_converted"]}
                )
            except Exception as e:
                logger.warning(f"DWG转换失败: {dwg_file}: {e}")
                job.add_flag(f"转换失败:{dwg_file.name}")

    def _stage_detect_frames(self, job: Job, context: dict) -> None:
        dxf_files = list(context["dxf_files"])
        self.frame_detector.set_project_no(job.project_no)
        job.progress.details.update(
            {"dxf_total": len(dxf_files), "dxf_processed": 0, "frames_total": 0}
        )
        for dxf_path in dxf_files:
            try:
                self._update_progress(
                    job,
                    current_file=dxf_path.name,
                    message="图框检测中",
                    details={"dxf_current": dxf_path.name},
                )
                frames = self.frame_detector.detect_frames(dxf_path)
                source_dwg = context.get("dxf_to_dwg", {}).get(str(dxf_path.resolve()))
                if source_dwg is not None:
                    for frame in frames:
                        frame.runtime.cad_source_file = Path(source_dwg)
                context["frames"].extend(frames)
                job.progress.details["dxf_processed"] = (
                    job.progress.details.get("dxf_processed", 0) + 1
                )
                job.progress.details["frames_total"] = len(context["frames"])
                self._update_progress(
                    job,
                    details={
                        "dxf_processed": job.progress.details["dxf_processed"],
                        "frames_total": job.progress.details["frames_total"],
                    },
                )
            except Exception as e:
                logger.warning(f"图框检测失败: {dxf_path}: {e}")
                job.add_flag(f"检测失败:{dxf_path.name}")

    def _stage_verify_frames(self, job: Job, context: dict) -> None:
        self._update_progress(job, message="锚点验证已在检测阶段完成", force=True)

    def _stage_scale_fit(self, job: Job, context: dict) -> None:
        self._update_progress(job, message="比例拟合已在检测阶段完成", force=True)

    def _stage_extract_fields(self, job: Job, context: dict) -> None:
        total = len(context["frames"])
        self.titleblock_extractor.set_project_no(job.project_no)
        job.progress.details.update({"frames_field_total": total, "frames_field_done": 0})
        for i, frame in enumerate(context["frames"]):
            dxf_path = frame.runtime.source_file
            try:
                self._update_progress(
                    job,
                    current_file=dxf_path.name,
                    message=f"字段提取中 ({i + 1}/{total})",
                    details={"frames_field_done": i + 1},
                )
                self.titleblock_extractor.extract_fields(dxf_path, frame)
            except Exception as e:
                logger.warning(f"字段提取失败: {frame.frame_id}: {e}")
                frame.add_flag("提取失败")

        effective_frames, excluded_frames = split_anchor_valid_frames(context["frames"])
        context["frames"] = effective_frames
        existing_excluded = context.setdefault("excluded_frames", [])
        if isinstance(existing_excluded, list):
            existing_excluded.extend(excluded_frames)
        job.progress.details["frames_total"] = len(effective_frames)
        job.progress.details["frames_anchor_invalid_filtered"] = len(excluded_frames)

    def _stage_a4_grouping(self, job: Job, context: dict) -> None:
        remaining, sheet_sets = self.a4_grouper.group_a4_pages(context["frames"])
        context["frames"] = remaining
        context["sheet_sets"] = sheet_sets
        context["same_code_multipage_families"] = self.same_code_multipage_grouper.group_frames(
            remaining,
        )

    def _stage_fix_titleblock_consistency(self, job: Job, context: dict) -> None:
        cfg = self.config.deliverable_consistency_fix
        if not cfg.enabled:
            self._update_progress(job, message="图签一致性修正已关闭", force=True)
            return

        all_frames = self.titleblock_consistency.collect_document_frames(
            context["frames"],
            context["sheet_sets"],
        )
        frame_by_id = {frame.frame_id: frame for frame in all_frames}
        source_to_all_frames: dict[Path, list[Any]] = {}
        source_to_plans: dict[Path, list[Any]] = {}
        source_to_scale_out_of_range: dict[Path, list[dict[str, Any]]] = {}
        report: dict[str, Any] = {"sources": []}

        for frame in all_frames:
            source_path = Path(frame.runtime.cad_source_file or frame.runtime.source_file)
            source_to_all_frames.setdefault(source_path, []).append(frame)
            if self.titleblock_consistency.is_scale_candidate_out_of_range(
                frame.runtime.geom_scale_factor
            ):
                self._mark_consistency_flag(frame, "scale_text", "MISMATCH")
                self._mark_consistency_flag(frame, "scale_text", "FIX_SKIPPED")
                frame.add_flag("SCALE_CANDIDATE_OUT_OF_RANGE")
                source_to_scale_out_of_range.setdefault(source_path, []).append(
                    {
                        "frame_id": frame.frame_id,
                        "internal_code": frame.titleblock.internal_code,
                        "current_text": frame.titleblock.scale_text,
                        "geom_scale_factor": frame.runtime.geom_scale_factor,
                    }
                )
            plans = self.titleblock_consistency.build_frame_plans(frame)
            if plans:
                source_to_plans.setdefault(source_path, []).extend(plans)

        for sheet_set in context["sheet_sets"]:
            for plan in self.titleblock_consistency.build_sheet_set_plans(sheet_set):
                frame = frame_by_id.get(plan.frame_id)
                if frame is None:
                    continue
                source_path = Path(frame.runtime.cad_source_file or frame.runtime.source_file)
                source_to_all_frames.setdefault(source_path, []).append(frame)
                source_to_plans.setdefault(source_path, []).append(plan)

        if not source_to_plans and not source_to_scale_out_of_range:
            self._update_progress(job, message="图签图幅/比例一致性已通过", force=True)
            return

        work_dir = self._require_work_dir(job)
        consistency_dir = work_dir / "work" / "titleblock_consistency"
        consistency_dir.mkdir(parents=True, exist_ok=True)
        report_path = consistency_dir / "consistency_report.json"
        slot_runtime = job.params.get("cad_slot_runtime")

        for source_path in sorted(
            set(source_to_plans.keys()) | set(source_to_scale_out_of_range.keys()),
            key=lambda path: str(path),
        ):
            plans = source_to_plans.get(source_path, [])
            out_of_range_scales = source_to_scale_out_of_range.get(source_path, [])
            safe_plans = [plan for plan in plans if plan.replacements]
            skipped_plans = [plan for plan in plans if not plan.replacements]
            source_report = {
                "source_dwg": str(source_path),
                "safe_plan_count": len(safe_plans),
                "skipped_plan_count": len(skipped_plans),
                "out_of_range_scale_count": len(out_of_range_scales),
                "out_of_range_scales": out_of_range_scales,
                "output_dwg": None,
                "errors": [],
                "plans": [
                    {
                        "frame_id": plan.frame_id,
                        "field_name": plan.field_name,
                        "expected_text": plan.expected_text,
                        "current_text": plan.current_text,
                        "replacement_count": len(plan.replacements),
                    }
                    for plan in plans
                ],
            }
            report["sources"].append(source_report)

            for plan in skipped_plans:
                frame = frame_by_id.get(plan.frame_id)
                if frame is None:
                    continue
                self._mark_consistency_flag(frame, plan.field_name, "MISMATCH")
                self._mark_consistency_flag(frame, plan.field_name, "FIX_SKIPPED")

            if not safe_plans:
                continue

            output_dwg = consistency_dir / f"{source_path.stem}.consistency{source_path.suffix}"
            source_report["output_dwg"] = str(output_dwg)
            try:
                result = self.titleblock_consistency_bridge.apply(
                    job_id=job.job_id,
                    source_dwg=source_path,
                    output_dwg=output_dwg,
                    plans=safe_plans,
                    workspace_dir=consistency_dir / source_path.stem,
                    slot_runtime=slot_runtime if isinstance(slot_runtime, dict) else None,
                )
                errors = [
                    str(error)
                    for error in result.get("errors", [])
                    if isinstance(error, str) and error
                ]
                source_report["errors"] = errors
                if errors or not output_dwg.exists():
                    raise RuntimeError("; ".join(errors) if errors else "corrected dwg missing")

                for frame in source_to_all_frames.get(source_path, []):
                    frame.runtime.cad_source_file = output_dwg

                for plan in safe_plans:
                    frame = frame_by_id.get(plan.frame_id)
                    if frame is None:
                        continue
                    self._mark_consistency_flag(frame, plan.field_name, "MISMATCH")
                    self._mark_consistency_flag(frame, plan.field_name, "AUTO_FIXED")
                    self.titleblock_consistency.apply_expected_texts(frame, plan)
            except Exception as exc:  # noqa: BLE001
                logger.warning("图签一致性修正失败: %s: %s", source_path, exc)
                source_report["errors"].append(str(exc))
                for plan in safe_plans:
                    frame = frame_by_id.get(plan.frame_id)
                    if frame is None:
                        continue
                    self._mark_consistency_flag(frame, plan.field_name, "MISMATCH")
                    self._mark_consistency_flag(frame, plan.field_name, "FIX_SKIPPED")

        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _mark_consistency_flag(frame: Any, field_name: str, suffix: str) -> None:
        mapping = {
            "paper_size_text": "PAPER_SIZE",
            "scale_text": "SCALE",
            "a4_marker_revision": "A4_MARKER_REVISION",
        }
        prefix = mapping.get(field_name)
        if prefix:
            frame.add_flag(f"{prefix}_{suffix}")

    def _module5_engine(self) -> str:
        """模块5主执行引擎（固定为 cad_dxf）。"""
        return "cad_dxf"

    @staticmethod
    def _is_steel_liner_mode(frames: list[FrameMeta], sheet_sets: list[SheetSet]) -> bool:
        ctx = DocContext(
            params=GlobalDocParams(project_no=""),
            frames=frames,
            sheet_sets=sheet_sets,
        )
        return ctx.is_steel_liner_mode()

    # ==================================================================
    # 阶段 7 (Stage B): SPLIT_AND_RENAME — 仅裁切
    # ==================================================================

    def _stage_split(self, job: Job, context: dict) -> None:
        """模块5固定走 CAD-DXF 切图阶段。"""
        self._stage_split_cad_dxf(job, context)

    def _stage_split_cad_dxf(self, job: Job, context: dict) -> None:
        """cad_dxf 主路径：按 source_dxf 分组，执行 CAD 内核导出。"""
        work_dir = self._require_work_dir(job)
        drawings_dir = work_dir / "output" / "drawings"
        task_root = work_dir / "work" / "cad_tasks"
        drawings_dir.mkdir(parents=True, exist_ok=True)
        task_root.mkdir(parents=True, exist_ok=True)

        grouped = self.cad_dxf_executor.group_by_source_dxf(
            context["frames"],
            context["sheet_sets"],
        )
        steel_liner_mode = self._is_steel_liner_mode(context["frames"], context["sheet_sets"])
        context["steel_liner_mode"] = steel_liner_mode
        total = len(grouped)
        done = 0
        job.progress.details.update({"split_total": total, "split_done": 0})
        context["cad_dxf_results"] = {}

        for done, (source_dxf, group) in enumerate(grouped.items(), start=1):
            self._update_progress(
                job,
                current_file=source_dxf.name,
                message=f"CAD-DXF执行中 ({done}/{total})",
                details={"split_done": done},
            )
            try:
                slot_runtime = job.params.get("cad_slot_runtime")
                result = self.cad_dxf_executor.execute_source_dxf(
                    job_id=job.job_id,
                    source_dxf=source_dxf,
                    frames=group["frames"],
                    sheet_sets=group["sheet_sets"],
                    output_dir=drawings_dir,
                    task_root=task_root,
                    slot_runtime=slot_runtime if isinstance(slot_runtime, dict) else None,
                    plot_style_key=STEEL_LINER_PLOT_STYLE_KEY if steel_liner_mode else None,
                )
                context["cad_dxf_results"][str(source_dxf)] = result
            except Exception as e:  # noqa: BLE001
                logger.warning("CAD-DXF执行失败: %s: %s", source_dxf, e)
                context["cad_dxf_results"][str(source_dxf)] = {
                    "schema_version": "cad-dxf-result@1.0",
                    "source_dxf": str(source_dxf),
                    "frames": [],
                    "sheet_sets": [],
                    "errors": [str(e)],
                }
                job.add_flag(f"DXF执行失败:{source_dxf.name}")
                for frame in group["frames"]:
                    frame.add_flag("DXF执行失败")
                for sheet_set in group["sheet_sets"]:
                    if "DXF执行失败" not in sheet_set.flags:
                        sheet_set.flags.append("DXF执行失败")

    # ==================================================================
    # 阶段 8 (Stage B): EXPORT_PDF_AND_DWG — 统一导出
    # ==================================================================

    def _stage_export(self, job: Job, context: dict) -> None:
        """模块5固定走 CAD-DXF 导出阶段。"""
        self._stage_export_cad_dxf(job, context)

    def _stage_export_cad_dxf(self, job: Job, context: dict) -> None:
        """cad_dxf 主路径的导出校验与结果回填。"""
        drawings_dir = self._require_work_dir(job) / "output" / "drawings"
        drawings_dir.mkdir(parents=True, exist_ok=True)

        frames_by_id = {frame.frame_id: frame for frame in context["frames"]}
        sheet_sets_by_id = {ss.cluster_id: ss for ss in context["sheet_sets"]}
        results = context.get("cad_dxf_results", {})

        total = len(context["frames"]) + len(context["sheet_sets"])
        done = 0
        job.progress.details.update({"export_total": total, "export_done": 0})

        for source_dxf, result in results.items():
            self._update_progress(
                job,
                current_file=Path(source_dxf).name,
                message=f"结果回填中 ({done}/{total})",
                details={"export_done": done},
            )
            frame_count, sheet_count = self.cad_dxf_executor.apply_result(
                result=result,
                frames_by_id=frames_by_id,
                sheet_sets_by_id=sheet_sets_by_id,
            )
            done += frame_count + sheet_count

            for err in result.get("errors", []):
                if isinstance(err, str) and err:
                    job.add_flag(f"CAD结果错误:{Path(source_dxf).name}:{err}")

        # 对未被 result 命中的帧做补充校验，保证失败可见
        for frame in context["frames"]:
            if frame.runtime.pdf_path is None or not frame.runtime.pdf_path.exists():
                frame.add_flag("PDF缺失")

            if frame.runtime.dwg_path is None or not frame.runtime.dwg_path.exists():
                frame.add_flag("DWG缺失")

        # 成组结果若无显式成功记录，保守追加失败标记
        result_cluster_ids = {
            str(item.get("cluster_id", ""))
            for result in results.values()
            for item in result.get("sheet_sets", [])
            if isinstance(item, dict)
        }
        for sheet_set in context["sheet_sets"]:
            if sheet_set.cluster_id not in result_cluster_ids and "导出失败" not in sheet_set.flags:
                sheet_set.flags.append("导出失败")

        self._update_progress(
            job,
            message=f"结果回填完成 ({done}/{total})",
            details={"export_done": done},
        )

    # ==================================================================
    # 阶段 9-10: 文档生成 / 打包（不变）
    # ==================================================================

    def _stage_generate_docs(self, job: Job, context: dict) -> None:
        work_dir = self._require_work_dir(job)
        docs_dir = work_dir / "output" / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        doc_ctx = self._build_doc_context(job, context)
        validation_errors = self.doc_param_validator.validate(doc_ctx)
        if validation_errors:
            for err in validation_errors:
                logger.error("文档参数校验失败: %s", err)
                if err not in job.errors:
                    job.errors.append(err)
            job.add_flag("文档参数校验失败")
            raise RuntimeError("文档参数校验失败")

        doc_ctx.derived = self.derivation.compute(doc_ctx)

        try:
            self._update_progress(job, message="生成封面中")
            self.cover_gen.generate(doc_ctx, docs_dir)
        except Exception as e:
            logger.error(f"封面生成失败: {e}")
            job.add_flag("封面生成失败")

        try:
            self._update_progress(job, message="生成目录中")
            catalog_result = self._generate_catalog_with_diagnostics(doc_ctx, docs_dir)
            page_count = catalog_result.page_count
            doc_ctx.derived.catalog_page_total = page_count
            if catalog_result.pdf_export_error is not None:
                error_text = str(catalog_result.pdf_export_error)
                job.add_flag(f"目录PDF导出失败: {error_text}")
                job.progress.details["catalog_pdf_export_error"] = error_text
                job.progress.details["catalog_pdf_export_traceback"] = "".join(
                    traceback.format_exception(
                        type(catalog_result.pdf_export_error),
                        catalog_result.pdf_export_error,
                        catalog_result.pdf_export_error.__traceback__,
                    )
                )
        except Exception as e:
            logger.error(f"目录生成失败: {e}")
            job.add_flag("目录生成失败")

        try:
            self._update_progress(job, message="生成设计文件中")
            self.design_gen.generate(doc_ctx, docs_dir)
        except Exception as e:
            logger.error(f"设计文件生成失败: {e}")
            job.add_flag("设计文件生成失败")

        try:
            self._update_progress(job, message="生成IED中")
            if not doc_ctx.params.include_ied_plan:
                job.artifacts.ied_xlsx = None
            else:
                ied_dir = work_dir / "ied"
                ied_dir.mkdir(parents=True, exist_ok=True)
                ied_xlsx = self.ied_gen.generate(doc_ctx, ied_dir)
            if doc_ctx.params.include_ied_plan:
                job.artifacts.ied_xlsx = ied_xlsx
        except Exception as e:
            logger.error(f"IED生成失败: {e}")
            job.add_flag("IED生成失败")

        job.artifacts.docs_dir = docs_dir

    def _generate_catalog_with_diagnostics(self, doc_ctx: DocContext, docs_dir: Path) -> Any:
        catalog_gen_dict = getattr(self.catalog_gen, "__dict__", {})
        has_diagnostics = (
            "generate_with_diagnostics" in catalog_gen_dict
            or hasattr(type(self.catalog_gen), "generate_with_diagnostics")
        )
        if has_diagnostics:
            return self.catalog_gen.generate_with_diagnostics(doc_ctx, docs_dir)

        catalog_xlsx, catalog_pdf, page_count = self.catalog_gen.generate(doc_ctx, docs_dir)
        return SimpleNamespace(
            xlsx_path=catalog_xlsx,
            pdf_path=catalog_pdf,
            page_count=page_count,
            pdf_export_error=None,
        )

    def _build_doc_context(self, job: Job, context: dict) -> DocContext:
        merged_params = dict(job.params)
        merged_params.pop("project_no", None)
        merged_params = normalize_global_doc_params(merged_params)
        frame_001 = self._find_frame_001(
            context.get("frames", []),
            context.get("sheet_sets", []),
        )
        if frame_001:
            tb = frame_001.titleblock
            self._fill_if_missing(merged_params, "engineering_no", tb.engineering_no)
            self._fill_if_missing(merged_params, "subitem_no", tb.subitem_no)
            self._fill_if_missing(merged_params, "discipline", tb.discipline)
            self._fill_if_missing(merged_params, "revision", tb.revision)
            self._fill_if_missing(merged_params, "doc_status", tb.status)

        normalized_discipline = normalize_discipline_label(
            merged_params.get("discipline"),
            self.spec.get_mappings(),
        )
        if normalized_discipline:
            merged_params["discipline"] = normalized_discipline

        params = GlobalDocParams(project_no=job.project_no, **merged_params)
        return DocContext(
            params=params,
            frames=context["frames"],
            sheet_sets=context["sheet_sets"],
            rules=self.spec.doc_generation.get("rules", {}),
            mappings=self.spec.get_mappings(),
            options=job.options,
        )

    @staticmethod
    def _find_frame_001(frames: list[Any], sheet_sets: list[Any]) -> Any | None:
        candidates = PipelineExecutor._primary_doc_frame_candidates(frames, sheet_sets)

        exact_001 = [frame for frame in candidates if PipelineExecutor._is_exact_001_frame(frame)]
        frame = PipelineExecutor._first_readable_frame(exact_001)
        if frame is not None:
            return frame

        same_code_primary = [
            frame for frame in candidates
            if PipelineExecutor._same_code_page_index(frame) == 1
        ]
        frame = PipelineExecutor._first_readable_frame(same_code_primary)
        if frame is not None:
            return frame

        sequenced = sorted(
            (
                frame for frame in candidates
                if getattr(getattr(frame, "titleblock", None), "get_seq_no", None)
                and frame.titleblock.get_seq_no() is not None
            ),
            key=lambda frame: (
                frame.titleblock.get_seq_no() or 9999,
                frame.titleblock.internal_code or "",
            ),
        )
        return PipelineExecutor._first_readable_frame(sequenced)

    @staticmethod
    def _primary_doc_frame_candidates(frames: list[Any], sheet_sets: list[Any]) -> list[Any]:
        candidates: list[Any] = []
        seen_ids: set[str] = set()

        for frame in frames:
            frame_id = getattr(getattr(frame, "runtime", None), "frame_id", None)
            if not frame_id or frame_id in seen_ids:
                continue
            seen_ids.add(frame_id)
            candidates.append(frame)

        for sheet_set in sheet_sets:
            master_page = getattr(sheet_set, "master_page", None)
            master_frame = getattr(master_page, "frame_meta", None)
            frame_id = getattr(getattr(master_frame, "runtime", None), "frame_id", None)
            if not frame_id or frame_id in seen_ids:
                continue
            seen_ids.add(frame_id)
            candidates.append(master_frame)

        return candidates

    @staticmethod
    def _is_exact_001_frame(frame: Any) -> bool:
        internal_code = getattr(getattr(frame, "titleblock", None), "internal_code", None) or ""
        return internal_code.endswith("-001")

    @staticmethod
    def _same_code_page_index(frame: Any) -> int:
        raw_extracts = getattr(frame, "raw_extracts", None)
        if not isinstance(raw_extracts, dict):
            return 0
        meta = raw_extracts.get("same_code_multipage")
        if not isinstance(meta, dict):
            return 0
        try:
            return int(meta.get("page_index", 0) or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _has_required_doc_fields(frame: Any) -> bool:
        tb = getattr(frame, "titleblock", None)
        if tb is None:
            return False
        required = [
            getattr(tb, "engineering_no", None),
            getattr(tb, "subitem_no", None),
            getattr(tb, "discipline", None),
            getattr(tb, "revision", None),
            getattr(tb, "status", None),
        ]
        return all(str(value or "").strip() for value in required)

    @staticmethod
    def _first_readable_frame(frames: list[Any]) -> Any | None:
        for frame in frames:
            if PipelineExecutor._has_required_doc_fields(frame):
                return frame
        return None

    @staticmethod
    def _fill_if_missing(target: dict, key: str, value: object | None) -> None:
        if value is None:
            return
        current = target.get(key)
        if current is None or (isinstance(current, str) and current.strip() == ""):
            target[key] = value

    def _stage_package(self, job: Job, context: dict) -> None:
        self._update_progress(job, message="打包中")
        work_dir = self._require_work_dir(job)
        drawings_dir = work_dir / "output" / "drawings"
        docs_dir = work_dir / "output" / "docs"

        job.artifacts.drawings_dir = drawings_dir if drawings_dir.exists() else None
        job.artifacts.docs_dir = docs_dir if docs_dir.exists() else None
        job.artifacts.package_zip = work_dir / "package.zip"

        self._record_workload(job, context)
        self.packager.generate_manifest(job, context=context)
        zip_path = self.packager.package(job)
        job.artifacts.package_zip = zip_path
        if not bool(job.options.get("split_only", False)):
            self._generate_preview_pdf(job, context)

    def _record_workload(self, job: Job, context: dict) -> None:
        summary = self.workload_calculator.build_from_frame_sets(
            list(context.get("frames") or []),
            list(context.get("sheet_sets") or []),
        )
        job.progress.details["workload"] = summary.model_dump(mode="json")
        job.progress.details["effective_workload"] = round(
            float(summary.final_workload_a1 or summary.initial_workload_a1 or 0.0),
            self.workload_calculator.precision,
        )

    def _generate_preview_pdf(self, job: Job, context: dict) -> None:
        try:
            preview_result = self.preview_pdf_service.build_preview(
                job_id=job.job_id,
                output_dir=self._require_work_dir(job) / "output" / "preview",
                frames=context.get("frames", []),
                sheet_sets=context.get("sheet_sets", []),
                findings=[],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("preview pdf generation failed for %s: %s", job.job_id, exc)
            job.add_flag("PREVIEW_PDF_GENERATE_FAILED")
            return

        job.artifacts.preview_pdf = preview_result.pdf_path
        job.artifacts.preview_mode = preview_result.mode

    # ==================================================================
    # Flags 聚合
    # ==================================================================

    def _aggregate_flags(self, job: Job, context: dict) -> None:
        """将 frame / sheet_set 级 flags 聚合到 job.flags"""
        for frame in context.get("frames", []):
            for flag in frame.runtime.flags:
                job.add_flag(f"[{output_name_for_frame(frame)}] {flag}")
        for ss in context.get("sheet_sets", []):
            for flag in ss.flags:
                job.add_flag(f"[{output_name_for_sheet_set(ss)}] {flag}")

    @staticmethod
    def _raise_if_fatal_export_errors(job: Job) -> None:
        cad_fatal_markers = ("DXF执行失败", "CAD结果错误", "PDF缺失", "DWG缺失")

        def is_cad_fatal_flag(flag: str) -> bool:
            text = str(flag or "").strip()
            if any(marker in text for marker in cad_fatal_markers):
                return True
            return text == "导出失败" or text.endswith("] 导出失败") or text.endswith("]导出失败")

        cad_fatal_flags = [flag for flag in job.flags if is_cad_fatal_flag(flag)]

        details = job.progress.details
        export_total = int(details.get("export_total", 0) or 0)
        export_done = int(details.get("export_done", 0) or 0)
        incomplete_export = export_total > 0 and export_done < export_total

        if not cad_fatal_flags and not incomplete_export:
            return

        reasons: list[str] = []
        if cad_fatal_flags:
            reasons.append(cad_fatal_flags[0])
        if incomplete_export:
            reasons.append(f"export_done={export_done}/{export_total}")
        if reasons:
            raise RuntimeError(f"CAD导出失败: {'; '.join(reasons)}")

    # ==================================================================
    # 进度更新
    # ==================================================================

    def _update_progress(
        self,
        job: Job,
        *,
        message: str | None = None,
        current_file: str | None = None,
        details: dict[str, int | str | float] | None = None,
        force: bool = False,
    ) -> None:
        if message is not None:
            job.progress.message = message
        if current_file is not None:
            job.progress.current_file = current_file
        if details:
            job.progress.details.update(details)
        now = time.time()
        if force or (now - self._last_progress_write) >= self._progress_interval_sec:
            self._persist_job(job)
            self._last_progress_write = now

    def _persist_job(self, job: Job) -> None:
        job_dir = self.config.get_job_dir(job.job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        job_file = job_dir / "job.json"
        with open(job_file, "w", encoding="utf-8") as f:
            json.dump(
                job.model_dump(mode="json"),
                f,
                ensure_ascii=False,
                indent=2,
                default=str,
            )

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        return bool(value)
