from __future__ import annotations

from pathlib import Path

from src.cad.font_inventory import InstalledFontInventory


def test_font_inventory_prefers_autocad_shx_options(tmp_path: Path) -> None:
    acad_fonts = tmp_path / "AutoCAD" / "Fonts"
    win_fonts = tmp_path / "Windows" / "Fonts"
    acad_fonts.mkdir(parents=True)
    win_fonts.mkdir(parents=True)
    (acad_fonts / "simplex.shx").write_text("", encoding="utf-8")
    (acad_fonts / "romans.shx").write_text("", encoding="utf-8")
    (win_fonts / "arial.ttf").write_text("", encoding="utf-8")

    inventory = InstalledFontInventory(
        autocad_fonts_dirs=[acad_fonts],
        windows_fonts_dir=win_fonts,
        include_registry=False,
    )

    options = inventory.list_options(preferred_kinds={"shx"})

    assert [item["value"] for item in options] == ["romans.shx", "simplex.shx"]
    assert all(item["kind"] == "shx" for item in options)
