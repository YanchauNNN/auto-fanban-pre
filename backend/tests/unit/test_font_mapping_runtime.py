from __future__ import annotations

from pathlib import Path

from src.cad.font_mapping_runtime import (
    build_font_mapping_entries,
    build_font_runtime_plan,
    choose_fontalt_font,
)


def test_build_font_mapping_entries_keeps_kind_specific_mappings() -> None:
    missing_fonts = [
        {"font_name": "MENU2.TTF", "bigfont_name": "", "kind": "ttf"},
        {"font_name": "simplex.shx", "bigfont_name": "", "kind": "shx"},
        {"font_name": "txt.shx", "bigfont_name": "gbcbig.shx", "kind": "bigfont"},
    ]

    entries = build_font_mapping_entries(
        missing_fonts=missing_fonts,
        replacement_fonts={
            "ttf": "simsun.ttc",
            "shx": "romans.shx",
            "bigfont": "hztxt.shx",
        },
    )

    assert entries == [
        ("MENU2.TTF", "simsun.ttc"),
        ("simplex.shx", "romans.shx"),
        ("gbcbig.shx", "hztxt.shx"),
    ]


def test_choose_fontalt_prefers_explicit_replacement() -> None:
    font_alt = choose_fontalt_font(
        replacement_fonts={"ttf": "simsun.ttc"},
        default_fontalt_by_kind={"ttf": "simhei.ttf", "shx": "simplex.shx"},
    )

    assert font_alt == "simsun.ttc"


def test_choose_fontalt_falls_back_to_default() -> None:
    font_alt = choose_fontalt_font(
        replacement_fonts={},
        default_fontalt_by_kind={"shx": "simplex.shx"},
    )

    assert font_alt == "simplex.shx"


def test_build_font_runtime_plan_writes_fontmap_file(tmp_path: Path) -> None:
    plan = build_font_runtime_plan(
        workspace_dir=tmp_path,
        missing_fonts=[{"font_name": "MENU2.TTF", "bigfont_name": "", "kind": "ttf"}],
        replacement_fonts={"ttf": "simsun.ttc"},
        enable_fontmap=True,
        default_fontalt_by_kind={"ttf": "simsun.ttc"},
    )

    assert plan.font_map_path is not None
    assert plan.font_map_path.exists()
    assert plan.font_map_path.read_text(encoding="utf-8").strip() == "MENU2.TTF;simsun.ttc"
    assert plan.runtime_overrides["font_map_path"] == str(plan.font_map_path)
    assert plan.runtime_overrides["font_alt"] == "simsun.ttc"
