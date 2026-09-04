from __future__ import annotations

import gzip
import importlib.util
import json
import os
import shutil
import sys
from dataclasses import asdict
from pathlib import Path

import fitz
import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = (
    WORKTREE_ROOT
    / "tools"
    / "ai"
    / "building-structure-standards"
    / "scripts"
    / "build_full_corpus.py"
)


def _load_builder():
    spec = importlib.util.spec_from_file_location("standards_incremental_for_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_pdf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def _write_manifest(path: Path, relative_path: str) -> None:
    path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "standard_code": "GB/T TEST-2026",
                        "standard_name": "测试标准",
                        "version": "2026",
                        "source_path": relative_path,
                        "official_source_url": "",
                        "authorization": "内部离线检索已授权",
                        "confidentiality": "内部",
                        "official_status": "待核验",
                        "replacement_standard": "",
                        "major": "建筑结构总图",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_incremental_builder_reuses_unchanged_source_cache(tmp_path: Path) -> None:
    builder = _load_builder()
    source_root = tmp_path / "规范下载"
    relative_path = "001-010/GB T TEST-2026 测试标准.pdf"
    _write_pdf(source_root / relative_path, "1.1.1 cached evidence")
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, relative_path)
    output = tmp_path / "standards.sqlite"
    cache = tmp_path / "cache"

    first = builder.build_incremental_corpus(
        manifest_path=manifest,
        source_root=source_root,
        output_path=output,
        cache_dir=cache,
    )
    second = builder.build_incremental_corpus(
        manifest_path=manifest,
        source_root=source_root,
        output_path=output,
        cache_dir=cache,
    )

    assert first["parsed_count"] == 1
    assert first["cache_hit_count"] == 0
    assert first["published"] is True
    assert first["low_text_page_count"] == 1
    assert first["ocr_queue"] == [{"source_path": relative_path, "page_numbers": [1]}]
    assert second["parsed_count"] == 0
    assert second["cache_hit_count"] == 1
    assert second["published"] is True
    assert output.is_file()


def test_incremental_builder_keeps_previous_database_on_parse_failure(
    tmp_path: Path,
) -> None:
    builder = _load_builder()
    source_root = tmp_path / "规范下载"
    relative_path = "001-010/GB T TEST-2026 测试标准.pdf"
    _write_pdf(source_root / relative_path, "1.1.1 valid evidence")
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, relative_path)
    output = tmp_path / "standards.sqlite"
    cache = tmp_path / "cache"
    initial = builder.build_incremental_corpus(
        manifest_path=manifest,
        source_root=source_root,
        output_path=output,
        cache_dir=cache,
    )
    assert initial["published"] is True
    original = output.read_bytes()
    (source_root / relative_path).write_bytes(b"not-a-pdf")

    failed = builder.build_incremental_corpus(
        manifest_path=manifest,
        source_root=source_root,
        output_path=output,
        cache_dir=cache,
    )

    assert failed["failed_count"] == 1
    assert failed["published"] is False
    assert output.read_bytes() == original


def test_incremental_builder_writes_validation_for_published_database(
    tmp_path: Path,
) -> None:
    builder = _load_builder()
    source_root = tmp_path / "规范下载"
    relative_path = "001-010/GB T TEST-2026 测试标准.pdf"
    _write_pdf(source_root / relative_path, "1.1.1 structural validation evidence")
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, relative_path)
    output = tmp_path / "standards.sqlite"
    validation_report = tmp_path / "validation_report.json"

    result = builder.build_incremental_corpus(
        manifest_path=manifest,
        source_root=source_root,
        output_path=output,
        cache_dir=tmp_path / "cache",
        validation_report_path=validation_report,
    )

    validation = json.loads(validation_report.read_text(encoding="utf-8"))
    assert result["published"] is True
    assert validation["failed_count"] == 0
    assert validation["database_sha256"] == builder._sha256(output)
    assert validation["manifest_source_count"] == 1
    assert validation["database_source_count"] == 1
    assert validation["relative_source_paths_valid"] is True


