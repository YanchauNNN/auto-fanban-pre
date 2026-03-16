from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from src.audit_check.executor import AuditCheckExecutor
from src.audit_check.roi_mapper import AuditFieldContextMapper
from src.audit_check.models import AuditLexicon, ScanTextItem
from src.config import SpecLoader, reload_config
from src.models import BBox, FrameMeta, FrameRuntime, Job, JobStatus, JobType, TitleblockFields


def _configure_env(monkeypatch, tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    monkeypatch.setenv("FANBAN_SPEC_PATH", str(repo_root / "documents" / "参数规范.yaml"))
    monkeypatch.setenv("FANBAN_RUNTIME_SPEC_PATH", str(repo_root / "documents" / "参数规范_运行期.yaml"))
    monkeypatch.setenv("FANBAN_STORAGE_DIR", str(tmp_path / "storage"))
    SpecLoader.clear_cache()
    reload_config()


def test_audit_check_executor_writes_reports_and_summary(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)

    source_dwg = tmp_path / "2016-A01.dwg"
    source_dwg.write_bytes(b"dwg")
    dxf_path = tmp_path / "converted.dxf"
    dxf_path.write_text("0\nEOF\n", encoding="utf-8")

    lexicon = AuditLexicon(
        project_options=["2016", "1418"],
        allowed_texts={"2016": {"2016"}, "1418": {"1418", "JD"}},
        foreign_texts={"2016": {"1418", "JD"}, "1418": {"2016"}},
        token_projects={"2016": {"2016"}, "1418": {"1418"}, "JD": {"1418"}},
    )

    executor = AuditCheckExecutor()
    monkeypatch.setattr(executor.oda, "dwg_to_dxf", lambda src, out_dir: dxf_path)
    monkeypatch.setattr(executor.frame_detector, "detect_frames", lambda path: [])
    monkeypatch.setattr(executor.titleblock_extractor, "extract_fields", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor.a4_grouper, "group_a4_pages", lambda frames: ([], []))
    monkeypatch.setattr(executor.lexicon_loader, "load", lambda path: lexicon)
    monkeypatch.setattr(
        executor.dotnet_scanner,
        "scan",
        lambda **kwargs: [
            ScanTextItem(
                raw_text="14181NH-JGS01-002",
                entity_type="DBText",
                field_context="titleblock_internal_code",
                position_x=10.0,
                position_y=20.0,
            ),
            ScanTextItem(
                raw_text="JD1NHT11001B25C42SD",
                entity_type="MText",
                field_context="titleblock_external_code",
                position_x=12.0,
                position_y=22.0,
            ),
        ],
    )

    job = Job(
        job_id="job-audit-executor",
        job_type=JobType.AUDIT_REPLACE,
        project_no="2016",
        input_files=[source_dwg],
        options={"mode": "check"},
    )

    executor.execute(job)

    assert job.status == JobStatus.SUCCEEDED
    assert job.artifacts.report_json and job.artifacts.report_json.exists()
    assert job.artifacts.report_xlsx and job.artifacts.report_xlsx.exists()
    load_workbook(job.artifacts.report_xlsx)
    assert job.progress.details["findings_count"] == 2
    assert job.progress.details["affected_drawings_count"] == 1
    assert job.progress.details["top_wrong_texts"] == ["1418", "JD"]


def test_audit_field_context_mapper_initializes_roi_margin_before_building_regions(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_env(monkeypatch, tmp_path)

    frame = FrameMeta(
        runtime=FrameRuntime(
            frame_id="frame-audit-1",
            source_file=tmp_path / "demo.dxf",
            outer_bbox=BBox(xmin=0, ymin=0, xmax=200, ymax=100),
            roi_profile_id="BASE10",
            sx=1.0,
            sy=1.0,
        ),
        titleblock=TitleblockFields(internal_code="1234567-JGS01-001"),
    )

    mapper = AuditFieldContextMapper([frame], [])

    assert mapper is not None


def test_audit_check_executor_reuses_shared_prep_without_rerunning_oda_or_detection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_env(monkeypatch, tmp_path)

    source_dwg = tmp_path / "20261RS-JGS65.dwg"
    source_dwg.write_bytes(b"dwg")
    shared_dir = tmp_path / "shared"
    shared_dir.mkdir(parents=True, exist_ok=True)
    (shared_dir / "source_converted.dxf").write_text("0\nEOF\n", encoding="utf-8")
    (shared_dir / "frames.json").write_text("[]", encoding="utf-8")
    (shared_dir / "sheet_sets.json").write_text("[]", encoding="utf-8")
    (shared_dir / "titleblock_extracts.json").write_text("[]", encoding="utf-8")
    (shared_dir / "audit_roi_context.json").write_text("{}", encoding="utf-8")

    lexicon = AuditLexicon(
        project_options=["2026"],
        allowed_texts={"2026": {"2026"}},
        foreign_texts={"2026": {"JD"}},
        token_projects={"2026": {"2026"}, "JD": {"1418"}},
    )

    executor = AuditCheckExecutor()
    monkeypatch.setattr(
        executor.oda,
        "dwg_to_dxf",
        lambda src, out_dir: (_ for _ in ()).throw(AssertionError("should not convert dwg")),
    )
    monkeypatch.setattr(
        executor.frame_detector,
        "detect_frames",
        lambda path: (_ for _ in ()).throw(AssertionError("should not detect frames")),
    )
    monkeypatch.setattr(
        executor.titleblock_extractor,
        "extract_fields",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("should not extract titleblock fields")
        ),
    )
    monkeypatch.setattr(
        executor.a4_grouper,
        "group_a4_pages",
        lambda frames: (_ for _ in ()).throw(AssertionError("should not regroup a4 pages")),
    )
    monkeypatch.setattr(executor.lexicon_loader, "load", lambda path: lexicon)
    monkeypatch.setattr(
        executor.dotnet_scanner,
        "scan",
        lambda **kwargs: [
            ScanTextItem(
                raw_text="JD1RSL32001B25C42SD",
                entity_type="DBText",
                field_context="titleblock_external_code",
                position_x=10.0,
                position_y=10.0,
            ),
        ],
    )

    job = Job(
        job_id="job-audit-shared-prep",
        job_type=JobType.AUDIT_REPLACE,
        project_no="2026",
        input_files=[source_dwg],
        options={"mode": "check"},
        params={"shared_prep_dir": str(shared_dir)},
    )

    executor.execute(job)

    assert job.status == JobStatus.SUCCEEDED
    assert job.artifacts.report_json and job.artifacts.report_json.exists()
