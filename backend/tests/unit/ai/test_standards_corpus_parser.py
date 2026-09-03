from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import fitz

WORKTREE_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = (
    WORKTREE_ROOT
    / "tools"
    / "ai"
    / "building-structure-standards"
    / "scripts"
    / "build_corpus.py"
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
        stored_path = connection.execute(
            "SELECT source_path FROM sources"
        ).fetchone()[0]
    finally:
        connection.close()
    assert stored_path == "001-010/GB T TEST-2026 测试标准.pdf"
