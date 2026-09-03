from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path


def load_reuse():
    directory = (
        Path(__file__).resolve().parents[4] / "tools/ai/building-structure-standards/scripts"
    )
    sys.path.insert(0, str(directory))
    return importlib.import_module("standards_reuse")


def test_legacy_table_rows_are_preserved_but_not_promoted_to_usable(tmp_path):
    reuse = load_reuse()
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE sources(source_id INTEGER, source_sha256 TEXT);
            CREATE TABLE pages(source_id INTEGER, page_number INTEGER, printed_page TEXT, text TEXT, anchor TEXT);
            CREATE TABLE standard_tables(source_id INTEGER, table_id TEXT, page_number INTEGER, rows_json TEXT, markdown TEXT, anchor TEXT);
            INSERT INTO pages VALUES(1, 1, '1', '1.0.1 body', 'old.pdf#page=1');
            INSERT INTO standard_tables VALUES(1, 'p1-t1', 1, '[["A","B"],["1","2"]]', 'grid', 'old.pdf#page=1');
        """)
        db.execute("INSERT INTO sources VALUES(1, ?)", ("a" * 64,))
    original = path.read_bytes()
    source = reuse.corpus.SourceSpec("TEST", "test", "2026", "new.pdf", "", "已授权", "内部")
    parsed = reuse.BaselineSources([path]).read("a" * 64, source)
    assert parsed.tables[0].rows == [["A", "B"], ["1", "2"]]
    assert parsed.tables[0].quality_status == "review_required"
    assert "legacy_table_candidate" in parsed.tables[0].quality_flags
    assert path.read_bytes() == original


def test_ocr_enrichment_preserves_baseline_review_risks():
    reuse = load_reuse()
    source = reuse.corpus.SourceSpec("TEST", "test", "2026", "test.pdf", "", "已授权", "内部")
    current = reuse.corpus.ParsedSource(
        source, "a" * 64, [reuse.corpus.PageRecord(1, "1", "native", "p1")], [], []
    )
    prior = reuse.corpus.ParsedSource(
        source,
        "a" * 64,
        [
            reuse.corpus.PageRecord(
                1,
                "1",
                "OCR",
                "p1",
                ocr_text="OCR",
                quality_status="review_required",
                quality_flags=["manual_review_pending"],
            )
        ],
        [],
        [],
    )
    result = reuse.enrich_with_ocr(current, prior)
    assert result.pages[0].quality_status == "review_required"
    assert "manual_review_pending" in result.pages[0].quality_flags