def test_incremental_builder_validates_only_requested_source_subset(
    tmp_path: Path,
) -> None:
    builder = _load_builder()
    source_root = tmp_path / "规范下载"
    first_path = "001-010/GB T FIRST-2026 第一标准.pdf"
    second_path = "011-020/GB T SECOND-2026 第二标准.pdf"
    _write_pdf(source_root / first_path, "1.1.1 first evidence")
    _write_pdf(source_root / second_path, "2.1.1 second evidence")
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, first_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    second = dict(payload["sources"][0])
    second.update(
        {
            "standard_code": "GB/T SECOND-2026",
            "standard_name": "第二标准",
            "source_path": second_path,
        }
    )
    payload["sources"].append(second)
    manifest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = builder.build_incremental_corpus(
        manifest_path=manifest,
        source_root=source_root,
        output_path=tmp_path / "standards.sqlite",
        cache_dir=tmp_path / "cache",
        validation_report_path=tmp_path / "validation.json",
        max_sources=1,
    )

    assert result["published"] is True
    assert result["validation"]["manifest_source_count"] == 1
    assert result["validation"]["database_source_count"] == 1


def test_same_pdf_renamed_reuses_text_and_refreshes_metadata(tmp_path, monkeypatch):
    builder = _load_builder()
    root = tmp_path / "sources"
    _write_pdf(root / "old.pdf", "1.1.1 original evidence")
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, "old.pdf")
    kwargs = {
        "manifest_path": manifest,
        "source_root": root,
        "output_path": tmp_path / "index.sqlite",
        "cache_dir": tmp_path / "cache",
    }
    builder.build_incremental_corpus(**kwargs)
    shutil.copy2(root / "old.pdf", root / "new.pdf")
    _write_manifest(manifest, "new.pdf")

    def no_parse(*args, **kwargs):
        raise AssertionError("identical PDF must reuse raw text")

    monkeypatch.setattr(builder.corpus, "parse_source", no_parse)
    result = builder.build_incremental_corpus(**kwargs)
    assert result["published"]
    assert result["cache_hit_count"] == 1
    import sqlite3

    with sqlite3.connect(kwargs["output_path"]) as db:
        assert db.execute("select source_path from sources").fetchone()[0] == "new.pdf"
        assert db.execute("select anchor from pages").fetchone()[0] == "new.pdf#page=1"


def test_same_size_and_mtime_different_pdf_is_not_cache_hit(tmp_path):
    builder = _load_builder()
    root = tmp_path / "sources"
    pdf = root / "source.pdf"
    _write_pdf(pdf, "1.1.1 evidence")
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, "source.pdf")
    kwargs = {
        "manifest_path": manifest,
        "source_root": root,
        "output_path": tmp_path / "index.sqlite",
        "cache_dir": tmp_path / "cache",
    }
    builder.build_incremental_corpus(**kwargs)
    before = pdf.stat()
    pdf.write_bytes(b"x" * before.st_size)
    os.utime(pdf, ns=(before.st_atime_ns, before.st_mtime_ns))
    result = builder.build_incremental_corpus(**kwargs)
    assert result["cache_hit_count"] == 0
    assert not result["published"]
    assert result["failed_count"] == 1


