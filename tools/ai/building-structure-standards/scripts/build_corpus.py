from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from dataclasses import dataclass, field, fields
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable


CLAUSE_HEADING_RE = re.compile(
    r"^\s*((?:[A-Z]\.)?(?:\d+\.)+\d+|\d+)(?:(?:\s+|(?=[\u4e00-\u9fff]))(.*?))?\s*$"
)
PARSER_VERSION = "standards-structure-2.3"
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from standards_io import replace_atomic  # noqa: E402

SPECIAL_HEADING_RE = re.compile(r"^\s*(术\s*语|附录\s*[A-Z一二三四五六七八九十]*)\s*$")
PAGE_MARKER_RE = re.compile(
    r"(?:[—\-]\s*)?(?:第\s*)?"
    r"([0-9ivxlcdm一二三四五六七八九十百]+)"
    r"(?:\s*页)?(?:\s*[—\-])?",
    re.I,
)


@dataclass(frozen=True)
class SourceSpec:
    standard_code: str
    standard_name: str
    version: str
    source_path: str
    official_source_url: str
    authorization: str
    confidentiality: str
    official_status: str = ""
    replacement_standard: str = ""
    major: str = ""
    relative_source_path: str = ""


@dataclass
class PageRecord:
    page_number: int
    printed_page: str
    text: str
    anchor: str
    native_text: str = ""
    ocr_text: str = ""
    text_source: str = "native"
    ocr_confidence: float = 0.0
    quality_status: str = "usable"
    quality_flags: list[str] = field(default_factory=list)
    content_role: str = "unknown"
    ocr_provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class ClauseRecord:
    clause_id: str
    heading: str
    text: str
    page_start: int
    page_end: int
    anchor: str
    table_ids: list[str] = field(default_factory=list)
    content_role: str = "normative"


@dataclass
class TableRecord:
    table_id: str
    page_number: int
    rows: list[list[str]]
    markdown: str
    anchor: str
    quality_status: str = "usable"
    table_label: str = ""
    quality_flags: list[str] = field(default_factory=list)


@dataclass
class ParsedSource:
    source: SourceSpec
    source_sha256: str
    pages: list[PageRecord]
    clauses: list[ClauseRecord]
    tables: list[TableRecord]
    warnings: list[str] = field(default_factory=list)


def parse_source(source: SourceSpec) -> ParsedSource:
    path = Path(source.source_path)
    if not path.is_file():
        raise FileNotFoundError(f"source file does not exist: {path}")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf(source, path)
    if suffix in {".html", ".htm"}:
        return _parse_html(source, path)
    raise ValueError(f"unsupported source type: {suffix}")


def _parse_pdf(source: SourceSpec, path: Path) -> ParsedSource:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError(
            "PDF parsing requires PyMuPDF; install it in the offline runtime."
        ) from exc

    document = fitz.open(path)
    pages: list[PageRecord] = []
    tables: list[TableRecord] = []
    warnings: list[str] = []
    try:
        for page_index, page in enumerate(document):
            page_number = page_index + 1
            raw_text = page.get_text("text", sort=True)
            text = _normalize_page_text(raw_text)
            printed_page = _detect_printed_page(text)
            anchor = f"{path.name}#page={page_number}"
            pages.append(
                PageRecord(
                    page_number=page_number,
                    printed_page=printed_page,
                    text=text,
                    anchor=anchor,
                    native_text=raw_text,
                    quality_status=(
                        "usable"
                        if text
                        else "review_required"
                        if page.get_images() or page.get_drawings()
                        else "blank"
                    ),
                    quality_flags=[] if text else ["no_native_text"],
                )
            )
            try:
                finder = page.find_tables()
                for table_index, table in enumerate(finder.tables, start=1):
                    rows = _clean_table_rows(table.extract())
                    if not rows:
                        continue
                    table_id = f"p{page_number}-t{table_index}"
                    tables.append(
                        TableRecord(
                            table_id=table_id,
                            page_number=page_number,
                            rows=rows,
                            markdown=_table_markdown(rows),
                            anchor=anchor,
                        )
                    )
            except Exception as exc:
                warnings.append(f"page {page_number} table extraction failed: {exc}")
    finally:
        document.close()

    clauses = _split_clauses(pages, tables)
    return ParsedSource(
        source=source,
        source_sha256=_sha256(path),
        pages=pages,
        clauses=clauses,
        tables=tables,
        warnings=warnings,
    )


