from __future__ import annotations

import json
import shutil
from pathlib import Path

import ezdxf
from openpyxl import load_workbook

from src.audit_check.lexicon import AuditLexiconLoader
from src.audit_check.matcher import AuditMatchEngine
from src.audit_check.models import AuditLexicon, ScanTextItem
from src.audit_replace.executor import AuditReplaceExecutor, derive_replaced_dwg_filename
from src.audit_replace.mapping import ReplaceMapping, ReplaceMappingBuilder
from src.config import SpecLoader, reload_config
from src.models import BBox, Job, JobStatus, JobType


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


def _build_external_code_split_dxf(
    tmp_path: Path,
    code: str = "JD1RCG11002B25C42SD",
) -> tuple[Path, list[tuple[str, str]]]:
    dxf_path = tmp_path / "external-code-source.dxf"
    doc = ezdxf.new("R2018")
    modelspace = doc.modelspace()
    chars: list[tuple[str, str]] = []
    for index, char in enumerate(code):
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


def test_derive_replaced_dwg_filename_rewrites_target_unit_when_explicit() -> None:
    assert (
        derive_replaced_dwg_filename(
            source_name="20162RC-JGS09-A.dwg",
            source_project_no="2016",
            target_project_no="1915",
            source_unit_no="2",
            target_unit_no="1",
        )
        == "19151RC-JGS09-A.dwg"
    )


def test_rewrite_target_unit_text_rewrites_embedded_factory_code_prefix() -> None:
    from src.audit_replace.executor import rewrite_target_unit_text

    assert (
        rewrite_target_unit_text(
            "例如：08ZZ0089N实际应为2RC08ZZ0089N.",
            target_project_no="1915",
            source_unit_no="2",
            target_unit_no="1",
        )
        == "例如：08ZZ0089N实际应为1RC08ZZ0089N."
    )
    assert (
        rewrite_target_unit_text(
            "HP2RCG11001B25C42SD",
            target_project_no="1915",
            source_unit_no="2",
            target_unit_no="1",
        )
        == "HP1RCG11001B25C42SD"
    )


