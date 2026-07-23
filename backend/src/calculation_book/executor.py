from __future__ import annotations

import json
from pathlib import Path

from src.config import get_config, load_mechanism_spec
from src.models import Job

from .archive import ArchiveLimits
from .models import CalculationBookParams
from .ocr import recognize_sm
from .processor import (
    CalculationBookAssets,
    CalculationBookMechanism,
    CalculationBookProcessor,
    CalculationBookStage,
)


class CalculationBookJobExecutor:
    """Adapt the pure calculation-book processor to the persisted Job lifecycle."""

    def execute(self, job: Job) -> None:
        config = get_config()
        mechanism_spec = load_mechanism_spec().calculation_book
        if not job.input_files:
            raise FileNotFoundError("计算书任务缺少上传的 ZIP")
        work_dir = job.work_dir or config.get_job_dir(job.job_id)
        work_dir.mkdir(parents=True, exist_ok=True)
        job.work_dir = work_dir
        params = CalculationBookParams.model_validate(job.params)
        runtime = config.calculation_book

        processor = CalculationBookProcessor(
            assets=CalculationBookAssets(
                template_root=runtime.template_dir,
                rebar_table=runtime.rebar_table,
            ),
            mechanism=CalculationBookMechanism(
                archive_limits=ArchiveLimits(
                    max_files=runtime.max_archive_files,
                    max_total_bytes=runtime.max_archive_mb * 1024 * 1024,
                    max_single_file_bytes=runtime.max_single_file_mb * 1024 * 1024,
                    max_compression_ratio=runtime.max_compression_ratio,
                ),
                row_counts=tuple(mechanism_spec.row_counts),
                spacings=tuple(mechanism_spec.spacings),
                max_diameter=mechanism_spec.max_diameter,
                extra_ratio=mechanism_spec.extra_ratio,
                chapter=mechanism_spec.chapter,
            ),
            ocr_recognizer=lambda path: recognize_sm(
                path,
                tesseract_exe=runtime.tesseract_exe,
                tessdata_dir=runtime.tessdata_dir,
                threshold=mechanism_spec.ocr_threshold,
            ),
        )

        job.mark_running(stage=CalculationBookStage.VALIDATE_ARCHIVE.value)
        self._persist(job)

        def update_progress(
            stage: CalculationBookStage,
            percent: int,
            message: str,
            details: dict[str, object],
        ) -> None:
            job.progress.stage = stage.value
            job.progress.percent = percent
            job.progress.message = message
            job.progress.details.update(details)
            self._persist(job)

        try:
            result = processor.process(
                archive_path=Path(job.input_files[0]),
                output_dir=work_dir / "calculation-book",
                params=params,
                progress=update_progress,
            )
            job.artifacts.calculation_docx = result.output_path
            job.progress.details.update(
                {
                    "figure_count": result.figure_count,
                    "template_type": result.template_type,
                    "output_filename": result.output_path.name,
                    "rebar_selections": [
                        {
                            "specification": selection.specification,
                            "target_area": selection.target_area,
                            "actual_area": selection.actual_area,
                            "margin_percent": round(selection.margin_percent, 1),
                        }
                        for selection in result.selections
                    ],
                }
            )
            job.mark_succeeded()
            self._persist(job)
        except Exception as exc:
            job.mark_failed(str(exc))
            self._persist(job)
            raise

    @staticmethod
    def _persist(job: Job) -> None:
        if job.work_dir is None:
            return
        target = job.work_dir / "job.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                job.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        temporary.replace(target)
