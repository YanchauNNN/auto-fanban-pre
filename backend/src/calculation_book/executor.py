from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from src.ai.chat_client import build_chat_client
from src.ai.rebar_suggestion_task import (
    RebarSuggestionTaskLimits,
    build_rebar_suggestion_task,
)
from src.ai.reinforcement_task_normalizer import (
    ReinforcementTaskNormalizationError,
    ReinforcementTaskNormalizer,
    ReinforcementTaskNormalizerLimits,
)
from src.config import get_config, load_ai_spec, load_mechanism_spec
from src.models import Job

from .archive import ArchiveLimits
from .diagnostic_log import CalculationBookDiagnosticLog, DiagnosticLogError
from .models import CalculationBookParams, ReinforcementSource
from .ocr import recognize_stress_legend
from .processor import (
    CalculationBookAssets,
    CalculationBookMechanism,
    CalculationBookProcessor,
    CalculationBookStage,
)
from .rebar_recommender import (
    RebarSuggestionInput,
    RebarSuggestionInvoker,
    RebarSuggestionResult,
    recommend_rebar_suggestions,
)

_SKILL_ID = "reinforcement_table_normalizer"
_REBAR_SUGGESTION_SKILL_ID = "recommend-rebar-from-smx"
_AI_DETAIL_KEY = "ai_reinforcement_normalization"
_CELL_ADDRESS_PATTERN = re.compile(r"^[A-Za-z]+[1-9]\d*$")
_WARNING_CODE_ALIASES = {
    "duplicate_wall_id": "duplicate_reinforcement_rows",
}
_WARNING_CODES = {
    "needs_review",
    "duplicate_reinforcement_rows",
    "split_image_group",
    "image_only_wall",
    "workbook_only_wall",
    "image_only_slab",
    "workbook_only_slab",
    "NO_ELIGIBLE_CANDIDATE",
    "AI_NEEDS_REVIEW",
    "AI_BASE_FAILURE_LIMIT",
    "OCR_RECOGNITION_FAILED",
    "UNKNOWN_IMAGE_NAME",
}
_WALL_FIELDS = ("wall_id", "wall", "X", "Y", "Z")
_SLAB_FIELDS = (
    "elevation",
    "top_x",
    "top_y",
    "middle_x",
    "middle_y",
    "bottom_x",
    "bottom_y",
    "z",
)


def build_calculation_book_warning_reason(
    *,
    code: str,
    scope: str,
    identity: str | None,
    direction: str | None,
) -> str:
    """Build UI-safe copy without using model- or workbook-provided prose."""
    if code == "duplicate_reinforcement_rows":
        return "同一墙体存在重复配筋行，相关配筋字段已留空"
    if code == "split_image_group":
        return "墙体存在 -1/-2 应力图组，配筋对应关系需人工补充，相关配筋字段已留空"
    if code == "image_only_wall":
        return "应力图中存在该墙体，但配筋表没有对应数据，相关配筋字段已留空"
    if code == "workbook_only_wall":
        return "配筋表中存在该墙体，但应力图中没有对应图组，未生成对应图片段落"
    if code == "image_only_slab":
        return "应力图中存在该楼板标高，但配筋表没有对应数据，相关配筋字段已留空"
    if code == "workbook_only_slab":
        return "配筋表中存在该楼板标高，但应力图中没有对应图组，未生成对应图片段落"
    if code == "NO_ELIGIBLE_CANDIDATE":
        return "后端未生成满足配筋规则的候选，当前方向已留空，请人工复核"
    if code == "AI_NEEDS_REVIEW":
        return "人工智能未能形成确定配筋建议，当前方向已留空，请人工复核"
    if code == "AI_BASE_FAILURE_LIMIT":
        return "人工智能连续三次调用或协议失败，当前方向已留空，请人工复核"
    if code == "OCR_RECOGNITION_FAILED":
        return "应力云图 SMX 识别失败，当前方向配筋建议已留空，请人工复核"
    if code == "UNKNOWN_IMAGE_NAME":
        return "云图文件名无法确定墙体或楼板对应关系，未生成该图片的配筋建议"
    subject = "墙体" if scope == "wall" else "楼板" if scope == "slab" else "配筋"
    identity_text = f" {identity}" if identity else ""
    direction_text = f"的 {direction} 向" if direction else "的部分"
    return f"{subject}{identity_text} {direction_text}配筋信息无法确定，相关字段已留空"


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
RebarSuggestionFactory = Callable[[Any], RebarSuggestionInvoker]


