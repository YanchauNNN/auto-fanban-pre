from __future__ import annotations

from pathlib import Path

import pytest

from src.cad.autocad_path_resolver import _default_install_candidates, resolve_autocad_paths


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

    def test_resolve_from_extra_candidates(self, temp_dir: Path, monkeypatch):
        install_dir = temp_dir / "AutoCAD 2022"
        (install_dir / "Fonts").mkdir(parents=True)
        (install_dir / "acad.exe").touch()
        (install_dir / "accoreconsole.exe").touch()
        monkeypatch.delenv("FANBAN_AUTOCAD_INSTALL_DIR", raising=False)

        info = resolve_autocad_paths(
            configured_install_dir=None,
            extra_candidates=[install_dir],
            registry_candidates=[],
            include_default_candidates=False,
        )

        assert info.install_dir == install_dir
        assert info.fonts_dir == install_dir / "Fonts"
        assert info.accoreconsole_exe == install_dir / "accoreconsole.exe"

    def test_resolve_prefers_first_usable_install_dir_over_earlier_existing_dir(
        self,
        temp_dir: Path,
        monkeypatch,
    ):
        bad_dir = temp_dir / "AutoCAD 2022"
        bad_dir.mkdir(parents=True)

        good_dir = temp_dir / "AutoCAD 2021"
        (good_dir / "Fonts").mkdir(parents=True)
        (good_dir / "acad.exe").touch()
        (good_dir / "accoreconsole.exe").touch()
        monkeypatch.delenv("FANBAN_AUTOCAD_INSTALL_DIR", raising=False)

        info = resolve_autocad_paths(
            configured_install_dir=None,
            extra_candidates=[bad_dir, good_dir],
            registry_candidates=[],
            include_default_candidates=False,
        )

        assert info.install_dir == good_dir
        assert info.accoreconsole_exe == good_dir / "accoreconsole.exe"

    @pytest.mark.parametrize("root_suffix", [Path("PF") / "Root", Path("Program Files") / "Root"])
    def test_resolve_supports_installer_layout_root_subdirs(
        self,
        temp_dir: Path,
        monkeypatch,
        root_suffix: Path,
    ):
        installer_root = temp_dir / "AutoCAD_2022_Simplified_Chinese_Win_64bit_dlm" / "x64" / "acad"
        install_dir = installer_root / root_suffix
        install_dir.mkdir(parents=True)
        (install_dir / "acad.exe").touch()
        (install_dir / "accoreconsole.exe").touch()
        monkeypatch.delenv("FANBAN_AUTOCAD_INSTALL_DIR", raising=False)

        info = resolve_autocad_paths(
            configured_install_dir=None,
            extra_candidates=[installer_root],
            registry_candidates=[],
            include_default_candidates=False,
        )

        assert info.install_dir == install_dir
        assert info.accoreconsole_exe == install_dir / "accoreconsole.exe"

    def test_resolve_prefers_later_candidate_with_accoreconsole_over_earlier_acad_only(
        self,
        temp_dir: Path,
        monkeypatch,
    ):
        older_dir = temp_dir / "AutoCAD 2020"
        older_dir.mkdir(parents=True)
        (older_dir / "acad.exe").touch()

        better_dir = temp_dir / "AutoCAD 2022"
        better_dir.mkdir(parents=True)
        (better_dir / "acad.exe").touch()
        (better_dir / "accoreconsole.exe").touch()
        monkeypatch.delenv("FANBAN_AUTOCAD_INSTALL_DIR", raising=False)

        info = resolve_autocad_paths(
            configured_install_dir=None,
            extra_candidates=[older_dir, better_dir],
            registry_candidates=[],
            include_default_candidates=False,
        )

        assert info.install_dir == better_dir
        assert info.accoreconsole_exe == better_dir / "accoreconsole.exe"

    def test_resolve_no_match(self, monkeypatch):
        monkeypatch.delenv("FANBAN_AUTOCAD_INSTALL_DIR", raising=False)
        info = resolve_autocad_paths(
            configured_install_dir="Z:/not-exists/autocad",
            extra_candidates=[],
            registry_candidates=[],
            include_default_candidates=False,
        )

        assert info.install_dir is None
        assert info.fonts_dir is None
        assert info.acad_exe is None

    def test_default_candidates_include_plain_autocad_roots(self):
        candidates = _default_install_candidates()

        assert Path(r"D:\AUTOCAD\AutoCAD 2022") in candidates
