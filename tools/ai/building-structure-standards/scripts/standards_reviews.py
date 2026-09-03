from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _review_sha(review: dict[str, Any]) -> str:
    return hashlib.sha256(_json(review).encode("utf-8")).hexdigest()


def record_fingerprint(kind: str, row: dict[str, Any]) -> str:
    if kind == "clause":
        keys = (
            "clause_id",
            "text",
            "heading",
            "page_start",
            "page_end",
            "content_role",
        )
        payload = {key: row[key] for key in keys}
        payload["table_ids"] = (
            json.loads(row["table_ids_json"])
            if "table_ids_json" in row
            else row["table_ids"]
        )
    elif kind == "table":
        keys = ("table_id", "table_label", "page_number", "markdown")
        payload = {key: row[key] for key in keys}
        payload["rows"] = (
            json.loads(row["rows_json"]) if "rows_json" in row else row["rows"]
        )
    else:
        raise ValueError("unsupported review kind")
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _validate_review(review: dict[str, Any]) -> None:
    if not isinstance(review, dict) or review.get("kind") not in {"clause", "table"}:
        raise ValueError("invalid record review")
    for key in ("review_id", "standard_code", "record_id", "reviewer", "reviewed_at"):
        if not isinstance(review.get(key), str) or not review[key].strip():
            raise ValueError(f"review requires {key}")
    if (
        review.get("scope") != "complete_record"
        or review.get("method") != "visual_transcription"
    ):
        raise ValueError("review must cover the complete visually transcribed record")
    if datetime.fromisoformat(review["reviewed_at"]).tzinfo is None:
        raise ValueError("review timestamp must include timezone")
    for key in ("source_sha256", "base_record_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(review.get(key, ""))):
            raise ValueError(f"invalid {key}")
    start, end = review.get("page_start"), review.get("page_end")
    if type(start) is not int or type(end) is not int or start < 1 or end < start:
        raise ValueError("invalid review page range")
    pages = review.get("pages")
    if not isinstance(pages, list) or len(pages) != end - start + 1:
        raise ValueError("review must include every continuation page")
    for number, page in zip(range(start, end + 1), pages, strict=True):
        if (
            not isinstance(page, dict)
            or type(page.get("page_number")) is not int
            or page["page_number"] != number
            or not isinstance(page.get("printed_page"), str)
            or not page["printed_page"].strip()
            or not re.fullmatch(r"[0-9a-f]{64}", str(page.get("image_sha256", "")))
        ):
            raise ValueError("invalid rendered-page evidence")
    replacement = review.get("replacement")
    if not isinstance(replacement, dict):
        raise ValueError("review replacement is missing")
    if review["kind"] == "clause":
        if (
            not isinstance(replacement.get("text"), str)
            or not replacement["text"].strip()
        ):
            raise ValueError("reviewed clause text is empty")
    else:
        rows = replacement.get("rows")
        if (
            start != end
            or not isinstance(rows, list)
            or len(rows) < 2
            or not all(isinstance(row, list) and len(row) >= 2 for row in rows)
            or len({len(row) for row in rows}) != 1
            or not all(
                isinstance(cell, str) and cell.strip() for row in rows for cell in row
            )
            or len(set(rows[0])) != len(rows[0])
            or len({row[0] for row in rows[1:]}) != len(rows) - 1
        ):
            raise ValueError(
                "reviewed table needs unique headers and rectangular cells"
            )
        if (
            not isinstance(replacement.get("title"), str)
            or not replacement["title"].strip()
            or not isinstance(replacement.get("notes"), list)
            or not all(
                isinstance(note, str) and note.strip() for note in replacement["notes"]
            )
        ):
            raise ValueError("table title and explicit notes list are required")


def _table_markdown(replacement: dict[str, Any]) -> str:
    rows = replacement["rows"]

    def escape(cell: str) -> str:
        return cell.replace("|", "\\|").replace("\n", " ")

    lines = [
        replacement["title"],
        "",
        "| " + " | ".join(map(escape, rows[0])) + " |",
        "| " + " | ".join("---" for _ in rows[0]) + " |",
    ]
    lines.extend("| " + " | ".join(map(escape, row)) + " |" for row in rows[1:])
    return "\n".join([*lines, "", *replacement["notes"]])


def _apply(connection: sqlite3.Connection, payload: dict[str, Any], root: Path) -> int:
    if (
        payload.get("schema_version") != 1
        or not isinstance(payload.get("reviews"), list)
        or not payload["reviews"]
    ):
        raise ValueError("non-empty schema_version 1 reviews are required")
    connection.execute("""CREATE TABLE IF NOT EXISTS evidence_reviews (
        source_id INTEGER NOT NULL, kind TEXT NOT NULL, record_id TEXT NOT NULL,
        page_start INTEGER NOT NULL, record_sha256 TEXT NOT NULL,
        review_json TEXT NOT NULL, original_record_json TEXT NOT NULL, review_sha256 TEXT NOT NULL,
        PRIMARY KEY (source_id, kind, record_id, page_start))""")
    ids: set[str] = set()
    applied = 0
    for review in payload["reviews"]:
        _validate_review(review)
        if review["review_id"] in ids:
            raise ValueError("duplicate review id")
        ids.add(review["review_id"])
        sources = connection.execute(
            "SELECT * FROM sources WHERE source_sha256=? AND standard_code=?",
            (review["source_sha256"], review["standard_code"]),
        ).fetchall()
        if not sources:
            raise ValueError("review source PDF SHA256 is absent")
        for source in sources:
            relative = Path(source["source_path"])
            path = (root / relative).resolve()
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not path.is_relative_to(root)
            ):
                raise ValueError("review source path escapes source root")
            if not path.is_file() or _sha(path) != review["source_sha256"]:
                raise ValueError("review source PDF SHA256 mismatch")
            kind = review["kind"]
            table, key, page = (
                ("clauses", "clause_id", "page_start")
                if kind == "clause"
                else ("standard_tables", "table_id", "page_number")
            )
            records = connection.execute(
                f"SELECT rowid AS record_pk, * FROM {table} WHERE source_id=? AND {key}=? AND {page}=?",
                (source["source_id"], review["record_id"], review["page_start"]),
            ).fetchall()
            if len(records) != 1:
                raise ValueError("review target is missing or ambiguous")
            original = dict(records[0])
            if record_fingerprint(kind, original) != review["base_record_sha256"]:
                raise ValueError("review base record fingerprint mismatch")
            pages = connection.execute(
                "SELECT page_number FROM pages WHERE source_id=? AND page_number BETWEEN ? AND ? ORDER BY page_number",
                (source["source_id"], review["page_start"], review["page_end"]),
            ).fetchall()
            if [row[0] for row in pages] != list(
                range(review["page_start"], review["page_end"] + 1)
            ):
                raise ValueError(
                    "review page range is missing or ambiguous in database"
                )
            replacement = review["replacement"]
            updated = dict(original)
            if kind == "clause":
                if (
                    original["page_end"] != review["page_end"]
                    or original["content_role"] != "normative"
                    or json.loads(original["table_ids_json"])
                ):
                    raise ValueError(
                        "clause review cannot change span, role or approve associated tables"
                    )
                updated.update(
                    text=replacement["text"],
                    heading=replacement["text"].splitlines()[0],
                )
                connection.execute(
                    "UPDATE clauses SET text=?,heading=? WHERE rowid=?",
                    (updated["text"], updated["heading"], original["record_pk"]),
                )
                # Keep the FTS projection consistent with the corrected searchable text.
                if connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='clauses_fts'"
                ).fetchone():
                    connection.execute(
                        "UPDATE clauses_fts SET text=?,heading=? WHERE rowid=?",
                        (updated["text"], updated["heading"], original["record_pk"]),
                    )
            else:
                updated.update(
                    rows_json=_json(replacement["rows"]),
                    markdown=_table_markdown(replacement),
                    quality_status="usable",
                    quality_flags_json="[]",
                )
                connection.execute(
                    "UPDATE standard_tables SET rows_json=?,markdown=?,quality_status='usable',"
                    "quality_flags_json='[]' WHERE rowid=?",
                    (updated["rows_json"], updated["markdown"], original["record_pk"]),
                )
            try:
                connection.execute(
                    "INSERT INTO evidence_reviews VALUES (?,?,?,?,?,?,?,?)",
                    (
                        source["source_id"],
                        kind,
                        review["record_id"],
                        review["page_start"],
                        record_fingerprint(kind, updated),
                        _json(review),
                        _json(original),
                        _review_sha(review),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("review target was already reviewed") from exc
            applied += 1
    return applied


def publish_reviewed_corpus(
    *,
    database: Path | str,
    reviews_path: Path | str,
    source_root: Path | str,
    output_path: Path | str,
) -> dict[str, Any]:
    from standards_io import cache_writer_lock, replace_atomic

    source, output = Path(database).resolve(), Path(output_path).resolve()
    manifest = Path(reviews_path).resolve()
    if output == source or (output.exists() and output.samefile(source)):
        raise ValueError("review output must be different from input database")
    if not source.is_file():
        raise FileNotFoundError(source)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    original_sha = _sha(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    with cache_writer_lock(output.parent):
        descriptor, name = tempfile.mkstemp(
            prefix=output.name + ".", suffix=".staging", dir=output.parent
        )
        os.close(descriptor)
        staging = Path(name)
        try:
            with closing(
                sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
            ) as original:
                connection = sqlite3.connect(staging)
                try:
                    original.backup(connection)
                    connection.row_factory = sqlite3.Row
                    with connection:
                        count = _apply(connection, payload, Path(source_root).resolve())
                finally:
                    connection.close()
            if _sha(source) != original_sha:
                raise ValueError("input corpus changed during review replay")
            replace_atomic(staging, output)
        finally:
            staging.unlink(missing_ok=True)
    return {
        "schema_version": 1,
        "applied_record_count": count,
        "review_count": len(payload["reviews"]),
        "input_database_sha256": original_sha,
        "database_sha256": _sha(output),
        "review_manifest_sha256": _sha(manifest),
        "ocr_executed": False,
        "published": True,
    }


def attach_record_review(
    connection: sqlite3.Connection, row: dict[str, Any], kind: str
) -> None:
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE name='evidence_reviews'"
    ).fetchone():
        return
    key, page = (
        (row["clause_id"], row["page_start"])
        if kind == "clause"
        else (row["table_id"], row["page_number"])
    )
    stored = connection.execute(
        "SELECT * FROM evidence_reviews WHERE source_id=? AND kind=? AND record_id=? AND page_start=?",
        (row["source_id"], kind, key, page),
    ).fetchone()
    if stored is None:
        return
    try:
        review = json.loads(stored["review_json"])
        _validate_review(review)
        if (
            _review_sha(review) != stored["review_sha256"]
            or review["source_sha256"] != row["source_sha256"]
            or review["standard_code"] != row["standard_code"]
            or review["kind"] != kind
            or review["record_id"] != key
            or review["page_start"] != page
            or record_fingerprint(kind, row) != stored["record_sha256"]
        ):
            raise ValueError("reviewed record changed")
        expected_pages = list(range(review["page_start"], review["page_end"] + 1))
        if [item["page_number"] for item in row["page_quality"]] != expected_pages:
            raise ValueError("reviewed pages changed")
        if row.get("content_role") != "normative":
            raise ValueError("reviewed role changed")
        row["record_review"] = {
            key: review[key]
            for key in (
                "review_id",
                "reviewer",
                "reviewed_at",
                "method",
                "scope",
                "source_sha256",
                "pages",
            )
        }
        row["unreviewed_page_quality_flags"] = list(row["quality_flags"])
        row["quality_flags"] = []
        if kind == "clause":
            row["printed_page_start"] = review["pages"][0]["printed_page"]
            row["printed_page_end"] = review["pages"][-1]["printed_page"]
        else:
            row["printed_page"] = review["pages"][0]["printed_page"]
    except (ValueError, TypeError, KeyError, IndexError):
        row["quality_flags"].append("record_review_invalid")