def test_reuses_pdf_sha_baseline_ocr_without_parsing_or_running_ocr(tmp_path, monkeypatch):
    builder = _load_builder()
    root = tmp_path / "sources"
    pdf = root / "source.pdf"
    _write_pdf(pdf, "1.0.1 native evidence")
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, "source.pdf")
    spec = builder._source_spec(
        json.loads(manifest.read_text("utf-8"))["sources"][0], pdf, "source.pdf"
    )
    parsed = builder.corpus.parse_source(spec)
    parsed.pages[0].native_text = ""
    parsed.pages[0].text = "3.1.6 前条。\n3.1.7\n" + "加固设计应根据检测结果确定。" * 4
    parsed.pages[0].ocr_text = parsed.pages[0].text
    parsed.pages[0].text_source = "ocr"
    parsed.pages[0].ocr_confidence = 0.98
    baseline = tmp_path / "baseline.sqlite"
    builder.corpus.build_sqlite([parsed], baseline)
    before = baseline.read_bytes()

    def no_parse(*args, **kwargs):
        raise AssertionError("reuse must not extract PDF or run OCR")

    monkeypatch.setattr(builder.corpus, "parse_source", no_parse)
    result = builder.build_incremental_corpus(
        manifest_path=manifest,
        source_root=root,
        output_path=tmp_path / "candidate.sqlite",
        cache_dir=tmp_path / "cache",
        reuse_databases=[baseline],
    )
    assert result["published"]
    assert result["baseline_reuse_count"] == 1
    assert baseline.read_bytes() == before
    import sqlite3

    with sqlite3.connect(tmp_path / "candidate.sqlite") as db:
        assert db.execute("select count(*) from clauses where clause_id='3.1.7'").fetchone()[0] == 1
        quality, provenance = db.execute(
            "select quality_status,ocr_provenance_json from pages"
        ).fetchone()
        assert quality == "review_required"
        assert json.loads(provenance)["source_sha256"] == builder._sha256(pdf)


def test_parser_version_change_reindexes_existing_text_not_pdf(tmp_path, monkeypatch):
    builder = _load_builder()
    root = tmp_path / "sources"
    _write_pdf(root / "source.pdf", "1.1.1 original evidence")
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, "source.pdf")
    kwargs = {
        "manifest_path": manifest,
        "source_root": root,
        "output_path": tmp_path / "index.sqlite",
        "cache_dir": tmp_path / "cache",
    }
    builder.build_incremental_corpus(**kwargs)
    monkeypatch.setattr(builder.corpus, "PARSER_VERSION", "new-parser-for-test")
    monkeypatch.setattr(
        builder.corpus,
        "parse_source",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no PDF reparse")),
    )
    result = builder.build_incremental_corpus(**kwargs)
    assert result["published"]
    state = json.loads((tmp_path / "cache/state.json").read_text("utf-8"))
    assert state["sources"]["source.pdf"]["parser_version"] == "new-parser-for-test"


def test_cache_only_run_reports_missing_source_without_parsing(tmp_path, monkeypatch):
    builder = _load_builder()
    root = tmp_path / "sources"
    _write_pdf(root / "source.pdf", "1.1.1 evidence")
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, "source.pdf")
    called = []
    monkeypatch.setattr(builder.corpus, "parse_source", lambda *a: called.append(True))
    result = builder.build_incremental_corpus(
        manifest_path=manifest,
        source_root=root,
        output_path=tmp_path / "candidate.sqlite",
        cache_dir=tmp_path / "cache",
        require_cached=True,
    )
    assert called == []
    assert not result["published"]
    assert result["failed_count"] == 1


def test_duplicate_pdf_contents_keep_separate_source_paths(tmp_path):
    builder = _load_builder()
    root = tmp_path / "sources"
    _write_pdf(root / "first.pdf", "1.1.1 same evidence")
    shutil.copyfile(root / "first.pdf", root / "second.pdf")
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, "first.pdf")
    payload = json.loads(manifest.read_text("utf-8"))
    payload["sources"].append({**payload["sources"][0], "source_path": "second.pdf"})
    manifest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = builder.build_incremental_corpus(
        manifest_path=manifest,
        source_root=root,
        output_path=tmp_path / "candidate.sqlite",
        cache_dir=tmp_path / "cache",
    )
    assert result["published"]
    assert result["parsed_count"] == 1
    assert result["cache_hit_count"] == 1


