from __future__ import annotations

import json
import shutil
from pathlib import Path

import ezdxf
from openpyxl import load_workbook

from src.audit_check.models import AuditLexicon, ScanTextItem
from src.audit_replace.executor import AuditReplaceExecutor, derive_replaced_dwg_filename
from src.audit_replace.mapping import ReplaceMapping
from src.config import SpecLoader, reload_config
from src.models import Job, JobStatus, JobType


def _configure_env(monkeypatch, tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    monkeypatch.setenv("FANBAN_SPEC_PATH", str(repo_root / "documents" / "参数规范.yaml"))
    monkeypatch.setenv(
        "FANBAN_RUNTIME_SPEC_PATH",
        str(repo_root / "documents" / "参数规范_运行期.yaml"),
    )
    monkeypatch.setenv("FANBAN_STORAGE_DIR", str(tmp_path / "storage"))
    SpecLoader.clear_cache()
    reload_config()


def _build_replace_source_dxf(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    dxf_path = tmp_path / "source.dxf"
    doc = ezdxf.new("R2018")
    modelspace = doc.modelspace()
    text = modelspace.add_text("2026")
    mtext = modelspace.add_mtext("2026 REACTOR")
    no_op = modelspace.add_text("COMMON")
    missing_target = modelspace.add_text("NEEDS_TARGET")

    block = doc.blocks.new(name="TITLEBLOCK")
    block.add_attdef("CODE", insert=(0, 0), text="CODE")
    insert = modelspace.add_blockref("TITLEBLOCK", (0, 0))
    insert.add_auto_attribs({"CODE": "20261NH-JGS51-001"})

    doc.saveas(dxf_path)
    return dxf_path, {
        "text": text.dxf.handle,
        "mtext": mtext.dxf.handle,
        "no_op": no_op.dxf.handle,
        "missing_target": missing_target.dxf.handle,
        "attrib": insert.attribs[0].dxf.handle,
    }


def _build_external_code_split_dxf(tmp_path: Path) -> tuple[Path, list[tuple[str, str]]]:
    dxf_path = tmp_path / "external-code-source.dxf"
    doc = ezdxf.new("R2018")
    modelspace = doc.modelspace()
    chars: list[tuple[str, str]] = []
    for index, char in enumerate("JD1RCG11002B25C42SD"):
        entity = modelspace.add_text(char, dxfattribs={"insert": (float(index), 0.0)})
        chars.append((char, entity.dxf.handle))
    doc.saveas(dxf_path)
    return dxf_path, chars


def test_audit_replace_executor_writes_replaced_dwg_reports_and_preserves_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_env(monkeypatch, tmp_path)

    source_dwg = tmp_path / "20261NH-JGS51-B.dwg"
    source_dwg.write_bytes(b"original-dwg")
    dxf_path, handles = _build_replace_source_dxf(tmp_path)

    lexicon = AuditLexicon(
        project_options=["2016", "2026"],
        allowed_texts={"2016": {"2016"}, "2026": {"2026", "COMMON", "NEEDS_TARGET"}},
        foreign_texts={"2016": {"2026", "COMMON", "NEEDS_TARGET"}, "2026": {"2016"}},
        token_projects={
            "2016": {"2016"},
            "2026": {"2026"},
            "COMMON": {"2016", "2026"},
            "NEEDS_TARGET": {"2026"},
        },
    )
    mapping = ReplaceMapping(
        source_project_no="2026",
        target_project_no="2016",
        replacements={"2026": "2016"},
        no_op_tokens=["COMMON"],
        missing_target_tokens=["NEEDS_TARGET"],
    )

    executor = AuditReplaceExecutor()
    monkeypatch.setattr(executor.oda, "dwg_to_dxf", lambda src, out_dir: dxf_path)

    def _fake_dxf_to_dwg(
        src: Path,
        output_dir: Path,
        target_version_code: str | None = None,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "converted.dwg"
        shutil.copyfile(src, output_path)
        return output_path

    monkeypatch.setattr(executor.oda, "dxf_to_dwg", _fake_dxf_to_dwg)
    monkeypatch.setattr(executor.frame_detector, "detect_frames", lambda path: [])
    monkeypatch.setattr(executor.titleblock_extractor, "extract_fields", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor.a4_grouper, "group_a4_pages", lambda frames: ([], []))
    monkeypatch.setattr(executor.lexicon_loader, "load", lambda path: lexicon)
    monkeypatch.setattr(
        executor.mapping_builder,
        "build",
        lambda workbook_path, source_project_no, target_project_no: mapping,
    )
    monkeypatch.setattr(
        executor.dotnet_scanner,
        "scan",
        lambda **kwargs: [
            ScanTextItem(raw_text="2026", entity_type="DBText", entity_handle=handles["text"]),
            ScanTextItem(raw_text="2026 REACTOR", entity_type="MText", entity_handle=handles["mtext"]),
            ScanTextItem(
                raw_text="20261NH-JGS51-001",
                entity_type="AttributeReference",
                entity_handle=handles["attrib"],
                field_context="titleblock_internal_code",
            ),
            ScanTextItem(raw_text="COMMON", entity_type="DBText", entity_handle=handles["no_op"]),
            ScanTextItem(
                raw_text="NEEDS_TARGET",
                entity_type="DBText",
                entity_handle=handles["missing_target"],
            ),
        ],
    )

    job = Job(
        job_id="job-audit-replace-executor",
        job_type=JobType.AUDIT_REPLACE,
        project_no="2016",
        input_files=[source_dwg],
        options={"mode": "replace"},
        params={"source_project_no": "2026", "target_project_no": "2016"},
    )

    executor.execute(job)

    assert job.status == JobStatus.SUCCEEDED
    assert source_dwg.read_bytes() == b"original-dwg"
    assert job.artifacts.replaced_dwg and job.artifacts.replaced_dwg.exists()
    assert job.artifacts.replaced_dwg.name == "20161NH-JGS51-B.dwg"
    assert job.artifacts.replaced_dwg.read_text(encoding="utf-8")  # copied DXF payload
    assert job.artifacts.report_json and job.artifacts.report_json.exists()
    assert job.artifacts.report_xlsx and job.artifacts.report_xlsx.exists()
    load_workbook(job.artifacts.report_xlsx)

    replaced_dxf = job.work_dir / "work" / "replace" / "replaced.dxf"
    replaced_doc = ezdxf.readfile(replaced_dxf)
    entity_db = replaced_doc.entitydb

    assert entity_db.get(handles["text"]).dxf.text == "2016"
    assert entity_db.get(handles["mtext"]).text == "2016 REACTOR"
    assert entity_db.get(handles["attrib"]).dxf.text == "20161NH-JGS51-001"
    assert entity_db.get(handles["no_op"]).dxf.text == "COMMON"
    assert entity_db.get(handles["missing_target"]).dxf.text == "NEEDS_TARGET"

    report_payload = json.loads(job.artifacts.report_json.read_text(encoding="utf-8"))
    assert report_payload["replacement_count"] == 3
    assert report_payload["missing_target_tokens"] == ["NEEDS_TARGET"]
    assert report_payload["no_op_tokens"] == ["COMMON"]
    assert report_payload["skipped_count"] == 2
    assert job.progress.details["replacement_count"] == 3
    assert job.progress.details["affected_drawings_count"] == 1


def test_replace_token_ignores_spaces_in_source_project_name() -> None:
    updated = AuditReplaceExecutor._replace_token(
        "3.根据浙江金七门核电厂1、2号机组2016-J01ZHC04《厂址设计参数》",
        "浙江金七门核电厂 1、2 号 机 组",
        "江苏徐圩核能供热发电厂一期工程",
    )

    assert updated == "3.根据江苏徐圩核能供热发电厂一期工程2016-J01ZHC04《厂址设计参数》"


def test_derive_replaced_dwg_filename_replaces_source_project_no() -> None:
    assert (
        derive_replaced_dwg_filename(
            source_name="20162KA-JGS03-A.dwg",
            source_project_no="2016",
            target_project_no="2026",
        )
        == "20262KA-JGS03-A.dwg"
    )


def test_audit_replace_executor_uses_original_upload_name_for_replaced_dwg(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_env(monkeypatch, tmp_path)

    stored_source_dwg = tmp_path / "uploads" / "20162RC-JGS09-A-4d8dd053.dwg"
    stored_source_dwg.parent.mkdir(parents=True, exist_ok=True)
    stored_source_dwg.write_bytes(b"original-dwg")
    dxf_path, handles = _build_replace_source_dxf(tmp_path)

    lexicon = AuditLexicon(
        project_options=["2016", "1915"],
        allowed_texts={"2016": {"2016"}, "1915": {"1915"}},
        foreign_texts={"2016": {"1915"}, "1915": {"2016"}},
        token_projects={"2016": {"2016"}, "1915": {"1915"}},
    )
    mapping = ReplaceMapping(
        source_project_no="2016",
        target_project_no="1915",
        replacements={"2016": "1915"},
    )

    executor = AuditReplaceExecutor()
    monkeypatch.setattr(executor.oda, "dwg_to_dxf", lambda src, out_dir: dxf_path)

    def _fake_dxf_to_dwg(
        src: Path,
        output_dir: Path,
        target_version_code: str | None = None,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "converted.dwg"
        shutil.copyfile(src, output_path)
        return output_path

    monkeypatch.setattr(executor.oda, "dxf_to_dwg", _fake_dxf_to_dwg)
    monkeypatch.setattr(executor.frame_detector, "detect_frames", lambda path: [])
    monkeypatch.setattr(executor.titleblock_extractor, "extract_fields", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor.a4_grouper, "group_a4_pages", lambda frames: ([], []))
    monkeypatch.setattr(executor.lexicon_loader, "load", lambda path: lexicon)
    monkeypatch.setattr(
        executor.mapping_builder,
        "build",
        lambda workbook_path, source_project_no, target_project_no: mapping,
    )
    monkeypatch.setattr(
        executor.dotnet_scanner,
        "scan",
        lambda **kwargs: [
            ScanTextItem(raw_text="2016", entity_type="DBText", entity_handle=handles["text"]),
        ],
    )

    job = Job(
        job_id="job-audit-replace-original-name",
        job_type=JobType.AUDIT_REPLACE,
        project_no="1915",
        input_files=[stored_source_dwg],
        options={"mode": "replace"},
        params={"source_project_no": "2016", "target_project_no": "1915"},
        source_filename="20162RC-JGS09-A.dwg",
    )

    executor.execute(job)

    assert job.artifacts.replaced_dwg is not None
    assert job.artifacts.replaced_dwg.name == "19152RC-JGS09-A.dwg"
    assert job.artifacts.report_json is not None
    report_payload = json.loads(job.artifacts.report_json.read_text(encoding="utf-8"))
    assert report_payload["source_filename"] == "20162RC-JGS09-A.dwg"


def test_audit_replace_executor_replaces_split_external_code_prefix(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_env(monkeypatch, tmp_path)

    source_dwg = tmp_path / "20162RC-JGS09-A.dwg"
    source_dwg.write_bytes(b"original-dwg")
    dxf_path, char_handles = _build_external_code_split_dxf(tmp_path)

    lexicon = AuditLexicon(
        project_options=["2016", "1915"],
        allowed_texts={"2016": {"JD"}, "1915": {"HP"}},
        foreign_texts={"2016": {"HP"}, "1915": {"JD"}},
        token_projects={"JD": {"2016"}, "HP": {"1915"}},
    )
    mapping = ReplaceMapping(
        source_project_no="2016",
        target_project_no="1915",
        replacements={"JD": "HP"},
    )

    executor = AuditReplaceExecutor()
    monkeypatch.setattr(executor.oda, "dwg_to_dxf", lambda src, out_dir: dxf_path)

    def _fake_dxf_to_dwg(
        src: Path,
        output_dir: Path,
        target_version_code: str | None = None,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "converted.dwg"
        shutil.copyfile(src, output_path)
        return output_path

    monkeypatch.setattr(executor.oda, "dxf_to_dwg", _fake_dxf_to_dwg)
    monkeypatch.setattr(executor.frame_detector, "detect_frames", lambda path: [])
    monkeypatch.setattr(executor.titleblock_extractor, "extract_fields", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor.a4_grouper, "group_a4_pages", lambda frames: ([], []))
    monkeypatch.setattr(executor.lexicon_loader, "load", lambda path: lexicon)
    monkeypatch.setattr(
        executor.mapping_builder,
        "build",
        lambda workbook_path, source_project_no, target_project_no: mapping,
    )
    monkeypatch.setattr(
        executor.dotnet_scanner,
        "scan",
        lambda **kwargs: [
            ScanTextItem(
                raw_text=char,
                entity_type="DBText",
                entity_handle=handle,
                field_context="titleblock_external_code",
                internal_code="20162RC-JGS09-001",
                position_x=float(index),
                position_y=0.0,
            )
            for index, (char, handle) in enumerate(char_handles)
        ],
    )

    job = Job(
        job_id="job-audit-replace-split-external-code",
        job_type=JobType.AUDIT_REPLACE,
        project_no="1915",
        input_files=[source_dwg],
        options={"mode": "replace"},
        params={"source_project_no": "2016", "target_project_no": "1915"},
    )

    executor.execute(job)

    replaced_dxf = job.work_dir / "work" / "replace" / "replaced.dxf"
    replaced_doc = ezdxf.readfile(replaced_dxf)
    entity_db = replaced_doc.entitydb
    rebuilt = "".join(str(entity_db.get(handle).dxf.text) for _, handle in char_handles)
    assert rebuilt == "HP1RCG11002B25C42SD"

    assert job.artifacts.report_json is not None
    report_payload = json.loads(job.artifacts.report_json.read_text(encoding="utf-8"))
    external_rows = [
        entry
        for entry in report_payload["replacements"]
        if entry.get("field_context") == "titleblock_external_code"
    ]
    assert [(row["matched_text"], row["replacement_text"]) for row in external_rows] == [
        ("J", "H"),
        ("D", "P"),
    ]


def test_derive_replaced_dwg_filename_appends_target_project_when_source_project_absent() -> None:
    assert (
        derive_replaced_dwg_filename(
            source_name="厂房索引图.dwg",
            source_project_no="2016",
            target_project_no="2026",
        )
        == "厂房索引图——2026.dwg"
    )
