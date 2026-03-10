"""
Managed AutoCAD plot-resource deployment for Module5.

The packaged app must carry its own PC3/PMP/CTB assets and deploy them onto
AutoCAD-visible directories on the target machine. Deployment is intentionally
overwrite-first for managed files so stale user copies do not keep breaking
real-machine runs.
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
    roots = list(_normalize_asset_roots(asset_roots))
    pc3_source = _pick_pc3_source(path_info, roots, pc3_name)
    pmp_source = _pick_required_asset_source(
        roots,
        [
            Path("plotters") / pmp_name,
            Path(pmp_name),
        ],
        missing_message=f"缺少必需PMP资源: {pmp_name}",
    )
    ctb_source = _pick_ctb_source(path_info, roots, ctb_name)

    target_plotters_dirs = _resolve_target_plotters_dirs(path_info)
    if not target_plotters_dirs:
        raise FileNotFoundError("未找到 AutoCAD Plotters 目录")

    target_plot_styles_dirs = _resolve_target_plot_styles_dirs(path_info, target_plotters_dirs)
    deployed: list[Path] = []

    for plotters_dir in target_plotters_dirs:
        plotters_dir.mkdir(parents=True, exist_ok=True)
        _copy_managed_file(
            source=pc3_source,
            target=plotters_dir / pc3_name,
            deployed=deployed,
        )
        _copy_managed_file(
            source=pmp_source,
            target=plotters_dir / pmp_name,
            deployed=deployed,
        )
        _copy_managed_file(
            source=pmp_source,
            target=plotters_dir / "PMP Files" / pmp_name,
            deployed=deployed,
        )

    for plot_styles_dir in target_plot_styles_dirs:
        plot_styles_dir.mkdir(parents=True, exist_ok=True)
        _copy_managed_file(
            source=ctb_source,
            target=plot_styles_dir / ctb_name,
            deployed=deployed,
        )

    primary_plotters = target_plotters_dirs[0]
    primary_plot_styles = target_plot_styles_dirs[0]
    return PlotResourceContext(
        plotters_dir=primary_plotters.resolve(),
        plot_styles_dir=primary_plot_styles.resolve(),
        pc3_path=(primary_plotters / pc3_name).resolve(),
        pmp_path=(primary_plotters / "PMP Files" / pmp_name).resolve(),
        ctb_path=(primary_plot_styles / ctb_name).resolve(),
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
    roots.extend([repo_root / "test" / "dist" / "assets", repo_root / "documents"])
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            key = str(root.resolve())
        except Exception:
            key = str(root)
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def _normalize_asset_roots(asset_roots: Iterable[Path] | None) -> list[Path]:
    if asset_roots is None:
        return [root for root in default_asset_roots() if root.exists()]
    return [Path(root) for root in asset_roots if Path(root).exists()]


def _resolve_target_plotters_dirs(path_info: AutoCADPathInfo) -> list[Path]:
    candidates: list[Path] = []

    def add(path: Path | None) -> None:
        if path is None:
            return
        resolved = Path(path)
        if resolved not in candidates:
            candidates.append(resolved)

    add(path_info.plotters_dir)
    if path_info.install_dir is not None:
        add(Path(path_info.install_dir) / "Plotters")
    for discovered in _discover_all_user_plotter_dirs():
        add(discovered)
    return candidates


def _resolve_target_plot_styles_dirs(
    path_info: AutoCADPathInfo,
    target_plotters_dirs: list[Path],
) -> list[Path]:
    candidates: list[Path] = []

    def add(path: Path | None) -> None:
        if path is None:
            return
        resolved = Path(path)
        if resolved not in candidates:
            candidates.append(resolved)

    add(path_info.plot_styles_dir)
    for plotters_dir in target_plotters_dirs:
        add(plotters_dir / "Plot Styles")
    return candidates


def _discover_all_user_plotter_dirs() -> list[Path]:
    appdata = os.getenv("APPDATA")
    if not appdata:
        return []
    autodesk_root = Path(appdata) / "Autodesk"
    if not autodesk_root.exists() or not autodesk_root.is_dir():
        return []
    return [path for path in autodesk_root.rglob("Plotters") if path.is_dir()]


def _pick_pc3_source(
    path_info: AutoCADPathInfo,
    roots: list[Path],
    pc3_name: str,
) -> Path:
    source = _pick_asset_source(
        roots,
        [
            Path("plotters") / pc3_name,
            Path(pc3_name),
        ],
    )
    if source is not None:
        return source
    if path_info.pc3_path is not None and Path(path_info.pc3_path).name == pc3_name:
        return Path(path_info.pc3_path)
    raise FileNotFoundError(f"缺少必需PC3资源: {pc3_name}")


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


def _pick_required_asset_source(
    roots: list[Path],
    relative_candidates: list[Path],
    *,
    missing_message: str,
) -> Path:
    source = _pick_asset_source(roots, relative_candidates)
    if source is None:
        raise FileNotFoundError(missing_message)
    return source


def _pick_asset_source(roots: list[Path], relative_candidates: list[Path]) -> Path | None:
    for root in roots:
        for relative in relative_candidates:
            candidate = root / relative
            if candidate.exists() and candidate.is_file():
                return candidate
    return None


def _copy_managed_file(*, source: Path, target: Path, deployed: list[Path]) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.is_file():
        try:
            if target.read_bytes() == source.read_bytes():
                return target
        except OSError:
            pass
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
        deployed.append(target)
    return target
