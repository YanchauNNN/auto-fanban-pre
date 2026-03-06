from __future__ import annotations

from pathlib import Path

from src.cad.autocad_path_resolver import resolve_autocad_paths


class TestAutoCADPathResolver:
    def test_resolve_from_configured_install_dir(self, temp_dir: Path, monkeypatch):
        install_dir = temp_dir / "AutoCAD 2021"
        (install_dir / "Fonts").mkdir(parents=True)
        (install_dir / "Plotters" / "Plot Styles").mkdir(parents=True)
        (install_dir / "acad.exe").touch()
        (install_dir / "accoreconsole.exe").touch()
        (install_dir / "Plotters" / "打印PDF2.pc3").touch()
        (install_dir / "Plotters" / "DWG To PDF.pc3").touch()
        (install_dir / "Plotters" / "Plot Styles" / "monochrome.ctb").touch()
        monkeypatch.setenv("APPDATA", str(temp_dir / "empty_appdata"))

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
        assert info.pc3_path == install_dir / "Plotters" / "打印PDF2.pc3"

    def test_resolve_prefers_user_plotters_over_install_dir(self, temp_dir: Path, monkeypatch):
        install_dir = temp_dir / "AutoCAD 2022"
        (install_dir / "Fonts").mkdir(parents=True)
        (install_dir / "Plotters" / "Plot Styles").mkdir(parents=True)
        (install_dir / "Plotters" / "打印PDF2.pc3").write_text("install-pc3", encoding="utf-8")
        (install_dir / "Plotters" / "Plot Styles" / "monochrome.ctb").write_text(
            "install-ctb",
            encoding="utf-8",
        )

        appdata = temp_dir / "AppData" / "Roaming"
        user_plotters = appdata / "Autodesk" / "AutoCAD 2022" / "R24.1" / "chs" / "Plotters"
        user_plot_styles = user_plotters / "Plot Styles"
        user_plot_styles.mkdir(parents=True)
        (user_plotters / "打印PDF2.pc3").write_text("user-pc3", encoding="utf-8")
        (user_plot_styles / "monochrome.ctb").write_text("user-ctb", encoding="utf-8")
        monkeypatch.setenv("APPDATA", str(appdata))

        info = resolve_autocad_paths(
            configured_install_dir=install_dir,
            registry_candidates=[],
        )

        assert info.plotters_dir == user_plotters
        assert info.plot_styles_dir == user_plot_styles
        assert info.pc3_path == user_plotters / "打印PDF2.pc3"
        assert info.monochrome_ctb_path == user_plot_styles / "monochrome.ctb"

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
