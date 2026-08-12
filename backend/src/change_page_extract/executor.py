from __future__ import annotations

from pathlib import Path

from ..archive_tools import ArchiveExtractorSettings, ArchiveLimits, extract_archive
from ..config import get_config
from ..models import Job
from .service import ChangePageExtractService


class ChangePageExtractExecutor:
    """Extract one archive and persist its PDF page-count result."""

    def __init__(self) -> None:
        self.config = get_config()

    def execute(self, job: Job) -> None:
        if len(job.input_files) != 1:
            raise ValueError("change_page_extract requires exactly one archive")

        source_archive = Path(job.input_files[0]).resolve(strict=True)
        runtime = self.config.change_page_extract
        job.mark_running(stage="EXTRACT_ARCHIVE")
        job.progress.percent = 10
        job.progress.current_file = job.source_filename or source_archive.name
        job.progress.message = "正在安全解压压缩包"
        job.work_dir = self.config.get_job_dir(job.job_id)
        job.work_dir.mkdir(parents=True, exist_ok=True)

        extracted = extract_archive(
            source_archive,
            job.work_dir / "extracted",
            limits=ArchiveLimits(
                max_files=runtime.max_archive_files,
                max_total_bytes=runtime.max_extracted_total_mb * 1024 * 1024,
                max_single_file_bytes=runtime.max_single_file_mb * 1024 * 1024,
                max_compression_ratio=runtime.max_compression_ratio,
            ),
            extractor=ArchiveExtractorSettings(
                executable=runtime.archive_extractor.executable,
                fallback_executables=tuple(
                    runtime.archive_extractor.fallback_executables
                ),
                list_timeout_seconds=runtime.archive_extractor.list_timeout_seconds,
                extract_timeout_seconds=runtime.archive_extractor.extract_timeout_seconds,
                max_list_output_bytes=runtime.archive_extractor.max_list_output_bytes,
            ),
            zip_metadata_encodings=tuple(runtime.zip_metadata_encodings),
        )

        job.progress.stage = "COUNT_PDF_PAGES"
        job.progress.percent = 55
        job.progress.message = "正在统计 PDF 页数"
        result_path = job.work_dir / "output" / "change_page_result.json"
        result = ChangePageExtractService(
            line_template=runtime.result_line_template,
        ).build_result(
            archive_name=job.source_filename or source_archive.name,
            extraction_root=extracted.root,
            output_path=result_path,
        )

        job.artifacts.change_page_result_json = result_path
        job.progress.details.update(
            {
                "archive_format": extracted.archive_format.value,
                "pdf_count": result.pdf_count,
                "total_pages": result.total_pages,
                "ignored_file_count": result.ignored_file_count,
            }
        )
        job.progress.stage = "CHANGE_PAGE_COMPLETE"
        job.progress.message = "页码提取完成"
        job.mark_succeeded()
