from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = (
    WORKTREE_ROOT
    / "tools"
    / "ai"
    / "building-structure-standards"
    / "scripts"
)


def load_module(filename: str, name: str) -> object:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_versioned_database(tmp_path: Path) -> tuple[object, Path]:
    builder = load_module("build_corpus.py", "standards_builder_for_query")
    sources = []
    for year, status, replacement in (
        ("2020", "废止", "GB/T DEMO-2026"),
        ("2026", "现行", ""),
    ):
        html = tmp_path / f"demo-{year}.html"
        html.write_text(
            f"""
            <section id="clause-3-1-1" data-page="12">
              <h2>3.1.1 {year}版设计要求。</h2>
              <p>{'旧版要求' if year == '2020' else '当前安全要求'}。</p>
            </section>
            """,
            encoding="utf-8",
        )
        spec = builder.SourceSpec(
            standard_code=f"GB/T DEMO-{year}",
            standard_name="版本演示标准",
            version=year,
            source_path=str(html),
            official_source_url=f"https://official.example/{year}",
            authorization="内部离线检索已授权",
            confidentiality="公开",
            official_status=status,
            replacement_standard=replacement,
            major="结构",
        )
        sources.append(builder.parse_source(spec))
    database = tmp_path / "standards.sqlite"
    builder.build_sqlite(sources, database)
    return load_module("standards_query.py", "standards_query_for_test"), database


def test_exact_clause_returns_version_page_anchor_and_citation(tmp_path: Path) -> None:
    query, database = build_versioned_database(tmp_path)

    result = query.get_clause(database, "GB/T DEMO-2026", "3.1.1")

    assert result["found"] is True
    assert result["evidence_insufficient"] is False
    assert result["results"][0]["version"] == "2026"
    assert result["results"][0]["page_start"] == 12
    assert result["results"][0]["anchor"].endswith(
        "demo-2026.html#clause-3-1-1"
    )
    assert "GB/T DEMO-2026" in result["results"][0]["citation"]
    assert "第3.1.1条" in result["results"][0]["citation"]
    assert "第12页" in result["results"][0]["citation"]


def test_deprecated_standard_returns_replacement_warning(tmp_path: Path) -> None:
    query, database = build_versioned_database(tmp_path)

    result = query.get_clause(database, "GB/T DEMO-2020", "3.1.1")

    assert result["found"] is True
    assert any("废止" in warning for warning in result["warnings"])
    assert any("GB/T DEMO-2026" in warning for warning in result["warnings"])


def test_version_conflict_lists_current_and_deprecated_sources(tmp_path: Path) -> None:
    query, database = build_versioned_database(tmp_path)

    result = query.find_version_conflicts(database, "GB/T DEMO-2020")

    assert result["has_conflict"] is True
    assert [item["version"] for item in result["versions"]] == ["2026", "2020"]
    assert result["recommended_code"] == "GB/T DEMO-2026"


def test_search_without_evidence_is_explicit(tmp_path: Path) -> None:
    query, database = build_versioned_database(tmp_path)

    result = query.search(database, "不存在的防火间距")

    assert result["found"] is False
    assert result["evidence_insufficient"] is True
    assert result["results"] == []
    assert any("证据不足" in warning for warning in result["warnings"])


def test_catalog_reports_metadata_without_claiming_clause_evidence(tmp_path: Path) -> None:
    query, _ = build_versioned_database(tmp_path)
    catalog = tmp_path / "audit_catalog.json"
    catalog.write_text(
        json.dumps(
            [
                {
                    "standard_code": "GB DEMO-2020",
                    "standard_name": "演示标准",
                    "official_status": "废止",
                    "replacement_standard": "GB DEMO-2026",
                    "official_source_url": "https://official.example/2020",
                    "downloadability": "无官方全文",
                    "authorization": "待确认",
                    "confidentiality": "公开",
                    "local_file": "",
                    "included_in_corpus": False,
                },
                {
                    "standard_code": "GB DEMO-2026",
                    "standard_name": "演示标准",
                    "official_status": "现行",
                    "replacement_standard": "无官方替代信息",
                    "official_source_url": "https://official.example/2026",
                    "downloadability": "可人工下载",
                    "authorization": "待确认",
                    "confidentiality": "公开",
                    "local_file": "",
                    "included_in_corpus": False,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    entry = query.get_catalog_entry(catalog, "GB DEMO-2020")
    conflict = query.find_catalog_version_conflicts(catalog, "GB DEMO-2020")

    assert entry["found"] is True
    assert entry["content_evidence_available"] is False
    assert entry["record"]["official_status"] == "废止"
    assert any("不能回答精确条款" in warning for warning in entry["warnings"])
    assert conflict["has_conflict"] is True
    assert conflict["recommended_code"] == "GB DEMO-2026"


def test_cross_standard_advice_is_partial_when_one_source_has_no_fulltext(
    tmp_path: Path,
) -> None:
    query, database = build_versioned_database(tmp_path)
    catalog = tmp_path / "audit_catalog.json"
    catalog.write_text(
        json.dumps(
            [
                {
                    "standard_code": "GB/T DEMO-2026",
                    "standard_name": "版本演示标准",
                    "official_status": "现行",
                    "authorization": "内部离线检索已授权",
                    "confidentiality": "公开",
                    "local_file": "demo-2026.html",
                    "included_in_corpus": True,
                },
                {
                    "standard_code": "NB/T MISSING-2026",
                    "standard_name": "缺件标准",
                    "official_status": "现行",
                    "authorization": "待确认",
                    "confidentiality": "公开",
                    "local_file": "",
                    "included_in_corpus": False,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = query.collect_advice_evidence(
        database,
        catalog,
        "当前安全要求",
        requested_codes=["GB/T DEMO-2026", "NB/T MISSING-2026"],
    )

    assert result["evidence_level"] == "partial"
    assert result["design_advice_allowed"] is False
    assert result["available_codes"] == ["GB/T DEMO-2026"]
    assert result["missing_content_codes"] == ["NB/T MISSING-2026"]
    assert any("跨规范结论" in warning for warning in result["warnings"])
