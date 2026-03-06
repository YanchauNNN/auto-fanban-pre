"""
Plot resource deployment for Module5 PDF output.

This module ensures the required AutoCAD plot resources are available in an
AutoCAD-visible Plotters directory before the CAD runner starts.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .autocad_path_resolver import AutoCADPathInfo

PDF2_PC3_NAME = "打印PDF2.pc3"
PDF2_PMP_NAME = "tszdef-02fc5f1cb3db4a5b8afc9cce5dca6cd1.pmp"
MONOCHROME_CTB_NAME = "monochrome.ctb"


@dataclass(frozen=True)
class PlotResourceContext:
    plotters_dir: Path
    plot_styles_dir: Path
    pc3_path: Path
    pmp_path: Path
    ctb_path: Path
    deployed_files: tuple[Path, ...] = field(default_factory=tuple)


def ensure_plot_resources(
    *,
    path_info: AutoCADPathInfo,
    asset_roots: Iterable[Path] | None = None,
    pc3_name: str = PDF2_PC3_NAME,
    pmp_name: str = PDF2_PMP_NAME,
    ctb_name: str = MONOCHROME_CTB_NAME,
) -> PlotResourceContext:
    plotters_dir = _resolve_plotters_dir(path_info)
    plot_styles_dir = _resolve_plot_styles_dir(path_info, plotters_dir)
    plotters_dir.mkdir(parents=True, exist_ok=True)
    plot_styles_dir.mkdir(parents=True, exist_ok=True)

    roots = list(_normalize_asset_roots(asset_roots))
    deployed: list[Path] = []

    target_pc3 = plotters_dir / pc3_name
    pc3_source = _pick_pc3_source(path_info, roots, pc3_name)
    pc3_path = _ensure_file(target_pc3, pc3_source, deployed)

    target_pmp = plotters_dir / pmp_name
    pmp_source = _pick_asset_source(
        roots,
        [
            Path("plotters") / pmp_name,
            Path(pmp_name),
        ],
    )
    if pmp_source is None:
        raise FileNotFoundError(f"缺少必需PMP资源: {pmp_name}")
    pmp_path = _ensure_file(target_pmp, pmp_source, deployed)

    target_ctb = plot_styles_dir / ctb_name
    ctb_source = _pick_ctb_source(path_info, roots, ctb_name)
    ctb_path = _ensure_file(target_ctb, ctb_source, deployed)

    return PlotResourceContext(
        plotters_dir=plotters_dir.resolve(),
        plot_styles_dir=plot_styles_dir.resolve(),
        pc3_path=pc3_path.resolve(),
        pmp_path=pmp_path.resolve(),
        ctb_path=ctb_path.resolve(),
        deployed_files=tuple(path.resolve() for path in deployed),
    )


def default_asset_roots() -> list[Path]:
    env_root = os.getenv("FANBAN_PLOT_ASSET_ROOT")
    roots: list[Path] = []
    if env_root:
        roots.append(Path(env_root))
    if getattr(sys, "frozen", False):
        exe_root = Path(sys.executable).resolve().parent
        roots.extend([exe_root / "assets", exe_root / "_internal" / "assets"])
    repo_root = Path(__file__).resolve().parents[3]
    roots.extend(
        [
            repo_root / "test" / "dist" / "assets",
            repo_root / "documents",
        ],
    )
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve()) if root.exists() else str(root)
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def _normalize_asset_roots(asset_roots: Iterable[Path] | None) -> list[Path]:
    if asset_roots is None:
        return [root for root in default_asset_roots() if root.exists()]
    return [Path(root) for root in asset_roots]


def _resolve_plotters_dir(path_info: AutoCADPathInfo) -> Path:
    if path_info.plotters_dir is not None:
        return Path(path_info.plotters_dir)
    raise FileNotFoundError("未找到 AutoCAD Plotters 目录")


def _resolve_plot_styles_dir(path_info: AutoCADPathInfo, plotters_dir: Path) -> Path:
    if path_info.plot_styles_dir is not None:
        return Path(path_info.plot_styles_dir)
    return plotters_dir / "Plot Styles"


def _pick_pc3_source(
    path_info: AutoCADPathInfo,
    roots: list[Path],
    pc3_name: str,
) -> Path:
    if path_info.pc3_path is not None and Path(path_info.pc3_path).name == pc3_name:
        return Path(path_info.pc3_path)
    source = _pick_asset_source(
        roots,
        [
            Path("plotters") / pc3_name,
            Path(pc3_name),
        ],
    )
    if source is None:
        raise FileNotFoundError(f"缺少必需PC3资源: {pc3_name}")
    return source


def _pick_ctb_source(
    path_info: AutoCADPathInfo,
    roots: list[Path],
    ctb_name: str,
) -> Path:
    source = _pick_asset_source(
        roots,
        [
            Path("plot_styles") / ctb_name,
            Path(ctb_name),
        ],
    )
    if source is not None:
        return source
    if path_info.monochrome_ctb_path is not None and Path(path_info.monochrome_ctb_path).exists():
        return Path(path_info.monochrome_ctb_path)
    raise FileNotFoundError(f"缺少必需CTB资源: {ctb_name}")


def _pick_asset_source(roots: list[Path], relative_candidates: list[Path]) -> Path | None:
    for root in roots:
        for relative in relative_candidates:
            candidate = root / relative
            if candidate.exists() and candidate.is_file():
                return candidate
    return None


def _ensure_file(target: Path, source: Path, deployed: list[Path]) -> Path:
    if target.exists() and target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
        deployed.append(target)
    return target
