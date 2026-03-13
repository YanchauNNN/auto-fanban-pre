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
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..cad import (
    A4MultipageGrouper,
    CADDXFExecutor,
    FrameDetector,
    ODAConverter,
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
from ..models import DocContext, GlobalDocParams, normalize_global_doc_params
from .packager import Packager
from .stages import DELIVERABLE_STAGES, StageEnum

if TYPE_CHECKING:
    from ..models import Job

logger = logging.getLogger(__name__)


class PipelineExecutor:
    """流水线执行器"""

    def __init__(self):
        self.config = get_config()
        self.spec = load_spec()
        self._last_progress_write = 0.0
        self._progress_interval_sec = 2.0

        # 初始化各模块
        self.oda = ODAConverter()
        self.frame_detector = FrameDetector()
        self.titleblock_extractor = TitleblockExtractor()
        self.a4_grouper = A4MultipageGrouper()
        self.cad_dxf_executor = CADDXFExecutor(config=self.config)
        self.derivation = DerivationEngine()
        self.doc_param_validator = DocParamValidator()
        self.cover_gen = CoverGenerator()
        self.catalog_gen = CatalogGenerator()
        self.design_gen = DesignFileGenerator()
        self.ied_gen = IEDGenerator()
        self.packager = Packager()

    def execute(self, job: Job) -> None:
        """执行流水线"""
        job.mark_running()
        self._update_progress(job, message="任务开始", force=True)

        try:
            job.work_dir = self.config.get_job_dir(job.job_id)
            job.work_dir.mkdir(parents=True, exist_ok=True)

            context: dict = {
                "dxf_files": [],
                "dxf_to_dwg": {},
                "frames": [],
                "sheet_sets": [],
                # Stage 7 (cad_dxf) 产物: {source_dxf: result_json_dict}
                "cad_dxf_results": {},
            }

            split_only = bool(job.options.get("split_only", False))
            stages = (
                [
                    stage
                    for stage in DELIVERABLE_STAGES
                    if stage.name
                    in {
                        StageEnum.INGEST.value,
                        StageEnum.CONVERT_DWG_TO_DXF.value,
                        StageEnum.DETECT_FRAMES.value,
                        StageEnum.VERIFY_FRAMES_BY_ANCHOR.value,
                        StageEnum.SCALE_FIT_AND_CHECK.value,
                        StageEnum.EXTRACT_TITLEBLOCK_FIELDS.value,
                        StageEnum.A4_MULTIPAGE_GROUPING.value,
                        StageEnum.SPLIT_AND_RENAME.value,
                        StageEnum.EXPORT_PDF_AND_DWG.value,
                    }
                ]
                if split_only
                else DELIVERABLE_STAGES
            )
            for stage in stages:
                self._execute_stage(job, stage, context)

            # 聚合 frame/sheet_set flags 到 job
            self._aggregate_flags(job, context)
            self._raise_if_fatal_export_errors(job)

            job.mark_succeeded()
            self._update_progress(job, message="任务完成", force=True)

        except Exception as e:
            logger.exception(f"流水线执行失败: {job.job_id}")
            job.mark_failed(str(e))
            self._update_progress(job, message=f"任务失败: {e}", force=True)
            raise

    # ==================================================================
    # 阶段分发
    # ==================================================================

    def _execute_stage(self, job: Job, stage, context: dict) -> None:
        job.progress.stage = stage.name
        job.progress.percent = stage.progress_start
        logger.info(f"[{job.job_id}] 开始阶段: {stage.name}")
        self._update_progress(job, message=f"开始阶段: {stage.name}", force=True)

        try:
            handler = {
                StageEnum.INGEST.value: self._stage_ingest,
                StageEnum.CONVERT_DWG_TO_DXF.value: self._stage_convert,
                StageEnum.DETECT_FRAMES.value: self._stage_detect_frames,
                StageEnum.VERIFY_FRAMES_BY_ANCHOR.value: self._stage_verify_frames,
                StageEnum.SCALE_FIT_AND_CHECK.value: self._stage_scale_fit,
                StageEnum.EXTRACT_TITLEBLOCK_FIELDS.value: self._stage_extract_fields,
                StageEnum.A4_MULTIPAGE_GROUPING.value: self._stage_a4_grouping,
                StageEnum.SPLIT_AND_RENAME.value: self._stage_split,
                StageEnum.EXPORT_PDF_AND_DWG.value: self._stage_export,
                StageEnum.GENERATE_DOCS.value: self._stage_generate_docs,
                StageEnum.PACKAGE_ZIP.value: self._stage_package,
            }.get(stage.name)

            if handler:
                handler(job, context)

        except Exception as e:
            logger.error(f"[{job.job_id}] 阶段失败 {stage.name}: {e}")
            job.add_flag(f"阶段失败:{stage.name}")
            raise

        job.progress.percent = stage.progress_end
        self._update_progress(job, message=f"完成阶段: {stage.name}", force=True)

    # ==================================================================
    # 阶段 1-6: 不变（ingest / convert / detect / verify / scale / extract / a4）
    # ==================================================================

    def _stage_ingest(self, job: Job, context: dict) -> None:
        input_dir = job.work_dir / "input"
        input_dir.mkdir(exist_ok=True)
        for f in job.input_files:
            if f.exists():
                import shutil

                shutil.copy(f, input_dir / f.name)

    def _stage_convert(self, job: Job, context: dict) -> None:
        input_dir = job.work_dir / "input"
        dxf_dir = job.work_dir / "work" / "dxf"
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

    def _stage_a4_grouping(self, job: Job, context: dict) -> None:
        remaining, sheet_sets = self.a4_grouper.group_a4_pages(context["frames"])
        context["frames"] = remaining
        context["sheet_sets"] = sheet_sets

    def _module5_engine(self) -> str:
        """模块5主执行引擎（固定为 cad_dxf）。"""
        return "cad_dxf"

    # ==================================================================
    # 阶段 7 (Stage B): SPLIT_AND_RENAME — 仅裁切
    # ==================================================================

    def _stage_split(self, job: Job, context: dict) -> None:
        """模块5固定走 CAD-DXF 切图阶段。"""
        self._stage_split_cad_dxf(job, context)

    def _stage_split_cad_dxf(self, job: Job, context: dict) -> None:
        """cad_dxf 主路径：按 source_dxf 分组，执行 CAD 内核导出。"""
        drawings_dir = job.work_dir / "output" / "drawings"
        task_root = job.work_dir / "work" / "cad_tasks"
        drawings_dir.mkdir(parents=True, exist_ok=True)
        task_root.mkdir(parents=True, exist_ok=True)

        grouped = self.cad_dxf_executor.group_by_source_dxf(
            context["frames"],
            context["sheet_sets"],
        )
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
                result = self.cad_dxf_executor.execute_source_dxf(
                    job_id=job.job_id,
                    source_dxf=source_dxf,
                    frames=group["frames"],
                    sheet_sets=group["sheet_sets"],
                    output_dir=drawings_dir,
                    task_root=task_root,
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
        drawings_dir = job.work_dir / "output" / "drawings"
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
        docs_dir = job.work_dir / "output" / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        ied_dir = job.work_dir / "ied"
        ied_dir.mkdir(parents=True, exist_ok=True)

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
            catalog_xlsx, catalog_pdf, page_count = self.catalog_gen.generate(
                doc_ctx,
                docs_dir,
            )
            doc_ctx.derived.catalog_page_total = page_count
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
            ied_xlsx = self.ied_gen.generate(doc_ctx, ied_dir)
            job.artifacts.ied_xlsx = ied_xlsx
        except Exception as e:
            logger.error(f"IED生成失败: {e}")
            job.add_flag("IED生成失败")

        job.artifacts.docs_dir = docs_dir

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
        for frame in frames:
            internal_code = frame.titleblock.internal_code
            if internal_code and internal_code.endswith("-001"):
                return frame

        for sheet_set in sheet_sets:
            master_page = getattr(sheet_set, "master_page", None)
            master_frame = getattr(master_page, "frame_meta", None)
            internal_code = getattr(getattr(master_frame, "titleblock", None), "internal_code", None)
            if internal_code and internal_code.endswith("-001"):
                return master_frame

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
        drawings_dir = job.work_dir / "output" / "drawings"
        docs_dir = job.work_dir / "output" / "docs"

        job.artifacts.drawings_dir = drawings_dir if drawings_dir.exists() else None
        job.artifacts.docs_dir = docs_dir if docs_dir.exists() else None
        job.artifacts.package_zip = job.work_dir / "package.zip"

        self.packager.generate_manifest(job, context=context)
        zip_path = self.packager.package(job)
        job.artifacts.package_zip = zip_path

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
        fatal_markers = ("DXF执行失败", "CAD结果错误", "PDF缺失", "DWG缺失", "导出失败")
        fatal_flags = [flag for flag in job.flags if any(marker in flag for marker in fatal_markers)]

        details = job.progress.details
        export_total = int(details.get("export_total", 0) or 0)
        export_done = int(details.get("export_done", 0) or 0)
        incomplete_export = export_total > 0 and export_done < export_total

        if not fatal_flags and not incomplete_export:
            return

        reasons: list[str] = []
        if fatal_flags:
            reasons.append(fatal_flags[0])
        if incomplete_export:
            reasons.append(f"export_done={export_done}/{export_total}")
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
