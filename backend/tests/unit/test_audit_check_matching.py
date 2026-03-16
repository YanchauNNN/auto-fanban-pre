from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from src.audit_check.lexicon import AuditLexiconLoader
from src.audit_check.matcher import AuditMatchEngine
from src.audit_check.models import ScanTextItem


def _build_lexicon_workbook(path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Sheet1"
    ws.append(["project", "1418", "2016", "2026", "note"])
    ws.append(["lexicon", "CHANGJIANG", "JINQIMEN", "XUWEI", "note"])
    ws.append([None, "1418YNI-JGS01", "20161NH-JGS01-002", "20261NH-JGS01-002", None])
    ws.append([None, "SHARED", "SHARED", "OTHER", None])
    ws.append([None, "HL", "JD", "XZ", None])
    wb.save(path)
    return path


def test_lexicon_loader_includes_row1_and_row2_and_ignores_note_columns(tmp_path: Path) -> None:
    workbook = _build_lexicon_workbook(tmp_path / "lexicon.xlsx")

    lexicon = AuditLexiconLoader().load(workbook)

    assert lexicon.project_options == ["1418", "2016", "2026"]
    assert "1418" in lexicon.allowed_texts["1418"]
    assert "CHANGJIANG" in lexicon.allowed_texts["1418"]
    assert "JINQIMEN" in lexicon.foreign_texts["1418"]
    assert "2026" in lexicon.foreign_texts["1418"]
    assert "SHARED" not in lexicon.foreign_texts["1418"]


def test_match_engine_reports_code_like_project_no_and_short_code_but_suppresses_noise(
    tmp_path: Path,
) -> None:
    workbook = _build_lexicon_workbook(tmp_path / "lexicon.xlsx")
    lexicon = AuditLexiconLoader().load(workbook)
    engine = AuditMatchEngine(lexicon)

    findings = engine.evaluate(
        project_no="1418",
        items=[
            ScanTextItem(raw_text="20161NH-JGS01-002", entity_type="TEXT"),
            ScanTextItem(raw_text="JD1NHT11001B25C42SD", entity_type="TEXT"),
            ScanTextItem(raw_text="2026.03.12", entity_type="TEXT"),
            ScanTextItem(raw_text="2026.04", entity_type="TEXT"),
            ScanTextItem(raw_text="645X600X2016", entity_type="TEXT"),
            ScanTextItem(raw_text="RVV2016P", entity_type="TEXT"),
            ScanTextItem(raw_text="ABCD2016X", entity_type="TEXT"),
            ScanTextItem(raw_text="smooth", entity_type="TEXT"),
        ],
    )

    matched = {(item.matched_text, item.context_kind, item.confidence) for item in findings}
    assert ("2016", "code_like", "high") in matched
    assert ("JD", "code_like", "high") in matched
    assert all(item.raw_text != "2026.03.12" for item in findings)
    assert all(item.raw_text != "2026.04" for item in findings)
    assert all(item.raw_text != "645X600X2016" for item in findings)
    assert all(item.raw_text != "RVV2016P" for item in findings)
    assert all(item.raw_text != "smooth" for item in findings)
    assert any(item.raw_text == "ABCD2016X" and item.matched_text == "2016" for item in findings)


def test_match_engine_uses_field_context_to_promote_project_sensitive_hits(tmp_path: Path) -> None:
    workbook = _build_lexicon_workbook(tmp_path / "lexicon.xlsx")
    lexicon = AuditLexiconLoader().load(workbook)
    engine = AuditMatchEngine(lexicon)

    findings = engine.evaluate(
        project_no="1418",
        items=[
            ScanTextItem(
                raw_text="6TT2016GX",
                entity_type="ATTRIB",
                field_context="titleblock_internal_code",
            ),
        ],
    )

    assert len(findings) == 1
    assert findings[0].matched_text == "2016"
    assert findings[0].context_kind == "titleblock_internal_code"
    assert findings[0].confidence == "high"


def test_match_engine_reports_project_no_inside_digit_prefix_when_suffix_turns_non_ascii(
    tmp_path: Path,
) -> None:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Sheet1"
    ws.append(["project", "1907", "2016", "note"])
    ws.append(["lexicon", "SANMEN", "JINQIMEN", "note"])
    ws.append([None, "1907", "2016", None])
    workbook = tmp_path / "lexicon-1907.xlsx"
    wb.save(workbook)

    lexicon = AuditLexiconLoader().load(workbook)
    engine = AuditMatchEngine(lexicon)

    findings = engine.evaluate(
        project_no="2016",
        items=[
            ScanTextItem(
                raw_text="7788991907一一二二",
                entity_type="TEXT",
            ),
        ],
    )

    assert any(item.matched_text == "1907" for item in findings)


def test_match_engine_only_whitelists_exact_three_letters_plus_project_no_plus_one_letter(
    tmp_path: Path,
) -> None:
    workbook = _build_lexicon_workbook(tmp_path / "lexicon.xlsx")
    lexicon = AuditLexiconLoader().load(workbook)
    engine = AuditMatchEngine(lexicon)

    findings = engine.evaluate(
        project_no="1418",
        items=[
            ScanTextItem(raw_text="ABC2016X", entity_type="TEXT"),
            ScanTextItem(raw_text="ABCD2016X", entity_type="TEXT"),
            ScanTextItem(raw_text="12ABC2016X", entity_type="TEXT"),
        ],
    )

    assert all(item.raw_text != "ABC2016X" for item in findings)
    assert any(item.raw_text == "ABCD2016X" and item.matched_text == "2016" for item in findings)
    assert any(item.raw_text == "12ABC2016X" and item.matched_text == "2016" for item in findings)
