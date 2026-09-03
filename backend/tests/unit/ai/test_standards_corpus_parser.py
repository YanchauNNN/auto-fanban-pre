from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import fitz
import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = (
    WORKTREE_ROOT / "tools" / "ai" / "building-structure-standards" / "scripts" / "build_corpus.py"
)


def load_parser_module() -> object:
    spec = importlib.util.spec_from_file_location("building_standards_build_corpus", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_pdf(path: Path) -> None:
    document = fitz.open()
    font = "china-s"
    page1 = document.new_page()
    page1.insert_text((72, 72), "GB/T TEST-2026 测试标准", fontname=font)
    page1.insert_text((72, 110), "1 总则", fontname=font)
    page1.insert_text(
        (72, 140),
        "1.0.1 本标准用于验证PDF条款切分。",
        fontname=font,
    )
    page1.insert_text((290, 800), "1", fontname=font)

    page2 = document.new_page()
    page2.insert_text((72, 72), "3 基本规定", fontname=font)
    page2.insert_text(
        (72, 105),
        "3.1.1 设计应根据场地条件确定。",
        fontname=font,
    )
    x0, y0, width, height = 72, 150, 240, 80
    for x in (x0, x0 + width / 2, x0 + width):
        page2.draw_line((x, y0), (x, y0 + height))
    for y in (y0, y0 + height / 2, y0 + height):
        page2.draw_line((x0, y), (x0 + width, y))
    page2.insert_text((82, 175), "Level", fontname="helv")
    page2.insert_text((202, 175), "Limit", fontname="helv")
    page2.insert_text((82, 215), "A", fontname="helv")
    page2.insert_text((202, 215), "100", fontname="helv")
    page2.insert_text((290, 800), "2", fontname=font)

    page3 = document.new_page()
    page3.insert_text(
        (72, 72),
        "4.1.2 构件必须满足安全要求。",
        fontname=font,
    )
    page3.insert_text((290, 800), "3", fontname=font)
    document.save(path)
    document.close()


def test_pdf_parser_splits_clauses_tables_and_page_anchors(tmp_path: Path) -> None:
    parser = load_parser_module()
    pdf_path = tmp_path / "gbt-test-2026.pdf"
    make_pdf(pdf_path)
    source = parser.SourceSpec(
        standard_code="GB/T TEST-2026",
        standard_name="测试标准",
        version="2026",
        source_path=str(pdf_path),
        official_source_url="https://official.example/test",
        authorization="内部离线检索已授权",
        confidentiality="内部",
    )

    parsed = parser.parse_source(source)

    assert len(parsed.pages) == 3
    assert parsed.pages[1].page_number == 2
    assert parsed.pages[1].printed_page == "2"
    assert parsed.pages[1].anchor.endswith("gbt-test-2026.pdf#page=2")
    clauses = {clause.clause_id: clause for clause in parsed.clauses}
    assert {"1", "1.0.1", "3", "3.1.1", "4.1.2"} <= set(clauses)
    assert clauses["3.1.1"].page_start == 2
    assert clauses["4.1.2"].page_start == 3
    assert "必须" in clauses["4.1.2"].text
    assert parsed.tables
    assert parsed.tables[0].page_number == 2
    assert parsed.tables[0].rows == [["Level", "Limit"], ["A", "100"]]
    assert parsed.tables[0].anchor.endswith("gbt-test-2026.pdf#page=2")


def test_html_parser_uses_semantic_and_declared_page_anchors(tmp_path: Path) -> None:
    parser = load_parser_module()
    html_path = tmp_path / "haf-test.html"
    html_path.write_text(
        """
        <!doctype html><html><body>
          <h1>HAF TEST-2026 测试法规</h1>
          <section id="clause-3-1-1" data-page="12">
            <h2>3.1.1 厂址评价应保留证据。</h2>
            <p>证据不足时不得给出确定性结论。</p>
          </section>
          <table id="table-1" data-page="13">
            <tr><th>事件</th><th>等级</th></tr>
            <tr><td>外部事件</td><td>A</td></tr>
          </table>
        </body></html>
        """,
        encoding="utf-8",
    )
    source = parser.SourceSpec(
        standard_code="HAF TEST-2026",
        standard_name="测试法规",
        version="2026",
        source_path=str(html_path),
        official_source_url="https://official.example/haf",
        authorization="内部离线检索已授权",
        confidentiality="公开",
    )

    parsed = parser.parse_source(source)

    clause = next(item for item in parsed.clauses if item.clause_id == "3.1.1")
    assert clause.page_start == 12
    assert clause.anchor.endswith("haf-test.html#clause-3-1-1")
    assert "证据不足" in clause.text
    assert parsed.tables[0].page_number == 13
    assert parsed.tables[0].rows[1] == ["外部事件", "A"]
    assert parsed.tables[0].anchor.endswith("haf-test.html#table-1")


def test_sqlite_index_supports_exact_clause_and_full_text_search(tmp_path: Path) -> None:
    parser = load_parser_module()
    pdf_path = tmp_path / "gbt-test-2026.pdf"
    make_pdf(pdf_path)
    source = parser.SourceSpec(
        standard_code="GB/T TEST-2026",
        standard_name="测试标准",
        version="2026",
        source_path=str(pdf_path),
        official_source_url="https://official.example/test",
        authorization="内部离线检索已授权",
        confidentiality="内部",
    )
    parsed = parser.parse_source(source)
    database = tmp_path / "standards.sqlite"

    report = parser.build_sqlite([parsed], database)
    exact = parser.query_index(
        database,
        standard_code="GB/T TEST-2026",
        clause_id="3.1.1",
    )
    search = parser.query_index(database, query="安全要求")

    assert report["source_count"] == 1
    assert report["page_count"] == 3
    assert report["clause_count"] >= 5
    assert report["table_count"] >= 1
    assert exact[0]["clause_id"] == "3.1.1"
    assert exact[0]["page_start"] == 2
    assert search[0]["clause_id"] == "4.1.2"
    assert search[0]["anchor"].endswith("#page=3")


def test_manifest_build_uses_external_source_root_and_stores_relative_path(
    tmp_path: Path,
) -> None:
    parser = load_parser_module()
    source_root = tmp_path / "规范下载"
    pdf_path = source_root / "001-010" / "GB T TEST-2026 测试标准.pdf"
    pdf_path.parent.mkdir(parents=True)
    make_pdf(pdf_path)
    manifest = tmp_path / "source_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "standard_code": "GB/T TEST-2026",
                        "standard_name": "测试标准",
                        "version": "2026",
                        "source_path": "001-010/GB T TEST-2026 测试标准.pdf",
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
    database = tmp_path / "standards.sqlite"

    report = parser.build_from_manifest(
        manifest,
        database,
        source_root=source_root,
    )

    assert report["source_count"] == 1
    connection = sqlite3.connect(database)
    try:
        stored_path = connection.execute("SELECT source_path FROM sources").fetchone()[0]
    finally:
        connection.close()
    assert stored_path == "001-010/GB T TEST-2026 测试标准.pdf"


def test_standalone_clause_number_and_subitems_keep_correct_boundaries():
    parser = load_parser_module()
    pages = [
        parser.PageRecord(
            22,
            "12",
            "3.1.6 前条。\n3.1.7\n本条正文。\n1 子项甲。\n2 子项乙。\nA.1.1 附录正文。",
            "test.pdf#page=22",
        )
    ]
    clauses = parser._split_clauses(pages, [])
    by_id = {row.clause_id: row for row in clauses}
    assert "3.1.7" in by_id
    assert "本条正文" not in by_id["3.1.6"].text
    assert "1 子项甲" in by_id["3.1.7"].text
    assert "2" not in by_id
    assert "A.1.1" in by_id


def test_clause_roles_and_page_ranges_do_not_absorb_commentary_or_blank_pages():
    parser = load_parser_module()
    pages = [
        parser.PageRecord(1, "", "目录\n1.0.1 总则 .... 2", "test.pdf#page=1"),
        parser.PageRecord(2, "", "1 总则\n1.0.1 正文依据。", "test.pdf#page=2"),
        parser.PageRecord(3, "", "", "test.pdf#page=3"),
        parser.PageRecord(4, "", "条文说明\n1.0.1 说明文字。", "test.pdf#page=4"),
    ]
    clauses = parser._split_clauses(pages, [])
    normative = next(
        row for row in clauses if row.clause_id == "1.0.1" and row.content_role == "normative"
    )
    assert normative.page_end == 2
    assert "说明文字" not in normative.text
    assert any(row.content_role == "commentary" for row in clauses)
    assert pages[0].content_role == "toc"


def test_failed_build_preserves_existing_database(tmp_path):
    parser = load_parser_module()
    database = tmp_path / "existing.sqlite"
    database.write_bytes(b"existing-database")

    def failing_input():
        raise RuntimeError("injected source failure")
        yield

    with pytest.raises(RuntimeError, match="injected"):
        parser.build_sqlite(failing_input(), database)
    assert database.read_bytes() == b"existing-database"


def test_pdf_blank_page_is_recorded_without_aborting_source(tmp_path):
    parser = load_parser_module()
    path = tmp_path / "blank.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "1.1.1 Evidence")
    doc.new_page()
    doc.save(path)
    doc.close()
    source = parser.SourceSpec("TEST", "test", "2026", str(path), "", "已授权", "内部")
    parsed = parser.parse_source(source)
    assert parsed.pages[1].quality_status == "blank"
    assert parsed.clauses[0].page_end == 1


def test_ocr_split_role_headings_exit_toc_and_enter_commentary():
    parser = load_parser_module()
    pages = [
        parser.PageRecord(6, "", "目录\n1 总则 .... 1", "test.pdf#page=6"),
        parser.PageRecord(7, "", "1总\n则\n1.0.1为明确设防类别，制定本标准。", "test.pdf#page=7"),
        parser.PageRecord(24, "", "条文\n说明", "test.pdf#page=24"),
        parser.PageRecord(25, "", "1总\n则\n1.0.1 说明依据。", "test.pdf#page=25"),
    ]
    clauses = parser._split_clauses(pages, [])
    assert (
        next(
            row for row in clauses if row.page_start == 7 and row.clause_id == "1.0.1"
        ).content_role
        == "normative"
    )
    assert (
        next(
            row for row in clauses if row.page_start == 25 and row.clause_id == "1.0.1"
        ).content_role
        == "commentary"
    )


def test_spaced_native_clause_numbers_are_indexed_without_rewriting_raw_text():
    parser = load_parser_module()
    text = "3. 2. 1 作用和作用效应\n说明内容。\n10. 10. 10 预埋件应考虑高温。\nA．1．1 附录条款。"
    page = parser.PageRecord(31, "28", text, "test.pdf#page=31", native_text=text)
    clauses = parser._split_clauses([page], [])
    assert {row.clause_id for row in clauses} == {"3.2.1", "10.10.10", "A.1.1"}
    assert page.native_text == text


def test_reindex_preserves_review_flags_and_checks_individual_ocr_lines():
    parser = load_parser_module()
    text = "1.0.1 " + "应按检测结果核对设计条件。" * 6
    page = parser.PageRecord(
        1,
        "1",
        text,
        "test.pdf#page=1",
        ocr_text=text,
        text_source="ocr",
        ocr_confidence=0.99,
        quality_status="review_required",
        quality_flags=["manual_review_pending"],
        ocr_provenance={
            "lines": [{"text": text, "score": 0.2, "box": [[0, 0], [10, 0], [10, 10], [0, 10]]}]
        },
    )
    source = parser.SourceSpec("TEST", "test", "2026", "test.pdf", "", "已授权", "内部")
    parsed = parser.reindex_parsed_source(parser.ParsedSource(source, "a" * 64, [page], [], []))
    assert parsed.pages[0].quality_status == "review_required"
    assert "low_confidence_line" in parsed.pages[0].quality_flags
    assert "manual_review_pending" in parsed.pages[0].quality_flags


def test_toc_continuation_does_not_become_normative_at_chapter_title():
    parser = load_parser_module()
    pages = [
        parser.PageRecord(1, "", "目录", "test.pdf#page=1"),
        parser.PageRecord(2, "", "1 总则\n2 术语 ...... 1\n3 结构 ...... 2", "test.pdf#page=2"),
        parser.PageRecord(3, "", "1 总则\n1.0.1 本规范用于确定项目的设计条件。", "test.pdf#page=3"),
    ]
    clauses = parser._split_clauses(pages, [])
    assert pages[1].content_role == "toc"
    assert next(row for row in clauses if row.clause_id == "1.0.1").content_role == "normative"
