from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SKILL = ROOT / "tools/ai/building-structure-standards"
REFERENCE = ROOT / "documents/AI/reviews/standards_pilot_20260903_reference_cases.json"


@pytest.fixture
def validator(monkeypatch):
    monkeypatch.syspath_prepend(str(SKILL / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "reference_validator_test", SKILL / "scripts/validate_skill.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def clause():
    return {
        "standard_code": "GB TEST-2026",
        "clause_id": "1.0.1",
        "text": "Reviewed body with area 1000m\u00b2.",
        "page_start": 7,
        "page_end": 7,
        "printed_page_start": "1",
        "anchor": "reviewed.pdf#page=7",
        "citation": "GB TEST-2026 page 7",
        "content_role": "normative",
        "quality_status": "usable",
        "quality_flags": [],
        "text_source": "native",
        "evidence_quality": "usable",
    }


def clause_case(**expected):
    return {
        "id": "clause",
        "category": "reference",
        "operation": "clause",
        "standard_code": "GB TEST-2026",
        "clause_id": "1.0.1",
        "expected": {"found": True, **expected},
    }


def run_rows(validator, monkeypatch, rows, case):
    actual = {"found": bool(rows), "results": rows}
    monkeypatch.setattr(validator, "get_clause", lambda *args: actual)
    return validator.run_case(case, database=Path("unused"), catalog=Path("unused"))


@pytest.mark.parametrize(
    ("field", "value", "expectation"),
    [
        ("text", "AUDIT_CORRUPTED_TEXT", {"contains": "Reviewed body"}),
        ("page_start", 2, {"pdf_page": 7}),
        ("page_end", 9, {"page_end": 7}),
        ("printed_page_start", "2", {"printed_page": "1"}),
        ("anchor", "wrong.pdf#page=2", {"anchor_page": 7}),
        ("content_role", "commentary", {"content_role": "normative"}),
        ("quality_status", "review_required", {"quality_status": "usable"}),
        ("text", "Reviewed body\n1.0.2 Adjacent clause", {"not_contains": ["1.0.2"]}),
        ("text", "Reviewed body 1000m\u00b0", {"not_contains": "1000m\u00b0"}),
        ("standard_code", "WRONG", {"result_standard_code": "GB TEST-2026"}),
        ("quality_flags", ["unit_suspect"], {"quality_flags_not_contains": ["unit_suspect"]}),
    ],
)
def test_rejects_corrupted_result(validator, monkeypatch, clause, field, value, expectation):
    clause[field] = value
    passed, failures, _ = run_rows(validator, monkeypatch, [clause], clause_case(**expectation))
    assert not passed, f"silently accepted {field}={value!r}"
    assert failures


@pytest.mark.parametrize("hash_state", ["correct", "wrong", "none", "missing"])
def test_source_sha256_is_a_row_assertion(validator, monkeypatch, clause, hash_state):
    expected_hash = "a" * 64
    if hash_state != "missing":
        clause["source_sha256"] = {
            "correct": expected_hash,
            "wrong": "b" * 64,
            "none": None,
        }[hash_state]
    passed, failures, _ = run_rows(
        validator,
        monkeypatch,
        [clause],
        clause_case(contains="Reviewed body", source_sha256=expected_hash),
    )
    assert passed is (hash_state == "correct"), failures
    assert not any("unknown assertion" in failure for failure in failures)
    if not passed:
        assert any("source_sha256:" in failure for failure in failures)


@pytest.mark.parametrize("field", ["clause_id", "citation", "page_start", "content_role"])
def test_all_assertions_must_match_one_result(validator, monkeypatch, clause, field):
    other = copy.deepcopy(clause)
    clause["text"] = "wrong body"
    other[field] = {
        "clause_id": "1.0.2",
        "citation": "",
        "page_start": 9,
        "content_role": "commentary",
    }[field]
    case = clause_case(
        contains="Reviewed body",
        clause_id="1.0.1",
        citation_required=True,
        pdf_page=7,
        content_role="normative",
    )
    passed, failures, _ = run_rows(validator, monkeypatch, [clause, other], case)
    assert not passed
    assert "same result" in " ".join(failures)


def test_text_cannot_be_concatenated_across_results(validator, monkeypatch, clause):
    other = {**clause, "text": "body"}
    clause["text"] = "Reviewed"
    assert not run_rows(
        validator, monkeypatch, [clause, other], clause_case(contains="Reviewed body")
    )[0]


def test_valid_result_may_follow_unrelated_results(validator, monkeypatch, clause):
    other = {**clause, "text": "1.0.2 Adjacent clause", "clause_id": "1.0.2"}
    case = clause_case(
        contains=["Reviewed body", "1000m\u00b2"],
        not_contains=["1.0.2"],
        clause_id="1.0.1",
        pdf_page=7,
        printed_page="1",
        content_role="normative",
        quality_status="usable",
    )
    assert run_rows(validator, monkeypatch, [other, clause], case)[0]


@pytest.mark.parametrize("unit", ["1000m\u00b2", "1000m2", "1000m^2", "1000\u5e73\u65b9\u7c73"])
def test_explicit_unit_equivalents(validator, monkeypatch, clause, unit):
    clause["text"] = unit
    assert run_rows(
        validator,
        monkeypatch,
        [clause],
        clause_case(
            contains_any=["1000m\u00b2", "1000m2", "1000m^2", "1000\u5e73\u65b9\u7c73"],
            not_contains="1000m\u00b0",
        ),
    )[0]


def test_missing_quality_and_unknown_assertions_fail_closed(validator, monkeypatch, clause):
    clause.pop("quality_status")
    assert not run_rows(validator, monkeypatch, [clause], clause_case(quality_status="usable"))[0]
    assert not run_rows(validator, monkeypatch, [clause], clause_case(contians="Reviewed body"))[0]


def test_unit_alternatives_do_not_accept_corruption(validator, monkeypatch, clause):
    clause["text"] = "1000m\u00b0"
    assert not run_rows(
        validator, monkeypatch, [clause], clause_case(contains_any=["1000m\u00b2", "1000m2"])
    )[0]


def test_legacy_smoke_quality_uses_new_page_metadata(validator, monkeypatch, clause):
    clause.pop("evidence_quality")
    clause.pop("text_source")
    clause["page_quality"] = [{"text_source": "native"}, {"text_source": "ocr"}]
    case = clause_case(
        evidence_quality_in=["usable", "review_required", "legacy"],
        text_source_in=["native", "ocr", "blank"],
    )
    assert run_rows(validator, monkeypatch, [clause], case)[0]
    clause["page_quality"][1]["text_source"] = "unknown"
    assert not run_rows(validator, monkeypatch, [clause], case)[0]


@pytest.fixture
def table():
    return {
        "standard_code": "GB TEST-2026",
        "table_id": "p15-t1",
        "table_label": "3.2.2",
        "page_number": 15,
        "printed_page": "7",
        "anchor": "reviewed.pdf#page=15",
        "citation": "GB TEST-2026 table 3.2.2 page 15",
        "quality_status": "usable",
        "visual_required": False,
        "unit": "m",
        "rows": [["type", "civil/I-II", "civil/III"], ["other", "6", "7"]],
    }


def table_case(**expected):
    return {
        "id": "table",
        "category": "reference",
        "operation": "table",
        "standard_code": "GB TEST-2026",
        "table_id": "3.2.2",
        "expected": {"found": True, "table_label": "3.2.2", **expected},
    }


def run_table(validator, monkeypatch, table, case):
    monkeypatch.setattr(
        validator, "get_table", lambda *args: {"found": True, "table": table}, raising=False
    )
    return validator.run_case(case, database=Path("unused"), catalog=Path("unused"))


@pytest.mark.parametrize("corruption", ["none", "unit", "swapped", "flattened", "label", "page"])
def test_table_units_cells_and_location(validator, monkeypatch, table, corruption):
    case = table_case(
        unit="m",
        pdf_page=15,
        printed_page="7",
        table_cells=[
            {"row": "other", "column": "civil/I-II", "value": "6"},
            {"row": "other", "column": "civil/III", "value": "7"},
        ],
    )
    if corruption == "unit":
        table["unit"] = "mm"
    elif corruption == "swapped":
        table["rows"][1][1:] = ["7", "6"]
    elif corruption == "flattened":
        table["rows"] = []
        table["markdown"] = "other civil/I-II civil/III 6 7 m"
    elif corruption == "label":
        table["table_label"] = "3.2.3"
    elif corruption == "page":
        table["page_number"] = 16
    passed, _, _ = run_table(validator, monkeypatch, table, case)
    assert passed is (corruption == "none")


def test_visual_fallback_does_not_bypass_common_location_checks(validator, monkeypatch, table):
    table.update(rows=[], quality_status="visual_required", visual_required=True)
    case = table_case(
        pdf_page=15,
        citation_required=True,
        any_of=[
            {"quality_status": "usable", "table_cells": [{"row": 1, "column": 1, "value": "6"}]},
            {"quality_status": "visual_required", "visual_required": True},
        ],
    )
    assert run_table(validator, monkeypatch, table, case)[0]
    table["page_number"] = 2
    assert not run_table(validator, monkeypatch, table, case)[0]


def test_visual_required_cannot_return_unverified_cells(validator, monkeypatch, table):
    table.update(quality_status="visual_required", table_quality_status="visual_required")
    table.pop("visual_required")
    case = table_case(table_quality_status="visual_required", visual_required=True)
    assert not run_table(validator, monkeypatch, table, case)[0]
    table["rows"] = []
    assert run_table(validator, monkeypatch, table, case)[0]


def test_visual_locator_cannot_claim_design_advice_allowed(validator, monkeypatch, table):
    table.update(rows=[], quality_status="visual_required", visual_required=True)
    monkeypatch.setattr(
        validator,
        "get_table",
        lambda *args: {
            "found": True,
            "table": table,
            "design_advice_allowed": True,
        },
    )
    passed, _, _ = validator.run_case(
        table_case(visual_required=True), database=Path("unused"), catalog=Path("unused")
    )
    assert not passed


def test_reference_excludes_adjacent_body_even_without_clause_number(validator, monkeypatch):
    payload = json.loads(REFERENCE.read_text(encoding="utf-8"))
    case = payload["cases"][0]
    sample = payload["samples"][0]
    row = {
        "standard_code": sample["standard_code"],
        "clause_id": "1.0.1",
        "page_start": 7,
        "page_end": 7,
        "printed_page_start": "1",
        "anchor": "reviewed.pdf#page=7",
        "citation": "reviewed page",
        "content_role": "normative",
        "quality_status": "usable",
        "text": sample["expected_text"]
        + "\u672c\u6807\u51c6\u9002\u7528\u4e8e\u6297\u9707\u8bbe\u9632\u533a\u5efa\u7b51\u5de5\u7a0b\u7684\u6297\u9707\u8bbe\u9632\u5206\u7c7b\u3002",
    }
    assert not run_rows(validator, monkeypatch, [row], case)[0]


def test_query_errors_are_reported_not_treated_as_empty_success(validator, monkeypatch, tmp_path):
    def broken_query(*args):
        raise sqlite3.OperationalError("test query failure")

    monkeypatch.setattr(validator, "get_clause", broken_query)
    cases = write_cases(tmp_path, {"cases": [clause_case(found=False)]})
    report = validator.validate(database=cases, catalog=cases, cases_path=cases)
    assert report["failed_count"] == 1
    assert "OperationalError" in report["results"][0]["failures"][0]


@pytest.mark.parametrize("printed_page", ["7", ""])
def test_reference_visual_branch_matches_real_query_without_relaxing_printed_page(
    validator, tmp_path, printed_page
):
    payload = json.loads(REFERENCE.read_text(encoding="utf-8"))
    sample = next(
        item for item in payload["samples"] if item["id"] == "scan-table-column-associations"
    )
    case = next(item for item in payload["cases"] if item["reference_sample_id"] == sample["id"])
    assert case["expected"]["printed_page"] == sample["printed_page"] == "7"
    assert case["expected"]["any_of"][0]["table_cells"] == sample["sample_cells"]
    assert [cell["value"] for cell in sample["sample_cells"]] == ["6", "7", "25"]
    assert case["expected"]["any_of"][0]["unit"] == sample["unit"] == "m"

    database = tmp_path / "visual-table.sqlite"
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE sources (
                source_id INTEGER PRIMARY KEY, standard_code TEXT, standard_name TEXT,
                version TEXT, official_status TEXT, replacement_standard TEXT,
                authorization TEXT, confidentiality TEXT, source_sha256 TEXT
            );
            CREATE TABLE pages (
                source_id INTEGER, page_number INTEGER, printed_page TEXT,
                text_source TEXT, quality_status TEXT, quality_flags_json TEXT,
                content_role TEXT
            );
            CREATE TABLE standard_tables (
                source_id INTEGER, table_id TEXT, page_number INTEGER, rows_json TEXT,
                markdown TEXT, anchor TEXT, quality_status TEXT, table_label TEXT,
                quality_flags_json TEXT
            );
        """)
        connection.execute(
            "INSERT INTO sources VALUES (1, ?, 'reviewed table', '2009', ?, '', ?, '', ?)",
            (
                sample["standard_code"],
                "\u73b0\u884c",
                "\u5df2\u6388\u6743",
                sample["source_sha256"],
            ),
        )
        connection.execute(
            "INSERT INTO pages VALUES (1, 15, ?, 'ocr', 'usable', '[]', 'normative')",
            (printed_page,),
        )
        connection.execute(
            "INSERT INTO standard_tables VALUES (1, 'p15-t1', 15, '[]', '', "
            "'reviewed.pdf#page=15', 'visual_required', '3.2.2', '[]')"
        )

    passed, failures, actual = validator.run_case(case, database=database, catalog=REFERENCE)
    assert actual["table"]["table_quality_status"] == "visual_required"
    assert actual["table"]["quality_status"] == "visual_required"
    assert actual["table"]["rows"] == []
    assert actual["design_advice_allowed"] is False
    assert passed is bool(printed_page), failures
    assert not any("quality_status:" in failure for failure in failures), failures
    if not printed_page:
        assert any("printed_page:" in failure for failure in failures)

    cases = write_cases(tmp_path, {**payload, "cases": [case]})
    report = validator.validate(database=database, catalog=REFERENCE, cases_path=cases)
    assert report["independent_quality_gold"] is True
    assert report["passed_count"] == int(bool(printed_page))
    assert report["visual_locator_only_passed_count"] == int(bool(printed_page))
    assert report["independent_content_passed_count"] == 0
    assert report["independent_content_validation_passed"] is False


@pytest.mark.parametrize("mode", ["structured", "visual"])
@pytest.mark.parametrize("hash_state", ["correct", "wrong", "none", "missing"])
def test_independent_report_separates_content_from_visual_locator(
    validator, monkeypatch, mode, hash_state
):
    payload = json.loads(REFERENCE.read_text(encoding="utf-8"))
    rows = {}
    for sample in payload["samples"]:
        if "clause_id" not in sample:
            continue
        rows[sample["clause_id"]] = {
            "standard_code": sample["standard_code"],
            "source_sha256": sample["source_sha256"],
            "clause_id": sample["clause_id"],
            "text": sample.get(
                "expected_text", sample.get("expected_body_start", sample.get("expected_fragment"))
            ),
            "page_start": sample["pdf_page"],
            "page_end": sample["pdf_page"],
            "printed_page_start": sample["printed_page"],
            "anchor": f"reviewed.pdf#page={sample['pdf_page']}",
            "citation": "reviewed page",
            "content_role": "normative",
            "quality_status": "usable",
        }
    sample = payload["samples"][2]
    table = {
        "standard_code": sample["standard_code"],
        "source_sha256": sample["source_sha256"],
        "table_label": "\u88683.2.2",
        "table_id": "p15-t1",
        "page_number": 15,
        "printed_page": "7",
        "anchor": "reviewed.pdf#page=15",
        "citation": "reviewed table page",
        "unit": "m",
        "quality_status": "usable",
        "table_quality_status": "usable",
        "rows": [
            ["type", *[cell["column"] for cell in sample["sample_cells"]]],
            [sample["sample_cells"][0]["row"], "6", "7", "25"],
        ],
    }
    if mode == "visual":
        table.update(
            rows=[], table_quality_status="visual_required", quality_status="visual_required"
        )
    for row in [*rows.values(), table]:
        if hash_state == "wrong":
            row["source_sha256"] = "0" * 64
        elif hash_state == "none":
            row["source_sha256"] = None
        elif hash_state == "missing":
            row.pop("source_sha256")
    monkeypatch.setattr(
        validator,
        "get_clause",
        lambda db, code, clause_id: {
            "found": True,
            "results": [rows[clause_id]],
        },
    )
    monkeypatch.setattr(
        validator,
        "get_table",
        lambda *args: {
            "found": True,
            "table": table,
            "design_advice_allowed": mode != "visual",
            "evidence_insufficient": mode == "visual",
        },
    )
    report = validator.validate(database=REFERENCE, catalog=REFERENCE, cases_path=REFERENCE)
    assert report["independent_quality_gold"] is True
    if hash_state != "correct":
        assert report["failed_count"] == 4, report["results"]
        assert report["independent_content_passed_count"] == 0
        assert report["visual_locator_only_passed_count"] == 0
        assert report["independent_content_validation_passed"] is False
        assert all(
            any("source_sha256:" in failure for failure in result["failures"])
            for result in report["results"]
        )
        return
    assert report["passed_count"] == 4, report["results"]
    assert report["independent_content_passed_count"] == (4 if mode == "structured" else 3)
    assert report["visual_locator_only_passed_count"] == (0 if mode == "structured" else 1)
    assert report["independent_content_validation_passed"] is (mode == "structured")


def write_cases(tmp_path, payload):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.parametrize("override_case_hash", [False, True])
def test_independent_reference_hash_cannot_be_borrowed_from_another_row(
    validator, monkeypatch, tmp_path, clause, override_case_hash
):
    payload = json.loads(REFERENCE.read_text(encoding="utf-8"))
    sample = payload["samples"][0]
    case = payload["cases"][0]
    wrong_hash = "0" * 64
    if override_case_hash:
        case["expected"]["source_sha256"] = wrong_hash
    clause.update(
        standard_code=sample["standard_code"],
        text=sample["expected_text"],
        source_sha256=wrong_hash,
    )
    other = {**clause, "source_sha256": sample["source_sha256"], "text": "AUDIT_CORRUPTED_TEXT"}
    monkeypatch.setattr(
        validator,
        "get_clause",
        lambda *args: {
            "found": True,
            "results": [clause, other],
        },
    )
    cases = write_cases(tmp_path, {**payload, "cases": [case]})
    original_cases = cases.read_bytes()
    report = validator.validate(database=cases, catalog=cases, cases_path=cases)
    assert report["failed_count"] == 1, report["results"]
    assert report["independent_content_passed_count"] == 0
    failures = report["results"][0]["failures"]
    assert any("same result" in failure for failure in failures)
    assert any(
        "source_sha256:" in failure and sample["source_sha256"] in failure for failure in failures
    )
    assert cases.read_bytes() == original_cases


@pytest.mark.parametrize(
    "payload_extra",
    [{}, {"kind": "independent_reference"}, {"database_sha256": "generated-from-target"}],
)
def test_status_only_cases_never_claim_independent_content(
    validator, monkeypatch, tmp_path, clause, payload_extra
):
    monkeypatch.setattr(validator, "get_clause", lambda *args: {"found": True, "results": [clause]})
    cases = write_cases(tmp_path, {**payload_extra, "cases": [clause_case()]})
    report = validator.validate(database=cases, catalog=cases, cases_path=cases)
    assert report["passed_count"] == 1
    assert report["validation_kind"] == "functional_smoke"
    assert report["independent_content_passed_count"] == 0
    assert report["independent_content_validation_passed"] is False
    assert report["independent_quality_gold"] is False
    assert report["content_assertion_case_count"] == 0


def test_reference_cases_retain_review_and_are_runnable(validator, monkeypatch, tmp_path):
    payload = json.loads(REFERENCE.read_text(encoding="utf-8"))
    assert len(payload["samples"]) == 4
    assert len(payload["cases"]) == 4
    assert {case["reference_sample_id"] for case in payload["cases"]} == {
        sample["id"] for sample in payload["samples"]
    }
    for function in ("get_clause", "get_table"):
        monkeypatch.setattr(
            validator, function, lambda *args: {"found": False, "results": []}, raising=False
        )
    report = validator.validate(database=REFERENCE, catalog=REFERENCE, cases_path=REFERENCE)
    assert report["validation_kind"] == "independent_reference"
    assert report["case_count"] == 4
    assert report["failed_count"] == 4
    assert report["independent_quality_gold"] is True
    assert report["independent_content_validation_passed"] is False


def test_cli_explicit_cases_not_replaced_by_multi_source_inventory(
    validator, monkeypatch, tmp_path
):
    cases = write_cases(tmp_path, {"cases": []})
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"sources": [{}, {}]}), encoding="utf-8")
    seen = []
    monkeypatch.setattr(
        validator,
        "validate",
        lambda **kwargs: (
            seen.append(kwargs)
            or {
                "case_count": 1,
                "failed_count": 1,
            }
        ),
    )
    code = validator.main(
        [
            "--database",
            str(SKILL / "assets/data/standards.sqlite"),
            "--cases",
            str(cases),
            "--source-manifest",
            str(manifest),
            "--report",
            str(tmp_path / "report.json"),
        ]
    )
    assert seen and seen[0]["cases_path"] == cases
    assert code == 1


def test_real_database_corruption_is_detected_without_touching_source(validator, tmp_path):
    source = SKILL / "assets/data/standards.sqlite"
    database = tmp_path / "corrupted.sqlite"
    shutil.copyfile(source, database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE clauses SET text=?, page_start=2, anchor=? WHERE clause_id=?",
            ("AUDIT_CORRUPTED_TEXT", "wrong.pdf#page=2", "1.1.1"),
        )
    case = {
        **clause_case(contains="\u6c34\u51b7\u53cd\u5e94\u5806", pdf_page=3),
        "standard_code": "HAF 101-2023",
        "clause_id": "1.1.1",
    }
    passed, failures, _ = validator.run_case(
        case, database=database, catalog=SKILL / "assets/data/audit_catalog.json"
    )
    assert not passed
    assert any("pdf_page" in failure for failure in failures)
