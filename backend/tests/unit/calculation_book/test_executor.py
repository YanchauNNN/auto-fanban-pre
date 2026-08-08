from __future__ import annotations

import json
import traceback
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.ai.rebar_suggestion_task import (
    RebarSuggestionSkillMetadata,
    RebarSuggestionTaskError,
    RebarSuggestionTaskResult,
)
from src.ai.reinforcement_task_normalizer import (
    ReinforcementTaskNormalizationError,
)
from src.calculation_book.ai_rebar_suggestion_schema import (
    PROTOCOL_VERSION,
    AiRebarSuggestionResponse,
)
from src.calculation_book.diagnostic_log import (
    CalculationBookDiagnosticLog,
    DiagnosticLogError,
)
from src.calculation_book.executor import (
    CalculationBookJobExecutor,
    RebarSuggestionUnavailable,
    ReinforcementNormalizationUnavailable,
    ReinforcementNormalizerMetadata,
    build_rebar_suggestion_invoker,
    build_reinforcement_task_normalizer,
)
from src.calculation_book.processor import CalculationBookStage
from src.calculation_book.rebar_candidates import generate_rebar_candidates
from src.calculation_book.rebar_recommender import RebarSuggestionInput
from src.config import get_config, load_mechanism_spec
from src.models import Job, JobStatus, JobType


@pytest.fixture(autouse=True)
def _isolate_ai_diagnostic_log_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = get_config().model_copy(deep=True)
    config.calculation_book.ai_suggestion.log_dir = tmp_path / "central-ai-audit"
    monkeypatch.setattr("src.calculation_book.executor.get_config", lambda: config)


def _params() -> dict[str, object]:
    return {
        "template_type": "internal_structure",
        "project_no": "JQ",
        "project_name": "test project",
        "internal_code": "JQ00-NN-001",
        "version": "A",
        "subproject_code": "RX",
        "subproject_name": "internal structure",
        "design_phase": "construction",
        "document_name": "0.000m~15.000m calculation book",
        "workshop_length": 72.5,
        "workshop_width": 48.0,
        "raft_slab_top_elevation": -8.5,
        "roof_top_elevation": 31.2,
        "factory_extreme_min_temperature": -18.0,
        "factory_extreme_max_temperature": 39.0,
        "site_soil_temperature": 15.0,
        "include_slab_stress": True,
    }


def _job(tmp_path: Path, *, options: dict[str, object]) -> Job:
    archive = tmp_path / "input.zip"
    archive.write_bytes(b"archive")
    return Job(
        job_id="calc-job",
        job_type=JobType.CALCULATION_BOOK,
        project_no="JQ",
        input_files=[archive],
        options=options,
        params=_params(),
        work_dir=tmp_path / "job",
    )


class FakeNormalizer:
    def __init__(
        self,
        *,
        failure: Exception | None = None,
        warnings: tuple[object, ...] | None = None,
    ) -> None:
        self.calls: list[tuple[Path, bool, int | None]] = []
        self.failure = failure
        self.warnings = warnings

    def normalize(
        self,
        workbook_path: Path,
        *,
        include_slab: bool,
        expected_source_row_count: int | None = None,
    ):
        self.calls.append(
            (workbook_path, include_slab, expected_source_row_count)
        )
        if self.failure is not None:
            raise self.failure
        default_warnings = (
            SimpleNamespace(
                code="needs_review",
                scope="wall",
                identity="N5001",
                direction="X",
                source_sheet="Sheet1",
                source_row=7,
                source_cells={"X": "B7"},
                original_values={"X": "secret cell value"},
                resolved_values={},
                reason="ambiguous secret rationale",
                blank_fields=("X",),
            ),
        )
        return SimpleNamespace(
            wall_schedule=SimpleNamespace(rows=(object(), object())),
            slab_schedule=SimpleNamespace(rows=(object(),)),
            warnings=(self.warnings if self.warnings is not None else default_warnings),
            source_row_count=3,
        )


