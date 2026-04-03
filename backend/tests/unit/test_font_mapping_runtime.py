from __future__ import annotations

from pathlib import Path

from src.cad.font_mapping_runtime import (
    build_font_mapping_entries,
    build_font_runtime_plan,
    build_font_search_runtime_overrides,
    choose_fontalt_font,
    materialize_font_library_files,
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


def test_build_font_search_runtime_overrides_keeps_existing_font_library_dirs(
    tmp_path: Path,
) -> None:
    font_lib = tmp_path / "font-lib"
    font_lib.mkdir()
    missing_dir = tmp_path / "missing-lib"

    overrides = build_font_search_runtime_overrides(
        font_library_dirs=[font_lib, missing_dir],
    )

    assert overrides == {"support_path": str(font_lib)}


def test_build_font_search_runtime_overrides_merges_existing_support_path(
    tmp_path: Path,
) -> None:
    slot_support = tmp_path / "slot-support"
    font_lib = tmp_path / "font-lib"
    slot_support.mkdir()
    font_lib.mkdir()

    overrides = build_font_search_runtime_overrides(
        font_library_dirs=[font_lib],
        existing_support_path=f"{slot_support};{tmp_path / 'missing-lib'}",
    )

    assert overrides == {"support_path": f"{slot_support};{font_lib}"}


def test_materialize_font_library_files_copies_supported_fonts(
    tmp_path: Path,
) -> None:
    font_lib = tmp_path / "font-lib"
    font_lib.mkdir()
    (font_lib / "MENU2.TTF").write_text("ttf", encoding="utf-8")
    (font_lib / "simplex.shx").write_text("shx", encoding="utf-8")
    (font_lib / "ignore.txt").write_text("nope", encoding="utf-8")
    workspace = tmp_path / "work"

    copied = materialize_font_library_files(
        workspace_dir=workspace,
        font_library_dirs=[font_lib],
    )

    assert [path.name for path in copied] == ["MENU2.TTF", "simplex.shx"]
    assert (workspace / "MENU2.TTF").read_text(encoding="utf-8") == "ttf"
    assert not (workspace / "ignore.txt").exists()
