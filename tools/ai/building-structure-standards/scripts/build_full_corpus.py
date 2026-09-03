from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_corpus as corpus  # noqa: E402
import validate_full_corpus as full_validation  # noqa: E402


def build_incremental_corpus(
    *,
    manifest_path: Path | str,
    source_root: Path | str,
    output_path: Path | str,
    cache_dir: Path | str,
    report_path: Path | str | None = None,
    validation_report_path: Path | str | None = None,
    allow_partial: bool = False,
    max_sources: int | None = None,
) -> dict[str, Any]:
    manifest = Path(manifest_path).resolve()
    root = Path(source_root).resolve()
    output = Path(output_path).resolve()
    cache_root = Path(cache_dir).resolve()
    state_path = cache_root / "state.json"
    cache_root.mkdir(parents=True, exist_ok=True)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    source_items = [
        item for item in payload.get("sources", []) if isinstance(item, dict)
    ]
    if max_sources is not None:
        source_items = source_items[: max(0, int(max_sources))]

    previous_state = _load_state(state_path)
    previous_entries = previous_state.get("sources", {})
    current_entries: dict[str, dict[str, Any]] = {}
    parsed_count = 0
    cache_hit_count = 0
    failures: list[dict[str, str]] = []

    for item in source_items:
        relative_path = _safe_relative_pdf_path(str(item.get("source_path") or ""))
        source_path = (root / relative_path).resolve()
        _assert_under_root(source_path, root)
        try:
            stat = source_path.stat()
            fingerprint = {
                "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        except OSError as exc:
            failures.append({"source_path": relative_path, "error": str(exc)})
            current_entries[relative_path] = {
                "status": "failed",
                "error": str(exc),
            }
            _write_state(state_path, current_entries)
            continue

        previous = previous_entries.get(relative_path, {})
        cache_path = cache_root / _cache_name(relative_path)
        if (
            previous.get("status") == "parsed"
            and previous.get("fingerprint") == fingerprint
            and cache_path.is_file()
        ):
            current_entries[relative_path] = dict(previous)
            if "low_text_pages" not in current_entries[relative_path]:
                cached = _read_cache(cache_path)
                low_text_pages = [
                    page.page_number
                    for page in cached.pages
                    if len(page.text.strip()) < 40
                ]
                current_entries[relative_path]["low_text_pages"] = low_text_pages
                current_entries[relative_path]["low_text_page_count"] = len(
                    low_text_pages
                )
            cache_hit_count += 1
            continue

        try:
            spec = _source_spec(item, source_path, relative_path)
            parsed = corpus.parse_source(spec)
            _write_cache(cache_path, parsed)
            low_text_pages = [
                page.page_number for page in parsed.pages if len(page.text.strip()) < 40
            ]
            entry = {
                "status": "parsed",
                "fingerprint": fingerprint,
                "cache_file": cache_path.name,
                "source_sha256": parsed.source_sha256,
                "page_count": len(parsed.pages),
                "clause_count": len(parsed.clauses),
                "table_count": len(parsed.tables),
                "low_text_page_count": len(low_text_pages),
                "low_text_pages": low_text_pages,
                "warning_count": len(parsed.warnings),
            }
            current_entries[relative_path] = entry
            parsed_count += 1
        except Exception as exc:
            if cache_path.exists():
                cache_path.unlink()
            failures.append({"source_path": relative_path, "error": str(exc)})
            current_entries[relative_path] = {
                "status": "failed",
                "fingerprint": fingerprint,
                "error": str(exc),
            }
        _write_state(state_path, current_entries)

    _write_state(state_path, current_entries)
    successful_entries = [
        (relative_path, entry)
        for relative_path, entry in current_entries.items()
        if entry.get("status") == "parsed"
    ]
    published = False
    index_report: dict[str, Any] = {}
    validation_report: dict[str, Any] = {}
    if successful_entries and (allow_partial or not failures):
        output.parent.mkdir(parents=True, exist_ok=True)
        staging = output.with_name(f"{output.name}.staging")
        index_report = corpus.build_sqlite(
            _iter_cached_sources(cache_root, successful_entries),
            staging,
        )
        validation_report = full_validation.validate_full_corpus(
            database=staging,
            source_manifest=manifest,
            expected_source_paths=[path for path, _ in successful_entries],
        )
        if validation_report["failed_count"] == 0:
            os.replace(staging, output)
            published = True
        else:
            staging.unlink(missing_ok=True)
            failures.append(
                {
                    "source_path": "<full-corpus-validation>",
                    "error": ", ".join(validation_report["failures"]),
                }
            )

    report = {
        "schema_version": 1,
        "generated_at": _utc_now(),
        "manifest_path": str(manifest),
        "manifest_sha256": _sha256(manifest),
        "source_root": str(root),
        "requested_source_count": len(source_items),
        "parsed_count": parsed_count,
        "cache_hit_count": cache_hit_count,
        "successful_source_count": len(successful_entries),
        "failed_count": len(failures),
        "failures": failures,
        "low_text_page_count": sum(
            int(entry.get("low_text_page_count") or 0)
            for _, entry in successful_entries
        ),
        "ocr_required": any(
            int(entry.get("low_text_page_count") or 0) > 0
            for _, entry in successful_entries
        ),
        "ocr_queue": [
            {
                "source_path": relative_path,
                "page_numbers": list(entry.get("low_text_pages") or []),
            }
            for relative_path, entry in successful_entries
            if entry.get("low_text_pages")
        ],
        "published": published,
        "partial": bool(failures),
        "index": index_report,
        "validation": {
            key: validation_report.get(key)
            for key in (
                "validation_kind",
                "case_count",
                "passed_count",
                "failed_count",
                "database_sha256",
                "manifest_source_count",
                "database_source_count",
                "sources_without_clauses",
            )
        }
        if validation_report
        else {},
    }
    if validation_report_path is not None and validation_report:
        validation_file = Path(validation_report_path)
        validation_file.parent.mkdir(parents=True, exist_ok=True)
        validation_file.write_text(
            json.dumps(validation_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if report_path is not None:
        report_file = Path(report_path)
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return report


def _source_spec(
    item: dict[str, Any],
    source_path: Path,
    relative_path: str,
) -> corpus.SourceSpec:
    allowed = {field.name for field in fields(corpus.SourceSpec)}
    values = {key: value for key, value in item.items() if key in allowed}
    values["source_path"] = str(source_path)
    values["relative_source_path"] = relative_path
    return corpus.SourceSpec(**values)


def _write_cache(path: Path, parsed: corpus.ParsedSource) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8") as handle:
        json.dump(asdict(parsed), handle, ensure_ascii=False, separators=(",", ":"))
    os.replace(temporary, path)


def _read_cache(path: Path) -> corpus.ParsedSource:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    return corpus.ParsedSource(
        source=corpus.SourceSpec(**payload["source"]),
        source_sha256=payload["source_sha256"],
        pages=[corpus.PageRecord(**item) for item in payload["pages"]],
        clauses=[corpus.ClauseRecord(**item) for item in payload["clauses"]],
        tables=[corpus.TableRecord(**item) for item in payload["tables"]],
        warnings=list(payload.get("warnings") or []),
    )


def _iter_cached_sources(
    cache_root: Path,
    entries: Iterable[tuple[str, dict[str, Any]]],
) -> Iterable[corpus.ParsedSource]:
    for _, entry in entries:
        yield _read_cache(cache_root / str(entry["cache_file"]))


def _load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"sources": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"sources": {}}
    return payload if isinstance(payload, dict) else {"sources": {}}


def _write_state(path: Path, entries: dict[str, dict[str, Any]]) -> None:
    payload = {
        "schema_version": 1,
        "updated_at": _utc_now(),
        "sources": entries,
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _safe_relative_pdf_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    path = Path(normalized)
    if (
        not normalized
        or path.is_absolute()
        or normalized.startswith("//")
        or ".." in path.parts
        or path.suffix.casefold() != ".pdf"
    ):
        raise ValueError(f"unsafe standards source path: {value!r}")
    return path.as_posix()


def _assert_under_root(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("standards source path escapes source root") from exc


def _cache_name(relative_path: str) -> str:
    digest = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()
    return f"{digest}.json.gz"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the full offline standards corpus with resumable per-PDF cache."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--validation-report", type=Path)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--max-sources", type=int)
    args = parser.parse_args(argv)
    report = build_incremental_corpus(
        manifest_path=args.manifest,
        source_root=args.source_root,
        output_path=args.output,
        cache_dir=args.cache_dir,
        report_path=args.report,
        validation_report_path=args.validation_report,
        allow_partial=args.allow_partial,
        max_sources=args.max_sources,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["published"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