class FakeProcessor:
    def __init__(self) -> None:
        self.callbacks: list[object] = []
        self.stages: list[CalculationBookStage] = []

    def process(
        self,
        *,
        output_dir: Path,
        params,
        progress,
        reinforcement_normalizer,
        rebar_suggester=None,
        audit=None,
        **_kwargs,
    ):
        self.callbacks.append(reinforcement_normalizer)
        progress(CalculationBookStage.VALIDATE_ARCHIVE, 10, "validated", {})
        validated = None
        if reinforcement_normalizer is not None:
            validated = reinforcement_normalizer(
                output_dir / "extracted" / "rebar.xlsx",
                params.include_slab_stress,
            )
        progress(CalculationBookStage.OCR_REINFORCEMENT, 30, "ocr", {})
        self.stages.extend(
            (
                CalculationBookStage.VALIDATE_ARCHIVE,
                CalculationBookStage.OCR_REINFORCEMENT,
            )
        )
        suggestion = None
        suggestion_warnings: tuple[object, ...] = ()
        if rebar_suggester is not None:
            candidates = generate_rebar_candidates(smx=1000, direction="X")
            suggestion = rebar_suggester(
                (
                    RebarSuggestionInput(
                        item_id="wall:N5001:X",
                        member_kind="wall",
                        member_id="N5001",
                        direction="X",
                        smx=1000,
                        target_area=1100,
                        candidates=candidates,
                    ),
                )
            )
            suggestion_warnings = tuple(
                SimpleNamespace(
                    code=warning.code,
                    scope=warning.member_kind,
                    identity=warning.member_id,
                    direction=warning.direction,
                    source_sheet=None,
                    source_row=None,
                    source_cells={},
                    reason=warning.message,
                    blank_fields=(warning.direction,),
                )
                for warning in suggestion.warnings
            )
            if audit is not None and suggestion.selected:
                selected = suggestion.selected[0]
                audit(
                    "word_entry_written",
                    {
                        "member_kind": "wall",
                        "member_id": "N5001",
                        "direction": "X",
                        "spec": selected.candidate.canonical_specification,
                        "actual_area": selected.candidate.actual_area,
                        "smx": 1000,
                        "image_name": "N5001-X.png",
                    },
                )
        output = output_dir / "result.docx"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"docx")
        return SimpleNamespace(
            output_path=output,
            figure_count=3,
            template_type="internal_structure",
            selections=(),
            normalization_warnings=(
                validated.warnings if validated is not None else suggestion_warnings
            ),
            ai_rebar_suggestion=suggestion,
            ai_suggested_direction_count=(
                len(suggestion.selected) if suggestion is not None else 0
            ),
            ai_blank_direction_count=(
                len(suggestion.warnings) if suggestion is not None else 0
            ),
        )


class FakeRebarInvoker:
    def __init__(self, *, invalid_first: bool = False) -> None:
        self.calls = 0
        self.invalid_first = invalid_first

    def suggest(self, request, *, correlation_id: str) -> RebarSuggestionTaskResult:
        self.calls += 1
        item = request.items[0]
        candidate = (
            item.candidates[-1]
            if self.invalid_first and self.calls == 1
            else item.candidates[0]
        )
        response = AiRebarSuggestionResponse.model_validate(
            {
                "schema_version": PROTOCOL_VERSION,
                "items": [
                    {
                        "item_id": item.item_id,
                        "status": "selected",
                        "selected_candidate_id": candidate.candidate_id,
                        "reason": "minimum excess in the first eligible priority",
                        "review_reasons": [],
                    }
                ],
            }
        )
        return RebarSuggestionTaskResult(
            response=response,
            correlation_id=correlation_id,
            task_id=request.task_id,
            skill_id="recommend-rebar-from-smx",
            skill_version="1.0.0",
            skill_sha256="a" * 64,
            model="structured-test",
        )


class AlwaysFailRebarInvoker:
    model = "failed-model"

    def __init__(self) -> None:
        self.calls = 0

    def suggest(self, request, *, correlation_id: str) -> RebarSuggestionTaskResult:
        del request, correlation_id
        self.calls += 1
        raise RebarSuggestionTaskError(
            "infrastructure",
            "model_timeout",
            "sanitized timeout",
        )

    def skill_metadata(self) -> RebarSuggestionSkillMetadata:
        return RebarSuggestionSkillMetadata(
            skill_id="recommend-rebar-from-smx",
            skill_version="1.0.0",
            skill_sha256="b" * 64,
            model=self.model,
        )


def _executor(processor: FakeProcessor, normalizer: FakeNormalizer):
    return CalculationBookJobExecutor(
        processor=processor,
        normalizer=normalizer,
        normalizer_metadata=ReinforcementNormalizerMetadata(
            model="structured-test",
            profile="intranet-test",
        ),
    )


def test_executor_builds_processor_with_runtime_archive_extractor() -> None:
    import src.calculation_book.executor as executor_module

    runtime = executor_module.get_config().calculation_book
    processor = CalculationBookJobExecutor._build_processor(
        runtime=runtime,
        mechanism_spec=load_mechanism_spec().calculation_book,
    )

    assert processor.archive_extractor is runtime.archive_extractor


def test_executor_missing_input_uses_archive_neutral_copy(tmp_path: Path) -> None:
    job = _job(tmp_path, options={})
    job.input_files = []

    with pytest.raises(FileNotFoundError, match="上传的压缩包"):
        CalculationBookJobExecutor(processor=FakeProcessor()).execute(job)


