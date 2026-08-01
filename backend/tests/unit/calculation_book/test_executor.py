from __future__ import annotations

import traceback
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.ai.reinforcement_task_normalizer import (
    ReinforcementTaskNormalizationError,
)
from src.calculation_book.executor import (
    CalculationBookJobExecutor,
    ReinforcementNormalizationUnavailable,
    ReinforcementNormalizerMetadata,
    build_reinforcement_task_normalizer,
)
from src.calculation_book.processor import CalculationBookStage
from src.models import Job, JobStatus, JobType


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
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.calls: list[tuple[Path, bool, int | None]] = []
        self.failure = failure

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
        return SimpleNamespace(
            wall_schedule=SimpleNamespace(rows=(object(), object())),
            slab_schedule=SimpleNamespace(rows=(object(),)),
            warnings=(
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
            ),
            source_row_count=3,
        )


class FakeProcessor:
    def __init__(self) -> None:
        self.callbacks: list[object] = []
        self.stages: list[CalculationBookStage] = []

    def process(self, *, output_dir: Path, params, progress, reinforcement_normalizer, **_kwargs):
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
        output = output_dir / "result.docx"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"docx")
        return SimpleNamespace(
            output_path=output,
            figure_count=3,
            template_type="internal_structure",
            selections=(),
            normalization_warnings=(
                validated.warnings if validated is not None else ()
            ),
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
    assert job.progress.details["reinforcement_normalization_warnings"] == [
        {
            "code": "needs_review",
            "scope": "wall",
            "identity": "N5001",
            "direction": "X",
            "source_sheet": "Sheet1",
            "source_row": 7,
            "source_cells": {"X": "B7"},
            "reason": "wall row needs review for fields: X",
            "blank_fields": ["X"],
        }
    ]
    assert persisted_stages.index("AI_REINFORCEMENT_NORMALIZATION") < (
        persisted_stages.index("OCR_REINFORCEMENT")
    )


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
