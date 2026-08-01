from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from src.ai.chat_client import build_chat_client
from src.ai.reinforcement_task_normalizer import (
    ReinforcementTaskNormalizationError,
    ReinforcementTaskNormalizer,
    ReinforcementTaskNormalizerLimits,
)
from src.config import get_config, load_ai_spec, load_mechanism_spec
from src.models import Job

from .archive import ArchiveLimits
from .models import CalculationBookParams
from .ocr import recognize_stress_legend
from .processor import (
    CalculationBookAssets,
    CalculationBookMechanism,
    CalculationBookProcessor,
    CalculationBookStage,
)

_SKILL_ID = "reinforcement_table_normalizer"
_AI_DETAIL_KEY = "ai_reinforcement_normalization"
_CELL_ADDRESS_PATTERN = re.compile(r"^[A-Za-z]+[1-9]\d*$")


class ReinforcementNormalizerProtocol(Protocol):
    def normalize(
        self,
        workbook_path: Path,
        *,
        include_slab: bool,
        expected_source_row_count: int | None = None,
    ) -> Any: ...


@dataclass(frozen=True)
class ReinforcementNormalizerMetadata:
    model: str
    profile: str


@dataclass(frozen=True)
class BuiltReinforcementTaskNormalizer:
    normalizer: ReinforcementNormalizerProtocol
    metadata: ReinforcementNormalizerMetadata