def test_ai_job_normalizes_once_before_ocr_and_persists_only_safe_audit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    processor = FakeProcessor()
    normalizer = FakeNormalizer()
    job = _job(
        tmp_path,
        options={
            "ai_reinforcement_normalization": True,
            "ai_reinforcement_expected_source_row_count": 3,
        },
    )
    persisted_stages: list[str] = []
    original_persist = CalculationBookJobExecutor._persist

    def record_persist(current_job: Job) -> None:
        persisted_stages.append(current_job.progress.stage)
        original_persist(current_job)

    monkeypatch.setattr(
        CalculationBookJobExecutor,
        "_persist",
        staticmethod(record_persist),
    )

    _executor(processor, normalizer).execute(job)

    assert len(normalizer.calls) == 1
    assert normalizer.calls[0][1:] == (True, 3)
    assert job.status == JobStatus.SUCCEEDED
    audit = job.progress.details["ai_reinforcement_normalization"]
    assert audit == {
        "skill_id": "reinforcement_table_normalizer",
        "model": "structured-test",
        "profile": "intranet-test",
        "call_count": 1,
        "source_row_count": 3,
        "normalized_wall_count": 2,
        "normalized_slab_count": 1,
        "review_warning_count": 1,
        "duration_ms": pytest.approx(audit["duration_ms"], abs=1),
        "validation": "passed",
    }
    persisted = (job.work_dir / "job.json").read_text(encoding="utf-8")
    assert "secret cell value" not in persisted
    assert "prompt" not in persisted
    assert "api_key" not in persisted
    assert job.progress.details["calculation_book_warnings"] == [
        {
            "code": "needs_review",
            "scope": "wall",
            "identity": "N5001",
            "direction": "X",
            "source_sheet": "Sheet1",
            "source_row": 7,
            "source_cells": {"X": "B7"},
            "reason": "墙体 N5001 的 X 向配筋信息无法确定，相关字段已留空",
            "blank_fields": ["X"],
        }
    ]
    assert persisted_stages.index("AI_REINFORCEMENT_NORMALIZATION") < (
        persisted_stages.index("OCR_REINFORCEMENT")
    )


def test_executor_canonicalizes_duplicate_warnings_and_hides_missing_excel_evidence(
    tmp_path: Path,
) -> None:
    duplicate_alias = SimpleNamespace(
        code="duplicate_wall_id",
        scope="wall",
        identity="S7157",
        direction=None,
        source_sheet="Sheet1",
        source_row=28,
        source_cells={"wall": "A28", "X": "B28"},
        original_values={"X": "must-not-persist"},
        resolved_values={},
        reason="model-supplied secret reason",
        blank_fields=("X", "Y", "Z"),
    )
    preferred_duplicate = SimpleNamespace(
        code="duplicate_reinforcement_rows",
        scope="wall",
        identity="S7157",
        direction=None,
        source_sheet="Sheet1",
        source_row=28,
        source_cells={"wall": "A28", "X": "B28", "bad": "not-an-address"},
        original_values={"X": "another-secret"},
        resolved_values={},
        reason="another untrusted reason",
        blank_fields=("X", "Y", "Z"),
    )
    image_only = SimpleNamespace(
        code="image_only_wall",
        scope="wall",
        identity="N5012",
        direction=None,
        source_sheet="",
        source_row=0,
        source_cells={},
        original_values={},
        resolved_values={},
        reason="raw image-only reason",
        blank_fields=("X", "Y", "Z"),
    )
    job = _job(
        tmp_path,
        options={
            "ai_reinforcement_normalization": True,
            "ai_reinforcement_expected_source_row_count": 3,
        },
    )

    _executor(
        FakeProcessor(),
        FakeNormalizer(
            warnings=(duplicate_alias, preferred_duplicate, image_only)
        ),
    ).execute(job)

    assert job.progress.details["calculation_book_warnings"] == [
        {
            "code": "duplicate_reinforcement_rows",
            "scope": "wall",
            "identity": "S7157",
            "direction": None,
            "source_sheet": "Sheet1",
            "source_row": 28,
            "source_cells": {"wall": "A28", "X": "B28"},
            "reason": "同一墙体存在重复配筋行，相关配筋字段已留空",
            "blank_fields": ["X", "Y", "Z"],
        },
        {
            "code": "image_only_wall",
            "scope": "wall",
            "identity": "N5012",
            "direction": None,
            "source_sheet": None,
            "source_row": None,
            "source_cells": {},
            "reason": "应力图中存在该墙体，但配筋表没有对应数据，相关配筋字段已留空",
            "blank_fields": ["X", "Y", "Z"],
        },
    ]
    persisted = (job.work_dir / "job.json").read_text(encoding="utf-8")
    assert "model-supplied secret reason" not in persisted
    assert "must-not-persist" not in persisted
    assert "another-secret" not in persisted


