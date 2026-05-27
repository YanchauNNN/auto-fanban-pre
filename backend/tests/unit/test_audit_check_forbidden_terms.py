from __future__ import annotations

import yaml

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


def test_match_engine_reads_forbidden_terms_from_mechanism_yaml(tmp_path, monkeypatch) -> None:
    mechanism_spec = tmp_path / "documents" / "参数规范-3.yaml"
    mechanism_spec.parent.mkdir(parents=True, exist_ok=True)
    mechanism_spec.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "backend_mechanism": {
                    "audit_display": {
                        "forbidden_terms": ["禁词"],
                        "forbidden_term_priority": {"禁词": 0},
                        "finding_group_priority": {"禁词": 0},
                    },
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FANBAN_MECHANISM_SPEC_PATH", str(mechanism_spec))
    lexicon = AuditLexicon(
        project_options=["2016"],
        allowed_texts={"2016": set()},
        foreign_texts={"2016": set()},
        token_projects={},
    )

    findings = AuditMatchEngine(lexicon).evaluate(
        project_no="2016",
        items=[ScanTextItem(raw_text="这里有禁词", entity_type="TEXT", internal_code="20162SD-JGS03-001")],
    )

    assert findings[0].matched_text == "禁词"
    assert build_summary(findings)["top_wrong_texts"][0] == "禁词"
    assert build_finding_groups([{"matched_text": "禁词", "internal_code": "001"}])[0]["matched_text"] == "禁词"
