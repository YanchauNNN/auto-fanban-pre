from __future__ import annotations

from pathlib import Path

import pytest

from src.cad.autocad_path_resolver import AutoCADPathInfo
from src.cad.plot_resource_manager import (
    ALL_MANAGED_CTB_NAMES,
    MANAGED_CTB_NAME,
    MONOCHROME_CTB_NAME,
    PDF2_PC3_NAME,
    PDF2_PMP_NAME,
    default_asset_roots,
    ensure_plot_resources,
)


def _write_all_managed_ctbs(plot_styles_asset: Path, content: str = "managed-ctb") -> None:
    for name in ALL_MANAGED_CTB_NAMES:
        (plot_styles_asset / name).write_text(content * 256, encoding="utf-8")


def _path_info(
    plotters_dir: Path,
    plot_styles_dir: Path,
    system_ctb: Path | None = None,
) -> AutoCADPathInfo:
    return AutoCADPathInfo(
        install_dir=plotters_dir.parent,
        acad_exe=None,
        accoreconsole_exe=None,
        fonts_dir=None,
        plotters_dir=plotters_dir,
        plot_styles_dir=plot_styles_dir,
        monochrome_ctb_path=system_ctb,
        pc3_path=None,
        fallback_pdf_pc3_path=None,
    )


def test_ensure_plot_resources_deploys_pdf2_and_pmp_and_ctb(tmp_path: Path):
    asset_root = tmp_path / "assets"
    plotters_asset = asset_root / "plotters"
    plot_styles_asset = asset_root / "plot_styles"
    plotters_asset.mkdir(parents=True)
    plot_styles_asset.mkdir(parents=True)
    (plotters_asset / PDF2_PC3_NAME).write_text("pc3", encoding="utf-8")
    (plotters_asset / PDF2_PMP_NAME).write_text(
        "pmp",
        encoding="utf-8",
    )
    _write_all_managed_ctbs(plot_styles_asset)
    system_ctb = tmp_path / "system" / MONOCHROME_CTB_NAME
    system_ctb.parent.mkdir(parents=True)
    system_ctb.write_text("system-ctb" * 128, encoding="utf-8")

    target_plotters = tmp_path / "target" / "Plotters"
    target_plot_styles = target_plotters / "Plot Styles"

    result = ensure_plot_resources(
        path_info=_path_info(target_plotters, target_plot_styles, system_ctb),
        asset_roots=[asset_root],
    )

    assert result.pc3_path == target_plotters / PDF2_PC3_NAME
    assert result.pmp_path == target_plotters / "PMP Files" / PDF2_PMP_NAME
    assert result.ctb_path == target_plot_styles / MANAGED_CTB_NAME
    assert result.pc3_path.read_text(encoding="utf-8") == "pc3"
    assert result.pmp_path.read_text(encoding="utf-8") == "pmp"
    assert (
        target_plotters / PDF2_PMP_NAME
    ).read_text(encoding="utf-8") == "pmp"
    assert result.ctb_path.read_text(encoding="utf-8") == "managed-ctb" * 256
    assert not (target_plot_styles / MONOCHROME_CTB_NAME).exists()


def test_ensure_plot_resources_overwrites_stale_pc3_with_bundled_asset(tmp_path: Path):
    asset_root = tmp_path / "assets"
    plotters_asset = asset_root / "plotters"
    plot_styles_asset = asset_root / "plot_styles"
    plotters_asset.mkdir(parents=True)
    plot_styles_asset.mkdir(parents=True)
    (plotters_asset / PDF2_PC3_NAME).write_text("bundled-pc3", encoding="utf-8")
    (plotters_asset / PDF2_PMP_NAME).write_text(
        "bundled-pmp",
        encoding="utf-8",
    )
    _write_all_managed_ctbs(plot_styles_asset, "bundled-ctb")

    target_plotters = tmp_path / "target" / "Plotters"
    target_plot_styles = target_plotters / "Plot Styles"
    target_plot_styles.mkdir(parents=True)
    (target_plotters / PDF2_PC3_NAME).write_text("stale-pc3", encoding="utf-8")

    result = ensure_plot_resources(
        path_info=_path_info(target_plotters, target_plot_styles),
        asset_roots=[asset_root],
    )

    assert result.pc3_path.read_text(encoding="utf-8") == "bundled-pc3"


def test_ensure_plot_resources_prefers_bundled_pc3_over_existing_system_pc3(tmp_path: Path):
    asset_root = tmp_path / "assets"
    plotters_asset = asset_root / "plotters"
    plot_styles_asset = asset_root / "plot_styles"
    plotters_asset.mkdir(parents=True)
    plot_styles_asset.mkdir(parents=True)
    (plotters_asset / PDF2_PC3_NAME).write_text("bundled-pc3", encoding="utf-8")
    (plotters_asset / PDF2_PMP_NAME).write_text("bundled-pmp", encoding="utf-8")
    _write_all_managed_ctbs(plot_styles_asset, "bundled-ctb")

    system_root = tmp_path / "system"
    system_plotters = system_root / "Plotters"
    system_plot_styles = system_plotters / "Plot Styles"
    system_plot_styles.mkdir(parents=True)
    system_pc3 = system_plotters / PDF2_PC3_NAME
    system_pc3.write_text("system-pc3", encoding="utf-8")

    target_plotters = tmp_path / "target" / "Plotters"
    target_plot_styles = target_plotters / "Plot Styles"

    result = ensure_plot_resources(
        path_info=AutoCADPathInfo(
            install_dir=system_root,
            acad_exe=None,
            accoreconsole_exe=None,
            fonts_dir=None,
            plotters_dir=target_plotters,
            plot_styles_dir=target_plot_styles,
            monochrome_ctb_path=None,
            pc3_path=system_pc3,
            fallback_pdf_pc3_path=None,
        ),
        asset_roots=[asset_root],
    )

    assert result.pc3_path.read_text(encoding="utf-8") == "bundled-pc3"


