from __future__ import annotations

from src.cad.titleblock_consistency import (
    TextReplacement,
    TitleblockConsistencyService,
)


def test_paper_text_from_variant_normalizes_special_cases() -> None:
    service = TitleblockConsistencyService()

    assert service.paper_text_from_variant("CNPE_A0") == "A0"
    assert service.paper_text_from_variant("CNPE_A1+1/1") == "A1+1"
    assert service.paper_text_from_variant("CNPE_A4H") == "A4"


def test_plan_replacements_updates_only_changed_fragments() -> None:
    service = TitleblockConsistencyService()
    fragments = [
        {"text": "A", "x": 10.0, "y": 0.0},
        {"text": "0", "x": 20.0, "y": 0.2},
        {"text": "+", "x": 30.0, "y": 0.0},
        {"text": "1/2", "x": 40.0, "y": 0.0},
    ]

    replacements = service.plan_replacements(fragments, expected_text="A1+1/4")

    assert replacements == [
        TextReplacement(index=1, old_text="0", new_text="1"),
        TextReplacement(index=3, old_text="1/2", new_text="1/4"),
    ]


def test_plan_replacements_returns_empty_for_matching_fragments() -> None:
    service = TitleblockConsistencyService()
    fragments = [
        {"text": "A", "x": 10.0, "y": 0.0},
        {"text": "0", "x": 20.0, "y": 0.2},
    ]

    assert service.plan_replacements(fragments, expected_text="A0") == []


def test_paper_overlay_fragments_are_treated_as_consistent() -> None:
    service = TitleblockConsistencyService()
    fragments = [
        {
            "text": "A +1/4",
            "x": 10.0,
            "y": 0.0,
            "bbox": {"xmin": 10.0, "xmax": 100.0},
        },
        {
            "text": "0",
            "x": 40.0,
            "y": 0.0,
            "bbox": {"xmin": 40.0, "xmax": 50.0},
        },
    ]

    assert (
        service.plan_replacements(
            fragments,
            expected_text="A0+1/4",
            field_name="paper_size_text",
        )
        == []
    )
