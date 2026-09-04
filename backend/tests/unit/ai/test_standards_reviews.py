from __future__ import annotations

import copy
import hashlib
import importlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[4] / "tools/ai/building-structure-standards/scripts"


@pytest.fixture
def sample(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    corpus = importlib.import_module("build_corpus")
    query = importlib.import_module("standards_query")
    source_root = tmp_path / "pdfs"
    source_root.mkdir()
    pdf = source_root / "source.pdf"
    pdf.write_bytes(b"%PDF-1.7\nlocal test source")
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    spec = corpus.SourceSpec(
        "GB 12345-2026",
        "Test",
        "2026",
        str(pdf),
        "",
        "内部离线已授权",
        "public",
        official_status="待核验",
        relative_source_path="source.pdf",
    )
    pages = [
        corpus.PageRecord(
            n,
            "",
            "raw OCR text",
            f"source.pdf#page={n}",
            native_text="native original",
            ocr_text="raw OCR text",
            text_source="ocr",
            quality_status="review_required",
            quality_flags=["legacy_ocr_candidate", "suspicious_unit"],
            content_role="normative",
        )
        for n in (1, 2)
    ]
    clauses = [
        corpus.ClauseRecord(
            "1.0.1", "1.0.1 Area", "1.0.1 Area 1000m°\nContinuation.", 1, 2, "source.pdf#page=1"
        ),
        corpus.ClauseRecord("1.0.2", "Adjacent", "Unreviewed adjacent", 1, 1, "source.pdf#page=1"),
    ]
    table = corpus.TableRecord(
        "p1-v1",
        1,
        [],
        "",
        "source.pdf#page=1",
        "visual_required",
        "3.2.2",
        ["table_cells_unverified"],
    )
    db = tmp_path / "original.sqlite"
    corpus.build_sqlite([corpus.ParsedSource(spec, sha, pages, clauses, [table])], db)
    return {"db": db, "root": source_root, "pdf": pdf, "sha": sha, "query": query, "tmp": tmp_path}


def _module():
    assert (SCRIPTS / "standards_reviews.py").is_file(), "record-level review replay is missing"
    return importlib.import_module("standards_reviews")


def _manifest(sample, kind="clause"):
    module = _module()
    with sqlite3.connect(sample["db"]) as conn:
        conn.row_factory = sqlite3.Row
        table = "clauses" if kind == "clause" else "standard_tables"
        row = dict(conn.execute(f"SELECT * FROM {table} LIMIT 1").fetchone())
    end = 2 if kind == "clause" else 1
    review = {
        "review_id": "test-" + kind,
        "kind": kind,
        "standard_code": "GB 12345-2026",
        "source_sha256": sample["sha"],
        "record_id": "1.0.1" if kind == "clause" else "p1-v1",
        "page_start": 1,
        "page_end": end,
        "base_record_sha256": module.record_fingerprint(kind, row),
        "scope": "complete_record",
        "reviewer": "test visual reviewer",
        "method": "visual_transcription",
        "reviewed_at": "2026-09-03T12:00:00+08:00",
        "pages": [
            {"page_number": n, "printed_page": str(n + 10), "image_sha256": "a" * 64}
            for n in range(1, end + 1)
        ],
        "replacement": {"text": "1.0.1 Area 1000m²\nContinuation."}
        if kind == "clause"
        else {
            "rows": [["Category", "Distance (m)"], ["Other", "6"]],
            "title": "Table 3.2.2 Distance (m)",
            "notes": ["Measured between outside walls."],
        },
    }
    return {"schema_version": 1, "reviews": [review]}


def _publish(sample, manifest):
    path = sample["tmp"] / "reviews.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    output = sample["tmp"] / "reviewed.sqlite"
    report = _module().publish_reviewed_corpus(
        database=sample["db"],
        reviews_path=path,
        source_root=sample["root"],
        output_path=output,
    )
    return output, report


def _clause(sample, db, clause="1.0.1"):
    return sample["query"].get_clause(db, "GB 12345-2026", clause)["results"][0]


def test_review_corrects_only_target_and_preserves_raw_pages_and_original_database(sample):
    before = hashlib.sha256(sample["db"].read_bytes()).hexdigest()
    output, report = _publish(sample, _manifest(sample))
    row = _clause(sample, output)
    assert "1000m²" in row["text"] and "1000m°" not in row["text"]
    assert row["quality_status"] == "usable"
    assert row["printed_page_start"] == "11"
    assert row["record_review"]["review_id"] == "test-clause"
    assert row["page_quality"][0]["quality_status"] == "review_required"
    assert row["design_advice_allowed"] is False
    assert "standard_status_requires_review" in row["quality_flags"]
    assert _clause(sample, output, "1.0.2")["quality_status"] == "review_required"
    assert hashlib.sha256(sample["db"].read_bytes()).hexdigest() == before
    with sqlite3.connect(output) as conn, sqlite3.connect(sample["db"]) as original:
        assert (
            conn.execute("SELECT * FROM pages").fetchall()
            == original.execute("SELECT * FROM pages").fetchall()
        )
        assert (
            "1000m°"
            in conn.execute("SELECT original_record_json FROM evidence_reviews").fetchone()[0]
        )
        assert (
            "1000m²"
            in conn.execute("SELECT text FROM clauses_fts WHERE clause_id='1.0.1'").fetchone()[0]
        )
    assert report["applied_record_count"] == 1 and report["ocr_executed"] is False
    assert sample["query"].search(output, "1000m²")["found"] is True


@pytest.mark.parametrize(
    "defect",
    [
        "pdf_hash",
        "stale_text",
        "missing_continuation",
        "non_normative",
        "changed_span",
        "malformed_pages",
        "unsafe_path",
        "duplicate_review",
    ],
)
def test_review_rejects_wrong_scope_and_stale_inputs_without_publishing(sample, defect):
    manifest = _manifest(sample)
    review = manifest["reviews"][0]
    if defect == "pdf_hash":
        sample["pdf"].write_bytes(b"%PDF changed")
    elif defect == "stale_text":
        review["base_record_sha256"] = "b" * 64
    elif defect == "missing_continuation":
        review["pages"].pop()
    elif defect == "changed_span":
        review["page_end"] = 1
    elif defect == "malformed_pages":
        review["pages"][0]["image_sha256"] = "unverified"
    elif defect == "duplicate_review":
        manifest["reviews"].append(copy.deepcopy(review))
    else:
        with sqlite3.connect(sample["db"]) as conn:
            if defect == "non_normative":
                conn.execute("UPDATE clauses SET content_role='commentary'")
            else:
                conn.execute("UPDATE sources SET source_path='../source.pdf'")
    with pytest.raises(ValueError):
        _publish(sample, manifest)
    assert not (sample["tmp"] / "reviewed.sqlite").exists()


@pytest.mark.parametrize("kind", ["clause", "table"])
def test_reviewed_record_tampering_invalidates_runtime_review(sample, kind):
    output, _ = _publish(sample, _manifest(sample, kind))
    with sqlite3.connect(output) as conn:
        if kind == "clause":
            conn.execute("UPDATE clauses SET text='tampered' WHERE clause_id='1.0.1'")
        else:
            conn.execute("UPDATE standard_tables SET markdown='tampered'")
    row = (
        _clause(sample, output)
        if kind == "clause"
        else sample["query"].get_table(output, "GB 12345-2026", "3.2.2")["table"]
    )
    assert row["quality_status"] == "review_required"
    assert row["design_advice_allowed"] is False
    assert "record_review_invalid" in row["quality_flags"]


def test_reviewed_table_has_cells_notes_and_only_record_level_quality(sample):
    output, _ = _publish(sample, _manifest(sample, "table"))
    row = sample["query"].get_table(output, "GB 12345-2026", "3.2.2")["table"]
    assert row["rows"][1] == ["Other", "6"]
    assert "outside walls" in row["markdown"]
    assert row["quality_status"] == "usable"
    assert row["table_quality_status"] == "usable"
    assert row["printed_page"] == "11"
    assert row["design_advice_allowed"] is False


def test_review_rejects_in_place_output(sample):
    manifest = sample["tmp"] / "empty.json"
    manifest.write_text('{"schema_version": 1, "reviews": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="different"):
        _module().publish_reviewed_corpus(
            database=sample["db"],
            reviews_path=manifest,
            source_root=sample["root"],
            output_path=sample["db"],
        )


def test_source_status_does_not_make_correct_text_inaccurate_but_blocks_advice(sample):
    with sqlite3.connect(sample["db"]) as conn:
        conn.execute("UPDATE pages SET quality_status='usable', quality_flags_json='[]'")
    row = _clause(sample, sample["db"])
    assert row["quality_status"] == "usable"
    assert row["design_advice_allowed"] is False
    assert row["content_quality_flags"] == []
    assert "standard_status_requires_review" in row["quality_flags"]


def test_tampered_review_metadata_cannot_change_citation(sample):
    output, _ = _publish(sample, _manifest(sample))
    with sqlite3.connect(output) as conn:
        review = json.loads(conn.execute("SELECT review_json FROM evidence_reviews").fetchone()[0])
        review["pages"][0]["printed_page"] = "999"
        conn.execute("UPDATE evidence_reviews SET review_json=?", (json.dumps(review),))
    row = _clause(sample, output)
    assert row["quality_status"] == "review_required"
    assert "record_review_invalid" in row["quality_flags"]
    assert row["printed_page_start"] != "999"


def test_failed_review_keeps_existing_output(sample):
    manifest = _manifest(sample)
    manifest["reviews"][0]["base_record_sha256"] = "0" * 64
    output = sample["tmp"] / "reviewed.sqlite"
    output.write_bytes(b"preserved previous output")
    with pytest.raises(ValueError):
        _publish(sample, manifest)
    assert output.read_bytes() == b"preserved previous output"


def test_reviewed_current_authorized_record_can_support_advice_but_neighbor_cannot(sample):
    with sqlite3.connect(sample["db"]) as conn:
        conn.execute("UPDATE sources SET official_status='现行'")
    output, _ = _publish(sample, _manifest(sample))
    assert _clause(sample, output)["design_advice_allowed"] is True
    assert _clause(sample, output, "1.0.2")["design_advice_allowed"] is False


@pytest.mark.parametrize("current", [False, True])
def test_relocated_skill_backend_subprocess_preserves_review_and_source_gate(sample, current):
    from src.ai.building_standards_skill import BuildingStandardsSkill, BuildingStandardsSkillConfig

    if current:
        with sqlite3.connect(sample["db"]) as conn:
            conn.execute("UPDATE sources SET official_status='现行'")
    output, _ = _publish(sample, _manifest(sample))
    root = sample["tmp"] / "relocated-skill"
    (root / "scripts").mkdir(parents=True)
    (root / "assets/data").mkdir(parents=True)
    for name in ("standards_query.py", "standards_reviews.py"):
        shutil.copyfile(SCRIPTS / name, root / "scripts" / name)
    shutil.copyfile(output, root / "assets/data/standards.sqlite")
    for name in (
        "SKILL.md",
        "scripts/validate_full_corpus.py",
        "assets/data/manifest.json",
        "assets/data/validation_report.json",
    ):
        (root / name).write_text("{}", encoding="utf-8")
    (root / "assets/data/audit_catalog.json").write_text("[]", encoding="utf-8")
    skill = BuildingStandardsSkill(root=root, config=BuildingStandardsSkillConfig())
    context = skill.retrieve_if_applicable("GB 12345-2026 第1.0.1条", [])
    payload = json.loads(context.content)
    row = payload["evidence"][0]["results"][0]
    assert "1000m²" in row["text"]
    assert row["record_review"]["review_id"] == "test-clause"
    assert row["quality_status"] == "usable"
    assert payload["design_advice_allowed"] is current
    assert "record_review" in payload["policy"]["evidence_gate"]


def test_review_helpers_and_audit_survive_existing_package_install_flow(sample, monkeypatch):
    from zipfile import ZipFile

    from src.ai.building_standards_skill import (
        BuildingStandardsSkill,
        BuildingStandardsSkillConfig,
        install_skill_archive,
    )

    monkeypatch.syspath_prepend(str(SCRIPTS.parents[1]))
    packager = importlib.import_module("package_building_standards_skill")
    output, _ = _publish(sample, _manifest(sample))
    root = sample["tmp"] / "building-structure-standards"
    (root / "scripts").mkdir(parents=True)
    data = root / "assets/data"
    data.mkdir(parents=True)
    for name in ("standards_query.py", "standards_reviews.py", "validate_full_corpus.py"):
        shutil.copyfile(SCRIPTS / name, root / "scripts" / name)
    shutil.copyfile(output, data / "standards.sqlite")
    (root / "SKILL.md").write_text("Synthetic package smoke fixture", encoding="utf-8")
    for name, payload in {
        "audit_catalog.json": [],
        "source_manifest.json": {"sources": []},
        "parse_report.json": {"source_count": 1},
        "validation_report.json": {
            "failed_count": 0,
            "database_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        },
    }.items():
        (data / name).write_text(json.dumps(payload), encoding="utf-8")
    audit = sample["tmp"] / "audit.xlsx"
    audit.write_bytes(b"synthetic workbook fixture, not business data")
    cases = sample["tmp"] / "validation.yaml"
    cases.write_text("items: []\n", encoding="utf-8")
    archive = sample["tmp"] / "trial-skill.zip"
    packager.build_package(
        skill_root=root, output_zip=archive, audit_workbook=audit, validation_set=cases
    )
    with ZipFile(archive) as bundle:
        assert any(name.endswith("/scripts/standards_reviews.py") for name in bundle.namelist())
        assert not any(name.endswith(".pdf") for name in bundle.namelist())
    installed = install_skill_archive(archive, sample["tmp"] / "installed")
    skill = BuildingStandardsSkill(root=installed, config=BuildingStandardsSkillConfig())
    context = skill.retrieve_if_applicable("GB 12345-2026 第1.0.1条", [])
    payload = json.loads(context.content)
    assert payload["evidence"][0]["results"][0]["record_review"]["review_id"] == "test-clause"
    assert payload["design_advice_allowed"] is False
