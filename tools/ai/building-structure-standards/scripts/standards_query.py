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
    if not normalized_query:
        return _result_envelope([], missing_message="证据不足：查询词不能为空。")
    where = """
        (
            instr(normalize_text(c.text), ?) > 0
            OR instr(normalize_text(c.heading), ?) > 0
        )
    """
    params: list[Any] = [normalized_query.casefold(), normalized_query.casefold()]
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
            "design_advice_allowed": False,
            "standard": None,
            "warnings": [f"证据不足：离线语料中没有 {standard_code}。"],
        }
    standard = dict(row)
    return {
        "found": True,
        "evidence_insufficient": True,
        "design_advice_allowed": False,
        "standard": standard,
        "warnings": [*_source_warnings(standard), "标准元数据不代表相关正文证据。"],
    }


def get_table(
    database: Path | str,
    standard_code: str,
    table_id: str,
    *,
    source_id: int | None = None,
) -> dict[str, Any]:
    connection = _connect(database)
    try:
        columns = _columns(connection, "standard_tables")
        source_sha = "s.source_sha256" if "source_sha256" in _columns(connection, "sources") else "NULL"
        label_match = (
            " OR normalize_table_label(t.table_label)=?"
            if "table_label" in columns and _normalize_table_label(table_id)
            else ""
        )
        source_filter = " AND t.source_id=?" if source_id is not None else ""
        params: list[Any] = [standard_code, table_id]
        if label_match:
            params.append(_normalize_table_label(table_id))
        if source_id is not None:
            params.append(source_id)
        rows = connection.execute(
            f"""
            SELECT
                s.standard_code, s.standard_name, s.version, s.replacement_standard,
                s.official_status, s.authorization, s.confidentiality,
                {source_sha} AS source_sha256,
                t.*, p.printed_page
            FROM standard_tables t
            JOIN sources s ON s.source_id=t.source_id
            LEFT JOIN pages p
                ON p.source_id=t.source_id AND p.page_number=t.page_number
            WHERE s.standard_code=? AND (t.table_id=?{label_match}){source_filter}
            ORDER BY t.page_number, t.table_id
            """,
            params,
        ).fetchall()
        results = []
        for row in rows:
            result = dict(row)
            flags = _quality_flags(result.get("quality_flags_json"))
            table_status = result.get("quality_status") or "unknown"
            result["table_quality_status"] = table_status
            result["table_label"] = result.get("table_label") or result["table_id"]
            if not {"quality_status", "quality_flags_json"} <= columns:
                flags.append("table_quality_schema_missing")
            if table_status != "usable":
                flags.append(f"table_{table_status}")
            try:
                cells = json.loads(result.pop("rows_json"))
            except (ValueError, TypeError):
                cells = []
            if (
                not isinstance(cells, list) or not cells
                or not all(isinstance(row, list) and row for row in cells)
                or len({len(row) for row in cells}) != 1
            ):
                flags.append("table_rows_unverified")
                cells = []
            result["rows"] = [] if table_status == "visual_required" else cells
            if table_status == "visual_required":
                result["markdown"] = ""
            _attach_page_quality(connection, result, result["page_number"], result["page_number"])
            result["content_role"] = (
                result["page_quality"][0]["content_role"] if result["page_quality"] else "unknown"
            )
            _finish_quality(result, flags)
            if table_status == "visual_required":
                result["quality_status"] = "visual_required"
            result["links"] = _source_links(result["source_id"], result["page_number"])
            result["citation"] = (
                f"{result['standard_code']}（{result['version']}），"
                f"表 {_normalize_table_label(result['table_label'])}，"
                f"{_page_label(result['page_number'], result['printed_page'])}（{result['anchor']}）"
            )
            results.append(result)
    finally:
        connection.close()
    if not results:
        return {
            "found": False,
            "evidence_insufficient": True,
            "design_advice_allowed": False,
            "table": None,
            "warnings": [
                f"证据不足：离线语料中未找到 {standard_code} 表 {table_id}。"
            ],
        }
    results.sort(key=lambda item: (not item["design_advice_allowed"], item["content_role"] != "normative"))
    result = results[0]
    envelope = _result_envelope([result], missing_message="")
    return {
        **{key: value for key, value in envelope.items() if key != "results"},
        "table": result,
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
    searches = [
        search(database, query, standard_code=code, limit=limit)
        for code in (requested or [""])
    ]
    evidence = [row for result in searches for row in result["results"]]
    available_codes: list[str] = []
    missing_codes: list[str] = []
    insufficient_codes: list[str] = []
    warnings = [warning for result in searches for warning in result["warnings"]]
    for code in requested or list(dict.fromkeys(row["standard_code"] for row in evidence)):
        matches = [row for row in evidence if row["standard_code"] == code]
        if any(row["design_advice_allowed"] for row in matches):
            available_codes.append(code)
        elif matches:
            insufficient_codes.append(code)
        else:
            missing_codes.append(code)
            # Catalog metadata is diagnostic only; it can never supply body evidence.
            if Path(catalog_path).is_file():
                warnings.extend(get_catalog_entry(catalog_path, code)["warnings"])
    allowed = bool(available_codes) and not missing_codes and not insufficient_codes
    evidence_level = "sufficient" if allowed else ("partial" if evidence else "none")
    if missing_codes or insufficient_codes:
        warnings.append(
            "部分指定规范缺少相关合格正文证据，不能形成完整的跨规范结论或最终设计依据。"
        )
    return {
        "query": query,
        "evidence_level": evidence_level,
        "evidence_insufficient": not allowed,
        "design_advice_allowed": allowed,
        "available_codes": available_codes,
        "missing_content_codes": missing_codes,
        "insufficient_quality_codes": insufficient_codes,
        "evidence": evidence,
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
        role = "c.content_role" if "content_role" in _columns(connection, "clauses") else "'unknown'"
        source_sha = "s.source_sha256" if "source_sha256" in _columns(connection, "sources") else "NULL"
        rows = [
            dict(row)
            for row in connection.execute(
                f"""
                SELECT
                    s.source_id, s.standard_code, s.standard_name, s.version, s.major,
                    s.official_status, s.replacement_standard,
                    s.official_source_url, s.authorization, s.confidentiality,
                    {source_sha} AS source_sha256,
                    c.clause_id, c.heading, c.text, c.page_start,
                    c.page_end, c.anchor, c.table_ids_json,
                    {role} AS content_role,
                    p.printed_page AS printed_page_start
                FROM clauses c
                JOIN sources s ON s.source_id=c.source_id
                LEFT JOIN pages p
                    ON p.source_id=c.source_id AND p.page_number=c.page_start
                WHERE {where}
                ORDER BY
                    CASE WHEN {role}='normative' THEN 0 ELSE 1 END,
                    CASE WHEN s.official_status='现行' THEN 0 ELSE 1 END,
                    s.standard_code, c.page_start, c.clause_id
                LIMIT ?
                """,
                [*params, max(0, limit)],
            )
        ]
        for row in rows:
            row["table_ids"] = json.loads(row.pop("table_ids_json"))
            _attach_page_quality(connection, row, row["page_start"], row["page_end"])
            flags = [] if str(row.get("text") or "").strip() else ["empty_clause_text"]
            for table_id in row["table_ids"]:
                table = get_table(
                    database, row["standard_code"], table_id, source_id=row["source_id"],
                )
                if table["evidence_insufficient"]:
                    flags.append(f"table_evidence_insufficient:{table_id}")
            _finish_quality(row, flags)
    finally:
        connection.close()
    for row in rows:
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
        row["links"] = _source_links(row["source_id"], row["page_start"])
    return rows


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}


def _quality_flags(raw: Any) -> list[str]:
    try:
        flags = json.loads(raw)
    except (TypeError, ValueError):
        return ["quality_flags_missing_or_invalid"]
    if not isinstance(flags, list) or any(not isinstance(flag, str) or not flag for flag in flags):
        return ["quality_flags_missing_or_invalid"]
    return flags


def _attach_page_quality(
    connection: sqlite3.Connection, result: dict[str, Any], start: int, end: int,
) -> None:
    columns = _columns(connection, "pages")
    required = {"quality_status", "quality_flags_json", "content_role", "text_source"}
    flags = [] if required <= columns else ["page_quality_schema_missing"]
    pages = [dict(row) for row in connection.execute(
        "SELECT * FROM pages WHERE source_id=? AND page_number BETWEEN ? AND ? ORDER BY page_number",
        (result["source_id"], start, end),
    )]
    numbers = [page["page_number"] for page in pages]
    if start < 1 or end < start or len(set(numbers)) != end - start + 1 or len(set(numbers)) != len(numbers):
        flags.append("page_quality_missing_or_ambiguous")
    quality = []
    for page in pages:
        status = page.get("quality_status") or page.get("quality") or "unknown"
        legacy_status = page.get("quality")
        page_flags = _quality_flags(page.get("quality_flags_json"))
        if legacy_status and legacy_status != "usable":
            status = legacy_status
        role = page.get("content_role") or "unknown"
        if status != "usable":
            flags.append(f"page_{page['page_number']}:{status}")
        if role != "normative":
            flags.append(f"page_{page['page_number']}:non_normative:{role}")
        flags.extend(page_flags)
        quality.append({
            "page_number": page["page_number"],
            "printed_page": page.get("printed_page"),
            "quality_status": status,
            "quality_flags": page_flags,
            "content_role": role,
            "text_source": page.get("text_source") or "unknown",
            "ocr_confidence": page.get("ocr_confidence"),
            "ocr_provenance_json": page.get("ocr_provenance_json"),
        })
    result["page_quality"] = quality
    result["quality_flags"] = list(dict.fromkeys(flags))


def _finish_quality(result: dict[str, Any], extra_flags: list[str]) -> None:
    flags = [*result.get("quality_flags", []), *extra_flags]
    if result.get("content_role") != "normative":
        flags.append("non_normative_content")
    if result.get("official_status") != "现行":
        flags.append("standard_status_requires_review")
    if "已授权" not in str(result.get("authorization") or ""):
        flags.append("authorization_requires_review")
    result["quality_flags"] = list(dict.fromkeys(flags))
    result["quality_status"] = "review_required" if flags else "usable"
    result["evidence_insufficient"] = bool(flags)
    result["design_advice_allowed"] = not flags


def _source_links(source_id: int, page: int) -> dict[str, str]:
    return {
        "page": f"/api/ai/standards/{source_id}/page/{page}",
        "document": f"/api/ai/standards/{source_id}/document#page={page}",
        "download": f"/api/ai/standards/{source_id}/download",
    }


def _normalize_table_label(value: str) -> str:
    return re.sub(r"^(?:表|table)", "", re.sub(r"\s+", "", value).casefold())


def _result_envelope(
    rows: list[dict[str, Any]],
    *,
    missing_message: str,
) -> dict[str, Any]:
    warnings: list[str] = []
    for row in rows:
        warnings.extend(_source_warnings(row))
        if row.get("evidence_insufficient", True):
            warnings.append(
                f"证据不足：{row['standard_code']} 的命中内容仅供检索定位，不能作为最终设计依据："
                + ", ".join(row.get("quality_flags", []))
            )
    warnings = list(dict.fromkeys(warnings))
    if not rows:
        warnings.append(missing_message)
    return {
        "found": bool(rows),
        "evidence_insufficient": not any(row.get("design_advice_allowed") is True for row in rows),
        "design_advice_allowed": any(row.get("design_advice_allowed") is True for row in rows),
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
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.create_function("normalize_text", 1, lambda value: re.sub(r"\s+", "", value or "").casefold())
    connection.create_function("normalize_table_label", 1, lambda value: _normalize_table_label(value or ""))
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
