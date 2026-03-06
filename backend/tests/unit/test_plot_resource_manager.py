from __future__ import annotations

from pathlib import Path

import pytest

from src.cad.autocad_path_resolver import AutoCADPathInfo
from src.cad.plot_resource_manager import ensure_plot_resources


def _path_info(plotters_dir: Path, plot_styles_dir: Path, system_ctb: Path | None = None) -> AutoCADPathInfo:
    return AutoCADPathInfo(
        install_dir=None,
        acad_exe=None,
        accoreconsole_exe=None,
        fonts_dir=None,
        plotters_dir=plotters_dir,
        plot_styles_dir=plot_styles_dir,
        monochrome_ctb_path=system_ctb,
        pc3_path=None,
    )


def test_ensure_plot_resources_deploys_pdf2_and_pmp_and_ctb(tmp_path: Path):
    asset_root = tmp_path / "assets"
    plotters_asset = asset_root / "plotters"
    plot_styles_asset = asset_root / "plot_styles"
    plotters_asset.mkdir(parents=True)
    plot_styles_asset.mkdir(parents=True)
    (plotters_asset / "打印PDF2.pc3").write_text("pc3", encoding="utf-8")
    (plotters_asset / "tszdef-02fc5f1cb3db4a5b8afc9cce5dca6cd1.pmp").write_text(
        "pmp",
        encoding="utf-8",
    )
    system_ctb = tmp_path / "system" / "monochrome.ctb"
    system_ctb.parent.mkdir(parents=True)
    system_ctb.write_text("ctb", encoding="utf-8")

    target_plotters = tmp_path / "target" / "Plotters"
    target_plot_styles = target_plotters / "Plot Styles"

    result = ensure_plot_resources(
        path_info=_path_info(target_plotters, target_plot_styles, system_ctb),
        asset_roots=[asset_root],
    )

    assert result.pc3_path == target_plotters / "打印PDF2.pc3"
    assert result.pmp_path == target_plotters / "tszdef-02fc5f1cb3db4a5b8afc9cce5dca6cd1.pmp"
    assert result.ctb_path == target_plot_styles / "monochrome.ctb"
    assert result.pc3_path.read_text(encoding="utf-8") == "pc3"
    assert result.pmp_path.read_text(encoding="utf-8") == "pmp"
    assert result.ctb_path.read_text(encoding="utf-8") == "ctb"


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
