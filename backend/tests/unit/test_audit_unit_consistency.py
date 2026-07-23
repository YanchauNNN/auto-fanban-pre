from __future__ import annotations

from src.audit_check.matcher import AuditMatchEngine
from src.audit_check.models import AuditLexicon, ScanTextItem
from src.models import BBox
from src.pipeline.project_no_inference import infer_unit_no_from_path


def _engine() -> AuditMatchEngine:
    return AuditMatchEngine(
        AuditLexicon(
            project_options=["1418", "1907", "1915", "1916", "2016", "2026"],
            allowed_texts={
                "1418": set(),
                "1907": set(),
                "1915": set(),
                "1916": set(),
                "2016": set(),
                "2026": set(),
            },
            foreign_texts={
                "1418": set(),
                "1907": set(),
                "1915": set(),
                "1916": set(),
                "2016": set(),
                "2026": set(),
            },
            token_projects={},
        ),
    )


def test_infer_unit_no_from_project_code_filename() -> None:
    assert infer_unit_no_from_path("20261NS-JGS01.dwg", "2026") == "1"
    assert infer_unit_no_from_path("20261RB-SBS01.dwg", "2026") == "1"
    assert infer_unit_no_from_path("19151NS-JGS01.dwg", "1915") == "1"
    assert infer_unit_no_from_path("20260SC2JGS01.dwg", "2026") == "0"


