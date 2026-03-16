from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.models import Job, JobStatus, JobType
from src.pipeline.executor import PipelineExecutor
from src.pipeline.stages import StageEnum


def _make_executor_with_engine(engine: str) -> PipelineExecutor:
    executor = object.__new__(PipelineExecutor)
    executor.config = cast(Any, SimpleNamespace(module5_export=SimpleNamespace(engine=engine)))
    return executor


def test_stage_split_routes_to_cad_dxf():
    executor = _make_executor_with_engine("cad_dxf")
    executor._stage_split_cad_dxf = MagicMock()

    PipelineExecutor._stage_split(executor, MagicMock(), {"frames": [], "sheet_sets": []})

    executor._stage_split_cad_dxf.assert_called_once()


def test_stage_export_routes_to_cad_dxf():
    executor = _make_executor_with_engine("cad_dxf")
    executor._stage_export_cad_dxf = MagicMock()

    PipelineExecutor._stage_export(executor, MagicMock(), {"frames": [], "sheet_sets": []})

    executor._stage_export_cad_dxf.assert_called_once()


def test_execute_marks_job_failed_when_cad_export_reports_fatal_errors(tmp_path: Path):
    executor = object.__new__(PipelineExecutor)
    executor.config = cast(Any, SimpleNamespace(get_job_dir=lambda job_id: tmp_path / "storage" / "jobs" / job_id))
    executor._last_progress_write = 0.0
    executor._progress_interval_sec = 0.0
    executor._update_progress = MagicMock()

    def fake_execute_stage(job, stage, context):
        if stage.name == StageEnum.EXPORT_PDF_AND_DWG.value:
            job.progress.details.update({"export_total": 1, "export_done": 0})

    executor._execute_stage = fake_execute_stage
    executor._aggregate_flags = lambda job, context: job.add_flag("CAD结果错误:test.dwg:accoreconsole.exe 不存在")

    job = Job(
        job_id="job-export-failure",
        job_type=JobType.DELIVERABLE,
        project_no="2016",
        options={"split_only": True},
    )

    with pytest.raises(RuntimeError, match="CAD导出失败"):
        PipelineExecutor.execute(executor, job)

    assert job.status == JobStatus.FAILED
    assert any("CAD导出失败" in err for err in job.errors)


def test_execute_uses_shared_prep_and_skips_early_detection_stages(tmp_path: Path):
    prep_dir = tmp_path / "shared"
    prep_dir.mkdir(parents=True, exist_ok=True)
    (prep_dir / "source_converted.dxf").write_text("0\nEOF\n", encoding="utf-8")
    (prep_dir / "frames.json").write_text("[]", encoding="utf-8")
    (prep_dir / "sheet_sets.json").write_text("[]", encoding="utf-8")
    (prep_dir / "titleblock_extracts.json").write_text("[]", encoding="utf-8")
    (prep_dir / "audit_roi_context.json").write_text("{}", encoding="utf-8")
    (prep_dir / "prep_summary.json").write_text("{}", encoding="utf-8")

    executor = object.__new__(PipelineExecutor)
    executor.config = cast(
        Any,
        SimpleNamespace(get_job_dir=lambda job_id: tmp_path / "storage" / "jobs" / job_id),
    )
    executor._last_progress_write = 0.0
    executor._progress_interval_sec = 0.0
    executor._update_progress = MagicMock()
    seen_stages: list[str] = []

    def fake_execute_stage(job, stage, context):
        seen_stages.append(stage.name)

    executor._execute_stage = fake_execute_stage
    executor._aggregate_flags = lambda job, context: None
    executor._raise_if_fatal_export_errors = lambda job: None

    job = Job(
        job_id="job-shared-prep",
        job_type=JobType.DELIVERABLE,
        project_no="2026",
        params={"shared_prep_dir": str(prep_dir)},
    )

    PipelineExecutor.execute(executor, job)

    assert StageEnum.DETECT_FRAMES.value not in seen_stages
    assert StageEnum.EXTRACT_TITLEBLOCK_FIELDS.value not in seen_stages
    assert StageEnum.A4_MULTIPAGE_GROUPING.value not in seen_stages
    assert StageEnum.FIX_TITLEBLOCK_CONSISTENCY.value in seen_stages
