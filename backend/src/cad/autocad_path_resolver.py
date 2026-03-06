"""
AutoCAD 安装路径解析工具。

设计目标：
- 优先使用显式配置的安装目录
- 兼容环境变量覆盖与注册表自动发现
- 为模块5后续 AutoCAD COM/打印链路提供统一路径入口
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AutoCADPathInfo:
    """AutoCAD 关键路径快照。"""

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
    """解析 AutoCAD 安装路径与常用子路径。

    优先级：
    1) configured_install_dir
    2) 环境变量 FANBAN_AUTOCAD_INSTALL_DIR
    3) extra_candidates（调用方可注入）
    4) 注册表发现结果（可注入 registry_candidates 覆盖）
    5) 常见默认安装目录
    """

    candidates: list[Path] = []
    _append_candidate(candidates, configured_install_dir)
    _append_candidate(candidates, os.getenv("FANBAN_AUTOCAD_INSTALL_DIR"))

    for candidate in extra_candidates or []:
        _append_candidate(candidates, candidate)

    if registry_candidates is None:
        for candidate in _discover_registry_install_dirs():
            _append_candidate(candidates, candidate)
    else:
        for candidate in registry_candidates:
            _append_candidate(candidates, candidate)

    if include_default_candidates:
        for candidate in _default_install_candidates():
            _append_candidate(candidates, candidate)

    install_dir = _first_existing_dir(candidates)
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
    user_plotters = _discover_user_plotter_dirs(_extract_year_hint(install_dir.name))
    plotters_candidates = [*user_plotters, install_dir / "Plotters"]
    plot_styles_candidates = [
        *(p / "Plot Styles" for p in user_plotters),
        install_dir / "Plotters" / "Plot Styles",
    ]
    plotters_dir = _first_existing_dir(plotters_candidates)
    plot_styles_dir = _first_existing_dir(plot_styles_candidates)

    return AutoCADPathInfo(
        install_dir=install_dir,
        acad_exe=_first_existing_file([install_dir / "acad.exe", install_dir / "acadlt.exe"]),
        accoreconsole_exe=_first_existing_file([install_dir / "accoreconsole.exe"]),
        fonts_dir=fonts_dir,
        plotters_dir=plotters_dir,
        plot_styles_dir=plot_styles_dir,
        monochrome_ctb_path=_first_existing_file(
            [
                *(p / "Plot Styles" / "monochrome.ctb" for p in user_plotters),
                install_dir / "Plotters" / "Plot Styles" / "monochrome.ctb",
            ],
        ),
        pc3_path=_first_existing_file(
            [
                *(p / "打印PDF2.pc3" for p in user_plotters),
                install_dir / "Plotters" / "打印PDF2.pc3",
            ],
        ),
        fallback_pdf_pc3_path=_first_existing_file(
            [
                *(p / "DWG To PDF.pc3" for p in user_plotters),
                *(p / "AutoCAD PDF (General Documentation).pc3" for p in user_plotters),
                install_dir / "Plotters" / "DWG To PDF.pc3",
                install_dir / "Plotters" / "AutoCAD PDF (General Documentation).pc3",
            ],
        ),
    )


def _append_candidate(candidates: list[Path], raw: str | Path | None) -> None:
    if raw is None:
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


def _first_existing_file(paths: Iterable[Path]) -> Path | None:
    for path in paths:
        if path.exists() and path.is_file():
            return path
    return None


def _default_install_candidates() -> list[Path]:
    versions = ("2026", "2025", "2024", "2023", "2022", "2021")
    roots = (
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


def _extract_year_hint(name: str) -> str | None:
    match = re.search(r"20\d{2}", name)
    return match.group(0) if match else None


def _discover_user_plotter_dirs(year_hint: str | None) -> list[Path]:
    appdata = os.getenv("APPDATA")
    if not appdata:
        return []
    root = Path(appdata) / "Autodesk"
    if not root.exists() or not root.is_dir():
        return []

    found: list[Path] = [p for p in root.rglob("Plotters") if p.is_dir()]
    if not found:
        return []
    if not year_hint:
        return found

    preferred = [p for p in found if year_hint in str(p)]
    others = [p for p in found if year_hint not in str(p)]
    return [*preferred, *others]


def _iter_registry_subkeys(winreg, hive, root: str) -> list[str]:
    names: list[str] = []
    try:
        with winreg.OpenKey(hive, root) as key:
            count = winreg.QueryInfoKey(key)[0]
            for i in range(count):
                names.append(winreg.EnumKey(key, i))
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