def test_baseline_ocr_enriches_but_does_not_replace_current_native_assets(tmp_path):
    builder = _load_builder()
    root = tmp_path / "sources"
    pdf = root / "source.pdf"
    _write_pdf(pdf, "1.0.1 existing native")
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, "source.pdf")
    spec = builder._source_spec(json.loads(manifest.read_text("utf-8"))["sources"][0], pdf, "source.pdf")
    current = builder.corpus.parse_source(spec)
    current.tables.append(builder.corpus.TableRecord("retained-native", 1, [["a", "b"], ["c", "d"]], "grid", "source.pdf#page=1"))
    raw_cache = tmp_path / "raw"
    raw_cache.mkdir()
    builder._write_cache(raw_cache / "raw.json.gz", current)
    builder._write_state(raw_cache / "state.json", {"source.pdf": {"status": "parsed", "source_sha256": current.source_sha256, "cache_file": "raw.json.gz"}})
    baseline = builder.corpus.parse_source(spec)
    baseline.pages[0].native_text = "older native extraction"
    baseline.pages[0].ocr_text = "1.0.1 reused OCR body"
    baseline.pages[0].ocr_confidence = .98
    baseline_db = tmp_path / "baseline.sqlite"
    builder.corpus.build_sqlite([baseline], baseline_db)
    result = builder.build_incremental_corpus(
        manifest_path=manifest, source_root=root, output_path=tmp_path / "candidate.sqlite",
        cache_dir=tmp_path / "candidate-cache", reuse_cache_dirs=[raw_cache],
        reuse_databases=[baseline_db], require_cached=True,
    )
    assert result["published"]
    import sqlite3
    with sqlite3.connect(tmp_path / "candidate.sqlite") as db:
        native, ocr = db.execute("select native_text,ocr_text from pages").fetchone()
        assert "existing native" in native
        assert ocr == "1.0.1 reused OCR body"
        assert db.execute("select count(*) from standard_tables where table_id='retained-native'").fetchone()[0] == 1


def test_transient_windows_state_lock_is_retried_without_rebuilding_pdf(tmp_path, monkeypatch):
    builder = _load_builder()
    root = tmp_path / "sources"
    _write_pdf(root / "source.pdf", "1.0.1 native evidence")
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, "source.pdf")
    real_replace = os.replace
    failures = []

    def locked_replace(source, destination):
        if Path(destination).name == "state.json" and len(failures) < 2:
            failures.append(True)
            error = PermissionError("transient file handle")
            error.winerror = 32
            raise error
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", locked_replace)
    result = builder.build_incremental_corpus(
        manifest_path=manifest, source_root=root, output_path=tmp_path / "candidate.sqlite",
        cache_dir=tmp_path / "cache",
    )
    assert len(failures) == 2
    assert result["published"]
    assert result["parsed_count"] == 1


def test_permanent_windows_lock_preserves_destination_and_has_bounded_retries(tmp_path, monkeypatch):
    builder = _load_builder()
    io_module = sys.modules[builder.replace_atomic.__module__]
    source, destination = tmp_path / "new", tmp_path / "old"
    source.write_bytes(b"new data")
    destination.write_bytes(b"old data")
    attempts = []

    def locked(*args):
        attempts.append(True)
        error = PermissionError("persistent lock")
        error.winerror = 32
        raise error

    monkeypatch.setattr(os, "replace", locked)
    monkeypatch.setattr(io_module.time, "sleep", lambda _: None)
    import pytest
    with pytest.raises(PermissionError):
        builder.replace_atomic(source, destination)
    assert len(attempts) == io_module._policy()[0]
    assert destination.read_bytes() == b"old data"
    assert source.read_bytes() == b"new data"


@pytest.fixture
def incremental_case(tmp_path):
    builder = _load_builder()
    root = tmp_path / "sources"
    pdf = root / "source.pdf"
    _write_pdf(pdf, "1.0.1 preserved evidence")
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, "source.pdf")
    return builder, pdf, {
        "manifest_path": manifest,
        "source_root": root,
        "output_path": tmp_path / "candidate.sqlite",
        "cache_dir": tmp_path / "cache",
    }