def test_ensure_plot_resources_deploys_to_discovered_user_plotters(tmp_path: Path, monkeypatch):
    asset_root = tmp_path / "assets"
    plotters_asset = asset_root / "plotters"
    plot_styles_asset = asset_root / "plot_styles"
    plotters_asset.mkdir(parents=True)
    plot_styles_asset.mkdir(parents=True)
    (plotters_asset / PDF2_PC3_NAME).write_text("pc3", encoding="utf-8")
    (plotters_asset / PDF2_PMP_NAME).write_text(
        "pmp",
        encoding="utf-8",
    )
    _write_all_managed_ctbs(plot_styles_asset, "ctb")

    install_plotters = tmp_path / "Program Files" / "Autodesk" / "AutoCAD 2022" / "Plotters"
    install_plot_styles = install_plotters / "Plot Styles"
    install_plot_styles.mkdir(parents=True)

    appdata = tmp_path / "AppData" / "Roaming"
    local_appdata = tmp_path / "AppData" / "Local"
    old_user_plotters = appdata / "Autodesk" / "AutoCAD 2019" / "R23.0" / "chs" / "Plotters"
    old_user_plot_styles = old_user_plotters / "Plot Styles"
    old_user_plot_styles.mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))

    ensure_plot_resources(
        path_info=_path_info(install_plotters, install_plot_styles),
        asset_roots=[asset_root],
    )

    assert not (old_user_plotters / PDF2_PC3_NAME).exists()
    assert not (old_user_plot_styles / MANAGED_CTB_NAME).exists()


def test_ensure_plot_resources_preserves_existing_system_monochrome_ctb(tmp_path: Path):
    asset_root = tmp_path / "assets"
    plotters_asset = asset_root / "plotters"
    plot_styles_asset = asset_root / "plot_styles"
    plotters_asset.mkdir(parents=True)
    plot_styles_asset.mkdir(parents=True)
    (plotters_asset / PDF2_PC3_NAME).write_text("pc3", encoding="utf-8")
    (plotters_asset / PDF2_PMP_NAME).write_text("pmp", encoding="utf-8")
    _write_all_managed_ctbs(plot_styles_asset)

    target_plotters = tmp_path / "target" / "Plotters"
    target_plot_styles = target_plotters / "Plot Styles"
    target_plot_styles.mkdir(parents=True)
    existing_monochrome = target_plot_styles / MONOCHROME_CTB_NAME
    existing_monochrome.write_text("user-monochrome", encoding="utf-8")

    result = ensure_plot_resources(
        path_info=_path_info(target_plotters, target_plot_styles),
        asset_roots=[asset_root],
    )

    assert existing_monochrome.read_text(encoding="utf-8") == "user-monochrome"
    assert result.ctb_path == target_plot_styles / MANAGED_CTB_NAME
    assert result.ctb_path.read_text(encoding="utf-8") == "managed-ctb" * 256


def test_ensure_plot_resources_raises_when_pdf2_asset_missing(tmp_path: Path):
    asset_root = tmp_path / "assets"
    (asset_root / "plotters").mkdir(parents=True)
    target_plotters = tmp_path / "target" / "Plotters"
    target_plot_styles = target_plotters / "Plot Styles"

    with pytest.raises(FileNotFoundError, match="打印PDF2.pc3"):
        ensure_plot_resources(
            path_info=_path_info(target_plotters, target_plot_styles),
            asset_roots=[asset_root],
        )


def test_default_asset_roots_prefers_documents_resources():
    roots = default_asset_roots()
    repo_root = Path(__file__).resolve().parents[3]

    assert repo_root / "documents" / "Resources" in roots
    assert repo_root / "documents" not in roots


def test_build_script_uses_documents_resources_as_managed_source():
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "test" / "dist" / "src" / "build_fanban_m5.ps1"
    content = script.read_text(encoding="utf-8")

    assert 'Join-Path $repoRoot "documents\\Resources"' in content
    assert "Missing valid monochrome.ctb in the current AutoCAD user profile." not in content


def test_ensure_plot_resources_preloads_all_managed_ctbs(tmp_path: Path):
    asset_root = tmp_path / "assets"
    plotters_asset = asset_root / "plotters"
    plot_styles_asset = asset_root / "plot_styles"
    plotters_asset.mkdir(parents=True)
    plot_styles_asset.mkdir(parents=True)
    (plotters_asset / PDF2_PC3_NAME).write_text("pc3", encoding="utf-8")
    (plotters_asset / PDF2_PMP_NAME).write_text("pmp", encoding="utf-8")
    for name in ALL_MANAGED_CTB_NAMES:
        (plot_styles_asset / name).write_text(name * 64, encoding="utf-8")

    target_plotters = tmp_path / "target" / "Plotters"
    target_plot_styles = target_plotters / "Plot Styles"

    result = ensure_plot_resources(
        path_info=_path_info(target_plotters, target_plot_styles),
        asset_roots=[asset_root],
        ctb_name="fanban_monochrome-same width.ctb",
    )

    assert result.ctb_path == target_plot_styles / "fanban_monochrome-same width.ctb"
    for name in ALL_MANAGED_CTB_NAMES:
        assert (target_plot_styles / name).exists()
