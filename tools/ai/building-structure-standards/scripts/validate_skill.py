from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from standards_query import (
    collect_advice_evidence,
    get_catalog_entry,
    get_clause,
    get_standard,
    get_table,
    search,
)

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = SKILL_ROOT / "assets" / "data" / "standards.sqlite"
DEFAULT_CATALOG = SKILL_ROOT / "assets" / "data" / "audit_catalog.json"
DEFAULT_CASES = SKILL_ROOT / "references" / "gold_cases.json"
DEFAULT_REPORT = SKILL_ROOT / "assets" / "data" / "validation_report.json"
DEFAULT_SOURCE_MANIFEST = SKILL_ROOT / "assets" / "data" / "source_manifest.json"

ENVELOPE_KEYS = frozenset(
    {
        "found",
        "evidence_insufficient",
        "content_evidence_available",
        "evidence_level",
        "design_advice_allowed",
        "missing_content_codes",
        "warning_contains",
    }
)
ROW_KEYS = frozenset(
    {
        "official_status",
        "result_standard_code",
        "source_sha256",
        "clause_id",
        "contains",
        "contains_any",
        "not_contains",
        "citation_required",
        "pdf_page",
        "page_start",
        "page_end",
        "printed_page",
        "printed_page_start",
        "printed_page_end",
        "anchor",
        "anchor_page",
        "content_role",
        "quality_status",
        "quality_flags_contains",
        "quality_flags_not_contains",
        "evidence_quality_in",
        "text_source_in",
        "table_id",
        "table_label",
        "table_cells",
        "unit",
        "visual_required",
        "table_quality_status",
        "any_of",
    }
)


def _normalized(value: Any) -> str:
    # Whitespace only: never fold superscripts, degrees, signs or decimal punctuation.
    return re.sub(r"\s+", "", str(value))


def _fragments(value: Any) -> list[str]:
    values = [value] if isinstance(value, str) else value
    if (
        not isinstance(values, list)
        or not values
        or any(not isinstance(item, str) or not item.strip() for item in values)
    ):
        raise ValueError("text assertions require non-empty strings")
    return values


def _row_value(row: dict[str, Any], key: str) -> Any:
    aliases = {
        "result_standard_code": "standard_code",
        "pdf_page": "page_start",
        "printed_page": "printed_page_start",
    }
    if key == "pdf_page" and "page_number" in row:
        return row["page_number"]
    if key in row:
        return row[key]
    if key == "quality_status" and row.get("page_quality"):
        statuses = {page.get("quality_status") for page in row["page_quality"]}
        return next(iter(statuses)) if len(statuses) == 1 else "mixed"
    if key == "visual_required":
        status = row.get("table_quality_status") or _row_value(row, "quality_status")
        return status == "visual_required" if status else None
    return row.get(aliases.get(key, key))


def _table_cell(row: dict[str, Any], cell: dict[str, Any]) -> Any:
    rows = row.get("rows") or []
    row_key, column_key = cell["row"], cell["column"]
    if not isinstance(rows, list) or not all(isinstance(item, list) for item in rows):
        raise ValueError("table rows must be a matrix, not flattened text")
    if isinstance(row_key, str):
        indexes = [
            i
            for i, values in enumerate(rows)
            if values and _normalized(values[0]) == _normalized(row_key)
        ]
        if len(indexes) != 1:
            raise ValueError(f"missing or ambiguous row label {row_key!r}")
        row_key = indexes[0]
    if isinstance(column_key, str):
        indexes = [
            i
            for i, value in enumerate(rows[0] if rows else [])
            if _normalized(value) == _normalized(column_key)
        ]
        if len(indexes) != 1:
            raise ValueError(f"missing or ambiguous column label {column_key!r}")
        column_key = indexes[0]
    if type(row_key) is not int or type(column_key) is not int or min(row_key, column_key) < 0:
        raise ValueError("table coordinates must be non-negative integers or exact labels")
    return rows[row_key][column_key]