def test_executor_serializes_ai_blank_warning_with_backend_owned_reason() -> None:
    warning = SimpleNamespace(
        code="OCR_RECOGNITION_FAILED",
        scope="slab",
        identity="11.45m",
        direction="X",
        source_sheet=None,
        source_row=None,
        source_cells={},
        reason="raw OCR exception with secret-token",
        blank_fields=("top_x",),
    )

    assert CalculationBookJobExecutor._safe_warnings((warning,)) == [
        {
            "code": "OCR_RECOGNITION_FAILED",
            "scope": "slab",
            "identity": "11.45m",
            "direction": "X",
            "source_sheet": None,
            "source_row": None,
            "source_cells": {},
            "reason": "应力云图 SMX 识别失败，当前方向配筋建议已留空，请人工复核",
            "blank_fields": ["top_x"],
        }
    ]


def test_standard_job_never_constructs_or_calls_normalizer(tmp_path: Path) -> None:
    processor = FakeProcessor()
    normalizer = FakeNormalizer()
    job = _job(tmp_path, options={"ai_reinforcement_normalization": False})

    _executor(processor, normalizer).execute(job)

    assert normalizer.calls == []
    assert processor.callbacks == [None]
    assert "ai_reinforcement_normalization" not in job.progress.details


def test_server_expected_count_is_forwarded_to_normalizer(tmp_path: Path) -> None:
    processor = FakeProcessor()
    normalizer = FakeNormalizer()
    job = _job(
        tmp_path,
        options={
            "ai_reinforcement_normalization": True,
            "ai_reinforcement_expected_source_row_count": 40,
        },
    )

    _executor(processor, normalizer).execute(job)

    assert normalizer.calls[0][1:] == (True, 40)


def test_normalization_callback_initialization_failure_is_persisted_as_failed(
    tmp_path: Path,
) -> None:
    class CallbackFailingExecutor(CalculationBookJobExecutor):
        def _normalization_callback(self, **_kwargs):
            raise ReinforcementNormalizationUnavailable(
                "normalizer_initialization_failed",
                "AI reinforcement normalizer initialization failed",
            )

    processor = FakeProcessor()
    job = _job(
        tmp_path,
        options={"ai_reinforcement_normalization": True},
    )

    with pytest.raises(ReinforcementNormalizationUnavailable):
        CallbackFailingExecutor(processor=processor).execute(job)

    assert job.status == JobStatus.FAILED
    assert processor.callbacks == []
    persisted = json.loads(
        (job.work_dir / "job.json").read_text(encoding="utf-8")
    )
    assert persisted["status"] == "failed"
    assert persisted["errors"] == [
        "AI reinforcement normalizer initialization failed"
    ]


def test_client_params_cannot_enable_ai_normalization(tmp_path: Path) -> None:
    processor = FakeProcessor()
    normalizer = FakeNormalizer()
    job = _job(tmp_path, options={})
    job.params["ai_reinforcement_normalization"] = True

    with pytest.raises(ValidationError):
        _executor(processor, normalizer).execute(job)

    assert normalizer.calls == []
    assert processor.callbacks == []


@pytest.mark.parametrize(
    "error_code",
    ["model_gateway_failed", "model_schema_invalid"],
)
def test_global_normalization_failure_marks_job_failed_with_sanitized_metadata(
    tmp_path: Path,
    error_code: str,
) -> None:
    processor = FakeProcessor()
    normalizer = FakeNormalizer(
        failure=ReinforcementTaskNormalizationError(
            error_code,
            "raw gateway body contains secret-token-and-cell-value",
        )
    )
    job = _job(tmp_path, options={"ai_reinforcement_normalization": True})

    with pytest.raises(ReinforcementTaskNormalizationError) as exc_info:
        _executor(processor, normalizer).execute(job)

    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    formatted = "".join(
        traceback.format_exception(
            type(exc_info.value),
            exc_info.value,
            exc_info.value.__traceback__,
        )
    )
    assert "secret-token" not in formatted
    assert "cell-value" not in formatted
    assert "raw gateway body" not in formatted
    assert job.status == JobStatus.FAILED
    assert job.progress.details["ai_reinforcement_normalization"] == {
        "stage": "AI_REINFORCEMENT_NORMALIZATION",
        "error_code": error_code,
        "model": "structured-test",
        "profile": "intranet-test",
    }
    persisted = (job.work_dir / "job.json").read_text(encoding="utf-8")
    assert "secret" not in persisted
    assert "cell-value" not in persisted
    assert "api_key" not in persisted