def _parse_html(source: SourceSpec, path: Path) -> ParsedSource:
    html = path.read_text(encoding="utf-8")
    parser = _StandardsHtmlParser()
    parser.feed(html)
    clauses: list[ClauseRecord] = []
    tables: list[TableRecord] = []
    page_text: dict[int, list[str]] = {}
    current: ClauseRecord | None = None

    for event in parser.text_events:
        text = _clean_text(" ".join(event["text"]))
        if not text:
            continue
        declared_page = int(event["page"])
        page_text.setdefault(declared_page, []).append(text)
        match = (
            _match_clause_heading(text) if str(event["tag"]).startswith("h") else None
        )
        if match:
            if current is not None:
                clauses.append(current)
            clause_id = match.group(1)
            fragment = str(event["fragment"] or f"clause-{clause_id.replace('.', '-')}")
            current = ClauseRecord(
                clause_id=clause_id,
                heading=text,
                text=text,
                page_start=declared_page,
                page_end=declared_page,
                anchor=f"{path.name}#{fragment}",
            )
        elif current is not None:
            current.text = f"{current.text}\n{text}"
            current.page_end = max(current.page_end, declared_page)
    if current is not None:
        clauses.append(current)

    for table_index, table in enumerate(parser.table_events, start=1):
        rows = _clean_table_rows(table["rows"])
        if not rows:
            continue
        page_number = int(table["page"])
        fragment = str(table["fragment"] or f"table-{table_index}")
        table_id = fragment
        tables.append(
            TableRecord(
                table_id=table_id,
                page_number=page_number,
                rows=rows,
                markdown=_table_markdown(rows),
                anchor=f"{path.name}#{fragment}",
            )
        )
        page_text.setdefault(page_number, []).append(_table_markdown(rows))

    declared_pages = sorted(page_text) or [1]
    pages = [
        PageRecord(
            page_number=page,
            printed_page=str(page),
            text="\n".join(page_text.get(page, [])),
            anchor=f"{path.name}#page={page}",
        )
        for page in declared_pages
    ]
    _attach_tables(clauses, tables)
    return ParsedSource(
        source=source,
        source_sha256=_sha256(path),
        pages=pages,
        clauses=clauses,
        tables=tables,
    )


def _match_clause_heading(line: str) -> re.Match[str] | None:
    prefix = re.match(r"^\s*((?:[A-Z]\s*[.．]\s*)?\d+(?:\s*[.．]\s*\d+)+)", line)
    if prefix:
        normalized = re.sub(r"\s+", "", prefix.group(1)).replace("．", ".")
        line = normalized + line[prefix.end() :]
    return CLAUSE_HEADING_RE.match(line)


def _split_clauses(
    pages: list[PageRecord],
    tables: list[TableRecord],
) -> list[ClauseRecord]:
    clauses: list[ClauseRecord] = []
    current: ClauseRecord | None = None
    role = "unknown"
    for page in pages:
        lines = [line.strip() for line in page.text.splitlines() if line.strip()]
        toc_page = any(
            re.sub(r"\s+", "", line) in {"目录", "目次", "Contents"}
            for line in lines[:3]
        ) or any(re.search(r"(?:\.{2,}|…{2,}|·{2,})\s*\d+\s*$", line) for line in lines)
        has_body_prose = any(
            re.search(r"[\u4e00-\u9fff]{2,}.*[。！？；]", line) for line in lines
        )
        page.content_role = role
        for line_index, line in enumerate(lines):
            if page.printed_page and _page_marker(line) == page.printed_page:
                continue
            compact = re.sub(r"\s+", "", line)
            combined = compact + (
                re.sub(r"\s+", "", lines[line_index + 1])
                if line_index + 1 < len(lines)
                else ""
            )
            marker = (
                combined if combined in {"条文说明", "条款说明", "1总则"} else compact
            )
            next_role = role
            if marker in {"条文说明", "条款说明"}:
                next_role = "commentary"
            elif compact in {"目录", "目次", "Contents"}:
                next_role = "toc"
            elif compact in {"公告", "前言", "发布公告"} or (
                line_index < 3 and "部公告" in compact
            ):
                next_role = "announcement"
            elif (
                role != "commentary"
                and not toc_page
                and marker == "1总则"
                and (role != "toc" or has_body_prose)
            ):
                next_role = "normative"
            elif (
                role in {"unknown", "toc", "announcement"}
                and not toc_page
                and (role == "unknown" or has_body_prose)
                and re.match(r"^1\.0\.1(?:\s|$|(?=[\u4e00-\u9fff]))", line)
            ):
                next_role = "normative"
            if next_role != role:
                if current is not None:
                    clauses.append(current)
                    current = None
                role = next_role
                page.content_role = role
            match = _match_clause_heading(line)
            if match and match.group(1).isdigit():
                heading = match.group(2) or ""
                # Single numbers inside a clause are list items, not new clauses.
                if (
                    not heading
                    or re.search(r"[。；;，,：:]", heading)
                    or (
                        current is not None
                        and "." in current.clause_id
                        and line_index != 0
                    )
                ):
                    match = None
            special = SPECIAL_HEADING_RE.match(line)
            if match or special:
                if current is not None:
                    clauses.append(current)
                clause_id = (
                    match.group(1) if match else re.sub(r"\s+", "", special.group(1))
                )
                current = ClauseRecord(
                    clause_id=clause_id,
                    heading=line,
                    text=line,
                    page_start=page.page_number,
                    page_end=page.page_number,
                    anchor=page.anchor,
                    content_role=role,
                )
            elif current is not None:
                current.text = f"{current.text}\n{line}"
                current.page_end = page.page_number
    if current is not None:
        clauses.append(current)
    _attach_tables(clauses, tables)
    return clauses


