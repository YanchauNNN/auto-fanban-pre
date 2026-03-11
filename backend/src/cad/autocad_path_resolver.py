"""
AutoCAD installation path discovery helpers.

The packaged Module5 app depends on accoreconsole.exe and on AutoCAD-visible
Plotters / Plot Styles locations. The resolver therefore prefers usable
installations with a real accoreconsole.exe, ignores unsupported old versions,
and prefers formal install roots over installer-media layouts.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

MIN_SUPPORTED_AUTOCAD_YEAR = 2018
PDF2_PC3_NAME = "打印PDF2.pc3"


@dataclass(frozen=True)
class AutoCADPathInfo:
    install_dir: Path | None
    acad_exe: Path | None
    accoreconsole_exe: Path | None
    fonts_dir: Path | None
    plotters_dir: Path | None
    plot_styles_dir: Path | None
    monochrome_ctb_path: Path | None
    pc3_path: Path | None
    fallback_pdf_pc3_path: Path | None = None


def resolve_autocad_paths(
    configured_install_dir: str | Path | None = None,
    *,
    extra_candidates: Iterable[str | Path] | None = None,
    registry_candidates: Iterable[str | Path] | None = None,
    include_default_candidates: bool = True,
) -> AutoCADPathInfo:
    install_dir = _resolve_install_dir_by_priority(
        configured_install_dir=configured_install_dir,
        extra_candidates=extra_candidates,
        registry_candidates=registry_candidates,
        include_default_candidates=include_default_candidates,
    )
    if install_dir is None:
        return AutoCADPathInfo(
            install_dir=None,
            acad_exe=None,
            accoreconsole_exe=None,
            fonts_dir=None,
            plotters_dir=None,
            plot_styles_dir=None,
            monochrome_ctb_path=None,
            pc3_path=None,
            fallback_pdf_pc3_path=None,
        )

    fonts_dir = _first_existing_dir([install_dir / "Fonts"])
    year_hint = _extract_year_hint(str(install_dir))
    all_user_plotters = _discover_user_plotter_dirs()
    preferred_user_plotters = _filter_plotters_by_year(all_user_plotters, year_hint)
    other_user_plotters = [p for p in all_user_plotters if p not in preferred_user_plotters]

    plotters_candidates = [*preferred_user_plotters, install_dir / "Plotters", *other_user_plotters]
    plot_styles_candidates = [
        *(p / "Plot Styles" for p in preferred_user_plotters),
        install_dir / "Plotters" / "Plot Styles",
        *(p / "Plot Styles" for p in other_user_plotters),
    ]

    return AutoCADPathInfo(
        install_dir=install_dir,
        acad_exe=_first_existing_file([install_dir / "acad.exe", install_dir / "acadlt.exe"]),
        accoreconsole_exe=_first_existing_file([install_dir / "accoreconsole.exe"]),
        fonts_dir=fonts_dir,
        plotters_dir=_first_existing_dir(plotters_candidates),
        plot_styles_dir=_first_existing_dir(plot_styles_candidates),
        monochrome_ctb_path=_first_existing_file(
            [
                *(p / "Plot Styles" / "monochrome.ctb" for p in preferred_user_plotters),
                install_dir / "Plotters" / "Plot Styles" / "monochrome.ctb",
                *(p / "Plot Styles" / "monochrome.ctb" for p in other_user_plotters),
            ],
        ),
        pc3_path=_first_existing_file(
            [
                *(p / PDF2_PC3_NAME for p in preferred_user_plotters),
                install_dir / "Plotters" / PDF2_PC3_NAME,
                *(p / PDF2_PC3_NAME for p in other_user_plotters),
            ],
        ),
        fallback_pdf_pc3_path=_first_existing_file(
            [
                *(p / "DWG To PDF.pc3" for p in preferred_user_plotters),
                *(p / "AutoCAD PDF (General Documentation).pc3" for p in preferred_user_plotters),
                install_dir / "Plotters" / "DWG To PDF.pc3",
                install_dir / "Plotters" / "AutoCAD PDF (General Documentation).pc3",
                *(p / "DWG To PDF.pc3" for p in other_user_plotters),
                *(p / "AutoCAD PDF (General Documentation).pc3" for p in other_user_plotters),
            ],
        ),
    )


def _resolve_install_dir_by_priority(
    *,
    configured_install_dir: str | Path | None,
    extra_candidates: Iterable[str | Path] | None,
    registry_candidates: Iterable[str | Path] | None,
    include_default_candidates: bool,
) -> Path | None:
    candidate_groups: list[list[Path]] = []

    configured_group: list[Path] = []
    _append_candidate(configured_group, configured_install_dir)
    if configured_group:
        candidate_groups.append(configured_group)

    env_group: list[Path] = []
    _append_candidate(env_group, os.getenv("FANBAN_AUTOCAD_INSTALL_DIR"))
    if env_group:
        candidate_groups.append(env_group)

    extra_group: list[Path] = []
    for candidate in extra_candidates or []:
        _append_candidate(extra_group, candidate)
    if extra_group:
        candidate_groups.append(extra_group)

    registry_group: list[Path] = []
    if registry_candidates is None:
        for candidate in _discover_registry_install_dirs():
            _append_candidate(registry_group, candidate)
    else:
        for candidate in registry_candidates:
            _append_candidate(registry_group, candidate)
    if registry_group:
        candidate_groups.append(registry_group)

    default_group: list[Path] = []
    if include_default_candidates:
        for candidate in _default_install_candidates():
            _append_candidate(default_group, candidate)
    if default_group:
        candidate_groups.append(default_group)

    for group in candidate_groups:
        install_dir = _first_resolved_install_dir(group)
        if install_dir is not None:
            return install_dir
    return None


def _append_candidate(candidates: list[Path], raw: str | Path | None) -> None:
    if raw is None:
        return
    if isinstance(raw, str) and not raw.strip():
        return
    path = Path(raw).expanduser()
    key = str(path).strip()
    if not key:
        return
    lower_set = {str(p).lower() for p in candidates}
    if key.lower() not in lower_set:
        candidates.append(path)


def _first_existing_dir(paths: Iterable[Path]) -> Path | None:
    for path in paths:
        if path.exists() and path.is_dir():
            return path
    return None


def _first_resolved_install_dir(paths: Iterable[Path]) -> Path | None:
    best_match: tuple[tuple[int, int, int], Path] | None = None
    for path in paths:
        resolved = _resolve_install_dir_candidate(path)
        if resolved is None:
            continue
        rank = _install_dir_rank(resolved)
        if best_match is None or rank > best_match[0]:
            best_match = (rank, resolved)
    return best_match[1] if best_match is not None else None


def _resolve_install_dir_candidate(path: Path) -> Path | None:
    best_match: tuple[tuple[int, int, int], Path] | None = None
    for candidate in _expand_install_dir_candidates(path):
        rank = _install_dir_rank(candidate)
        if rank <= (0, 0, 0):
            continue
        if best_match is None or rank > best_match[0]:
            best_match = (rank, candidate)
    return best_match[1] if best_match is not None else None


def _expand_install_dir_candidates(path: Path) -> list[Path]:
    if not path.exists():
        return []

    if path.is_file():
        if path.name.lower() in {"acad.exe", "acadlt.exe", "accoreconsole.exe"}:
            return [path.parent]
        return []

    candidates: list[Path] = []
    for candidate in (
        path,
        path / "Root",
        path / "PF" / "Root",
        path / "Program Files" / "Root",
    ):
        if candidate.exists() and candidate.is_dir() and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _install_dir_rank(path: Path) -> tuple[int, int, int]:
    year = _extract_year_int(path)
    if year is not None and year < MIN_SUPPORTED_AUTOCAD_YEAR:
        return (0, 0, 0)

    has_accoreconsole = (path / "accoreconsole.exe").exists()
    has_acad = (path / "acad.exe").exists() or (path / "acadlt.exe").exists()
    if not has_accoreconsole and not has_acad:
        return (0, 0, 0)

    executable_score = 2 if has_accoreconsole else 1
    install_kind_score = 2 if _looks_like_official_install_dir(path) else 1
    year_score = year or 0
    return (executable_score, install_kind_score, year_score)


def _looks_like_official_install_dir(path: Path) -> bool:
    normalized = str(path).lower().replace("/", "\\")
    return "\\pf\\root" not in normalized and "\\program files\\root" not in normalized


def _first_existing_file(paths: Iterable[Path]) -> Path | None:
    for path in paths:
        if path.exists() and path.is_file():
            return path
    return None


def _default_install_candidates() -> list[Path]:
    versions = ("2026", "2025", "2024", "2023", "2022", "2021", "2020", "2019", "2018")
    roots = (
        Path(r"D:\AUTOCAD"),
        Path(r"C:\AUTOCAD"),
        Path(r"D:\Program Files\AUTOCAD"),
        Path(r"C:\Program Files\AUTOCAD"),
        Path(r"D:\Program Files\Autodesk"),
        Path(r"C:\Program Files\Autodesk"),
    )
    result: list[Path] = []
    for root in roots:
        for year in versions:
            result.append(root / f"AutoCAD {year}")
    return result


def _discover_registry_install_dirs() -> list[Path]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except Exception:
        return []

    results: list[Path] = []
    uninstall_roots = (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    )
    autodesk_root = r"SOFTWARE\Autodesk\AutoCAD"

    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for root in uninstall_roots:
            for sub in _iter_registry_subkeys(winreg, hive, root):
                full = f"{root}\\{sub}"
                display_name = (_read_registry_str(winreg, hive, full, "DisplayName") or "").lower()
                if "autocad" not in display_name:
                    continue
                install = _read_registry_str(winreg, hive, full, "InstallLocation")
                _append_candidate(results, install)

        for version in _iter_registry_subkeys(winreg, hive, autodesk_root):
            version_root = f"{autodesk_root}\\{version}"
            for product in _iter_registry_subkeys(winreg, hive, version_root):
                product_root = f"{version_root}\\{product}"
                acad_location = _read_registry_str(winreg, hive, product_root, "AcadLocation")
                _append_candidate(results, acad_location)

    return results


def _extract_year_hint(text: str) -> str | None:
    match = re.search(r"20\d{2}", text)
    return match.group(0) if match else None


def _extract_year_int(path: Path) -> int | None:
    hint = _extract_year_hint(str(path))
    if hint is None:
        return None
    try:
        return int(hint)
    except ValueError:
        return None


def _filter_plotters_by_year(paths: list[Path], year_hint: str | None) -> list[Path]:
    if not year_hint:
        return []
    return [path for path in paths if year_hint in str(path)]


def _discover_user_plotter_dirs() -> list[Path]:
    appdata = os.getenv("APPDATA")
    if not appdata:
        return []
    root = Path(appdata) / "Autodesk"
    if not root.exists() or not root.is_dir():
        return []
    return [path for path in root.rglob("Plotters") if path.is_dir()]


def _iter_registry_subkeys(winreg, hive, root: str) -> list[str]:
    names: list[str] = []
    try:
        with winreg.OpenKey(hive, root) as key:
            count = winreg.QueryInfoKey(key)[0]
            for index in range(count):
                names.append(winreg.EnumKey(key, index))
    except Exception:
        return names
    return names


def _read_registry_str(winreg, hive, root: str, value_name: str) -> str | None:
    try:
        with winreg.OpenKey(hive, root) as key:
            value, _ = winreg.QueryValueEx(key, value_name)
            if isinstance(value, str):
                return value
    except Exception:
        return None
    return None
