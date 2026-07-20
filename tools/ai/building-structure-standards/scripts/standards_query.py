from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DATABASE = (
    Path(__file__).resolve().parents[1] / "assets" / "data" / "standards.sqlite"
)
DEFAULT_CATALOG = (
    Path(__file__).resolve().parents[1] / "assets" / "data" / "audit_catalog.json"
)


def get_clause(
    database: Path | str,
    standard_code: str,
    clause_id: str,
) -> dict[str, Any]:
    rows = _fetch_clauses(
        database,
        where="s.standard_code = ? AND c.clause_id = ?",
        params=[standard_code, clause_id],
        limit=20,
    )
    return _result_envelope(
        rows,
        missing_message=(
            f"证据不足：离线语料中未找到 {standard_code} 第{clause_id}条。"
        ),
    )


def search(
    database: Path | str,
    query: str,
    *,
    standard_code: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    normalized_query = re.sub(r"\s+", "", query)
    wildcard = f"%{normalized_query}%"
    where = """
        (
            REPLACE(REPLACE(REPLACE(c.text, char(10), ''), char(13), ''), ' ', '')
                LIKE ?
            OR REPLACE(REPLACE(REPLACE(c.heading, char(10), ''), char(13), ''), ' ', '')
                LIKE ?
            OR REPLACE(s.standard_name, ' ', '') LIKE ?
        )
    """
    params: list[Any] = [wildcard, wildcard, wildcard]
    if standard_code:
        where = f"s.standard_code = ? AND {where}"
        params.insert(0, standard_code)
    rows = _fetch_clauses(database, where=where, params=params, limit=limit)
    return _result_envelope(
        rows,
        missing_message=(
            f"证据不足：已授权离线语料中没有与“{query}”直接匹配的条款。"
        ),
    )


def get_standard(
    database: Path | str,
    standard_code: str,
) -> dict[str, Any]:
    connection = _connect(database)
    try:
        row = connection.execute(
            """
            SELECT
                s.*,
                (SELECT COUNT(*) FROM pages p WHERE p.source_id=s.source_id)
                    AS page_count,
                (SELECT COUNT(*) FROM clauses c WHERE c.source_id=s.source_id)
                    AS clause_count,
                (SELECT COUNT(*) FROM standard_tables t WHERE t.source_id=s.source_id)
                    AS table_count
            FROM sources s
            WHERE s.standard_code = ?
            """,
            (standard_code,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return {
            "found": False,
            "evidence_insufficient": True,
            "standard": None,
            "warnings": [f"证据不足：离线语料中没有 {standard_code}。"],
        }
    standard = dict(row)
    return {
        "found": True,
        "evidence_insufficient": False,
        "standard": standard,
        "warnings": _source_warnings(standard),
    }


def get_table(
    database: Path | str,
    standard_code: str,
    table_id: str,
) -> dict[str, Any]:
    connection = _connect(database)
    try:
        row = connection.execute(
            """
            SELECT
                s.standard_code, s.standard_name, s.version,
                s.official_status, s.authorization, s.confidentiality,
                t.table_id, t.page_number, p.printed_page,
                t.rows_json, t.markdown, t.anchor
            FROM standard_tables t
            JOIN sources s ON s.source_id=t.source_id
            LEFT JOIN pages p
                ON p.source_id=t.source_id AND p.page_number=t.page_number
            WHERE s.standard_code=? AND t.table_id=?
            """,
            (standard_code, table_id),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return {
            "found": False,
            "evidence_insufficient": True,
            "table": None,
            "warnings": [
                f"证据不足：离线语料中未找到 {standard_code} 表 {table_id}。"
            ],
        }
    result = dict(row)
    result["rows"] = json.loads(result.pop("rows_json"))
    result["citation"] = (
        f"{result['standard_code']}（{result['version']}），"
        f"表 {result['table_id']}，{_page_label(result['page_number'], result['printed_page'])}"
        f"（{result['anchor']}）"
    )
    return {
        "found": True,
        "evidence_insufficient": False,
        "table": result,
        "warnings": _source_warnings(result),
    }


def find_version_conflicts(
    database: Path | str,
    standard_code: str,
) -> dict[str, Any]:
    base = re.sub(r"-\d{4}(?:.*)?$", "", standard_code).strip()
    connection = _connect(database)
    try:
        rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT
                    standard_code, standard_name, version, official_status,
                    replacement_standard, official_source_url,
                    authorization, confidentiality
                FROM sources
                WHERE standard_code = ? OR standard_code LIKE ?
                """,
                (standard_code, f"{base}-%"),
            )
        ]
    finally:
        connection.close()
    rows.sort(
        key=lambda item: (
            item["official_status"] == "现行",
            _version_sort_key(item["version"]),
        ),
        reverse=True,
    )
    current = next(
        (item for item in rows if item["official_status"] == "现行"),
        rows[0] if rows else None,
    )
    return {
        "query_code": standard_code,
        "base_code": base,
        "has_conflict": len(rows) > 1,
        "recommended_code": current["standard_code"] if current else "",
        "versions": rows,
        "warnings": (
            ["发现多个版本；设计建议应优先采用官方现行版本，并核对项目适用日期。"]
            if len(rows) > 1
            else []
        ),
    }


def get_catalog_entry(
    catalog_path: Path | str,
    standard_code: str,
) -> dict[str, Any]:
    records = [
        item
        for item in _load_catalog(catalog_path)
        if str(item.get("standard_code") or "") == standard_code
    ]
    if not records:
        return {
            "found": False,
            "content_evidence_available": False,
            "record": None,
            "warnings": [f"审计目录中未找到 {standard_code}。"],
        }
    record = records[0]
    content_available = bool(
        record.get("included_in_corpus") and record.get("local_file")
    )
    warnings = _source_warnings(record)
    if not content_available:
        warnings.append(
            "该条目只有审计元数据，没有已授权全文，不能回答精确条款或数值。"
        )
    return {
        "found": True,
        "content_evidence_available": content_available,
        "record": record,
        "warnings": list(dict.fromkeys(warnings)),
    }


def find_catalog_version_conflicts(
    catalog_path: Path | str,
    standard_code: str,
) -> dict[str, Any]:
    base = re.sub(r"-\d{4}(?:.*)?$", "", standard_code).strip()
    rows = [
        item
        for item in _load_catalog(catalog_path)
        if str(item.get("standard_code") or "") == standard_code
        or str(item.get("standard_code") or "").startswith(f"{base}-")
    ]
    rows.sort(
        key=lambda item: (
            str(item.get("official_status") or "") == "现行",
            _version_sort_key(item.get("standard_code")),
        ),
        reverse=True,
    )
    current = next(
        (item for item in rows if item.get("official_status") == "现行"),
        rows[0] if rows else None,
    )
    return {
        "query_code": standard_code,
        "base_code": base,
        "has_conflict": len(rows) > 1,
        "recommended_code": (
            str(current.get("standard_code") or "") if current else ""
        ),
        "versions": rows,
        "warnings": (
            ["审计目录发现多个版本；必须结合官方状态和项目适用日期复核。"]
            if len(rows) > 1
            else []
        ),
    }


def collect_advice_evidence(
    database: Path | str,
    catalog_path: Path | str,
    query: str,
    *,
    requested_codes: list[str] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    requested = list(dict.fromkeys(requested_codes or []))
    search_result = search(database, query, limit=limit)
    available_codes: list[str] = []
    missing_codes: list[str] = []
    warnings = list(search_result["warnings"])

    if requested:
        for code in requested:
            standard = get_standard(database, code)
            if standard["found"]:
                available_codes.append(code)
                continue
            catalog = get_catalog_entry(catalog_path, code)
            if catalog["found"] and catalog["content_evidence_available"]:
                available_codes.append(code)
            else:
                missing_codes.append(code)
                warnings.extend(catalog["warnings"])
    else:
        available_codes = list(
            dict.fromkeys(
                item["standard_code"] for item in search_result["results"]
            )
        )

    evidence_level = "none"
    if search_result["found"]:
        evidence_level = "partial" if missing_codes else "sufficient"
    if missing_codes:
        warnings.append(
            "部分指定规范没有已授权全文，不能形成完整的跨规范结论或最终设计依据。"
        )
    return {
        "query": query,
        "evidence_level": evidence_level,
        "design_advice_allowed": evidence_level == "sufficient",
        "available_codes": available_codes,
        "missing_content_codes": missing_codes,
        "evidence": search_result["results"],
        "warnings": list(dict.fromkeys(warnings)),
    }


def _fetch_clauses(
    database: Path | str,
    *,
    where: str,
    params: list[Any],
    limit: int,
) -> list[dict[str, Any]]:
    connection = _connect(database)
    try:
        rows = [
            dict(row)
            for row in connection.execute(
                f"""
                SELECT
                    s.standard_code, s.standard_name, s.version, s.major,
                    s.official_status, s.replacement_standard,
                    s.official_source_url, s.authorization, s.confidentiality,
                    c.clause_id, c.heading, c.text, c.page_start,
                    c.page_end, c.anchor, c.table_ids_json,
                    p.printed_page AS printed_page_start
                FROM clauses c
                JOIN sources s ON s.source_id=c.source_id
                LEFT JOIN pages p
                    ON p.source_id=c.source_id AND p.page_number=c.page_start
                WHERE {where}
                ORDER BY
                    CASE WHEN s.official_status='现行' THEN 0 ELSE 1 END,
                    s.standard_code, c.page_start, c.clause_id
                LIMIT ?
                """,
                [*params, max(1, limit)],
            )
        ]
    finally:
        connection.close()
    for row in rows:
        row["table_ids"] = json.loads(row.pop("table_ids_json"))
        page = (
            str(row["page_start"])
            if row["page_start"] == row["page_end"]
            else f"{row['page_start']}-{row['page_end']}"
        )
        row["citation"] = (
            f"{row['standard_code']}（{row['version']}），"
            f"第{row['clause_id']}条，"
            f"{_page_label(page, row['printed_page_start'])}（{row['anchor']}）"
        )
    return rows


def _result_envelope(
    rows: list[dict[str, Any]],
    *,
    missing_message: str,
) -> dict[str, Any]:
    warnings: list[str] = []
    for row in rows:
        warnings.extend(_source_warnings(row))
    warnings = list(dict.fromkeys(warnings))
    if not rows:
        warnings.append(missing_message)
    return {
        "found": bool(rows),
        "evidence_insufficient": not rows,
        "results": rows,
        "warnings": warnings,
    }


def _source_warnings(source: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    status = str(source.get("official_status") or "")
    replacement = str(source.get("replacement_standard") or "")
    if status and status != "现行":
        warnings.append(
            f"{source.get('standard_code', '该标准')} 官方状态为“{status}”，"
            "不得直接作为当前设计依据。"
        )
    if status == "废止" and replacement:
        warnings.append(f"官方替代信息：{replacement}。")
    authorization = str(source.get("authorization") or "")
    if "已授权" not in authorization:
        warnings.append(f"语料授权状态需复核：{authorization or '未知'}。")
    return warnings


def _connect(database: Path | str) -> sqlite3.Connection:
    path = Path(database)
    if not path.is_file():
        raise FileNotFoundError(f"standards database does not exist: {path}")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _load_catalog(path: Path | str) -> list[dict[str, Any]]:
    catalog_path = Path(path)
    if not catalog_path.is_file():
        raise FileNotFoundError(f"audit catalog does not exist: {catalog_path}")
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("audit catalog must be a JSON array")
    return [item for item in payload if isinstance(item, dict)]


def _version_sort_key(value: Any) -> tuple[int, str]:
    text = str(value or "")
    match = re.search(r"\d{4}", text)
    return (int(match.group(0)) if match else 0, text)


def _page_label(physical_page: Any, printed_page: Any) -> str:
    physical = str(physical_page)
    printed = str(printed_page or "").strip()
    if printed and printed != physical:
        return f"PDF第{physical}页（印刷页{printed}）"
    return f"第{physical}页"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Query the authorized offline building standards corpus."
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    subparsers = parser.add_subparsers(dest="command", required=True)

    clause = subparsers.add_parser("clause")
    clause.add_argument("standard_code")
    clause.add_argument("clause_id")

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--code", default="")
    search_parser.add_argument("--limit", type=int, default=10)

    standard = subparsers.add_parser("standard")
    standard.add_argument("standard_code")

    table = subparsers.add_parser("table")
    table.add_argument("standard_code")
    table.add_argument("table_id")

    versions = subparsers.add_parser("versions")
    versions.add_argument("standard_code")

    catalog = subparsers.add_parser("catalog")
    catalog.add_argument("standard_code")

    catalog_versions = subparsers.add_parser("catalog-versions")
    catalog_versions.add_argument("standard_code")

    advice = subparsers.add_parser("advice")
    advice.add_argument("query")
    advice.add_argument("--code", action="append", default=[])
    advice.add_argument("--limit", type=int, default=20)

    args = parser.parse_args(argv)
    if args.command == "clause":
        result = get_clause(args.database, args.standard_code, args.clause_id)
    elif args.command == "search":
        result = search(
            args.database,
            args.query,
            standard_code=args.code,
            limit=args.limit,
        )
    elif args.command == "standard":
        result = get_standard(args.database, args.standard_code)
    elif args.command == "table":
        result = get_table(args.database, args.standard_code, args.table_id)
    elif args.command == "versions":
        result = find_version_conflicts(args.database, args.standard_code)
    elif args.command == "catalog":
        result = get_catalog_entry(args.catalog, args.standard_code)
    elif args.command == "catalog-versions":
        result = find_catalog_version_conflicts(args.catalog, args.standard_code)
    else:
        result = collect_advice_evidence(
            args.database,
            args.catalog,
            args.query,
            requested_codes=args.code,
            limit=args.limit,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
