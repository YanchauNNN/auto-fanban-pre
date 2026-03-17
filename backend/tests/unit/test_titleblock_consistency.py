from __future__ import annotations

from pathlib import Path

from src.cad.titleblock_consistency import (
    TextReplacement,
    TitleblockConsistencyService,
)
from src.models import BBox, FrameMeta, FrameRuntime, TitleblockFields


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


def test_plan_replacements_can_patch_split_paper_suffix() -> None:
    service = TitleblockConsistencyService()
    fragments = [
        {"text": "A", "x": 10.0, "y": 0.0},
        {"text": "2", "x": 20.0, "y": 0.0},
    ]

    replacements = service.plan_replacements(
        fragments,
        expected_text="A2H",
        field_name="paper_size_text",
    )

    assert replacements == [TextReplacement(index=1, old_text="2", new_text="2H")]


def test_plan_replacements_can_patch_compound_paper_fragment() -> None:
    service = TitleblockConsistencyService()
    fragments = [
        {"text": "A", "x": 10.0, "y": 0.0},
        {"text": "0+1/2", "x": 20.0, "y": 0.0},
    ]

    replacements = service.plan_replacements(
        fragments,
        expected_text="A0+1/4",
        field_name="paper_size_text",
    )

    assert replacements == [TextReplacement(index=1, old_text="0+1/2", new_text="0+1/4")]


def test_build_frame_plans_uses_parsed_scale_text_not_raw_roi_noise() -> None:
    service = TitleblockConsistencyService()
    frame = FrameMeta(
        runtime=FrameRuntime(
            frame_id="frame-1",
            source_file=Path(__file__),
            outer_bbox=BBox(xmin=0, ymin=0, xmax=100, ymax=100),
            paper_variant_id="CNPE_A1+1/2",
            geom_scale_factor=50.0,
            sx=50.0,
            sy=50.0,
            roi_profile_id="BASE10",
        ),
        titleblock=TitleblockFields(
            internal_code="18185NE-JGS11-003",
            paper_size_text="A 1+1/2",
            scale_text="1:50",
            scale_denominator=50,
        ),
        raw_extracts={
            "比例": [
                {"text": "5NE 8.450 and 8.450m Prefabricated Stairs", "x": 10.0, "y": 0.0},
                {"text": "1:50", "x": 90.0, "y": 0.0},
            ]
        },
    )

    plans = service.build_frame_plans(frame)

    assert [plan.field_name for plan in plans] == []
