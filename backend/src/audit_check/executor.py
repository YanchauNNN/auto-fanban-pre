from __future__ import annotations

from pathlib import Path

from ..cad import (
    A4MultipageGrouper,
    CADDXFExecutor,
    FrameDetector,
    ODAConverter,
    SameCodeMultipageGrouper,
    TitleblockExtractor,
)
from ..config import get_config
from ..models import Job
from ..pipeline.preview_pdf_service import PreviewPdfService
from ..pipeline.shared_prep import SharedPrepService
from ..workload.calculator import WorkloadCalculator
from .bridge import AuditDotNetScanner
from .lexicon import AuditLexiconLoader
from .matcher import AuditMatchEngine
from .models import AuditFinding
from .reporting import write_report_json, write_report_xlsx
from .roi_mapper import AuditFieldContextMapper
from .standard_review import StandardLibraryLoader, StandardReviewEngine


class AuditCheckExecutor:
    def __init__(self) -> None:
        self.config = get_config()
        self.oda = ODAConverter()
        self.frame_detector = FrameDetector()
        self.titleblock_extractor = TitleblockExtractor()
        self.a4_grouper = A4MultipageGrouper()
        self.same_code_multipage_grouper = SameCodeMultipageGrouper()
        self.cad_dxf_executor = CADDXFExecutor(config=self.config)
        self.preview_pdf_service = PreviewPdfService()
        self.lexicon_loader = AuditLexiconLoader()
        self.standard_library_loader = StandardLibraryLoader()
        self.dotnet_scanner = AuditDotNetScanner()
        self.workload_calculator = WorkloadCalculator()

    def execute(self, job: Job) -> None:
        if not job.input_files:
            raise ValueError("audit_check requires one uploaded dwg file")

        source_dwg = Path(job.input_files[0]).resolve()
        project_no = str(job.project_no or "").strip()
        if not project_no:
            raise ValueError("project_no is required for audit_check")

        job.mark_running(stage="AUDIT_CHECK")
        job.progress.message = "auditing"
        job.work_dir = self.config.get_job_dir(job.job_id)
        job.work_dir.mkdir(parents=True, exist_ok=True)

        shared_prep_dir = str(job.params.get("shared_prep_dir") or "").strip()
        if shared_prep_dir:
            prep = SharedPrepService.load(Path(shared_prep_dir))
            remaining_frames = prep.frames
            sheet_sets = prep.sheet_sets
            preview_source = prep.source_input_dwg
        else:
            dxf_dir = job.work_dir / "work" / "audit_dxf"
            dxf_dir.mkdir(parents=True, exist_ok=True)
            dxf_path = self.oda.dwg_to_dxf(source_dwg, dxf_dir)

            self.frame_detector.set_project_no(project_no)
            self.titleblock_extractor.set_project_no(project_no)
            frames = self.frame_detector.detect_frames(dxf_path)
            for frame in frames:
                frame.runtime.cad_source_file = source_dwg
                self.titleblock_extractor.extract_fields(dxf_path, frame)
            remaining_frames, sheet_sets = self.a4_grouper.group_a4_pages(frames)
            preview_source = source_dwg

        lexicon = self.lexicon_loader.load(self.config.audit_check.lexicon_path)
        mapper = AuditFieldContextMapper(remaining_frames, sheet_sets)
        slot_runtime = job.params.get("cad_slot_runtime")
        scan_items = self.dotnet_scanner.scan(
            job_id=job.job_id,
            source_dwg=source_dwg,
            workspace_dir=job.work_dir / "work",
            slot_runtime=slot_runtime if isinstance(slot_runtime, dict) else None,
        )
        annotated_items = [mapper.annotate(item) for item in scan_items]

        findings = AuditMatchEngine(lexicon).evaluate(
            project_no=project_no,
            unit_no=str(job.params.get("unit_no") or "").strip() or None,
            items=annotated_items,
        )
        findings.extend(self._standard_review_findings(annotated_items))

        reports_dir = job.work_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_json = reports_dir / "report.json"
        report_xlsx = reports_dir / "report.xlsx"

        summary = write_report_json(
            report_json,
            source_filename=source_dwg.name,
            project_no=project_no,
            findings=findings,
        )
        write_report_xlsx(
            report_xlsx,
            source_filename=source_dwg.name,
            project_no=project_no,
            findings=findings,
            summary=summary,
        )

        job.artifacts.reports_dir = reports_dir
        job.artifacts.report_json = report_json
        job.artifacts.report_xlsx = report_xlsx
        job.progress.details["findings_count"] = int(summary["findings_count"])
        job.progress.details["affected_drawings_count"] = int(summary["affected_drawings_count"])
        job.progress.details["top_wrong_texts"] = list(summary["top_wrong_texts"])
        job.progress.details["top_internal_codes"] = list(summary["top_internal_codes"])
        self._record_workload(job, remaining_frames, sheet_sets)
        self._generate_preview_pdf(
            job,
            source_dwg=preview_source,
            frames=remaining_frames,
            sheet_sets=sheet_sets,
            findings=findings,
        )
        job.mark_succeeded()

    def _record_workload(self, job: Job, frames: list, sheet_sets: list) -> None:
        summary = self.workload_calculator.build_from_frame_sets(frames, sheet_sets)
        job.progress.details["workload"] = summary.model_dump(mode="json")
        job.progress.details["effective_workload"] = round(
            float(summary.final_workload_a1 or summary.initial_workload_a1 or 0.0),
            self.workload_calculator.precision,
        )

    def _generate_preview_pdf(
        self,
        job: Job,
        *,
        source_dwg: Path,
        frames: list,
        sheet_sets: list,
        findings: list[AuditFinding],
    ) -> None:
        try:
            export_frames = [frame.model_copy(deep=True) for frame in frames]
            export_sheet_sets = [sheet_set.model_copy(deep=True) for sheet_set in sheet_sets]
            self.same_code_multipage_grouper.group_frames(export_frames)
            grouped = self.cad_dxf_executor.group_by_source_dxf(export_frames, export_sheet_sets)

            preview_pages_dir = job.work_dir / "output" / "preview_pages"
            preview_task_root = job.work_dir / "work" / "preview_cad_tasks"
            preview_pages_dir.mkdir(parents=True, exist_ok=True)
            preview_task_root.mkdir(parents=True, exist_ok=True)

            for grouped_source, group in grouped.items():
                result = self.cad_dxf_executor.execute_source_dxf(
                    job_id=f"{job.job_id}-preview",
                    source_dxf=grouped_source or source_dwg,
                    frames=group["frames"],
                    sheet_sets=group["sheet_sets"],
                    output_dir=preview_pages_dir,
                    task_root=preview_task_root,
                    slot_runtime=(
                        job.params.get("cad_slot_runtime")
                        if isinstance(job.params.get("cad_slot_runtime"), dict)
                        else None
                    ),
                    plot_style_key=job.plot_style_key,
                )
                self.cad_dxf_executor.apply_result(
                    result=result,
                    frames_by_id={frame.frame_id: frame for frame in group["frames"]},
                    sheet_sets_by_id={sheet_set.cluster_id: sheet_set for sheet_set in group["sheet_sets"]},
                )

            preview_result = self.preview_pdf_service.build_preview(
                job_id=job.job_id,
                output_dir=job.work_dir / "output" / "preview",
                frames=export_frames,
                sheet_sets=export_sheet_sets,
                findings=findings,
            )
        except Exception as exc:  # noqa: BLE001
            job.add_flag("PREVIEW_PDF_GENERATE_FAILED")
            job.progress.details["preview_error"] = str(exc)
            return

        job.artifacts.preview_pdf = preview_result.pdf_path
        job.artifacts.preview_mode = preview_result.mode

    def _standard_review_findings(self, items: list) -> list[AuditFinding]:
        standard_cfg = self.config.audit_check.standard_review
        if not standard_cfg.enabled:
            return []
        entries = self.standard_library_loader.load(
            standard_cfg.library_path,
            sheet_name=standard_cfg.sheet_name,
        )
        return StandardReviewEngine(
            entries,
            same_line_y_tolerance=standard_cfg.same_line_y_tolerance,
        ).evaluate(items)