class ReinforcementNormalizationUnavailable(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


NormalizerFactory = Callable[[Any], BuiltReinforcementTaskNormalizer]


def build_reinforcement_task_normalizer(
    config: Any,
) -> BuiltReinforcementTaskNormalizer:
    """Build the queued task's structured-model normalizer from runtime config."""

    settings = config.calculation_book.ai_normalization
    if not settings.enabled:
        raise ReinforcementNormalizationUnavailable(
            "ai_normalization_disabled",
            "AI reinforcement normalization is disabled by runtime configuration",
        )
    spec = load_ai_spec(config.ai_spec_path)
    client = build_chat_client(
        spec,
        model_kind="structured",
        timeout_seconds=settings.request_timeout_seconds,
        temperature=settings.temperature,
        max_output_tokens=settings.max_output_tokens,
        max_retries=settings.max_retries,
    )
    resolved_models = spec.resolve_models()
    profile = spec.resolve_gateway_profile_name() or "default"
    return BuiltReinforcementTaskNormalizer(
        normalizer=ReinforcementTaskNormalizer(
            client=client,
            skill_root=settings.skill_root,
            limits=ReinforcementTaskNormalizerLimits(
                max_non_empty_cells=settings.max_non_empty_cells,
                max_snapshot_chars=settings.max_snapshot_chars,
                max_skill_chars=settings.max_skill_chars,
            ),
        ),
        metadata=ReinforcementNormalizerMetadata(
            model=resolved_models.structured.model,
            profile=profile,
        ),
    )


class CalculationBookJobExecutor:
    """Adapt the pure calculation-book processor to the persisted Job lifecycle."""

    def __init__(
        self,
        *,
        processor: CalculationBookProcessor | None = None,
        normalizer: ReinforcementNormalizerProtocol | None = None,
        normalizer_metadata: ReinforcementNormalizerMetadata | None = None,
        normalizer_factory: NormalizerFactory | None = None,
    ) -> None:
        if normalizer is not None and normalizer_factory is not None:
            raise ValueError("normalizer and normalizer_factory are mutually exclusive")
        self._processor = processor
        self._normalizer = normalizer
        self._normalizer_metadata = normalizer_metadata or (
            ReinforcementNormalizerMetadata(
                model=("injected" if normalizer is not None else "not_initialized"),
                profile=("injected" if normalizer is not None else "not_initialized"),
            )
        )
        self._normalizer_factory = (
            normalizer_factory or build_reinforcement_task_normalizer
        )

    def execute(self, job: Job) -> None:
        config = get_config()
        mechanism_spec = load_mechanism_spec().calculation_book
        if not job.input_files:
            raise FileNotFoundError("计算书任务缺少上传的 ZIP/RAR")
        work_dir = job.work_dir or config.get_job_dir(job.job_id)
        work_dir.mkdir(parents=True, exist_ok=True)
        job.work_dir = work_dir
        params = CalculationBookParams.model_validate(job.params)
        runtime = config.calculation_book
        processor = self._processor or self._build_processor(
            runtime=runtime,
            mechanism_spec=mechanism_spec,
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

        requires_ai = job.options.get("ai_reinforcement_normalization") is True
        reinforcement_normalizer = None
        if requires_ai:
            reinforcement_normalizer = self._normalization_callback(
                job=job,
                config=config,
                update_progress=update_progress,
            )

        try:
            result = processor.process(
                archive_path=Path(job.input_files[0]),
                output_dir=work_dir / "calculation-book",
                params=params,
                progress=update_progress,
                reinforcement_normalizer=reinforcement_normalizer,
            )
            job.artifacts.calculation_docx = result.output_path
            job.progress.details.update(
                {
                    "figure_count": result.figure_count,
                    "template_type": result.template_type,
                    "output_filename": result.output_path.name,
                    "rebar_selections": [
                        {
                            "wall_id": selection.wall_id,
                            "direction": selection.direction,
                            "specification": selection.specification,
                            "actual_area": selection.actual_area,
                            "calculation_area": selection.calculation_area,
                            "margin_percent": (
                                round(selection.margin_percent, 1)
                                if selection.margin_percent is not None
                                else None
                            ),
                        }
                        for selection in result.selections
                    ],
                }
            )
            warnings = getattr(result, "normalization_warnings", ())
            if warnings:
                job.progress.details["reinforcement_normalization_warnings"] = [
                    self._safe_warning(warning) for warning in warnings
                ]
            job.mark_succeeded()
            self._persist(job)
        except Exception as exc:
            job.mark_failed(str(exc))
            self._persist(job)
            raise

    def _normalization_callback(
        self,
        *,
        job: Job,
        config: Any,
        update_progress: Callable[
            [CalculationBookStage, int, str, dict[str, object]], None
        ],
    ) -> Callable[[Path, bool], Any]:
        def normalize(workbook_path: Path, include_slab: bool) -> Any:
            started_at = time.perf_counter()
            metadata = self._normalizer_metadata
            update_progress(
                CalculationBookStage.AI_REINFORCEMENT_NORMALIZATION,
                20,
                "正在使用人工智能规范化非标准配筋表",
                {},
            )
            try:
                if self._normalizer is not None:
                    normalizer = self._normalizer
                else:
                    built = self._normalizer_factory(config)
                    normalizer = built.normalizer
                    metadata = built.metadata
                validated = normalizer.normalize(
                    workbook_path,
                    include_slab=include_slab,
                    expected_source_row_count=(
                        self._expected_source_row_count(job)
                    ),
                )
            except (
                ReinforcementTaskNormalizationError,
                ReinforcementNormalizationUnavailable,
            ) as exc:
                update_progress(
                    CalculationBookStage.AI_REINFORCEMENT_NORMALIZATION,
                    20,
                    "人工智能配筋表规范化失败",
                    {
                        _AI_DETAIL_KEY: {
                            "stage": CalculationBookStage.AI_REINFORCEMENT_NORMALIZATION.value,
                            "error_code": exc.code,
                            "model": metadata.model,
                            "profile": metadata.profile,
                        }
                    },
                )
                if isinstance(exc, ReinforcementTaskNormalizationError):
                    raise ReinforcementTaskNormalizationError(
                        exc.code,
                        "AI reinforcement normalization failed",
                    ) from exc
                raise ReinforcementNormalizationUnavailable(
                    exc.code,
                    "AI reinforcement normalization is unavailable",
                ) from exc
            except Exception as exc:
                update_progress(
                    CalculationBookStage.AI_REINFORCEMENT_NORMALIZATION,
                    20,
                    "人工智能配筋表规范化失败",
                    {
                        _AI_DETAIL_KEY: {
                            "stage": CalculationBookStage.AI_REINFORCEMENT_NORMALIZATION.value,
                            "error_code": "normalizer_initialization_failed",
                            "model": metadata.model,
                            "profile": metadata.profile,
                        }
                    },
                )
                raise ReinforcementNormalizationUnavailable(
                    "normalizer_initialization_failed",
                    "AI reinforcement normalizer initialization failed",
                ) from exc

            audit = {
                "skill_id": _SKILL_ID,
                "model": metadata.model,
                "profile": metadata.profile,
                "call_count": 1,
                "source_row_count": validated.source_row_count,
                "normalized_wall_count": len(validated.wall_schedule.rows),
                "normalized_slab_count": (
                    len(validated.slab_schedule.rows)
                    if validated.slab_schedule is not None
                    else 0
                ),
                "review_warning_count": len(validated.warnings),
                "duration_ms": max(
                    0,
                    round((time.perf_counter() - started_at) * 1000),
                ),
                "validation": "passed",
            }
            update_progress(
                CalculationBookStage.AI_REINFORCEMENT_NORMALIZATION,
                25,
                "非标准配筋表规范化完成",
                {_AI_DETAIL_KEY: audit},
            )
            return validated

        return normalize

    @staticmethod
    def _expected_source_row_count(job: Job) -> int | None:
        value = job.options.get("ai_reinforcement_expected_source_row_count")
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return None
        return value

    @staticmethod
    def _safe_warning(warning: Any) -> dict[str, object]:
        blank_fields = [str(field) for field in warning.blank_fields]
        scope = warning.scope if warning.scope in {"wall", "slab"} else "reinforcement"
        source_cells = {
            str(field): str(address).upper()
            for field, address in warning.source_cells.items()
            if _CELL_ADDRESS_PATTERN.fullmatch(str(address)) is not None
        }
        return {
            "code": warning.code,
            "scope": scope,
            "identity": warning.identity,
            "direction": warning.direction,
            "source_sheet": warning.source_sheet,
            "source_row": warning.source_row,
            "source_cells": source_cells,
            "reason": (
                f"{scope} row needs review for fields: "
                + ", ".join(blank_fields)
            ),
            "blank_fields": blank_fields,
        }

    @staticmethod
    def _build_processor(*, runtime: Any, mechanism_spec: Any) -> CalculationBookProcessor:
        return CalculationBookProcessor(
            assets=CalculationBookAssets(
                template_root=runtime.template_dir,
            ),
            mechanism=CalculationBookMechanism(
                archive_limits=ArchiveLimits(
                    max_files=runtime.max_archive_files,
                    max_total_bytes=runtime.max_archive_mb * 1024 * 1024,
                    max_single_file_bytes=runtime.max_single_file_mb * 1024 * 1024,
                    max_compression_ratio=runtime.max_compression_ratio,
                ),
                chapter=mechanism_spec.chapter,
            ),
            ocr_recognizer=lambda path, direction: recognize_stress_legend(
                path,
                direction=direction,
                tesseract_exe=runtime.tesseract_exe,
                tessdata_dir=runtime.tessdata_dir,
                threshold=mechanism_spec.ocr_threshold,
                expected_count=mechanism_spec.ocr_legend_value_count,
                min_confidence=mechanism_spec.ocr_min_confidence,
                min_vertical_ratio=mechanism_spec.ocr_min_vertical_ratio,
                endpoint_absolute_tolerance=(
                    mechanism_spec.ocr_endpoint_absolute_tolerance
                ),
                endpoint_relative_tolerance=(
                    mechanism_spec.ocr_endpoint_relative_tolerance
                ),
                header_crop=tuple(mechanism_spec.ocr_header_crop),
                legend_crop=tuple(mechanism_spec.ocr_legend_crop),
                header_scale=mechanism_spec.ocr_header_scale,
                legend_scale=mechanism_spec.ocr_legend_scale,
            ),
        )

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