def test_real_normalizer_builder_uses_structured_model_and_task_limits(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []
    fake_spec = SimpleNamespace(
        resolve_models=lambda: SimpleNamespace(
            structured=SimpleNamespace(model="structured-prod")
        ),
        resolve_gateway_profile_name=lambda: "prod-intranet",
    )
    monkeypatch.setattr(
        "src.calculation_book.executor.load_ai_spec",
        lambda path: fake_spec,
    )
    monkeypatch.setattr(
        "src.calculation_book.executor.build_chat_client",
        lambda spec, **kwargs: calls.append({"spec": spec, **kwargs}) or object(),
    )
    settings = SimpleNamespace(
        enabled=True,
        skill_root=tmp_path / "skill",
        max_non_empty_cells=123,
        max_snapshot_chars=456,
        max_skill_chars=789,
        request_timeout_seconds=91,
        max_output_tokens=22_000,
        temperature=0.0,
        max_retries=2,
    )
    config = SimpleNamespace(
        ai_spec_path=tmp_path / "ai.yaml",
        calculation_book=SimpleNamespace(ai_normalization=settings),
    )

    built = build_reinforcement_task_normalizer(config)

    assert calls == [
        {
            "spec": fake_spec,
            "model_kind": "structured",
            "timeout_seconds": 91,
            "temperature": 0.0,
            "max_output_tokens": 22_000,
            "max_retries": 2,
        }
    ]
    assert built.metadata == ReinforcementNormalizerMetadata(
        model="structured-prod",
        profile="prod-intranet",
    )
    assert built.normalizer.skill_root == settings.skill_root
    assert built.normalizer.limits.max_non_empty_cells == 123


def test_unexpected_normalizer_failure_drops_original_exception_chain(
    tmp_path: Path,
) -> None:
    processor = FakeProcessor()
    normalizer = FakeNormalizer(
        failure=RuntimeError(
            "unexpected raw model response secret-token-and-cell-value"
        )
    )
    job = _job(tmp_path, options={"ai_reinforcement_normalization": True})

    with pytest.raises(ReinforcementNormalizationUnavailable) as exc_info:
        _executor(processor, normalizer).execute(job)

    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    formatted = "".join(
        traceback.format_exception(
            type(exc_info.value),
            exc_info.value,
            exc_info.value.__traceback__,
        )
    )
    assert "secret-token" not in formatted
    assert "cell-value" not in formatted
    assert "raw model response" not in formatted
    assert job.status == JobStatus.FAILED
    assert job.progress.details["ai_reinforcement_normalization"] == {
        "stage": "AI_REINFORCEMENT_NORMALIZATION",
        "error_code": "normalizer_initialization_failed",
        "model": "structured-test",
        "profile": "intranet-test",
    }
    persisted = (job.work_dir / "job.json").read_text(encoding="utf-8")
    assert "secret-token" not in persisted
    assert "cell-value" not in persisted


def test_real_normalizer_builder_fails_closed_when_disabled(tmp_path: Path) -> None:
    config = SimpleNamespace(
        ai_spec_path=tmp_path / "ai.yaml",
        calculation_book=SimpleNamespace(
            ai_normalization=SimpleNamespace(enabled=False)
        ),
    )

    with pytest.raises(RuntimeError, match="disabled"):
        build_reinforcement_task_normalizer(config)


def test_ai_suggestion_job_builds_one_invoker_and_persists_safe_summary_and_log(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    processor = FakeProcessor()
    invoker = FakeRebarInvoker()
    factory_calls: list[object] = []
    job = _job(
        tmp_path,
        options={
            "reinforcement_source": "ai_suggested",
            "ai_rebar_suggestion": True,
            "ai_reinforcement_normalization": False,
        },
    )
    job.params["reinforcement_source"] = "ai_suggested"
    central_log_dir = tmp_path / "central-ai-audit"
    config = get_config().model_copy(deep=True)
    config.calculation_book.ai_suggestion.log_dir = central_log_dir
    config.calculation_book.ai_suggestion.log_retention_days = 17
    monkeypatch.setattr("src.calculation_book.executor.get_config", lambda: config)
    create_kwargs: dict[str, object] = {}
    original_create = CalculationBookDiagnosticLog.create_for_job

    def capture_create_kwargs(**kwargs):
        create_kwargs.update(kwargs)
        return original_create(**kwargs)

    monkeypatch.setattr(
        "src.calculation_book.executor.CalculationBookDiagnosticLog.create_for_job",
        capture_create_kwargs,
    )

    executor = CalculationBookJobExecutor(
        processor=processor,
        rebar_suggestion_factory=(
            lambda config: factory_calls.append(config) or invoker
        ),
    )
    executor.execute(job)

    assert len(factory_calls) == 1
    assert invoker.calls == 1
    assert job.status == JobStatus.SUCCEEDED
    assert job.artifacts.calculation_log is not None
    assert job.artifacts.calculation_log.is_file()
    assert job.artifacts.calculation_log == (
        central_log_dir / f"calculation-book-{job.job_id}.log"
    )
    assert create_kwargs["log_dir"] == central_log_dir
    assert create_kwargs["retention_days"] == 17
    assert "work_dir" not in create_kwargs
    assert job.progress.details["ai_rebar_suggestion"] == {
        "skill_id": "recommend-rebar-from-smx",
        "skill_version": "1.0.0",
        "skill_sha256": "a" * 64,
        "model": "structured-test",
        "call_count": 1,
        "suggested_direction_count": 1,
        "blank_direction_count": 0,
        "repair_round_count": 0,
        "validation": "passed",
    }
    persisted = (job.work_dir / "job.json").read_text(encoding="utf-8")
    assert "candidate_counts" not in persisted
    assert "candidates" not in persisted
    assert "selected_candidate_id" not in persisted

    records = [
        json.loads(line)
        for line in job.artifacts.calculation_log.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert records[0]["event"] == "task_started"
    assert records[-1]["event"] == "task_completed"
    assert any(record["event"] == "ai_call_started" for record in records)
    assert any(record["event"] == "item_finalized" for record in records)
    assert any(record["event"] == "word_entry_written" for record in records)
    assert records[-1]["details"]["figure_count"] == 3


def test_ai_repair_progress_persists_only_safe_round_information(
    tmp_path: Path,
) -> None:
    invoker = FakeRebarInvoker(invalid_first=True)
    job = _job(
        tmp_path,
        options={
            "reinforcement_source": "ai_suggested",
            "ai_rebar_suggestion": True,
        },
    )
    job.params["reinforcement_source"] = "ai_suggested"

    CalculationBookJobExecutor(
        processor=FakeProcessor(),
        rebar_suggestion_invoker=invoker,
    ).execute(job)

    assert invoker.calls == 2
    assert job.progress.details["ai_rebar_suggestion_round"] == 2
    assert job.progress.message == "AI 配筋建议第 2 轮修正"
    persisted = (job.work_dir / "job.json").read_text(encoding="utf-8")
    assert "candidate_counts" not in persisted
    assert "excluded_candidate_ids" not in persisted
    assert "better_candidate_ids" not in persisted
    assert "input_summary_sha256" not in persisted


def test_ai_base_failure_limit_succeeds_with_blank_result_and_safe_metadata(
    tmp_path: Path,
) -> None:
    invoker = AlwaysFailRebarInvoker()
    job = _job(
        tmp_path,
        options={
            "reinforcement_source": "ai_suggested",
            "ai_rebar_suggestion": True,
        },
    )
    job.params["reinforcement_source"] = "ai_suggested"

    CalculationBookJobExecutor(
        processor=FakeProcessor(),
        rebar_suggestion_invoker=invoker,
    ).execute(job)

    assert invoker.calls == 3
    assert job.status == JobStatus.SUCCEEDED
    assert job.progress.details["ai_rebar_suggestion"] == {
        "skill_id": "recommend-rebar-from-smx",
        "skill_version": "1.0.0",
        "skill_sha256": "b" * 64,
        "model": "failed-model",
        "call_count": 3,
        "suggested_direction_count": 0,
        "blank_direction_count": 1,
        "repair_round_count": 0,
        "validation": "passed_with_warnings",
    }
    assert job.progress.details["calculation_book_warnings"] == [
        {
            "code": "AI_BASE_FAILURE_LIMIT",
            "scope": "wall",
            "identity": "N5001",
            "direction": "X",
            "source_sheet": None,
            "source_row": None,
            "source_cells": {},
            "reason": "人工智能连续三次调用或协议失败，当前方向已留空，请人工复核",
            "blank_fields": ["X"],
        }
    ]
    assert job.artifacts.calculation_log is not None
    records = [
        json.loads(line)
        for line in job.artifacts.calculation_log.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert records[-1]["event"] == "task_completed"
    assert sum(record["event"] == "ai_call_failed" for record in records) == 3


def test_provided_job_never_builds_ai_invoker_or_requires_diagnostic_log(
    tmp_path: Path,
) -> None:
    processor = FakeProcessor()
    factory_calls: list[object] = []
    job = _job(
        tmp_path,
        options={
            "reinforcement_source": "provided",
            "ai_rebar_suggestion": False,
            "ai_reinforcement_normalization": False,
        },
    )

    CalculationBookJobExecutor(
        processor=processor,
        rebar_suggestion_factory=(
            lambda config: factory_calls.append(config) or FakeRebarInvoker()
        ),
    ).execute(job)

    assert factory_calls == []
    assert job.status == JobStatus.SUCCEEDED
    assert job.artifacts.calculation_log is None
    assert "ai_rebar_suggestion" not in job.progress.details


def test_ai_suggestion_job_fails_closed_when_log_creation_is_unavailable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    processor = FakeProcessor()
    job = _job(
        tmp_path,
        options={
            "reinforcement_source": "ai_suggested",
            "ai_rebar_suggestion": True,
        },
    )
    job.params["reinforcement_source"] = "ai_suggested"

    def fail_create(**_kwargs):
        raise OSError("sensitive filesystem detail")

    monkeypatch.setattr(
        "src.calculation_book.executor.CalculationBookDiagnosticLog.create_for_job",
        fail_create,
    )

    with pytest.raises(RebarSuggestionUnavailable) as exc_info:
        CalculationBookJobExecutor(
            processor=processor,
            rebar_suggestion_factory=lambda _config: FakeRebarInvoker(),
        ).execute(job)

    assert exc_info.value.code == "diagnostic_log_unavailable"
    assert job.status == JobStatus.FAILED
    assert processor.callbacks == []
    assert job.artifacts.calculation_log is None
    persisted = (job.work_dir / "job.json").read_text(encoding="utf-8")
    assert "sensitive filesystem detail" not in persisted


def test_ai_suggestion_job_writes_failed_terminal_record_and_closes_log(
    tmp_path: Path,
) -> None:
    class FailingProcessor(FakeProcessor):
        def process(self, **_kwargs):
            raise RuntimeError("render failed")

    job = _job(
        tmp_path,
        options={
            "reinforcement_source": "ai_suggested",
            "ai_rebar_suggestion": True,
        },
    )
    job.params["reinforcement_source"] = "ai_suggested"

    with pytest.raises(RuntimeError, match="render failed"):
        CalculationBookJobExecutor(
            processor=FailingProcessor(),
            rebar_suggestion_factory=lambda _config: FakeRebarInvoker(),
        ).execute(job)

    assert job.status == JobStatus.FAILED
    assert job.artifacts.calculation_log is not None
    records = [
        json.loads(line)
        for line in job.artifacts.calculation_log.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert records[-1]["event"] == "task_failed"
    assert records[-1]["details"]["error_code"] == "RuntimeError"


def test_ai_job_closes_and_hides_log_when_failed_terminal_cannot_be_written(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FailingProcessor(FakeProcessor):
        def process(self, **_kwargs):
            raise RuntimeError("render failed")

    class FailingTerminalLog:
        def __init__(self, path: Path) -> None:
            self.path = path
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_bytes(b"")
            self.closed = False

        def write(self, event: str, **_details) -> None:
            if event == "task_failed":
                raise DiagnosticLogError("log_write_failed", "safe failure")

        def close(self) -> None:
            self.closed = True

    job = _job(
        tmp_path,
        options={
            "reinforcement_source": "ai_suggested",
            "ai_rebar_suggestion": True,
        },
    )
    job.params["reinforcement_source"] = "ai_suggested"
    fake_log = FailingTerminalLog(
        tmp_path / "job" / "calculation-book" / "logs" / "failed.log"
    )
    monkeypatch.setattr(
        "src.calculation_book.executor.CalculationBookDiagnosticLog.create_for_job",
        lambda **_kwargs: fake_log,
    )

    with pytest.raises(RebarSuggestionUnavailable) as exc_info:
        CalculationBookJobExecutor(
            processor=FailingProcessor(),
            rebar_suggestion_factory=lambda _config: FakeRebarInvoker(),
        ).execute(job)

    assert exc_info.value.code == "diagnostic_log_unavailable"
    assert fake_log.closed is True
    assert job.status == JobStatus.FAILED
    assert job.artifacts.calculation_log is None


def test_ai_job_fails_and_hides_log_when_success_close_is_not_durable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class CloseFailingLog:
        def __init__(self, path: Path) -> None:
            self.path = path
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_bytes(b"")
            self.closed = False

        def write(self, _event: str, **_details) -> None:
            return None

        def close(self) -> None:
            self.closed = True
            raise DiagnosticLogError("log_flush_failed", "safe failure")

    job = _job(
        tmp_path,
        options={
            "reinforcement_source": "ai_suggested",
            "ai_rebar_suggestion": True,
        },
    )
    job.params["reinforcement_source"] = "ai_suggested"
    fake_log = CloseFailingLog(
        tmp_path / "job" / "calculation-book" / "logs" / "failed.log"
    )
    monkeypatch.setattr(
        "src.calculation_book.executor.CalculationBookDiagnosticLog.create_for_job",
        lambda **_kwargs: fake_log,
    )

    with pytest.raises(RebarSuggestionUnavailable) as exc_info:
        CalculationBookJobExecutor(
            processor=FakeProcessor(),
            rebar_suggestion_factory=lambda _config: FakeRebarInvoker(),
        ).execute(job)

    assert exc_info.value.code == "diagnostic_log_unavailable"
    assert fake_log.closed is True
    assert job.status == JobStatus.FAILED
    assert job.artifacts.calculation_log is None
    assert job.artifacts.calculation_docx is None


def test_ai_job_hides_word_but_keeps_failed_log_when_completion_record_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class CompletionWriteFailingLog:
        def __init__(self, path: Path) -> None:
            self.path = path
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_bytes(b"")
            self.closed = False
            self.events: list[str] = []

        def write(self, event: str, **_details) -> None:
            if event == "task_completed":
                raise DiagnosticLogError("log_write_failed", "safe failure")
            self.events.append(event)

        def close(self) -> None:
            self.closed = True

    job = _job(
        tmp_path,
        options={
            "reinforcement_source": "ai_suggested",
            "ai_rebar_suggestion": True,
        },
    )
    job.params["reinforcement_source"] = "ai_suggested"
    fake_log = CompletionWriteFailingLog(
        tmp_path
        / "job"
        / "calculation-book"
        / "logs"
        / "calculation-book-calc-job.log"
    )
    monkeypatch.setattr(
        "src.calculation_book.executor.CalculationBookDiagnosticLog.create_for_job",
        lambda **_kwargs: fake_log,
    )

    with pytest.raises(DiagnosticLogError):
        CalculationBookJobExecutor(
            processor=FakeProcessor(),
            rebar_suggestion_invoker=FakeRebarInvoker(),
        ).execute(job)

    assert fake_log.closed is True
    assert fake_log.events[-1] == "task_failed"
    assert job.status == JobStatus.FAILED
    assert job.artifacts.calculation_log == fake_log.path
    assert job.artifacts.calculation_docx is None


def test_ai_job_hides_completed_log_when_success_state_persistence_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job = _job(
        tmp_path,
        options={
            "reinforcement_source": "ai_suggested",
            "ai_rebar_suggestion": True,
        },
    )
    job.params["reinforcement_source"] = "ai_suggested"
    original_persist = CalculationBookJobExecutor._persist

    def fail_only_success_state(candidate: Job) -> None:
        if candidate.status == JobStatus.SUCCEEDED:
            raise OSError("simulated successful-state persistence failure")
        original_persist(candidate)

    monkeypatch.setattr(
        CalculationBookJobExecutor,
        "_persist",
        staticmethod(fail_only_success_state),
    )

    with pytest.raises(OSError):
        CalculationBookJobExecutor(
            processor=FakeProcessor(),
            rebar_suggestion_invoker=FakeRebarInvoker(),
        ).execute(job)

    assert job.status == JobStatus.FAILED
    assert job.artifacts.calculation_docx is None
    assert job.artifacts.calculation_log is None
    persisted = json.loads((job.work_dir / "job.json").read_text(encoding="utf-8"))
    assert persisted["status"] == "failed"
    assert persisted["artifacts"]["calculation_docx"] is None
    assert persisted["artifacts"]["calculation_log"] is None


def test_real_rebar_suggestion_builder_uses_one_structured_skill_capability(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []
    fake_spec = object()
    fake_invoker = object()
    monkeypatch.setattr(
        "src.calculation_book.executor.load_ai_spec",
        lambda path: calls.append({"ai_spec_path": path}) or fake_spec,
    )
    monkeypatch.setattr(
        "src.calculation_book.executor.build_rebar_suggestion_task",
        lambda spec, **kwargs: calls.append({"spec": spec, **kwargs})
        or fake_invoker,
    )
    settings = SimpleNamespace(
        enabled=True,
        skill_root=tmp_path / "skill",
        skill_version="2.0.0",
        request_timeout_seconds=321,
        max_output_tokens=12_345,
        max_skill_bytes=111,
        max_reference_files=3,
        max_request_bytes=222,
        max_response_bytes=333,
        max_identifier_chars=44,
    )
    config = SimpleNamespace(
        ai_spec_path=tmp_path / "ai.yaml",
        calculation_book=SimpleNamespace(ai_suggestion=settings),
    )

    built = build_rebar_suggestion_invoker(config)

    assert built is fake_invoker
    assert calls[0] == {"ai_spec_path": config.ai_spec_path}
    assert calls[1]["spec"] is fake_spec
    assert calls[1]["skill_root"] == settings.skill_root
    assert calls[1]["skill_version"] == "2.0.0"
    assert calls[1]["request_timeout_seconds"] == 321
    assert calls[1]["max_output_tokens"] == 12_345
    limits = calls[1]["limits"]
    assert limits.max_skill_bytes == 111
    assert limits.max_reference_files == 3
    assert limits.max_request_bytes == 222
    assert limits.max_response_bytes == 333
    assert limits.max_response_tokens == 12_345
    assert limits.max_identifier_chars == 44


def test_real_rebar_suggestion_builder_fails_closed_when_disabled(
    tmp_path: Path,
) -> None:
    config = SimpleNamespace(
        calculation_book=SimpleNamespace(
            ai_suggestion=SimpleNamespace(enabled=False)
        )
    )

    with pytest.raises(RebarSuggestionUnavailable) as exc_info:
        build_rebar_suggestion_invoker(config)

    assert exc_info.value.code == "ai_suggestion_disabled"