def reindex_parsed_source(
    parsed: ParsedSource, source: SourceSpec | None = None
) -> ParsedSource:
    """Reuse raw candidates; never promote legacy OCR to reviewed evidence."""
    from standards_ocr import OcrLineResult, select_page_text

    if source is not None:
        parsed.source = source
    filename = Path(parsed.source.source_path).name
    for page in parsed.pages:
        page.anchor = f"{filename}#page={page.page_number}"
        native = page.native_text or (page.text if page.text_source != "ocr" else "")
        prior_flags = list(page.quality_flags)
        if page.quality_status in {"review_required", "failed"}:
            prior_flags.append("prior_review_required")
        try:
            ocr_lines = [
                OcrLineResult(**line) for line in page.ocr_provenance.get("lines", [])
            ]
        except (TypeError, ValueError):
            ocr_lines = []
            prior_flags.append("invalid_ocr_line_evidence")
        decision = select_page_text(
            native_text=native,
            ocr_text=page.ocr_text,
            ocr_confidence=page.ocr_confidence,
            parse_mode="text_primary",
            blank_verified=page.quality_status == "blank",
            legacy_ocr=bool(
                page.ocr_text
                and (not ocr_lines or not page.ocr_provenance.get("engine_identity"))
            ),
            ocr_lines=ocr_lines,
        )
        page.native_text = native
        page.text = decision.selected_text
        page.text_source = decision.text_source
        page.quality_status = decision.quality
        page.quality_flags = list(
            dict.fromkeys([*prior_flags, *decision.quality_flags])
        )
        if prior_flags and page.quality_status == "usable":
            page.quality_status = "review_required"
        page.printed_page = _detect_printed_page(page.text) or page.printed_page
    # Native table extraction is retained; OCR-only table references never invent cells.
    tables = [
        table for table in parsed.tables if table.quality_status != "visual_required"
    ]
    for table in tables:
        table.anchor = f"{filename}#page={table.page_number}"
    for page in parsed.pages:
        labels = list(
            dict.fromkeys(re.findall(r"表\s*([A-Z]?\.?\d+(?:\.\d+)+)", page.text))
        )
        native_tables = [
            table for table in tables if table.page_number == page.page_number
        ]
        if len(labels) == 1 and len(native_tables) == 1:
            native_tables[0].table_label = labels[0]
        for label in labels:
            if any(table.table_label == label for table in native_tables):
                continue
            tables.append(
                TableRecord(
                    table_id=f"p{page.page_number}-visual-{label}",
                    page_number=page.page_number,
                    rows=[],
                    markdown="",
                    anchor=page.anchor,
                    table_label=label,
                    quality_status="visual_required",
                    quality_flags=["table_cells_unverified"],
                )
            )
    parsed.tables = tables
    parsed.clauses = _split_clauses(parsed.pages, parsed.tables)
    return parsed


