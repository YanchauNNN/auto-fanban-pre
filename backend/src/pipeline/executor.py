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
from typing import TYPE_CHECKING

from ..cad import (
    A4MultipageGrouper,
    FrameDetector,
    FrameSplitter,
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
from ..models import DocContext, GlobalDocParams
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
        self.splitter = FrameSplitter()
        self.derivation = DerivationEngine()
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
                "frames": [],
                "sheet_sets": [],
                # Stage 7 产物: {frame_id: split_dxf_path}
                "split_results": {},
                # Stage 7 产物: {cluster_id: split_dxf_path}
                "sheet_set_splits": {},
            }

            for stage in DELIVERABLE_STAGES:
                self._execute_stage(job, stage, context)

            # 聚合 frame/sheet_set flags 到 job
            self._aggregate_flags(job, context)

            job.mark_succeeded()

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

    # ==================================================================
    # 阶段 7 (Stage B): SPLIT_AND_RENAME — 仅裁切
    # ==================================================================

    def _stage_split(self, job: Job, context: dict) -> None:
        """仅裁切DXF，产出中间产物到 work/split/"""
        split_dir = job.work_dir / "work" / "split"
        split_dir.mkdir(parents=True, exist_ok=True)

        # -- 普通图框（按源DXF分组批量裁切）--
        frames_by_dxf: dict[Path, list] = {}
        for frame in context["frames"]:
            frames_by_dxf.setdefault(frame.runtime.source_file, []).append(frame)

        total = len(context["frames"]) + len(context["sheet_sets"])
        done = 0
        job.progress.details.update({"split_total": total, "split_done": 0})

        for dxf_path, frames in frames_by_dxf.items():
            try:
                self._update_progress(
                    job,
                    current_file=dxf_path.name,
                    message=f"裁切中 ({done}/{total})",
                    details={"split_done": done},
                )

                def _progress_cb(entity_count: int) -> None:
                    self._update_progress(
                        job,
                        message=f"裁切中(实体已处理 {entity_count})",
                    )

                results = self.splitter.clip_frames_batch(
                    dxf_path,
                    frames,
                    split_dir,
                    progress_cb=_progress_cb,
                )
                for frame, split_path in results:
                    context["split_results"][frame.frame_id] = split_path
                done += len(results)
                self._update_progress(
                    job,
                    message=f"裁切中 ({done}/{total})",
                    details={"split_done": done},
                )
            except Exception as e:
                logger.warning(f"批量裁切失败: {dxf_path}: {e}")
                for frame in frames:
                    frame.add_flag("裁切失败")

        # -- A4成组 --
        for sheet_set in context["sheet_sets"]:
            try:
                dxf_path = sheet_set.master_page.frame_meta.runtime.source_file
                self._update_progress(
                    job,
                    current_file=dxf_path.name,
                    message=f"A4成组裁切中 ({done + 1}/{total})",
                    details={"split_done": done + 1},
                )
                split_path = self.splitter.clip_sheet_set(
                    dxf_path,
                    sheet_set,
                    split_dir,
                )
                context["sheet_set_splits"][sheet_set.cluster_id] = split_path
                done += 1
            except Exception as e:
                logger.warning(f"A4成组裁切失败: {sheet_set.cluster_id}: {e}")
                sheet_set.flags.append("裁切失败")
                done += 1

    # ==================================================================
    # 阶段 8 (Stage B): EXPORT_PDF_AND_DWG — 统一导出
    # ==================================================================

    def _stage_export(self, job: Job, context: dict) -> None:
        """从中间DXF导出 PDF + DWG 到 output/drawings/"""
        drawings_dir = job.work_dir / "output" / "drawings"
        drawings_dir.mkdir(parents=True, exist_ok=True)

        split_results: dict = context.get("split_results", {})
        sheet_set_splits: dict = context.get("sheet_set_splits", {})

        total = len(split_results) + len(sheet_set_splits)
        done = 0
        job.progress.details.update({"export_total": total, "export_done": 0})

        # -- 批量 DXF→DWG（ODA 一次调用转换整个目录）--
        split_dir = job.work_dir / "work" / "split"
        self._batch_dxf_to_dwg(split_dir, drawings_dir)

        # -- 单帧：导出 PDF + 查找 DWG --
        frame_tasks: list[tuple] = []
        for frame in context["frames"]:
            split_dxf = split_results.get(frame.frame_id)
            if not split_dxf:
                continue
            name = output_name_for_frame(frame)
            pdf_path = drawings_dir / f"{name}.pdf"
            dwg_path = drawings_dir / f"{name}.dwg"
            clip_bbox = frame.runtime.outer_bbox
            paper_size_mm = self.splitter._get_paper_size_mm(frame.runtime.paper_variant_id)
            frame_tasks.append(
                (frame, split_dxf, name, pdf_path, dwg_path, clip_bbox, paper_size_mm)
            )

        pdf_engine = getattr(self.splitter, "_pdf_engine", "python")
        batch_autocad_ok = False
        if frame_tasks and pdf_engine == "autocad_com":
            batch_jobs = [
                (split_dxf, pdf_path, clip_bbox, paper_size_mm)
                for (_, split_dxf, _, pdf_path, _, clip_bbox, paper_size_mm) in frame_tasks
            ]
            try:
                # 关键优化：同一批单帧任务仅启动一次 AutoCAD
                self.splitter.autocad_pdf_exporter.export_single_page_batch(batch_jobs)
                batch_autocad_ok = True
            except Exception as e:
                logger.warning(f"AutoCAD 批量PDF出图失败，回退逐张模式: {e}")

        for frame, split_dxf, name, pdf_path, dwg_path, clip_bbox, paper_size_mm in frame_tasks:
            try:
                done += 1
                self._update_progress(
                    job,
                    message=f"导出中 ({done}/{total})",
                    details={"export_done": done},
                )

                if not (pdf_engine == "autocad_com" and batch_autocad_ok):
                    self.splitter._export_single_page_routed(
                        split_dxf,
                        pdf_path,
                        clip_bbox=clip_bbox,
                        paper_size_mm=paper_size_mm,
                        name=name,
                    )
                frame.runtime.pdf_path = pdf_path

                # DWG（已由批量转换产出，确认存在）
                if dwg_path.exists():
                    frame.runtime.dwg_path = dwg_path
                else:
                    # 单独尝试转换
                    try:
                        frame.runtime.dwg_path = self.splitter._convert_to_dwg(
                            split_dxf,
                            drawings_dir,
                            name,
                        )
                    except Exception as dwg_err:
                        logger.warning(f"DWG转换失败: {name}: {dwg_err}")
                        frame.add_flag("DWG转换失败")
            except Exception as e:
                logger.warning(f"导出失败: {frame.frame_id}: {e}")
                frame.add_flag("导出失败")

        # -- A4成组：导出多页 PDF + 查找 DWG --
        for sheet_set in context["sheet_sets"]:
            split_dxf = sheet_set_splits.get(sheet_set.cluster_id)
            if not split_dxf:
                continue
            try:
                done += 1
                self._update_progress(
                    job,
                    message=f"A4成组导出中 ({done}/{total})",
                    details={"export_done": done},
                )
                name = output_name_for_sheet_set(sheet_set)
                pdf_path = drawings_dir / f"{name}.pdf"
                dwg_path = drawings_dir / f"{name}.dwg"

                # 多页PDF（严格窗口打印 + 1:1 A4 图幅）
                page_bboxes = [p.outer_bbox for p in sheet_set.pages]
                a4_paper = self.splitter._get_a4_paper_size(page_bboxes[0]) if page_bboxes else None
                is_fallback = self.splitter._export_multipage_routed(
                    split_dxf,
                    pdf_path,
                    page_bboxes,
                    paper_size_mm=a4_paper,
                    name=name,
                )
                if is_fallback:
                    sheet_set.flags.append("A4多页_PDF兜底为单页大图")

                # DWG
                if dwg_path.exists():
                    pass  # 已由批量转换产出
                else:
                    try:
                        self.splitter._convert_to_dwg(
                            split_dxf,
                            drawings_dir,
                            name,
                        )
                    except Exception as dwg_err:
                        logger.warning(f"A4 DWG转换失败: {name}: {dwg_err}")
                        sheet_set.flags.append("DWG转换失败")
            except Exception as e:
                logger.warning(f"A4成组导出失败: {sheet_set.cluster_id}: {e}")
                sheet_set.flags.append("导出失败")

    def _batch_dxf_to_dwg(self, split_dir: Path, output_dir: Path) -> None:
        """批量 DXF→DWG（单次ODA调用转换整个目录）"""
        dxf_files = list(split_dir.glob("*.dxf"))
        if not dxf_files:
            return
        try:
            self.splitter.oda.dxf_to_dwg(dxf_files[0], output_dir)
        except Exception as e:
            logger.warning(f"批量DXF→DWG失败: {e}")

    # ==================================================================
    # 阶段 9-10: 文档生成 / 打包（不变）
    # ==================================================================

    def _stage_generate_docs(self, job: Job, context: dict) -> None:
        docs_dir = job.work_dir / "output" / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        ied_dir = job.work_dir / "ied"
        ied_dir.mkdir(parents=True, exist_ok=True)

        doc_ctx = self._build_doc_context(job, context)
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
        params = GlobalDocParams(project_no=job.project_no, **job.params)
        return DocContext(
            params=params,
            frames=context["frames"],
            sheet_sets=context["sheet_sets"],
            rules=self.spec.doc_generation.get("rules", {}),
            mappings=self.spec.get_mappings(),
            options=job.options,
        )

    def _stage_package(self, job: Job, context: dict) -> None:
        self._update_progress(job, message="打包中")
        zip_path = self.packager.package(job)
        self.packager.generate_manifest(job, context=context)

        job.artifacts.package_zip = zip_path
        job.artifacts.drawings_dir = job.work_dir / "output" / "drawings"

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