def _row_failures(row: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    failures = [f"unknown assertion: {key}" for key in expected.keys() - ROW_KEYS]
    text = _normalized(row.get("text", row.get("markdown", "")))
    for key, value in expected.items():
        if key in {"contains", "not_contains", "contains_any"}:
            fragments = _fragments(value)
            matches = [_normalized(fragment) in text for fragment in fragments]
            valid = (
                any(matches)
                if key == "contains_any"
                else (not any(matches) if key == "not_contains" else all(matches))
            )
            if not valid:
                failures.append(f"{key}: expected {value!r}")
        elif key == "citation_required":
            if value and not str(row.get("citation") or "").strip():
                failures.append("citation is required")
        elif key == "anchor_page":
            pages = parse_qs(urlsplit(str(row.get("anchor") or "")).fragment).get("page")
            if pages != [str(value)]:
                failures.append(f"anchor_page: expected {value!r}, got {pages!r}")
        elif key in {"evidence_quality_in", "text_source_in"}:
            field = key.removesuffix("_in")
            actual_values = (
                [row[field]]
                if field in row
                else (
                    [_row_value(row, "quality_status")]
                    if key == "evidence_quality_in"
                    else [page.get("text_source") for page in row.get("page_quality", [])]
                )
            )
            if not actual_values or any(actual not in value for actual in actual_values):
                failures.append(f"{key}: expected each in {value!r}, got {actual_values!r}")
        elif key in {"quality_flags_contains", "quality_flags_not_contains"}:
            flags = row.get("quality_flags")
            if flags is None and "quality_flags_json" in row:
                flags = json.loads(row["quality_flags_json"])
            valid = isinstance(flags, list) and all(isinstance(flag, str) for flag in flags)
            if valid:
                valid = (
                    all(flag in flags for flag in value)
                    if key == "quality_flags_contains"
                    else (all(flag not in flags for flag in value))
                )
            if not valid:
                failures.append(f"{key}: expected {value!r}, got {flags!r}")
        elif key == "table_cells":
            if not isinstance(value, list) or not value:
                raise ValueError("table_cells requires at least one cell")
            for cell in value:
                try:
                    actual = _table_cell(row, cell)
                    if _normalized(actual) != _normalized(cell["value"]):
                        failures.append(f"table_cells: expected {cell!r}, got {actual!r}")
                except (IndexError, KeyError, TypeError, ValueError) as exc:
                    failures.append(f"table_cells: {cell!r}: {exc}")
        elif key == "any_of":
            if not isinstance(value, list) or not value or not all(value):
                raise ValueError("any_of requires non-empty assertion branches")
            branches = [_row_failures(row, branch) for branch in value]
            if all(branches):
                failures.append(f"any_of: no branch matched: {branches!r}")
        elif key == "unit":
            actual = row.get("unit")
            if actual is None:
                # Accept an explicit parenthesized title unit, not a substring of mm or m2.
                title = _normalized(row.get("markdown", ""))
                valid = any(token in title for token in (f"({value})", f"\uff08{value}\uff09"))
            else:
                valid = _normalized(actual) == _normalized(value)
            if not valid:
                failures.append(f"unit: expected {value!r}, got {actual!r}")
        elif key == "visual_required":
            if _row_value(row, key) is not value:
                failures.append(f"visual_required: expected {value!r}")
            if value and "table_id" in row and row.get("rows") != []:
                failures.append("visual_required table must not return unverified cells")
        elif key in ROW_KEYS:
            actual = _row_value(row, key)
            if key == "table_label":
                actual = re.sub(r"^\u8868", "", _normalized(actual))
                value = re.sub(r"^\u8868", "", _normalized(value))
            if actual != value:
                failures.append(f"{key}: expected {value!r}, got {actual!r}")
    return failures


def _result_rows(actual: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("results", "evidence"):
        if key in actual:
            return actual[key] or []
    return [actual[key] for key in ("table", "record", "standard") if actual.get(key)]


def _has_content_assertion(expected: dict[str, Any]) -> bool:
    return any(expected.get(key) for key in ("contains", "contains_any", "table_cells")) or any(
        _has_content_assertion(branch) for branch in expected.get("any_of", [])
    )


def _content_matched(row: dict[str, Any], expected: dict[str, Any]) -> bool:
    if _row_value(row, "visual_required") is True:
        return False
    if any(expected.get(key) for key in ("contains", "contains_any", "table_cells")):
        return True
    return any(
        not _row_failures(row, branch) and _content_matched(row, branch)
        for branch in expected.get("any_of", [])
    )


def _is_independent(case: dict[str, Any], payload: dict[str, Any]) -> bool:
    if payload.get("kind") != "independent_visual_review_samples" or payload.get("database_sha256"):
        return False
    sample = next(
        (
            sample
            for sample in payload.get("samples", [])
            if sample.get("id") == case.get("reference_sample_id")
        ),
        {},
    )
    expected = case["expected"]
    return bool(
        payload.get("reviewer")
        and payload.get("review_date")
        and sample.get("source_path")
        and re.fullmatch(r"[0-9a-fA-F]{64}", sample.get("source_sha256", ""))
        and sample.get("standard_code") == case.get("standard_code")
        and sample.get("pdf_page") == expected.get("pdf_page")
        and sample.get("printed_page") == expected.get("printed_page")
        and _has_content_assertion(expected)
    )


def run_case(
    case: dict[str, Any],
    *,
    database: Path,
    catalog: Path,
) -> tuple[bool, list[str], dict[str, Any]]:
    operation = case["operation"]
    if operation == "clause":
        actual = get_clause(
            database,
            case["standard_code"],
            case["clause_id"],
        )
    elif operation == "search":
        actual = search(
            database,
            case["query"],
            standard_code=case.get("standard_code", ""),
            limit=10,
        )
    elif operation == "table":
        actual = get_table(database, case["standard_code"], case["table_id"])
    elif operation == "catalog":
        actual = get_catalog_entry(catalog, case["standard_code"])
    elif operation == "standard":
        actual = get_standard(database, case["standard_code"])
    elif operation == "advice":
        actual = collect_advice_evidence(
            database,
            catalog,
            case["query"],
            requested_codes=case["requested_codes"],
        )
    else:
        raise ValueError(f"unknown operation: {operation}")

    failures: list[str] = []
    expected = case["expected"]
    for key in ENVELOPE_KEYS - {"warning_contains"}:
        if key in expected and actual.get(key) != expected[key]:
            failures.append(f"{key}: expected {expected[key]!r}, got {actual.get(key)!r}")
    if "warning_contains" in expected:
        for fragment in _fragments(expected["warning_contains"]):
            if not any(fragment in warning for warning in actual.get("warnings", [])):
                failures.append(f"warning_contains: missing {fragment!r}")
    row_expected = {key: value for key, value in expected.items() if key not in ENVELOPE_KEYS}
    if row_expected:
        candidates = [_row_failures(row, row_expected) for row in _result_rows(actual)]
        if not candidates or all(candidates):
            failures.append("all row assertions must match the same result")
            for index, candidate_failures in enumerate(candidates):
                failures.extend(f"result[{index}]: {failure}" for failure in candidate_failures)
    if operation == "table" and any(
        _row_value(row, "visual_required") is True
        and (
            actual.get("design_advice_allowed") is True or row.get("design_advice_allowed") is True
        )
        for row in _result_rows(actual)
    ):
        failures.append("visual_required table must not allow final design advice")
    return not failures, failures, actual


def validate(
    *,
    database: Path,
    catalog: Path,
    cases_path: Path,
) -> dict[str, Any]:
    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = payload["cases"]
    results: list[dict[str, Any]] = []
    for case in cases:
        independent = _is_independent(case, payload)
        if independent:
            sample = next(
                sample
                for sample in payload["samples"]
                if sample["id"] == case["reference_sample_id"]
            )
            # Bind every row assertion to the reviewed PDF, not a case-level override.
            case = {
                **case,
                "expected": {**case["expected"], "source_sha256": sample["source_sha256"]},
            }
        try:
            passed, failures, actual = run_case(case, database=database, catalog=catalog)
        except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
            passed, failures, actual = False, [f"{type(exc).__name__}: {exc}"], {}
        row_expected = {
            key: value for key, value in case["expected"].items() if key not in ENVELOPE_KEYS
        }
        content_validated = passed and any(
            not _row_failures(row, row_expected) and _content_matched(row, row_expected)
            for row in _result_rows(actual)
        )
        results.append(
            {
                "id": case["id"],
                "category": case["category"],
                "passed": passed,
                "failures": failures,
                "has_content_assertion": _has_content_assertion(case["expected"]),
                "independent_reference": independent,
                "content_validated": content_validated,
                "independent_content_validated": independent and content_validated,
                "visual_locator_only": passed
                and not content_validated
                and any(
                    _row_value(row, "visual_required") is True
                    and not _row_failures(row, row_expected)
                    for row in _result_rows(actual)
                ),
                "result_summary": {
                    "found": actual.get("found"),
                    "evidence_level": actual.get("evidence_level"),
                    "warnings": actual.get("warnings", []),
                },
            }
        )
    category_counts = Counter(case["category"] for case in cases)
    category_passed = Counter(result["category"] for result in results if result["passed"])
    passed_count = sum(result["passed"] for result in results)
    independent_count = sum(result["independent_reference"] for result in results)
    independent_passed = sum(result["independent_content_validated"] for result in results)
    independent_set = bool(cases) and independent_count == len(cases)
    return {
        "schema_version": 2,
        "validation_kind": "independent_reference" if independent_set else "functional_smoke",
        "independent_quality_gold": independent_set,
        "content_assertion_case_count": sum(result["has_content_assertion"] for result in results),
        "independent_reference_case_count": independent_count,
        "independent_content_passed_count": independent_passed,
        "independent_content_validation_passed": independent_set
        and independent_passed == len(cases),
        "visual_locator_only_passed_count": sum(
            result["visual_locator_only"] for result in results
        ),
        "quality_scope": (
            "Manually reviewed reference pages only; visual locators do not validate table cells."
            if independent_set
            else "Functional smoke only, not an independent content quality gold set."
        ),
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "case_count": len(cases),
        "passed_count": passed_count,
        "failed_count": len(cases) - passed_count,
        "pass_rate": passed_count / len(cases) if cases else 0,
        "categories": {
            category: {
                "case_count": count,
                "passed_count": category_passed[category],
            }
            for category, count in sorted(category_counts.items())
        },
        "database_sha256": _sha256(database),
        "catalog_sha256": _sha256(catalog),
        "cases_sha256": _sha256(cases_path),
        "results": results,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the offline standards skill.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument(
        "--cases",
        type=Path,
        help="Explicit cases always run, including multi-source corpora.",
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    args = parser.parse_args(argv)
    source_count = 0
    if args.cases is None:
        source_manifest = json.loads(args.source_manifest.read_text(encoding="utf-8"))
        source_count = len(source_manifest.get("sources", []))
    if source_count > 1:
        from validate_full_corpus import validate_full_corpus

        report = validate_full_corpus(
            database=args.database,
            source_manifest=args.source_manifest,
        )
        report["independent_quality_gold"] = False
        report["independent_content_validation_passed"] = False
    else:
        report = validate(
            database=args.database,
            catalog=args.catalog,
            cases_path=args.cases or DEFAULT_CASES,
        )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "results"},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