def _attach_tables(
    clauses: list[ClauseRecord],
    tables: list[TableRecord],
) -> None:
    for table in tables:
        candidates = [
            clause
            for clause in clauses
            if clause.page_start <= table.page_number <= clause.page_end
        ]
        if candidates:
            candidates[-1].table_ids.append(table.table_id)


def build_sqlite(
    parsed_sources: Iterable[ParsedSource],
    database_path: Path | str,
) -> dict[str, Any]:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        report = _build_sqlite_file(parsed_sources, temporary)
        replace_atomic(temporary, path)
        return report
    finally:
        temporary.unlink(missing_ok=True)


def _build_sqlite_file(
    parsed_sources: Iterable[ParsedSource],
    database_path: Path | str,
) -> dict[str, Any]:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE sources (
                source_id INTEGER PRIMARY KEY,
                standard_code TEXT NOT NULL,
                standard_name TEXT NOT NULL,
                version TEXT NOT NULL,
                major TEXT NOT NULL,
                official_status TEXT NOT NULL,
                replacement_standard TEXT NOT NULL,
                source_path TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                official_source_url TEXT NOT NULL,
                authorization TEXT NOT NULL,
                confidentiality TEXT NOT NULL
            );
            CREATE TABLE pages (
                page_id INTEGER PRIMARY KEY,
                source_id INTEGER NOT NULL REFERENCES sources(source_id),
                page_number INTEGER NOT NULL,
                printed_page TEXT NOT NULL,
                text TEXT NOT NULL,
                anchor TEXT NOT NULL,
                native_text TEXT NOT NULL,
                ocr_text TEXT NOT NULL,
                text_source TEXT NOT NULL,
                ocr_confidence REAL NOT NULL,
                quality_status TEXT NOT NULL,
                quality_flags_json TEXT NOT NULL,
                content_role TEXT NOT NULL,
                ocr_provenance_json TEXT NOT NULL
            );
            CREATE TABLE clauses (
                clause_pk INTEGER PRIMARY KEY,
                source_id INTEGER NOT NULL REFERENCES sources(source_id),
                clause_id TEXT NOT NULL,
                heading TEXT NOT NULL,
                text TEXT NOT NULL,
                page_start INTEGER NOT NULL,
                page_end INTEGER NOT NULL,
                anchor TEXT NOT NULL,
                table_ids_json TEXT NOT NULL,
                content_role TEXT NOT NULL
            );
            CREATE TABLE standard_tables (
                table_pk INTEGER PRIMARY KEY,
                source_id INTEGER NOT NULL REFERENCES sources(source_id),
                table_id TEXT NOT NULL,
                page_number INTEGER NOT NULL,
                rows_json TEXT NOT NULL,
                markdown TEXT NOT NULL,
                anchor TEXT NOT NULL,
                quality_status TEXT NOT NULL,
                table_label TEXT NOT NULL,
                quality_flags_json TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE clauses_fts USING fts5(
                standard_code,
                standard_name,
                clause_id,
                heading,
                text,
                tokenize='trigram'
            );
            CREATE INDEX idx_sources_code ON sources(standard_code);
            CREATE INDEX idx_clauses_source_clause ON clauses(source_id, clause_id);
            CREATE INDEX idx_pages_source_number ON pages(source_id, page_number);
            CREATE INDEX idx_tables_source_label ON standard_tables(source_id, table_label);
            """
        )
        source_count = 0
        page_count = 0
        clause_count = 0
        table_count = 0
        warning_items: list[dict[str, Any]] = []
        for source_index, parsed in enumerate(parsed_sources, start=1):
            spec = parsed.source
            source_count += 1
            page_count += len(parsed.pages)
            clause_count += len(parsed.clauses)
            table_count += len(parsed.tables)
            if parsed.warnings:
                warning_items.append(
                    {
                        "standard_code": spec.standard_code,
                        "warnings": parsed.warnings,
                    }
                )
            connection.execute(
                """
                INSERT INTO sources(
                    source_id, standard_code, standard_name, version, major,
                    official_status, replacement_standard, source_path,
                    source_sha256, official_source_url, authorization,
                    confidentiality
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_index,
                    spec.standard_code,
                    spec.standard_name,
                    spec.version,
                    spec.major,
                    spec.official_status,
                    spec.replacement_standard,
                    spec.relative_source_path or Path(spec.source_path).name,
                    parsed.source_sha256,
                    spec.official_source_url,
                    spec.authorization,
                    spec.confidentiality,
                ),
            )
            for page in parsed.pages:
                connection.execute(
                    """
                    INSERT INTO pages(
                        source_id, page_number, printed_page, text, anchor,
                        native_text, ocr_text, text_source, ocr_confidence,
                        quality_status, quality_flags_json, content_role, ocr_provenance_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_index,
                        page.page_number,
                        page.printed_page,
                        page.text,
                        page.anchor,
                        page.native_text
                        or (page.text if page.text_source == "native" else ""),
                        page.ocr_text,
                        page.text_source,
                        page.ocr_confidence,
                        page.quality_status,
                        json.dumps(page.quality_flags, ensure_ascii=False),
                        page.content_role,
                        json.dumps(page.ocr_provenance, ensure_ascii=False),
                    ),
                )
            for clause in parsed.clauses:
                cursor = connection.execute(
                    """
                    INSERT INTO clauses(
                        source_id, clause_id, heading, text, page_start,
                        page_end, anchor, table_ids_json, content_role
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_index,
                        clause.clause_id,
                        clause.heading,
                        clause.text,
                        clause.page_start,
                        clause.page_end,
                        clause.anchor,
                        json.dumps(clause.table_ids, ensure_ascii=False),
                        clause.content_role,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO clauses_fts(
                        rowid, standard_code, standard_name, clause_id,
                        heading, text
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cursor.lastrowid,
                        spec.standard_code,
                        spec.standard_name,
                        clause.clause_id,
                        clause.heading,
                        clause.text,
                    ),
                )
            for table in parsed.tables:
                connection.execute(
                    """
                    INSERT INTO standard_tables(
                        source_id, table_id, page_number, rows_json,
                        markdown, anchor, quality_status, table_label, quality_flags_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_index,
                        table.table_id,
                        table.page_number,
                        json.dumps(table.rows, ensure_ascii=False),
                        table.markdown,
                        table.anchor,
                        table.quality_status,
                        table.table_label,
                        json.dumps(table.quality_flags, ensure_ascii=False),
                    ),
                )
        connection.commit()
    finally:
        connection.close()

    return {
        "source_count": source_count,
        "page_count": page_count,
        "clause_count": clause_count,
        "table_count": table_count,
        "warnings": warning_items,
        "database_sha256": _sha256(path),
    }


def query_index(
    database_path: Path | str,
    *,
    query: str = "",
    standard_code: str = "",
    clause_id: str = "",
    limit: int = 10,
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if standard_code:
        where.append("s.standard_code = ?")
        params.append(standard_code)
    if clause_id:
        where.append("c.clause_id = ?")
        params.append(clause_id)
    if query:
        where.append("(c.text LIKE ? OR c.heading LIKE ? OR s.standard_name LIKE ?)")
        wildcard = f"%{query}%"
        params.extend([wildcard, wildcard, wildcard])
    sql = """
        SELECT
            s.standard_code, s.standard_name, s.version, s.major,
            s.official_status, s.replacement_standard, s.authorization,
            s.confidentiality, c.clause_id, c.heading, c.text,
            c.page_start, c.page_end, c.anchor, c.table_ids_json
        FROM clauses c
        JOIN sources s ON s.source_id = c.source_id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY s.standard_code, c.page_start, c.clause_id LIMIT ?"
    params.append(max(1, limit))
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = [dict(row) for row in connection.execute(sql, params)]
    finally:
        connection.close()
    for row in rows:
        row["table_ids"] = json.loads(row.pop("table_ids_json"))
    return rows


def build_from_manifest(
    manifest_path: Path | str,
    database_path: Path | str,
    *,
    source_root: Path | str | None = None,
) -> dict[str, Any]:
    manifest_file = Path(manifest_path)
    payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    skipped: list[dict[str, str]] = []
    source_base = (
        Path(source_root).resolve()
        if source_root is not None
        else manifest_file.parent.resolve()
    )
    source_fields = {item.name for item in fields(SourceSpec)}

    def iter_parsed_sources() -> Iterable[ParsedSource]:
        for item in payload.get("sources", []):
            source_data = {
                key: value for key, value in dict(item).items() if key in source_fields
            }
            source_path = Path(source_data["source_path"])
            relative_source_path = (
                source_path.as_posix()
                if not source_path.is_absolute()
                else source_path.name
            )
            if not source_path.is_absolute():
                source_path = (source_base / source_path).resolve()
            source_data["source_path"] = str(source_path)
            source_data["relative_source_path"] = relative_source_path
            authorization = str(source_data.get("authorization") or "")
            if "已授权" not in authorization:
                skipped.append(
                    {
                        "standard_code": str(source_data.get("standard_code") or ""),
                        "reason": "authorization gate",
                    }
                )
                continue
            yield parse_source(SourceSpec(**source_data))

    report = build_sqlite(iter_parsed_sources(), database_path)
    report["skipped_sources"] = skipped
    report["manifest_sha256"] = _sha256(manifest_file)
    return report


def _normalize_page_text(value: str) -> str:
    return "\n".join(
        _clean_text(line)
        for line in value.replace("\r", "\n").splitlines()
        if _clean_text(line)
    )


def _clean_text(value: Any) -> str:
    return re.sub(r"[ \t\u00a0]+", " ", str(value or "")).strip()


def _detect_printed_page(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    candidates = [*lines[:5], *reversed(lines[-5:])]
    for line in candidates:
        marker = _page_marker(line)
        if marker:
            return marker
    return ""


def _page_marker(value: str) -> str:
    match = PAGE_MARKER_RE.fullmatch(value.strip())
    return match.group(1) if match else ""


def _clean_table_rows(rows: Iterable[Iterable[Any]]) -> list[list[str]]:
    clean_rows: list[list[str]] = []
    for row in rows:
        cells = [_clean_text(cell) for cell in row]
        if any(cells):
            clean_rows.append(cells)
    return clean_rows


def _table_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    lines = [
        "| " + " | ".join(normalized[0]) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in normalized[1:])
    return "\n".join(lines)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _StandardsHtmlParser(HTMLParser):
    _TEXT_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6", "p", "li"})

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.text_events: list[dict[str, Any]] = []
        self.table_events: list[dict[str, Any]] = []
        self._block_tag = ""
        self._block_depth = 0
        self._block_text: list[str] = []
        self._block_page = 1
        self._block_fragment = ""
        self._table: dict[str, Any] | None = None
        self._row: list[list[str]] | None = None
        self._cell_tag = ""
        self._cell_text: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        self.stack.append((tag, attr_map))
        page, fragment = self._context()
        if tag in self._TEXT_TAGS and not self._block_tag:
            self._block_tag = tag
            self._block_depth = len(self.stack)
            self._block_text = []
            self._block_page = page
            self._block_fragment = fragment
        if tag == "table":
            self._table = {
                "page": page,
                "fragment": fragment,
                "rows": [],
            }
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell_tag = tag
            self._cell_text = []

    def handle_data(self, data: str) -> None:
        clean = _clean_text(data)
        if not clean:
            return
        if self._block_tag:
            self._block_text.append(clean)
        if self._cell_tag:
            self._cell_text.append(clean)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"} and self._cell_tag == tag and self._row is not None:
            self._row.append([" ".join(self._cell_text)])
            self._cell_tag = ""
            self._cell_text = []
        elif tag == "tr" and self._table is not None and self._row is not None:
            self._table["rows"].append([cell[0] if cell else "" for cell in self._row])
            self._row = None
        if tag == self._block_tag and len(self.stack) == self._block_depth:
            self.text_events.append(
                {
                    "tag": self._block_tag,
                    "text": list(self._block_text),
                    "page": self._block_page,
                    "fragment": self._block_fragment,
                }
            )
            self._block_tag = ""
            self._block_depth = 0
            self._block_text = []
        if tag == "table" and self._table is not None:
            self.table_events.append(self._table)
            self._table = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def _context(self) -> tuple[int, str]:
        page = 1
        fragment = ""
        for _, attrs in reversed(self.stack):
            if not fragment and attrs.get("id"):
                fragment = attrs["id"]
            if attrs.get("data-page"):
                try:
                    page = int(attrs["data-page"])
                except ValueError:
                    page = 1
                break
        return page, fragment


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build an authorized building/structure/site standards corpus."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args(argv)
    report = build_from_manifest(
        args.manifest,
        args.output,
        source_root=args.source_root,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
