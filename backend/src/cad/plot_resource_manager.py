"""
Managed AutoCAD plot-resource deployment for Module5.

The packaged app must carry its own PC3/PMP/CTB assets and deploy them onto
AutoCAD-visible directories on the target machine. Managed resources should be
self-contained and must not overwrite the user's generic system plot styles.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable
from zipfile import BadZipFile, ZipFile

from .autocad_path_resolver import AutoCADPathInfo
from .plot_asset_validation import (
    CAD_PLOT_ASSETS_BACKUP_ZIP,
    MIN_VALID_CTB_BYTES,
    is_valid_ctb_bytes,
    is_valid_ctb_file,
    is_valid_pc3_bytes,
    is_valid_pc3_file,
    is_valid_pmp_bytes,
    is_valid_pmp_file,
)

PDF2_PC3_NAME = "\u6253\u5370PDF2.pc3"
PDF2_PMP_NAME = "tszdef-02fc5f1cb3db4a5b8afc9cce5dca6cd1.pmp"
MONOCHROME_CTB_NAME = "monochrome.ctb"
MANAGED_CTB_NAME = "fanban_monochrome.ctb"
MANAGED_SAME_WIDTH_CTB_NAME = "fanban_monochrome-same width.ctb"
MANAGED_GRAYSCALE_CTB_NAME = "fanban_monochrome-huidu.ctb"
MANAGED_REVIEW_WHITE_CTB_NAME = "\u6253\u767d\u56fe.ctb"
MANAGED_TELECOM_CTB_NAME = "\u901a\u4fe1\u6253\u5370\u6837\u5f0f.ctb"
MANAGED_TELECOM_THIN_CTB_NAME = "\u901a\u4fe1\u6253\u5370\u6837\u5f0f\u7ec6\u7ebf.ctb"
MANAGED_STEEL_LINER_CTB_NAME = "\u7ed3\u6784\u4e8c\u5ba4\u5927\u56fe.ctb"
ALL_MANAGED_CTB_NAMES = (
    MANAGED_CTB_NAME,
    MANAGED_SAME_WIDTH_CTB_NAME,
    MANAGED_GRAYSCALE_CTB_NAME,
    MANAGED_REVIEW_WHITE_CTB_NAME,
    MANAGED_TELECOM_CTB_NAME,
    MANAGED_TELECOM_THIN_CTB_NAME,
    MANAGED_STEEL_LINER_CTB_NAME,
)
DEFAULT_PLOT_ASSET_ROOT_ENV_VAR = "FANBAN_PLOT_ASSET_ROOT"


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
    ctb_name: str = MANAGED_CTB_NAME,
    managed_ctb_names: Iterable[str] | None = None,
    min_valid_ctb_bytes: int = MIN_VALID_CTB_BYTES,
    target_plotters_dirs: Iterable[Path] | None = None,
    target_plot_styles_dirs: Iterable[Path] | None = None,
) -> PlotResourceContext:
    roots = list(_normalize_asset_roots(asset_roots))
    pc3_source = _pick_pc3_source(path_info, roots, pc3_name)
    pmp_source = _pick_required_asset_source(
        roots,
        [
            Path("plotters") / pmp_name,
            Path(pmp_name),
        ],
        missing_message=f"????PMP??: {pmp_name}",
        validator=is_valid_pmp_file,
        backup_validator=is_valid_pmp_bytes,
    )
    ctb_names_to_deploy = _resolve_managed_ctb_names(
        ctb_name=ctb_name,
        managed_ctb_names=managed_ctb_names,
    )
    ctb_sources = {
        name: _pick_ctb_source(
            path_info,
            roots,
            name,
            min_valid_ctb_bytes=min_valid_ctb_bytes,
        )
        for name in ctb_names_to_deploy
    }

    resolved_plotters_dirs = (
        [Path(path) for path in target_plotters_dirs]
        if target_plotters_dirs is not None
        else _resolve_target_plotters_dirs(path_info)
    )
    if not resolved_plotters_dirs:
        raise FileNotFoundError("??? AutoCAD Plotters ??")

    resolved_plot_styles_dirs = (
        [Path(path) for path in target_plot_styles_dirs]
        if target_plot_styles_dirs is not None
        else _resolve_target_plot_styles_dirs(path_info, resolved_plotters_dirs)
    )
    deployed: list[Path] = []

    for plotters_dir in resolved_plotters_dirs:
        plotters_dir.mkdir(parents=True, exist_ok=True)
        _copy_managed_file(source=pc3_source, target=plotters_dir / pc3_name, deployed=deployed)
        _copy_managed_file(source=pmp_source, target=plotters_dir / pmp_name, deployed=deployed)
        _copy_managed_file(
            source=pmp_source,
            target=plotters_dir / "PMP Files" / pmp_name,
            deployed=deployed,
        )

    for plot_styles_dir in resolved_plot_styles_dirs:
        plot_styles_dir.mkdir(parents=True, exist_ok=True)
        for managed_name, managed_source in ctb_sources.items():
            _copy_managed_file(
                source=managed_source,
                target=plot_styles_dir / managed_name,
                deployed=deployed,
            )

    primary_plotters = resolved_plotters_dirs[0]
    primary_plot_styles = resolved_plot_styles_dirs[0]
    return PlotResourceContext(
        plotters_dir=primary_plotters.resolve(),
        plot_styles_dir=primary_plot_styles.resolve(),
        pc3_path=(primary_plotters / pc3_name).resolve(),
        pmp_path=(primary_plotters / "PMP Files" / pmp_name).resolve(),
        ctb_path=(primary_plot_styles / ctb_name).resolve(),
        deployed_files=tuple(path.resolve() for path in deployed),
    )


def default_asset_roots() -> list[Path]:
    plot_assets_cfg = _load_plot_assets_config()
    env_var_name = (
        str(getattr(plot_assets_cfg, "env_asset_root_var", "") or "").strip()
        or DEFAULT_PLOT_ASSET_ROOT_ENV_VAR
    )
    env_root = os.getenv(env_var_name)
    roots: list[Path] = []
    if env_root:
        roots.append(Path(env_root))
    configured_roots = list(getattr(plot_assets_cfg, "asset_roots", []) or [])
    if configured_roots:
        roots.extend(Path(root) for root in configured_roots)
    module_path = Path(__file__).resolve()
    repo_like_roots: list[Path] = []
    for idx in (3, 4):
        with_root = module_path.parents[idx] if len(module_path.parents) > idx else None
        if with_root is not None and with_root not in repo_like_roots:
            repo_like_roots.append(with_root)
    for repo_root in repo_like_roots:
        roots.extend(
            [
                repo_root / "test" / "dist" / "assets",
                repo_root / "documents" / "Resources",
            ]
        )
    if getattr(sys, "frozen", False) and bool(
        getattr(plot_assets_cfg, "include_frozen_asset_dirs", True),
    ):
        exe_root = Path(sys.executable).resolve().parent
        roots.extend([exe_root / "assets", exe_root / "_internal" / "assets"])
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


def _resolve_managed_ctb_names(
    *,
    ctb_name: str,
    managed_ctb_names: Iterable[str] | None,
) -> tuple[str, ...]:
    names: list[str] = []
    for name in managed_ctb_names or ALL_MANAGED_CTB_NAMES:
        normalized = str(name or "").strip()
        if normalized and normalized not in names:
            names.append(normalized)
    requested = str(ctb_name or "").strip()
    if requested and requested not in names:
        names.append(requested)
    if not names:
        names.append(MANAGED_CTB_NAME)
    return tuple(names)


def _resolve_target_plotters_dirs(path_info: AutoCADPathInfo) -> list[Path]:
    candidates: list[Path] = []
    year_hint = _extract_year_hint(path_info)

    def add(path: Path | None) -> None:
        if path is None:
            return
        resolved = Path(path)
        if resolved not in candidates:
            candidates.append(resolved)

    add(path_info.plotters_dir)
    if path_info.install_dir is not None:
        add(Path(path_info.install_dir) / "Plotters")
    for discovered in _discover_all_user_plotter_dirs(year_hint=year_hint):
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


def _discover_all_user_plotter_dirs(*, year_hint: str | None) -> list[Path]:
    discovered: list[Path] = []
    for env_name in ("APPDATA", "LOCALAPPDATA"):
        root_value = os.getenv(env_name)
        if not root_value:
            continue
        autodesk_root = Path(root_value) / "Autodesk"
        if not autodesk_root.exists() or not autodesk_root.is_dir():
            continue
        for path in autodesk_root.rglob("Plotters"):
            if not path.is_dir():
                continue
            if year_hint and year_hint not in str(path):
                continue
            if path not in discovered:
                discovered.append(path)
    return discovered


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
        validator=is_valid_pc3_file,
        backup_validator=is_valid_pc3_bytes,
        backup_asset_name=pc3_name,
    )
    if source is not None:
        return source
    if (
        path_info.pc3_path is not None
        and Path(path_info.pc3_path).name == pc3_name
        and is_valid_pc3_file(Path(path_info.pc3_path))
    ):
        return Path(path_info.pc3_path)
    raise FileNotFoundError(f"????PC3??: {pc3_name}")


def _pick_ctb_source(
    path_info: AutoCADPathInfo,
    roots: list[Path],
    ctb_name: str,
    *,
    min_valid_ctb_bytes: int,
) -> Path:
    source = _pick_asset_source(
        roots,
        [
            Path("plot_styles") / ctb_name,
            Path(ctb_name),
        ],
        validator=lambda path: is_valid_ctb_file(path, min_valid_bytes=min_valid_ctb_bytes),
        backup_validator=lambda data: is_valid_ctb_bytes(data, min_valid_bytes=min_valid_ctb_bytes),
        backup_asset_name=ctb_name,
    )
    if source is not None:
        return source
    if (
        path_info.monochrome_ctb_path is not None
        and Path(path_info.monochrome_ctb_path).exists()
        and is_valid_ctb_file(
            Path(path_info.monochrome_ctb_path),
            min_valid_bytes=min_valid_ctb_bytes,
        )
    ):
        return Path(path_info.monochrome_ctb_path)
    raise FileNotFoundError(f"????CTB??: {ctb_name}")


def _pick_required_asset_source(
    roots: list[Path],
    relative_candidates: list[Path],
    *,
    missing_message: str,
    validator: Callable[[Path], bool] | None = None,
    backup_validator: Callable[[bytes], bool] | None = None,
) -> Path:
    source = _pick_asset_source(
        roots,
        relative_candidates,
        validator=validator,
        backup_validator=backup_validator,
    )
    if source is None:
        raise FileNotFoundError(missing_message)
    return source


def _pick_asset_source(
    roots: list[Path],
    relative_candidates: list[Path],
    *,
    validator: Callable[[Path], bool] | None = None,
    backup_validator: Callable[[bytes], bool] | None = None,
    backup_asset_name: str | None = None,
) -> Path | None:
    for root in roots:
        for relative in relative_candidates:
            candidate = root / relative
            if candidate.exists() and candidate.is_file() and (
                validator is None or validator(candidate)
            ):
                return candidate
    if backup_validator is None:
        return None
    for root in roots:
        restored = _extract_backup_asset(
            root,
            backup_asset_name or relative_candidates[0].name,
            backup_validator,
        )
        if restored is not None and (validator is None or validator(restored)):
            return restored
    return None


def _extract_backup_asset(
    root: Path,
    asset_name: str,
    validator: Callable[[bytes], bool],
) -> Path | None:
    archive_path = root / CAD_PLOT_ASSETS_BACKUP_ZIP
    if not archive_path.exists() or not archive_path.is_file():
        return None
    member_names = (
        asset_name,
        f"plotters/{asset_name}",
        f"plot_styles/{asset_name}",
        f"Plotters/{asset_name}",
        f"Plot Styles/{asset_name}",
    )
    try:
        with ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            member = next((name for name in member_names if name in names), None)
            if member is None:
                return None
            data = archive.read(member)
    except (BadZipFile, OSError, KeyError):
        return None
    if not validator(data):
        return None
    cache_dir = root / ".cad_plot_assets_backup_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / asset_name
    target.write_bytes(data)
    return target


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


def _extract_year_hint(path_info: AutoCADPathInfo) -> str | None:
    for candidate in (path_info.install_dir, path_info.plotters_dir, path_info.plot_styles_dir):
        if candidate is None:
            continue
        normalized = str(candidate).replace("/", "\\")
        for token in normalized.split("\\"):
            if token.isdigit() and len(token) == 4:
                return token
        for token in str(candidate).split():
            if token.isdigit() and len(token) == 4:
                return token
    return None


def _load_plot_assets_config():
    try:
        from ..config import get_config

        return get_config().plot_assets
    except Exception:
        return None
