from __future__ import annotations

from src.audit_check.matcher import AuditMatchEngine
from src.audit_check.models import AuditLexicon, ScanTextItem
from src.pipeline.project_no_inference import infer_unit_no_from_path


def _engine() -> AuditMatchEngine:
    return AuditMatchEngine(
        AuditLexicon(
            project_options=["1418", "1907", "1915", "1916", "2026"],
            allowed_texts={
                "1418": set(),
                "1907": set(),
                "1915": set(),
                "1916": set(),
                "2026": set(),
            },
            foreign_texts={
                "1418": set(),
                "1907": set(),
                "1915": set(),
                "1916": set(),
                "2026": set(),
            },
            token_projects={},
        ),
    )


def test_infer_unit_no_from_project_code_filename() -> None:
    assert infer_unit_no_from_path("20261NS-JGS01.dwg", "2026") == "1"
    assert infer_unit_no_from_path("19151NS-JGS01.dwg", "1915") == "1"


def test_unit_consistency_flags_wrong_code_and_explicit_unit_text() -> None:
    findings = _engine().evaluate(
        project_no="2026",
        unit_no="1",
        items=[
            ScanTextItem(raw_text="20261NS-JGS01", entity_type="TEXT"),
            ScanTextItem(raw_text="20262NS-JGS01", entity_type="TEXT"),
            ScanTextItem(raw_text="1号机组", entity_type="TEXT"),
            ScanTextItem(raw_text="2号机组", entity_type="TEXT"),
            ScanTextItem(raw_text="2号图纸", entity_type="TEXT"),
            ScanTextItem(raw_text="2026-02-01", entity_type="TEXT"),
        ],
    )

    assert [(finding.matched_text, finding.context_kind) for finding in findings] == [
        ("20262NS-JGS01", "unit_consistency"),
        ("2号机组", "unit_consistency"),
    ]


def test_unit_consistency_supports_project_specific_unit_ranges_and_island_text() -> None:
    cases = [
        ("1916", "3", "19163KP-JGS01", "19164KP-JGS01", "4号岛"),
        ("1907", "5", "19075NH-JGS01", "19076NH-JGS01", "6号机组"),
        ("1418", "3", "14183NI-JGS01", "14184NI-JGS01", "4号岛"),
    ]

    for project_no, unit_no, correct_code, wrong_code, wrong_unit_text in cases:
        findings = _engine().evaluate(
            project_no=project_no,
            unit_no=unit_no,
            items=[
                ScanTextItem(raw_text=correct_code, entity_type="TEXT"),
                ScanTextItem(raw_text=wrong_code, entity_type="TEXT"),
                ScanTextItem(raw_text=wrong_unit_text, entity_type="TEXT"),
                ScanTextItem(raw_text=f"{wrong_unit_text[0]}号图纸", entity_type="TEXT"),
            ],
        )

        assert [(finding.matched_text, finding.context_kind) for finding in findings] == [
            (wrong_code, "unit_consistency"),
            (wrong_unit_text, "unit_consistency"),
        ]


def test_unit_consistency_flags_short_unit_factory_code_fragment() -> None:
    findings = _engine().evaluate(
        project_no="2026",
        unit_no="2",
        items=[
            ScanTextItem(raw_text="20262RB-JGS11", entity_type="TEXT"),
            ScanTextItem(raw_text="2RB非能动热量导出水池", entity_type="TEXT"),
            ScanTextItem(raw_text="20261RB-JGS11", entity_type="TEXT"),
            ScanTextItem(raw_text="1RB非能动热量导出水池", entity_type="TEXT"),
        ],
    )

    assert [(finding.matched_text, finding.context_kind) for finding in findings] == [
        ("20261RB-JGS11", "unit_consistency"),
        ("1RB", "unit_consistency"),
    ]
