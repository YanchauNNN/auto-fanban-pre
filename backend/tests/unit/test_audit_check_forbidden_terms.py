from __future__ import annotations

from src.audit_check.matcher import AuditMatchEngine
from src.audit_check.models import AuditLexicon, ScanTextItem
from src.audit_check.reporting import build_summary
from src.result_views import build_finding_groups


def test_match_engine_reports_forbidden_discipline_word_first() -> None:
    lexicon = AuditLexicon(
        project_options=["2016", "2026"],
        allowed_texts={"2016": set(), "2026": set()},
        foreign_texts={"2016": {"2026"}},
        token_projects={"2026": {"2026"}},
    )
    engine = AuditMatchEngine(lexicon)

    findings = engine.evaluate(
        project_no="2016",
        items=[
            ScanTextItem(raw_text="2026", entity_type="TEXT", internal_code="20162SD-JGS03-001"),
            ScanTextItem(raw_text="工种负责人", entity_type="TEXT", internal_code="20162SD-JGS03-002"),
        ],
    )

    discipline = next(item for item in findings if item.matched_text == "工种")
    assert discipline.context_kind == "forbidden_term"
    assert discipline.confidence == "high"

    summary = build_summary(findings)
    assert summary["top_wrong_texts"][0] == "工种"

    groups = build_finding_groups(
        [
            {
                "matched_text": finding.matched_text,
                "internal_code": finding.internal_code,
            }
            for finding in findings
        ]
    )
    assert groups[0]["matched_text"] == "工种"