class RebarSuggestionUnavailable(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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


def build_rebar_suggestion_invoker(config: Any) -> RebarSuggestionInvoker:
    """Build exactly one structured-model Skill capability for an AI job."""

    settings = config.calculation_book.ai_suggestion
    if not settings.enabled:
        raise RebarSuggestionUnavailable(
            "ai_suggestion_disabled",
            "AI rebar suggestion is disabled by runtime configuration",
        )
    spec = load_ai_spec(config.ai_spec_path)
    return build_rebar_suggestion_task(
        spec,
        skill_root=settings.skill_root,
        skill_version=settings.skill_version,
        request_timeout_seconds=settings.request_timeout_seconds,
        max_output_tokens=settings.max_output_tokens,
        limits=RebarSuggestionTaskLimits(
            max_skill_bytes=settings.max_skill_bytes,
            max_reference_files=settings.max_reference_files,
            max_request_bytes=settings.max_request_bytes,
            max_response_bytes=settings.max_response_bytes,
            max_response_tokens=settings.max_output_tokens,
            max_identifier_chars=settings.max_identifier_chars,
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
        rebar_suggestion_invoker: RebarSuggestionInvoker | None = None,
        rebar_suggestion_factory: RebarSuggestionFactory | None = None,
    ) -> None:
        if normalizer is not None and normalizer_factory is not None:
            raise ValueError("normalizer and normalizer_factory are mutually exclusive")
        if (
            rebar_suggestion_invoker is not None
            and rebar_suggestion_factory is not None
        ):
            raise ValueError(
                "rebar_suggestion_invoker and rebar_suggestion_factory "
                "are mutually exclusive"
            )
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
        self._rebar_suggestion_invoker = rebar_suggestion_invoker
        self._rebar_suggestion_factory = (
            rebar_suggestion_factory or build_rebar_suggestion_invoker
        )

    def execute(self, job: Job) -> None:
        config = get_config()
        if not job.input_files:
            raise FileNotFoundError("计算书任务缺少上传的 ZIP/RAR")
        started_at = time.perf_counter()
        archive_path = Path(job.input_files[0])
        work_dir = job.work_dir or config.get_job_dir(job.job_id)
        work_dir.mkdir(parents=True, exist_ok=True)
        job.work_dir = work_dir
        params = CalculationBookParams.model_validate(job.params)
        runtime = config.calculation_book
        ai_suggestion_mode = (
            params.reinforcement_source is ReinforcementSource.AI_SUGGESTED
        )
        try:
            self._validate_server_mode(
                job=job,
                ai_suggestion_mode=ai_suggestion_mode,
            )
        except RebarSuggestionUnavailable as exc:
            job.mark_failed(str(exc))
            self._persist(job)
            raise
        diagnostic_log: CalculationBookDiagnosticLog | None = None
        if ai_suggestion_mode:
            diagnostic_log = self._create_diagnostic_log(
                job=job,
                work_dir=work_dir,
                max_bytes=runtime.ai_suggestion.log_max_bytes,
            )
            try:
                diagnostic_log.write(
                    "task_started",
                    archive_sha256=self._file_sha256(archive_path),
                    archive_size_bytes=archive_path.stat().st_size,
                    source_filename=(job.source_filename or archive_path.name),
                    params={
                        "reinforcement_source": params.reinforcement_source.value,
                        "include_slab_stress": params.include_slab_stress,
                        "template_type": params.template_type.value,
                    },
                    stage=CalculationBookStage.VALIDATE_ARCHIVE.value,
                )
            except Exception:
                with suppress(Exception):
                    diagnostic_log.close()
                job.artifacts.calculation_log = None
                failure = RebarSuggestionUnavailable(
                    "diagnostic_log_unavailable",
                    "AI rebar suggestion diagnostic log is unavailable",
                )
                job.mark_failed(str(failure))
                self._persist(job)
                raise failure from None

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
            job.mark_running(stage=CalculationBookStage.VALIDATE_ARCHIVE.value)
            self._persist(job)
            requires_ai = (
                job.options.get("ai_reinforcement_normalization") is True
            )
            reinforcement_normalizer = None
            if requires_ai:
                reinforcement_normalizer = self._normalization_callback(
                    job=job,
                    config=config,
                    update_progress=update_progress,
                )
            mechanism_spec = load_mechanism_spec().calculation_book
            processor = self._processor or self._build_processor(
                runtime=runtime,
                mechanism_spec=mechanism_spec,
            )
            audit = (
                self._diagnostic_audit_callback(
                    diagnostic_log=diagnostic_log,
                    job=job,
                    update_progress=update_progress,
                )
                if diagnostic_log is not None
                else None
            )
            rebar_suggestion_metadata: dict[str, str] = {}
            rebar_suggester = (
                self._rebar_suggestion_callback(
                    job=job,
                    config=config,
                    audit=audit,
                    metadata=rebar_suggestion_metadata,
                )
                if ai_suggestion_mode
                else None
            )
            result = processor.process(
                archive_path=archive_path,
                output_dir=work_dir / "calculation-book",
                params=params,
                progress=update_progress,
                reinforcement_normalizer=reinforcement_normalizer,
                rebar_suggester=rebar_suggester,
                audit=audit,
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
            job.progress.details["calculation_book_warnings"] = (
                self._safe_warnings(warnings)
            )
            ai_result = getattr(result, "ai_rebar_suggestion", None)
            if ai_suggestion_mode:
                if not isinstance(ai_result, RebarSuggestionResult):
                    raise RebarSuggestionUnavailable(
                        "ai_suggestion_result_missing",
                        "AI rebar suggestion result is unavailable",
                    )
                job.progress.details["ai_rebar_suggestion"] = (
                    self._safe_rebar_suggestion_summary(
                        ai_result,
                        suggested_direction_count=(
                            result.ai_suggested_direction_count
                        ),
                        blank_direction_count=result.ai_blank_direction_count,
                        warning_count=len(
                            job.progress.details["calculation_book_warnings"]
                        ),
                        fallback_metadata=rebar_suggestion_metadata,
                    )
                )
            if diagnostic_log is not None:
                diagnostic_log.write(
                    "task_completed",
                    duration_ms=self._duration_ms(started_at),
                    figure_count=result.figure_count,
                    warning_count=len(job.progress.details["calculation_book_warnings"]),
                    output_filename=result.output_path.name,
                )
                diagnostic_log.close()
            job.mark_succeeded()
            self._persist(job)
        except Exception as exc:
            failure: Exception = exc
            if diagnostic_log is not None and not diagnostic_log.closed:
                terminal_log_failed = False
                try:
                    diagnostic_log.write(
                        "task_failed",
                        stage=job.progress.stage,
                        duration_ms=self._duration_ms(started_at),
                        error_code=self._error_code(exc),
                    )
                except Exception:
                    terminal_log_failed = True
                try:
                    diagnostic_log.close()
                except Exception:
                    terminal_log_failed = True
                if terminal_log_failed:
                    failure = RebarSuggestionUnavailable(
                        "diagnostic_log_unavailable",
                        "AI rebar suggestion diagnostic log is unavailable",
                    )
                    job.artifacts.calculation_log = None
            elif (
                diagnostic_log is not None
                and isinstance(exc, DiagnosticLogError)
            ):
                failure = RebarSuggestionUnavailable(
                    "diagnostic_log_unavailable",
                    "AI rebar suggestion diagnostic log is unavailable",
                )
                job.artifacts.calculation_log = None
            job.mark_failed(str(failure))
            self._persist(job)
            if failure is exc:
                raise
            raise failure from None

    @staticmethod
    def _validate_server_mode(*, job: Job, ai_suggestion_mode: bool) -> None:
        option_source = str(job.options.get("reinforcement_source") or "provided")
        option_enabled = job.options.get("ai_rebar_suggestion") is True
        if ai_suggestion_mode:
            if option_source != "ai_suggested" or not option_enabled:
                raise RebarSuggestionUnavailable(
                    "reinforcement_source_mismatch",
                    "AI rebar suggestion source does not match server task options",
                )
        elif option_source == "ai_suggested" or option_enabled:
            raise RebarSuggestionUnavailable(
                "reinforcement_source_mismatch",
                "provided reinforcement source does not match server task options",
            )

    @staticmethod
    def _create_diagnostic_log(
        *,
        job: Job,
        work_dir: Path,
        max_bytes: int,
    ) -> CalculationBookDiagnosticLog:
        try:
            diagnostic_log = CalculationBookDiagnosticLog.create_for_job(
                work_dir=work_dir,
                job_id=job.job_id,
                correlation_id=job.job_id,
                max_bytes=max_bytes,
            )
        except Exception:
            failure = RebarSuggestionUnavailable(
                "diagnostic_log_unavailable",
                "AI rebar suggestion diagnostic log is unavailable",
            )
            job.mark_failed(str(failure))
            CalculationBookJobExecutor._persist(job)
            raise failure from None
        job.artifacts.calculation_log = diagnostic_log.path
        return diagnostic_log

    def _rebar_suggestion_callback(
        self,
        *,
        job: Job,
        config: Any,
        audit: Callable[[str, dict[str, object]], None] | None,
        metadata: dict[str, str],
    ) -> Callable[[tuple[RebarSuggestionInput, ...]], RebarSuggestionResult]:
        try:
            invoker = self._rebar_suggestion_invoker or (
                self._rebar_suggestion_factory(config)
            )
        except RebarSuggestionUnavailable:
            raise
        except Exception:
            raise RebarSuggestionUnavailable(
                "ai_suggestion_initialization_failed",
                "AI rebar suggestion capability could not be initialized",
            ) from None
        settings = config.calculation_book.ai_suggestion
        metadata.update(
            {
                "skill_id": _REBAR_SUGGESTION_SKILL_ID,
                "skill_version": str(settings.skill_version)[:160],
                "model": str(getattr(invoker, "model", "") or "")[:160],
            }
        )

        def suggest(
            items: tuple[RebarSuggestionInput, ...],
        ) -> RebarSuggestionResult:
            return recommend_rebar_suggestions(
                task_id=job.job_id,
                correlation_id=job.job_id,
                items=items,
                invoker=invoker,
                batch_size=settings.batch_size,
                max_consecutive_base_failures=(
                    settings.max_consecutive_base_failures
                ),
                audit=audit,
            )

        return suggest

    @staticmethod
    def _diagnostic_audit_callback(
        *,
        diagnostic_log: CalculationBookDiagnosticLog,
        job: Job,
        update_progress: Callable[
            [CalculationBookStage, int, str, dict[str, object]], None
        ],
    ) -> Callable[[str, dict[str, object]], None]:
        highest_repair_round = 0

        def audit(event: str, details: dict[str, object]) -> None:
            nonlocal highest_repair_round
            diagnostic_log.write(event, **details)
            if event != "repair_scheduled":
                return
            raw_round = details.get("next_round")
            if (
                isinstance(raw_round, bool)
                or not isinstance(raw_round, int)
                or raw_round <= highest_repair_round
            ):
                return
            highest_repair_round = raw_round
            update_progress(
                CalculationBookStage.AI_REBAR_SUGGESTION,
                max(30, min(job.progress.percent, 75)),
                f"AI 配筋建议第 {raw_round} 轮修正",
                {"ai_rebar_suggestion_round": raw_round},
            )

        return audit

    @staticmethod
    def _safe_rebar_suggestion_summary(
        result: RebarSuggestionResult,
        *,
        suggested_direction_count: int,
        blank_direction_count: int,
        warning_count: int,
        fallback_metadata: dict[str, str],
    ) -> dict[str, object]:
        if (
            isinstance(suggested_direction_count, bool)
            or not isinstance(suggested_direction_count, int)
            or suggested_direction_count < 0
            or isinstance(blank_direction_count, bool)
            or not isinstance(blank_direction_count, int)
            or blank_direction_count < 0
            or isinstance(warning_count, bool)
            or not isinstance(warning_count, int)
            or warning_count < 0
        ):
            raise RebarSuggestionUnavailable(
                "ai_suggestion_count_invalid",
                "AI rebar suggestion direction counts are invalid",
            )
        return {
            "skill_id": str(
                result.skill_id or fallback_metadata.get("skill_id", "")
            )[:160],
            "skill_version": str(
                result.skill_version
                or fallback_metadata.get("skill_version", "")
            )[:160],
            "skill_sha256": str(result.skill_sha256 or "")[:160],
            "model": str(
                result.model or fallback_metadata.get("model", "")
            )[:160],
            "call_count": max(0, int(result.call_count)),
            "suggested_direction_count": suggested_direction_count,
            "blank_direction_count": blank_direction_count,
            "repair_round_count": max(0, int(result.repair_round_count)),
            "validation": (
                "passed_with_warnings" if warning_count else "passed"
            ),
        }

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().upper()

    @staticmethod
    def _duration_ms(started_at: float) -> int:
        return max(0, min(round((time.perf_counter() - started_at) * 1000), 31_536_000_000))

    @staticmethod
    def _error_code(exc: Exception) -> str:
        value = str(getattr(exc, "code", "") or exc.__class__.__name__)
        if re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value) is None:
            return exc.__class__.__name__[:100]
        return value

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
            validated = None
            safe_failure: Exception | None = None
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
                    safe_failure = ReinforcementTaskNormalizationError(
                        exc.code,
                        "AI reinforcement normalization failed",
                    )
                else:
                    safe_failure = ReinforcementNormalizationUnavailable(
                        exc.code,
                        "AI reinforcement normalization is unavailable",
                    )
            except Exception:
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
                safe_failure = ReinforcementNormalizationUnavailable(
                    "normalizer_initialization_failed",
                    "AI reinforcement normalizer initialization failed",
                )

            if safe_failure is not None:
                raise safe_failure
            assert validated is not None

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

    @classmethod
    def _safe_warnings(cls, warnings: Any) -> list[dict[str, object]]:
        canonical: dict[tuple[object, ...], tuple[int, dict[str, object]]] = {}
        for warning in warnings:
            raw_code = str(getattr(warning, "code", "needs_review"))
            safe_warning = cls._safe_warning(warning)
            code = str(safe_warning["code"])
            if code == "duplicate_reinforcement_rows":
                key: tuple[object, ...] = (
                    code,
                    safe_warning["scope"],
                    safe_warning["identity"],
                    tuple(safe_warning["blank_fields"]),
                )
                priority = 1 if raw_code == "duplicate_reinforcement_rows" else 0
            else:
                key = (
                    code,
                    safe_warning["scope"],
                    safe_warning["identity"],
                    safe_warning["direction"],
                    safe_warning["source_sheet"],
                    safe_warning["source_row"],
                    tuple(safe_warning["blank_fields"]),
                )
                priority = 0
            previous = canonical.get(key)
            if previous is None or priority > previous[0]:
                canonical[key] = (priority, safe_warning)
        return [warning for _, warning in canonical.values()]

    @staticmethod
    def _safe_warning(warning: Any) -> dict[str, object]:
        raw_scope = str(getattr(warning, "scope", ""))
        scope = raw_scope if raw_scope in {"wall", "slab"} else "reinforcement"
        allowed_fields = _WALL_FIELDS if scope == "wall" else _SLAB_FIELDS
        raw_blank_fields = getattr(warning, "blank_fields", ())
        blank_fields = [
            str(field)
            for field in raw_blank_fields
            if str(field) in allowed_fields
        ]
        raw_code = str(getattr(warning, "code", "needs_review"))
        code = _WARNING_CODE_ALIASES.get(raw_code, raw_code)
        if code not in _WARNING_CODES:
            code = "needs_review"
        if code == "duplicate_reinforcement_rows" and scope == "wall":
            blank_fields = ["X", "Y", "Z"]

        raw_identity = getattr(warning, "identity", None)
        identity = (
            str(raw_identity).strip()[:100]
            if raw_identity is not None and str(raw_identity).strip()
            else None
        )
        raw_direction = getattr(warning, "direction", None)
        allowed_directions = set(allowed_fields) | {"X", "Y", "Z"}
        direction = (
            str(raw_direction)
            if raw_direction is not None
            and str(raw_direction) in allowed_directions
            else None
        )
        raw_sheet = str(getattr(warning, "source_sheet", "") or "").strip()
        raw_row = getattr(warning, "source_row", None)
        has_excel_evidence = (
            bool(raw_sheet)
            and isinstance(raw_row, int)
            and not isinstance(raw_row, bool)
            and raw_row > 0
        )
        raw_source_cells = getattr(warning, "source_cells", {})
        source_cells = {
            str(field): str(address).upper()
            for field, address in (
                raw_source_cells.items()
                if isinstance(raw_source_cells, dict)
                else ()
            )
            if has_excel_evidence
            and str(field) in allowed_fields
            and _CELL_ADDRESS_PATTERN.fullmatch(str(address)) is not None
        }
        return {
            "code": code,
            "scope": scope,
            "identity": identity,
            "direction": direction,
            "source_sheet": raw_sheet if has_excel_evidence else None,
            "source_row": raw_row if has_excel_evidence else None,
            "source_cells": source_cells,
            "reason": build_calculation_book_warning_reason(
                code=code,
                scope=scope,
                identity=identity,
                direction=direction,
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
