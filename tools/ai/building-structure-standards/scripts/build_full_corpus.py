from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_corpus as corpus  # noqa: E402
import validate_full_corpus as full_validation  # noqa: E402
from standards_io import cache_writer_lock, replace_atomic  # noqa: E402
from standards_reuse import BaselineSources, enrich_with_ocr  # noqa: E402


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
    reuse_databases: list[Path | str] | None = None,
    reuse_cache_dirs: list[Path | str] | None = None,
    require_cached: bool = False,
) -> dict[str, Any]:
    with cache_writer_lock(cache_dir):
        return _build_incremental_corpus_locked(
            manifest_path=manifest_path,
            source_root=source_root,
            output_path=output_path,
            cache_dir=cache_dir,
            report_path=report_path,
            validation_report_path=validation_report_path,
            allow_partial=allow_partial,
            max_sources=max_sources,
            reuse_databases=reuse_databases,
            reuse_cache_dirs=reuse_cache_dirs,
            require_cached=require_cached,
        )


def _build_incremental_corpus_locked(
    *,
    manifest_path: Path | str,
    source_root: Path | str,
    output_path: Path | str,
    cache_dir: Path | str,
    report_path: Path | str | None,
    validation_report_path: Path | str | None,
    allow_partial: bool,
    max_sources: int | None,
    reuse_databases: list[Path | str] | None,
    reuse_cache_dirs: list[Path | str] | None,
    require_cached: bool,
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
    candidates: dict[str, tuple[Path, str]] = {}
    for directory in [
        cache_root,
        *(Path(value).resolve() for value in (reuse_cache_dirs or [])),
    ]:
        for entry in _load_state(directory / "state.json").get("sources", {}).values():
            entry = _last_success(entry)
            if entry and entry.get("source_sha256"):
                candidate = (directory / str(entry.get("cache_file") or "")).resolve()
                _assert_under_root(candidate, directory)
                if candidate.is_file():
                    candidates[entry["source_sha256"]] = (
                        candidate,
                        str(entry.get("cache_sha256") or ""),
                    )
    baselines = BaselineSources(reuse_databases or [])
    current_entries: dict[str, dict[str, Any]] = {}
    parsed_count = 0
    cache_hit_count = 0
    baseline_reuse_count = 0
    failures: list[dict[str, str]] = []

    for item in source_items:
        relative_path = _safe_relative_pdf_path(str(item.get("source_path") or ""))
        source_path = (root / relative_path).resolve()
        _assert_under_root(source_path, root)
        last_success = _last_success(
            current_entries.get(relative_path, previous_entries.get(relative_path, {}))
        )
        retained_cache = {"last_success": last_success} if last_success else {}
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
                **retained_cache,
            }
            _write_state(state_path, {**previous_entries, **current_entries})
            continue

        try:
            pdf_sha = _sha256(source_path)
            path_key = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:12]
            cache_path = (
                cache_root / f"{pdf_sha}-{corpus.PARSER_VERSION}-{path_key}.json.gz"
            )
            spec = _source_spec(item, source_path, relative_path)
            baseline = baselines.read(pdf_sha, spec)
            if pdf_sha in candidates:
                candidate, expected_sha = candidates[pdf_sha]
                if expected_sha and _sha256(candidate) != expected_sha:
                    raise ValueError("cached text checksum mismatch")
                parsed = _read_cache(candidate)
                if parsed.source_sha256 != pdf_sha:
                    raise ValueError("cached PDF SHA256 does not match source PDF")
                if baseline is not None:
                    parsed = enrich_with_ocr(parsed, baseline)
                    baseline_reuse_count += 1
                else:
                    cache_hit_count += 1
            elif baseline is not None:
                parsed = baseline
                baseline_reuse_count += 1
            else:
                if require_cached:
                    raise ValueError(
                        "no matching PDF SHA256 in reusable text/OCR candidates"
                    )
                parsed = corpus.parse_source(spec)
                if parsed.source_sha256 != pdf_sha:
                    raise ValueError("source PDF changed while parsing")
                parsed_count += 1
            parsed = corpus.reindex_parsed_source(parsed, spec)
            _write_cache(cache_path, parsed)
            candidates[pdf_sha] = (cache_path, _sha256(cache_path))
            low_text_pages = [
                page.page_number for page in parsed.pages if len(page.text.strip()) < 40
            ]
            entry = {
                "status": "parsed",
                "fingerprint": fingerprint,
                "cache_file": cache_path.name,
                "source_sha256": parsed.source_sha256,
                "parser_version": corpus.PARSER_VERSION,
                "cache_sha256": _sha256(cache_path),
                "page_count": len(parsed.pages),
                "clause_count": len(parsed.clauses),
                "table_count": len(parsed.tables),
                "low_text_page_count": len(low_text_pages),
                "low_text_pages": low_text_pages,
                "warning_count": len(parsed.warnings),
            }
            current_entries[relative_path] = entry
        except Exception as exc:
            failures.append({"source_path": relative_path, "error": str(exc)})
            current_entries[relative_path] = {
                "status": "failed",
                "fingerprint": fingerprint,
                "error": str(exc),
                **retained_cache,
            }
        _write_state(state_path, {**previous_entries, **current_entries})

    _write_state(state_path, {**previous_entries, **current_entries})
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
        descriptor, name = tempfile.mkstemp(
            prefix=output.name + ".", suffix=".staging", dir=output.parent,
        )
        os.close(descriptor)
        staging = Path(name)
        try:
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
                replace_atomic(staging, output)
                published = True
            else:
                failures.append(
                    {
                        "source_path": "<full-corpus-validation>",
                        "error": ", ".join(validation_report["failures"]),
                    }
                )
        finally:
            staging.unlink(missing_ok=True)

    report = {
        "schema_version": 1,
        "generated_at": _utc_now(),
        "manifest_path": str(manifest),
        "manifest_sha256": _sha256(manifest),
        "source_root": str(root),
        "requested_source_count": len(source_items),
        "parsed_count": parsed_count,
        "cache_hit_count": cache_hit_count,
        "baseline_reuse_count": baseline_reuse_count,
        "parser_version": corpus.PARSER_VERSION,
        "ocr_executed": False,
        "require_cached": require_cached,
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
    replace_atomic(temporary, path)


def _read_cache(path: Path) -> corpus.ParsedSource:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    for table in payload["tables"]:
        if not table.get("quality_status"):
            table["quality_status"] = "review_required"
            flags = list(table.get("quality_flags") or [])
            if "legacy_table_candidate" not in flags:
                flags.append("legacy_table_candidate")
            table["quality_flags"] = flags
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
    for relative_path, entry in entries:
        path = cache_root / str(entry["cache_file"])
        if entry.get("cache_sha256") and _sha256(path) != entry["cache_sha256"]:
            raise ValueError(f"cache content changed before indexing: {relative_path}")
        parsed = _read_cache(path)
        yield parsed


def _last_success(entry: dict[str, Any]) -> dict[str, Any] | None:
    if entry.get("status") == "parsed":
        return entry
    previous = entry.get("last_success")
    if isinstance(previous, dict) and previous.get("status") == "parsed":
        return previous
    return None


def _load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"sources": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unreadable incremental state: {path}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), dict):
        raise ValueError(f"invalid incremental state: {path}")
    return payload


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
    replace_atomic(temporary, path)


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
    parser.add_argument("--reuse-database", type=Path, action="append", default=[])
    parser.add_argument("--reuse-cache-dir", type=Path, action="append", default=[])
    parser.add_argument("--require-cached", action="store_true")
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
        reuse_databases=args.reuse_database,
        reuse_cache_dirs=args.reuse_cache_dir,
        require_cached=args.require_cached,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["published"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
