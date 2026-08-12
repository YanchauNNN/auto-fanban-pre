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


def test_font_inventory_skips_windows_font_path_when_it_is_not_directory(tmp_path: Path) -> None:
    win_fonts_file = tmp_path / "Fonts"
    win_fonts_file.write_text("not a directory", encoding="utf-8")

    inventory = InstalledFontInventory(
        autocad_fonts_dirs=[],
        windows_fonts_dir=win_fonts_file,
        include_registry=False,
    )

    assert inventory.list_options(preferred_kinds={"ttf"}) == []


def test_font_inventory_skips_autocad_font_dir_deleted_after_init(tmp_path: Path) -> None:
    acad_fonts = tmp_path / "AutoCAD" / "Fonts"
    acad_fonts.mkdir(parents=True)
    inventory = InstalledFontInventory(
        autocad_fonts_dirs=[acad_fonts],
        include_windows_fonts=False,
    )
    acad_fonts.rmdir()

    assert inventory.list_options(preferred_kinds={"shx"}) == []


def test_font_inventory_skips_failed_windows_registry_source() -> None:
    class RegistryFailureInventory(InstalledFontInventory):
        def _iter_registry_entries(self) -> list[dict[str, str]]:
            raise OSError("registry denied")

    inventory = RegistryFailureInventory(
        autocad_fonts_dirs=[],
        windows_fonts_dir=Path(r"Z:\missing-font-dir"),
        include_registry=True,
    )

    assert inventory.list_options(preferred_kinds={"ttf"}) == []


def test_font_inventory_normalizes_registry_family_suffix() -> None:
    assert (
        InstalledFontInventory._normalize_registry_family_name("FangSong (TrueType)")
        == "FangSong"
    )
    assert (
        InstalledFontInventory._normalize_registry_family_name("宋体 (TrueType)")
        == "宋体"
    )
