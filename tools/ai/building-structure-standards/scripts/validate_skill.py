from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from standards_query import (
    collect_advice_evidence,
    get_catalog_entry,
    get_clause,
    get_standard,
    search,
)


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = SKILL_ROOT / "assets" / "data" / "standards.sqlite"
DEFAULT_CATALOG = SKILL_ROOT / "assets" / "data" / "audit_catalog.json"
DEFAULT_CASES = SKILL_ROOT / "references" / "gold_cases.json"
DEFAULT_REPORT = SKILL_ROOT / "assets" / "data" / "validation_report.json"
DEFAULT_SOURCE_MANIFEST = SKILL_ROOT / "assets" / "data" / "source_manifest.json"


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
        actual = search(database, case["query"], limit=10)
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
    for key in (
        "found",
        "evidence_insufficient",
        "content_evidence_available",
        "evidence_level",
        "design_advice_allowed",
        "missing_content_codes",
    ):
        if key in expected and actual.get(key) != expected[key]:
            failures.append(
                f"{key}: expected {expected[key]!r}, got {actual.get(key)!r}"
            )
    if "official_status" in expected:
        container = actual.get("record") or actual.get("standard") or {}
        if container.get("official_status") != expected["official_status"]:
            failures.append(
                "official_status: "
                f"expected {expected['official_status']!r}, "
                f"got {container.get('official_status')!r}"
            )
    if expected.get("contains"):
        results = actual.get("results") or []
        text = "\n".join(item.get("text", "") for item in results)
        normalized_text = re.sub(r"\s+", "", text)
        normalized_expected = re.sub(r"\s+", "", expected["contains"])
        if normalized_expected not in normalized_text:
            failures.append(f"missing expected text: {expected['contains']}")
    if expected.get("clause_id"):
        ids = [item.get("clause_id") for item in actual.get("results") or []]
        if expected["clause_id"] not in ids:
            failures.append(f"expected clause {expected['clause_id']}, got {ids}")
    if expected.get("citation_required"):
        citations = [
            item.get("citation")
            for item in actual.get("results") or []
            if item.get("citation")
        ]
        if not citations:
            failures.append("citation is required")
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
        passed, failures, actual = run_case(
            case,
            database=database,
            catalog=catalog,
        )
        results.append(
            {
                "id": case["id"],
                "category": case["category"],
                "passed": passed,
                "failures": failures,
                "result_summary": {
                    "found": actual.get("found"),
                    "evidence_level": actual.get("evidence_level"),
                    "warnings": actual.get("warnings", []),
                },
            }
        )
    category_counts = Counter(case["category"] for case in cases)
    category_passed = Counter(
        result["category"] for result in results if result["passed"]
    )
    passed_count = sum(result["passed"] for result in results)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
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
    parser = argparse.ArgumentParser(
        description="Validate the offline standards skill."
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    args = parser.parse_args(argv)
    source_manifest = json.loads(args.source_manifest.read_text(encoding="utf-8"))
    source_count = len(source_manifest.get("sources", []))
    if source_count > 1:
        from validate_full_corpus import validate_full_corpus

        report = validate_full_corpus(
            database=args.database,
            source_manifest=args.source_manifest,
        )
    else:
        report = validate(
            database=args.database,
            catalog=args.catalog,
            cases_path=args.cases,
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