def test_audit_replace_executor_rewrites_target_units_after_factory_index_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    executor = AuditReplaceExecutor()
    source_dwg = tmp_path / "factory-index-output.dwg"
    source_dwg.write_bytes(b"AC1032fake-dwg")
    source_dxf = tmp_path / "factory-index-output.dxf"
    doc = ezdxf.new("R2018")
    text = doc.modelspace().add_text("HP2RCG11001B25C42SD")
    doc.saveas(source_dxf)

    def _fake_dwg_to_dxf(src: Path, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "factory-index-output.dxf"
        shutil.copyfile(source_dxf, output_path)
        return output_path

    def _fake_dxf_to_dwg(
        src: Path,
        output_dir: Path,
        target_version_code: str | None = None,
    ) -> Path:
        return src

    monkeypatch.setattr(executor.oda, "dwg_to_dxf", _fake_dwg_to_dxf)
    monkeypatch.setattr(executor.oda, "dxf_to_dwg", _fake_dxf_to_dwg)

    rewritten_path = executor._rewrite_target_units_in_dwg(
        source_dwg=source_dwg,
        workspace_dir=tmp_path / "postprocess",
        target_project_no="1915",
        source_unit_no="2",
        target_unit_no="1",
    )

    rewritten_doc = ezdxf.readfile(rewritten_path)
    assert rewritten_doc.entitydb.get(text.dxf.handle).dxf.text == "HP1RCG11001B25C42SD"


def test_audit_replace_executor_rebuilds_post_factory_dwg_even_without_dxf_text_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    executor = AuditReplaceExecutor()
    source_dwg = tmp_path / "factory-index-output.dwg"
    source_dwg.write_bytes(b"AC1032fake-dwg")
    source_dxf = tmp_path / "factory-index-output.dxf"
    doc = ezdxf.new("R2018")
    doc.modelspace().add_text("HP1RCG11001B25C42SD")
    doc.saveas(source_dxf)
    converted_dwg = tmp_path / "converted.dwg"

    def _fake_dwg_to_dxf(src: Path, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "factory-index-output.dxf"
        shutil.copyfile(source_dxf, output_path)
        return output_path

    def _fake_dxf_to_dwg(
        src: Path,
        output_dir: Path,
        target_version_code: str | None = None,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, converted_dwg)
        return converted_dwg

    monkeypatch.setattr(executor.oda, "dwg_to_dxf", _fake_dwg_to_dxf)
    monkeypatch.setattr(executor.oda, "dxf_to_dwg", _fake_dxf_to_dwg)

    rewritten_path = executor._rewrite_target_units_in_dwg(
        source_dwg=source_dwg,
        workspace_dir=tmp_path / "postprocess",
        target_project_no="1915",
        source_unit_no="2",
        target_unit_no="1",
    )

    assert rewritten_path == converted_dwg
    assert converted_dwg.exists()


def test_real_lexicon_maps_and_matches_cp05_from_2016_to_1915(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_env(monkeypatch, tmp_path)
    repo_root = Path(__file__).resolve().parents[3]
    workbook_path = repo_root / "documents_bin" / "词库收集.xlsx"

    mapping = ReplaceMappingBuilder().build(
        workbook_path=workbook_path,
        source_project_no="2016",
        target_project_no="1915",
    )
    assert mapping.replacements["CP05JT0101"] == "1915JT0101"

    lexicon = AuditLexiconLoader().load(workbook_path)
    findings = AuditMatchEngine(lexicon).evaluate(
        project_no="1915",
        items=[
            ScanTextItem(
                raw_text="CP05JT0101",
                entity_type="DBText",
                entity_handle="ABCD",
            ),
        ],
    )
    entries = AuditReplaceExecutor._build_replace_entries(findings, mapping)

    assert [entry["matched_text"] for entry in entries] == ["CP05JT0101"]
    assert entries[0]["replacement_text"] == "1915JT0101"
    assert entries[0]["status"] == "pending"


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


def test_audit_replace_executor_rewrites_explicit_target_unit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_env(monkeypatch, tmp_path)

    stored_source_dwg = tmp_path / "20162RC-JGS09-A-7c6c852a.dwg"
    stored_source_dwg.write_bytes(b"stored-dwg")
    dxf_path = tmp_path / "source.dxf"
    doc = ezdxf.new("R2018")
    modelspace = doc.modelspace()
    code = modelspace.add_text("20162RC-JGS09-A")
    cp05 = modelspace.add_text("CP05JT0101")
    explicit_unit = modelspace.add_text("2号机组")
    explicit_island = modelspace.add_text("2号岛")
    short_factory_note = modelspace.add_text(
        "11.除特殊注明外，本图册中孔洞、套管、预埋件等编码中被省略的厂房代码均为2RC.",
    )
    doc.saveas(dxf_path)

    lexicon = AuditLexicon(
        project_options=["1915", "2016"],
        allowed_texts={"1915": {"1915", "1915JT0101"}, "2016": {"2016", "CP05JT0101"}},
        foreign_texts={"1915": {"2016", "CP05JT0101"}, "2016": {"1915", "1915JT0101"}},
        token_projects={
            "1915": {"1915"},
            "1915JT0101": {"1915"},
            "2016": {"2016"},
            "CP05JT0101": {"2016"},
        },
    )
    mapping = ReplaceMapping(
        source_project_no="2016",
        target_project_no="1915",
        replacements={"2016": "1915", "CP05JT0101": "1915JT0101"},
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
            ScanTextItem(raw_text="20162RC-JGS09-A", entity_type="DBText", entity_handle=code.dxf.handle),
            ScanTextItem(raw_text="CP05JT0101", entity_type="DBText", entity_handle=cp05.dxf.handle),
            ScanTextItem(
                raw_text="2号机组",
                entity_type="DBText",
                entity_handle=explicit_unit.dxf.handle,
            ),
            ScanTextItem(
                raw_text="2号岛",
                entity_type="DBText",
                entity_handle=explicit_island.dxf.handle,
            ),
        ],
    )

    job = Job(
        job_id="job-target-unit-rewrite",
        job_type=JobType.AUDIT_REPLACE,
        project_no="1915",
        source_filename="20162RC-JGS09-A.dwg",
        input_files=[stored_source_dwg],
        options={"mode": "replace"},
        params={
            "source_project_no": "2016",
            "source_island_no": "2",
            "target_project_no": "1915",
            "target_island_no": "1",
        },
    )

    executor.execute(job)

    assert job.artifacts.replaced_dwg is not None
    assert job.artifacts.replaced_dwg.name == "19151RC-JGS09-A.dwg"

    replaced_doc = ezdxf.readfile(job.work_dir / "work" / "replace" / "replaced.dxf")
    entity_db = replaced_doc.entitydb
    assert entity_db.get(code.dxf.handle).dxf.text == "19151RC-JGS09-A"
    assert entity_db.get(cp05.dxf.handle).dxf.text == "1915JT0101"
    assert entity_db.get(explicit_unit.dxf.handle).dxf.text == "1号机组"
    assert entity_db.get(explicit_island.dxf.handle).dxf.text == "1号岛"
    assert entity_db.get(short_factory_note.dxf.handle).dxf.text.endswith("1RC.")


def test_audit_replace_executor_replaces_split_external_code_prefix_and_unit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_env(monkeypatch, tmp_path)

    source_dwg = tmp_path / "20162RC-JGS09-A.dwg"
    source_dwg.write_bytes(b"original-dwg")
    dxf_path, char_handles = _build_external_code_split_dxf(tmp_path, "JD2RCG11002B25C42SD")

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
        params={
            "source_project_no": "2016",
            "source_island_no": "2",
            "target_project_no": "1915",
            "target_island_no": "1",
        },
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
        and entry.get("status") == "replaced"
    ]
    assert [(row["matched_text"], row["replacement_text"]) for row in external_rows] == [
        ("J", "H"),
        ("D", "P"),
        ("2", "1"),
    ]


def test_audit_replace_executor_does_not_group_split_external_code_outside_roi() -> None:
    items = [
        ScanTextItem(
            raw_text=char,
            entity_type="DBText",
            entity_handle=f"H{index}",
            field_context="titleblock_internal_code",
            internal_code="20162RC-JGS09-001",
            layout_name="Model",
            position_x=float(index),
            position_y=0.0,
        )
        for index, char in enumerate("JD2RCG11002B25C42SD")
    ]
    mapping = ReplaceMapping(
        source_project_no="2016",
        target_project_no="1915",
        replacements={"JD": "HP"},
    )

    prefix_entries = AuditReplaceExecutor._build_external_code_prefix_entries(
        items=items,
        mapping=mapping,
        existing_entries=[],
    )
    unit_entries = AuditReplaceExecutor._build_external_code_unit_entries(
        items=items,
        mapping=mapping,
        existing_entries=[],
        source_unit_no="2",
        target_unit_no="1",
    )

    assert prefix_entries == []
    assert unit_entries == []


def test_audit_replace_executor_groups_split_external_code_when_block_roi_context_is_missing() -> None:
    code = "JD1RCG11002B25C42SD"
    items = [
        ScanTextItem(
            raw_text=char,
            entity_type="MText" if index < 2 else "DBText",
            entity_handle=f"H{index}",
            field_context=None,
            internal_code="20161RC-JGS09-001",
            layout_name="Model",
            block_path="*U13" if index < 2 else "",
            position_x=float(index * 400),
            position_y=0.0 if index < 2 else -100.0,
            text_bbox=BBox(
                xmin=float(index * 400),
                ymin=-260.0 if index < 2 else -360.0,
                xmax=float(index * 400 + 240),
                ymax=40.0 if index < 2 else -60.0,
            ),
        )
        for index, char in enumerate(code)
    ]
    mapping = ReplaceMapping(
        source_project_no="2016",
        target_project_no="1915",
        replacements={"JD": "HP"},
    )

    prefix_entries = AuditReplaceExecutor._build_external_code_prefix_entries(
        items=items,
        mapping=mapping,
        existing_entries=[],
    )
    unit_entries = AuditReplaceExecutor._build_external_code_unit_entries(
        items=items,
        mapping=mapping,
        existing_entries=prefix_entries,
        source_unit_no="1",
        target_unit_no="2",
    )

    assert [(entry["matched_text"], entry["replacement_text"]) for entry in prefix_entries] == [
        ("J", "H"),
        ("D", "P"),
    ]
    assert [(entry["matched_text"], entry["replacement_text"]) for entry in unit_entries] == [
        ("1", "2"),
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
