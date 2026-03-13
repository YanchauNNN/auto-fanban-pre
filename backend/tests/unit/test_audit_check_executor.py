from __future__ import annotations

from pathlib import Path

from src.audit_check.executor import AuditCheckExecutor
from src.audit_check.models import AuditLexicon, ScanTextItem
from src.config import SpecLoader, reload_config
from src.models import Job, JobStatus, JobType


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
    assert job.progress.details["findings_count"] == 2
    assert job.progress.details["affected_drawings_count"] == 1
    assert job.progress.details["top_wrong_texts"] == ["1418", "JD"]
