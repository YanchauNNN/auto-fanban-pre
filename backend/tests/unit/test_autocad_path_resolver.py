from __future__ import annotations

from pathlib import Path

from src.cad.autocad_path_resolver import resolve_autocad_paths


class TestAutoCADPathResolver:
    def test_resolve_from_configured_install_dir(self, temp_dir: Path):
        install_dir = temp_dir / "AutoCAD 2021"
        (install_dir / "Fonts").mkdir(parents=True)
        (install_dir / "Plotters" / "Plot Styles").mkdir(parents=True)
        (install_dir / "acad.exe").touch()
        (install_dir / "accoreconsole.exe").touch()
        (install_dir / "Plotters" / "DWG To PDF.pc3").touch()
        (install_dir / "Plotters" / "Plot Styles" / "monochrome.ctb").touch()

        info = resolve_autocad_paths(
            configured_install_dir=install_dir,
            registry_candidates=[],
        )

        assert info.install_dir == install_dir
        assert info.acad_exe == install_dir / "acad.exe"
        assert info.accoreconsole_exe == install_dir / "accoreconsole.exe"
        assert info.fonts_dir == install_dir / "Fonts"
        assert info.plot_styles_dir == install_dir / "Plotters" / "Plot Styles"
        assert info.monochrome_ctb_path == install_dir / "Plotters" / "Plot Styles" / "monochrome.ctb"
        assert info.pc3_path == install_dir / "Plotters" / "DWG To PDF.pc3"

    def test_resolve_from_extra_candidates(self, temp_dir: Path):
        install_dir = temp_dir / "AutoCAD 2022"
        (install_dir / "Fonts").mkdir(parents=True)

        info = resolve_autocad_paths(
            configured_install_dir=None,
            extra_candidates=[install_dir],
            registry_candidates=[],
        )

        assert info.install_dir == install_dir
        assert info.fonts_dir == install_dir / "Fonts"

    def test_resolve_no_match(self):
        info = resolve_autocad_paths(
            configured_install_dir="Z:/not-exists/autocad",
            extra_candidates=[],
            registry_candidates=[],
            include_default_candidates=False,
        )

        assert info.install_dir is None
        assert info.fonts_dir is None
        assert info.acad_exe is None
