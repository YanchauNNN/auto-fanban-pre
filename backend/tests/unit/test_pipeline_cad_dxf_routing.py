from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from src.models import BBox, FrameMeta, FrameRuntime, Job, JobStatus, JobType
from src.pipeline.executor import PipelineExecutor
from src.pipeline.stages import DELIVERABLE_STAGES, StageEnum


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


def test_execute_records_stage_timings_into_job_details_and_artifact(tmp_path: Path) -> None:
    executor = object.__new__(PipelineExecutor)
    executor.config = cast(
        Any,
        SimpleNamespace(get_job_dir=lambda job_id: tmp_path / "storage" / "jobs" / job_id),
    )
    executor._last_progress_write = 0.0
    executor._progress_interval_sec = 0.0

    for attr in (
        "_stage_ingest",
        "_stage_font_preflight_and_replace",
        "_stage_convert",
        "_stage_detect_frames",
        "_stage_verify_frames",
        "_stage_scale_fit",
        "_stage_extract_fields",
        "_stage_a4_grouping",
        "_stage_fix_titleblock_consistency",
        "_stage_split",
        "_stage_export",
    ):
        setattr(executor, attr, lambda job, context: None)

    executor._aggregate_flags = lambda job, context: None
    executor._raise_if_fatal_export_errors = lambda job: None

    job = Job(
        job_id="job-stage-timings",
        job_type=JobType.DELIVERABLE,
        project_no="2026",
        options={"split_only": True},
    )

    PipelineExecutor.execute(executor, job)

    stage_timings = job.progress.details.get("stage_timings")
    assert isinstance(stage_timings, list)
    assert len(stage_timings) == 11
    assert stage_timings[0]["stage"] == StageEnum.INGEST.value
    assert stage_timings[-1]["stage"] == StageEnum.EXPORT_PDF_AND_DWG.value
    assert all(item["status"] == "succeeded" for item in stage_timings)

    timings_path = tmp_path / "storage" / "jobs" / job.job_id / "stage_timings.json"
    assert timings_path.exists()
    persisted = json.loads(timings_path.read_text(encoding="utf-8"))
    assert persisted == stage_timings


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
    assert StageEnum.FONT_PREFLIGHT_AND_REPLACE.value not in seen_stages
    assert StageEnum.FIX_TITLEBLOCK_CONSISTENCY.value in seen_stages


def test_execute_slot_bound_phase_defers_docs_until_post_phase(tmp_path: Path) -> None:
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
        job_id="job-slot-bound-phase",
        job_type=JobType.DELIVERABLE,
        project_no="2026",
    )

    post_phase = PipelineExecutor.execute_slot_bound_phase(executor, job)

    all_stage_names = [stage.name for stage in DELIVERABLE_STAGES]
    export_index = all_stage_names.index(StageEnum.EXPORT_PDF_AND_DWG.value)
    assert seen_stages == all_stage_names[: export_index + 1]
    assert callable(post_phase)
    assert job.status == JobStatus.RUNNING

    post_phase()

    assert seen_stages == all_stage_names
    assert job.status == JobStatus.SUCCEEDED


def test_stage_order_includes_font_preflight_before_convert() -> None:
    stage_names = [stage.name for stage in DELIVERABLE_STAGES]

    assert stage_names.index(StageEnum.FONT_PREFLIGHT_AND_REPLACE.value) < stage_names.index(
        StageEnum.CONVERT_DWG_TO_DXF.value
    )


def test_stage_detect_frames_sets_project_no_before_detection(tmp_path: Path) -> None:
    class _RecordingFrameDetector:
        def __init__(self) -> None:
            self.project_no: str | None = None
            self.detect_calls: list[tuple[Path, str | None]] = []

        def set_project_no(self, project_no: str | None) -> None:
            self.project_no = project_no

        def detect_frames(self, dxf_path: Path) -> list[Any]:
            self.detect_calls.append((dxf_path, self.project_no))
            return []

    executor = object.__new__(PipelineExecutor)
    executor.frame_detector = _RecordingFrameDetector()
    executor._update_progress = MagicMock()

    dxf_path = tmp_path / "sample.dxf"
    dxf_path.write_text("0\nEOF\n", encoding="utf-8")
    job = Job(job_id="job-detect-project-no", job_type=JobType.DELIVERABLE, project_no="1818")
    context = {"dxf_files": [dxf_path], "frames": [], "dxf_to_dwg": {}}

    PipelineExecutor._stage_detect_frames(executor, job, context)

    assert executor.frame_detector.detect_calls == [(dxf_path, "1818")]


def test_stage_extract_fields_drops_frames_with_anchor_validation_failure(tmp_path: Path) -> None:
    class _FlaggingExtractor:
        def extract_fields(self, dxf_path: Path, frame: FrameMeta) -> None:
            if frame.frame_id == "invalid-frame":
                frame.add_flag("未命中锚点文本")

    executor = object.__new__(PipelineExecutor)
    executor.titleblock_extractor = _FlaggingExtractor()
    executor._update_progress = MagicMock()

    dxf_path = tmp_path / "sample.dxf"
    dxf_path.write_text("0\nEOF\n", encoding="utf-8")
    valid_frame = FrameMeta(
        runtime=FrameRuntime(
            frame_id="valid-frame",
            source_file=dxf_path,
            outer_bbox=BBox(xmin=0, ymin=0, xmax=100, ymax=100),
        ),
    )
    invalid_frame = FrameMeta(
        runtime=FrameRuntime(
            frame_id="invalid-frame",
            source_file=dxf_path,
            outer_bbox=BBox(xmin=0, ymin=0, xmax=100, ymax=100),
        ),
    )
    job = Job(job_id="job-filter-invalid-frames", job_type=JobType.DELIVERABLE, project_no="1818")
    context = {"frames": [valid_frame, invalid_frame]}

    PipelineExecutor._stage_extract_fields(executor, job, context)

    assert [frame.frame_id for frame in context["frames"]] == ["valid-frame"]
    assert job.progress.details["frames_anchor_invalid_filtered"] == 1
