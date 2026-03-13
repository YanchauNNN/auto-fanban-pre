from __future__ import annotations

from pathlib import Path

from ..cad import A4MultipageGrouper, FrameDetector, ODAConverter, TitleblockExtractor
from ..config import get_config
from ..models import Job
from .bridge import AuditDotNetScanner
from .lexicon import AuditLexiconLoader
from .matcher import AuditMatchEngine
from .reporting import write_report_json, write_report_xlsx
from .roi_mapper import AuditFieldContextMapper


class AuditCheckExecutor:
    def __init__(self) -> None:
        self.config = get_config()
        self.oda = ODAConverter()
        self.frame_detector = FrameDetector()
        self.titleblock_extractor = TitleblockExtractor()
        self.a4_grouper = A4MultipageGrouper()
        self.lexicon_loader = AuditLexiconLoader()
        self.dotnet_scanner = AuditDotNetScanner()

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

        lexicon = self.lexicon_loader.load(_default_lexicon_path())
        dxf_dir = job.work_dir / "work" / "audit_dxf"
        dxf_dir.mkdir(parents=True, exist_ok=True)
        dxf_path = self.oda.dwg_to_dxf(source_dwg, dxf_dir)

        frames = self.frame_detector.detect_frames(dxf_path)
        for frame in frames:
            frame.runtime.cad_source_file = source_dwg
            self.titleblock_extractor.extract_fields(dxf_path, frame)
        remaining_frames, sheet_sets = self.a4_grouper.group_a4_pages(frames)

        mapper = AuditFieldContextMapper(remaining_frames, sheet_sets)
        scan_items = self.dotnet_scanner.scan(
            job_id=job.job_id,
            source_dwg=source_dwg,
            workspace_dir=job.work_dir / "work",
        )
        annotated_items = [mapper.annotate(item) for item in scan_items]

        findings = AuditMatchEngine(lexicon).evaluate(
            project_no=project_no,
            items=annotated_items,
        )

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
        job.mark_succeeded()


def _default_lexicon_path() -> Path:
    return Path(__file__).resolve().parents[3] / "documents_bin" / "词库收集.xlsx"