def test_unit_consistency_flags_wrong_code_and_explicit_unit_text() -> None:
    findings = _engine().evaluate(
        project_no="2026",
        unit_no="1",
        items=[
            ScanTextItem(raw_text="20261NS-JGS01", entity_type="TEXT"),
            ScanTextItem(raw_text="20262NS-JGS01", entity_type="TEXT"),
            ScanTextItem(raw_text="1号机组", entity_type="TEXT"),
            ScanTextItem(raw_text="1号岛", entity_type="TEXT"),
            ScanTextItem(raw_text="2号机组", entity_type="TEXT"),
            ScanTextItem(raw_text="2号岛", entity_type="TEXT"),
            ScanTextItem(raw_text="2号图纸", entity_type="TEXT"),
            ScanTextItem(raw_text="2026-02-01", entity_type="TEXT"),
        ],
    )

    assert [(finding.matched_text, finding.context_kind) for finding in findings] == [
        ("20262NS-JGS01", "unit_consistency"),
        ("2号机组", "unit_consistency"),
        ("2号岛", "unit_consistency"),
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


def test_unit_consistency_accepts_unlisted_unit_for_configured_project() -> None:
    findings = _engine().evaluate(
        project_no="1907",
        unit_no="7",
        items=[
            ScanTextItem(raw_text="19077NH-JGS01", entity_type="TEXT"),
            ScanTextItem(raw_text="19076NH-JGS01", entity_type="TEXT"),
            ScanTextItem(raw_text="7号机组", entity_type="TEXT"),
            ScanTextItem(raw_text="6号机组", entity_type="TEXT"),
            ScanTextItem(raw_text="6号岛", entity_type="TEXT"),
        ],
    )

    assert [(finding.matched_text, finding.context_kind) for finding in findings] == [
        ("19076NH-JGS01", "unit_consistency"),
        ("6号机组", "unit_consistency"),
        ("6号岛", "unit_consistency"),
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


def test_unit_consistency_flags_unit_factory_prefix_in_non_jgs_codes() -> None:
    findings = _engine().evaluate(
        project_no="2026",
        unit_no="1",
        items=[
            ScanTextItem(raw_text="20261RB-JGS11", entity_type="TEXT"),
            ScanTextItem(raw_text="20261RB-SBS01", entity_type="TEXT"),
            ScanTextItem(raw_text="20262RB-SBS01", entity_type="TEXT"),
        ],
    )

    assert [(finding.matched_text, finding.context_kind) for finding in findings] == [
        ("20262RB-SBS01", "unit_consistency"),
    ]


def test_unit_consistency_supports_2016_album_code() -> None:
    findings = _engine().evaluate(
        project_no="2016",
        unit_no="2",
        items=[
            ScanTextItem(raw_text="20162RC-JGS09-001", entity_type="TEXT"),
            ScanTextItem(raw_text="20161RC-JGS09-001", entity_type="TEXT"),
        ],
    )

    assert [(finding.matched_text, finding.context_kind) for finding in findings] == [
        ("20161RC-JGS09-001", "unit_consistency"),
    ]


def test_unit_consistency_supports_compact_internal_code() -> None:
    findings = _engine().evaluate(
        project_no="2026",
        unit_no="0",
        items=[
            ScanTextItem(raw_text="20260SC2JGS01-001", entity_type="TEXT"),
            ScanTextItem(raw_text="20261SC2JGS01-001", entity_type="TEXT"),
        ],
    )

    assert [(finding.matched_text, finding.context_kind) for finding in findings] == [
        ("20261SC2JGS01-001", "unit_consistency"),
    ]


def test_unit_consistency_flags_external_code_unit_in_titleblock_roi() -> None:
    findings = _engine().evaluate(
        project_no="2016",
        unit_no="2",
        items=[
            ScanTextItem(raw_text="20162RC-JGS09-001", entity_type="TEXT"),
            ScanTextItem(
                raw_text="JD2RCG11002B25C42SD",
                entity_type="TEXT",
                field_context="titleblock_external_code",
            ),
            ScanTextItem(
                raw_text="JD1RCG11002B25C42SD",
                entity_type="TEXT",
                field_context="titleblock_external_code",
            ),
            ScanTextItem(raw_text="JD1RCG11002B25C42SD", entity_type="TEXT"),
        ],
    )

    assert [(finding.matched_text, finding.context_kind) for finding in findings] == [
        ("JD1RCG11002B25C42SD", "unit_consistency"),
    ]


def test_unit_consistency_rebuilds_split_external_code_roi() -> None:
    code = "JD1RCG11002B25C42SD"
    items = [
        ScanTextItem(
            raw_text=char,
            entity_type="DBText",
            field_context="titleblock_external_code",
            internal_code="20161RC-JGS09-001",
            layout_name="Model",
            position_x=float(index * 10),
            position_y=100.0,
            text_bbox=BBox(
                xmin=float(index * 10),
                ymin=95.0,
                xmax=float(index * 10 + 8),
                ymax=105.0,
            ),
        )
        for index, char in enumerate(code)
    ]

    findings = _engine().evaluate(project_no="2016", unit_no="2", items=items)

    assert [(finding.matched_text, finding.context_kind) for finding in findings] == [
        (code, "unit_consistency"),
    ]
    assert findings[0].entity_type == "TEXT_GROUP"
    assert findings[0].text_bbox == BBox(xmin=0.0, ymin=95.0, xmax=188.0, ymax=105.0)


def test_unit_consistency_ignores_split_external_code_without_roi_context() -> None:
    code = "JD1RCG11002B25C42SD"
    items = [
        ScanTextItem(
            raw_text=char,
            entity_type="DBText",
            field_context=None,
            internal_code="20161RC-JGS09-001",
            layout_name="Model",
            position_x=float(index * 10),
            position_y=100.0,
            text_bbox=BBox(
                xmin=float(index * 10),
                ymin=95.0,
                xmax=float(index * 10 + 8),
                ymax=105.0,
            ),
        )
        for index, char in enumerate(code)
    ]

    findings = _engine().evaluate(project_no="2016", unit_no="2", items=items)

    assert findings == []


def test_unit_consistency_does_not_rebuild_split_external_code_outside_roi() -> None:
    code = "JD1RCG11002B25C42SD"
    items = [
        ScanTextItem(
            raw_text=char,
            entity_type="DBText",
            field_context="titleblock_internal_code",
            internal_code="20161RC-JGS09-001",
            layout_name="Model",
            position_x=float(index * 10),
            position_y=100.0,
            text_bbox=BBox(
                xmin=float(index * 10),
                ymin=95.0,
                xmax=float(index * 10 + 8),
                ymax=105.0,
            ),
        )
        for index, char in enumerate(code)
    ]

    findings = _engine().evaluate(project_no="2016", unit_no="2", items=items)

    assert findings == []


def test_unit_consistency_suppresses_dimension_like_short_fragments() -> None:
    findings = _engine().evaluate(
        project_no="2026",
        unit_no="1",
        items=[
            ScanTextItem(raw_text="20261RB-JGS11", entity_type="TEXT"),
            ScanTextItem(raw_text="3492x(570+600)x4", entity_type="TEXT"),
            ScanTextItem(raw_text="板厚6mm", entity_type="TEXT"),
            ScanTextItem(raw_text="9x300=<>", entity_type="Dimension"),
            ScanTextItem(raw_text="2RB非能动热量导出水池", entity_type="TEXT"),
        ],
    )

    assert [(finding.matched_text, finding.context_kind) for finding in findings] == [
        ("2RB", "unit_consistency"),
    ]


def test_unit_consistency_requires_observed_album_factory_for_short_fragments() -> None:
    findings = _engine().evaluate(
        project_no="2026",
        unit_no="1",
        items=[
            ScanTextItem(raw_text="2RB非能动热量导出水池", entity_type="TEXT"),
            ScanTextItem(raw_text="2MM", entity_type="TEXT"),
        ],
    )

    assert findings == []