@pytest.mark.parametrize("failure", ["missing", "invalid"])
@pytest.mark.parametrize("external_cache", [False, True])
def test_last_success_survives_repeated_failures_and_restored_pdf_reuses_cache(
    incremental_case, monkeypatch, failure, external_cache,
):
    builder, pdf, kwargs = incremental_case
    assert builder.build_incremental_corpus(**kwargs)["published"]
    original_pdf = pdf.read_bytes()
    original_database = kwargs["output_path"].read_bytes()
    state_path = kwargs["cache_dir"] / "state.json"
    successful_entry = json.loads(state_path.read_text("utf-8"))["sources"]["source.pdf"]
    if failure == "missing":
        pdf.unlink()
    else:
        pdf.write_bytes(b"not a PDF")
    failed_entries = []
    for _ in range(2):
        result = builder.build_incremental_corpus(**kwargs)
        assert result["failed_count"] == 1
        assert not result["published"]
        assert kwargs["output_path"].read_bytes() == original_database
        failed_entries.append(json.loads(state_path.read_text("utf-8"))["sources"]["source.pdf"])

    pdf.write_bytes(original_pdf)
    parse_calls = []

    def no_parse(*args, **kwargs):
        parse_calls.append(True)
        raise AssertionError("restored PDF must reuse last successful raw cache")

    monkeypatch.setattr(builder.corpus, "parse_source", no_parse)
    if external_cache:
        kwargs = {
            **kwargs,
            "reuse_cache_dirs": [kwargs["cache_dir"]],
            "cache_dir": kwargs["cache_dir"].with_name("recovery-cache"),
        }
    restored = builder.build_incremental_corpus(**kwargs, require_cached=True)
    assert restored["published"], restored["failures"]
    assert restored["parsed_count"] == 0
    assert restored["cache_hit_count"] == 1
    assert parse_calls == []
    for entry in failed_entries:
        assert entry["status"] == "failed"
        assert entry["last_success"] == successful_entry
        assert "last_success" not in entry["last_success"]


def test_each_build_validates_and_publishes_its_own_unique_staging(
    incremental_case, monkeypatch,
):
    builder, _, kwargs = incremental_case
    fixed_staging = kwargs["output_path"].with_suffix(".sqlite.staging")
    fixed_staging.write_bytes(b"another writer's staging")
    built, validated = [], []
    real_build = builder.corpus.build_sqlite
    real_validate = builder.full_validation.validate_full_corpus

    def build(sources, database_path):
        built.append(Path(database_path))
        return real_build(sources, database_path)

    def validate(**values):
        validated.append(Path(values["database"]))
        return real_validate(**values)

    monkeypatch.setattr(builder.corpus, "build_sqlite", build)
    monkeypatch.setattr(builder.full_validation, "validate_full_corpus", validate)
    for _ in range(2):
        result = builder.build_incremental_corpus(**kwargs)
        assert result["published"]
        assert result["validation"]["database_sha256"] == builder._sha256(kwargs["output_path"])
    assert len(set(built)) == 2
    assert built == validated
    assert all(path.parent == kwargs["output_path"].parent for path in built)
    assert all(not path.exists() for path in built)
    assert fixed_staging.read_bytes() == b"another writer's staging"


@pytest.mark.parametrize("phase", ["build", "validation", "publish"])
def test_failed_publication_cleans_only_own_staging_and_releases_writer(
    incremental_case, monkeypatch, phase,
):
    builder, _, kwargs = incremental_case
    assert builder.build_incremental_corpus(**kwargs)["published"]
    original = kwargs["output_path"].read_bytes()
    built = []
    real_build = builder.corpus.build_sqlite
    real_replace = builder.replace_atomic

    def build(sources, database_path):
        built.append(Path(database_path))
        if phase == "build":
            Path(database_path).write_bytes(b"partial SQLite")
            raise RuntimeError("injected publication failure")
        return real_build(sources, database_path)

    def validate(**values):
        raise RuntimeError("injected publication failure")

    def replace(source, destination):
        if Path(destination) == kwargs["output_path"]:
            raise RuntimeError("injected publication failure")
        return real_replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(builder.corpus, "build_sqlite", build)
        if phase == "validation":
            patch.setattr(builder.full_validation, "validate_full_corpus", validate)
        if phase == "publish":
            patch.setattr(builder, "replace_atomic", replace)
        with pytest.raises(RuntimeError, match="injected publication failure"):
            builder.build_incremental_corpus(**kwargs)
    assert kwargs["output_path"].read_bytes() == original
    assert len(built) == 1
    assert not built[0].exists()
    assert builder.build_incremental_corpus(**kwargs, require_cached=True)["published"]


