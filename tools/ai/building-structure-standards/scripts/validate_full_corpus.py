from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


def validate_full_corpus(
    *,
    database: Path | str,
    source_manifest: Path | str,
    expected_source_paths: list[str] | None = None,
) -> dict[str, Any]:
    database_path = Path(database)
    manifest_path = Path(source_manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_sources = [
        item for item in manifest.get("sources", []) if isinstance(item, dict)
    ]
    manifest_paths = (
        list(expected_source_paths)
        if expected_source_paths is not None
        else [str(item.get("source_path") or "") for item in manifest_sources]
    )

    connection = sqlite3.connect(database_path)
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        source_rows = connection.execute(
            "SELECT source_id, source_path, source_sha256 FROM sources ORDER BY source_id"
        ).fetchall()
        page_count = int(connection.execute("SELECT COUNT(*) FROM pages").fetchone()[0])
        clause_count = int(
            connection.execute("SELECT COUNT(*) FROM clauses").fetchone()[0]
        )
        table_count = int(
            connection.execute("SELECT COUNT(*) FROM standard_tables").fetchone()[0]
        )
        fts_count = int(
            connection.execute("SELECT COUNT(*) FROM clauses_fts").fetchone()[0]
        )
        sources_without_pages = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM sources s
                WHERE NOT EXISTS (SELECT 1 FROM pages p WHERE p.source_id = s.source_id)
                """
            ).fetchone()[0]
        )
        sources_without_clauses = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM sources s
                WHERE NOT EXISTS (SELECT 1 FROM clauses c WHERE c.source_id = s.source_id)
                """
            ).fetchone()[0]
        )
    finally:
        connection.close()

    database_paths = [str(row[1]) for row in source_rows]
    relative_paths_valid = all(
        _is_safe_relative_pdf_path(path) for path in database_paths
    )
    checks = {
        "sqlite_integrity": integrity == "ok",
        "source_count_matches_manifest": len(source_rows) == len(manifest_paths),
        "source_paths_match_manifest": sorted(database_paths) == sorted(manifest_paths),
        "relative_source_paths_valid": relative_paths_valid,
        "all_sources_have_pages": sources_without_pages == 0,
        "all_sources_have_sha256": all(
            bool(str(row[2]).strip()) for row in source_rows
        ),
        "fts_matches_clauses": fts_count == clause_count,
    }
    failures = [name for name, passed in checks.items() if not passed]
    passed_count = len(checks) - len(failures)
    return {
        "schema_version": 2,
        "validation_kind": "full_corpus_structural",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "case_count": len(checks),
        "passed_count": passed_count,
        "failed_count": len(failures),
        "pass_rate": passed_count / len(checks),
        "failures": failures,
        "checks": checks,
        "database_sha256": _sha256(database_path),
        "source_manifest_sha256": _sha256(manifest_path),
        "manifest_source_count": len(manifest_paths),
        "source_manifest_total_count": len(manifest_sources),
        "database_source_count": len(source_rows),
        "page_count": page_count,
        "clause_count": clause_count,
        "table_count": table_count,
        "fts_count": fts_count,
        "sources_without_pages": sources_without_pages,
        "sources_without_clauses": sources_without_clauses,
        "relative_source_paths_valid": relative_paths_valid,
    }


def _is_safe_relative_pdf_path(value: str) -> bool:
    normalized = value.strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    return bool(
        normalized
        and not path.is_absolute()
        and not normalized.startswith("//")
        and ".." not in path.parts
        and path.suffix.casefold() == ".pdf"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a complete offline standards SQLite corpus."
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    report = validate_full_corpus(
        database=args.database,
        source_manifest=args.source_manifest,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