def test_same_cache_rejects_concurrent_build_before_any_state_write(
    incremental_case, monkeypatch,
):
    builder, _, kwargs = incremental_case
    real_validate = builder.full_validation.validate_full_corpus
    attempted = []
    competing_output = kwargs["output_path"].with_name("competing.sqlite")

    def validate(**values):
        if not attempted:
            attempted.append(True)
            state = kwargs["cache_dir"] / "state.json"
            before = state.read_bytes()
            with pytest.raises(RuntimeError, match="cache writer already active"):
                builder.build_incremental_corpus(**{**kwargs, "output_path": competing_output})
            assert state.read_bytes() == before
            assert not competing_output.exists()
        return real_validate(**values)

    monkeypatch.setattr(builder.full_validation, "validate_full_corpus", validate)
    assert builder.build_incremental_corpus(**kwargs)["published"]
    assert attempted == [True]


@pytest.mark.parametrize("quality", ["missing", None, "", "usable", "review_required", "visual_required"])
def test_read_cache_preserves_legacy_table_cells_but_requires_review(
    incremental_case, quality,
):
    builder, pdf, kwargs = incremental_case
    item = json.loads(kwargs["manifest_path"].read_text("utf-8"))["sources"][0]
    parsed = builder.corpus.parse_source(builder._source_spec(item, pdf, "source.pdf"))
    table = builder.corpus.TableRecord(
        "original-table", 1, [["load", "kN"], ["10", "20"]],
        "| load | kN |\n| 10 | 20 |", "source.pdf#page=1",
        quality_flags=["original_flag"],
    )
    parsed.tables.append(table)
    payload = asdict(parsed)
    if quality == "missing":
        payload["tables"][0].pop("quality_status")
    else:
        payload["tables"][0]["quality_status"] = quality
    raw_cache = kwargs["cache_dir"]
    raw_cache.mkdir()
    cache_file = raw_cache / "raw.json.gz"
    with gzip.open(cache_file, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle)
    restored = builder._read_cache(cache_file)
    legacy = quality in {"missing", None, ""}
    expected_quality = "review_required" if legacy else quality
    expected_flags = ["original_flag", "legacy_table_candidate"] if legacy else ["original_flag"]
    assert restored.tables[0].quality_status == expected_quality
    assert restored.tables[0].quality_flags == expected_flags
    assert restored.tables[0].rows == table.rows
    assert restored.tables[0].markdown == table.markdown
    if quality == "visual_required":
        # The parser regenerates visual placeholders, unlike native table candidates.
        return

    builder._write_state(raw_cache / "state.json", {
        "source.pdf": {
            "status": "parsed", "source_sha256": parsed.source_sha256,
            "cache_file": cache_file.name, "cache_sha256": builder._sha256(cache_file),
        },
    })
    result = builder.build_incremental_corpus(**kwargs, require_cached=True)
    assert result["published"], result["failures"]
    import sqlite3

    with sqlite3.connect(kwargs["output_path"]) as database:
        actual_quality, flags, rows = database.execute(
            "select quality_status, quality_flags_json, rows_json from standard_tables "
            "where table_id='original-table'"
        ).fetchone()
    assert actual_quality == expected_quality
    assert json.loads(flags) == expected_flags
    assert json.loads(rows) == table.rows
