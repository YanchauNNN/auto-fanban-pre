from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable
from pathlib import Path

try:
    import winreg
except ImportError:  # pragma: no cover - windows only
    winreg = None  # type: ignore[assignment]

from ..config import get_config
from .autocad_path_resolver import resolve_autocad_paths

_TTF_EXTENSIONS = {".ttf", ".ttc", ".otf"}
_SHX_EXTENSIONS = {".shx"}
logger = logging.getLogger(__name__)


class InstalledFontInventory:
    def __init__(
        self,
        *,
        autocad_fonts_dirs: Iterable[str | Path] | None = None,
        windows_fonts_dir: str | Path | None = None,
        include_registry: bool = True,
        include_windows_fonts: bool = True,
    ) -> None:
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        self.windows_fonts_dir = Path(windows_fonts_dir) if windows_fonts_dir else (windir / "Fonts")
        self.include_registry = include_registry
        self.include_windows_fonts = include_windows_fonts
        self.autocad_fonts_dirs = self._resolve_autocad_fonts_dirs(autocad_fonts_dirs)

    def list_options(self, *, preferred_kinds: set[str] | None = None) -> list[dict[str, str]]:
        kinds = {str(kind or "").strip().lower() for kind in (preferred_kinds or set()) if str(kind or "").strip()}
        if not kinds:
            kinds = {"ttf", "shx", "bigfont"}

        entries: list[dict[str, str]] = []
        if "ttf" in kinds:
            entries.extend(self._list_windows_ttf_options())
        if "shx" in kinds:
            entries.extend(self._list_autocad_shx_options(kind="shx"))
        if "bigfont" in kinds:
            entries.extend(self._list_autocad_shx_options(kind="bigfont"))
        if "unknown" in kinds:
            entries.extend(self._list_windows_ttf_options())
            entries.extend(self._list_autocad_shx_options(kind="shx"))
            entries.extend(self._list_autocad_shx_options(kind="bigfont"))
        return self._dedupe(entries)

    def is_valid_font(self, value: str, *, kind: str | None = None) -> bool:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return False
        preferred_kinds = {str(kind or "").strip().lower()} if str(kind or "").strip() else None
        return any(option["value"].lower() == normalized for option in self.list_options(preferred_kinds=preferred_kinds))

    def _resolve_autocad_fonts_dirs(self, configured_dirs: Iterable[str | Path] | None) -> list[Path]:
        if configured_dirs is not None:
            return self._normalize_existing_dirs(configured_dirs)

        candidates: list[Path] = []
        env_dir = str(os.environ.get("FANBAN_AUTOCAD_FONTS_DIR") or "").strip()
        if env_dir:
            candidates.append(Path(env_dir))

        try:
            config = get_config()
            detected = resolve_autocad_paths(configured_install_dir=config.autocad.install_dir).fonts_dir
            if detected is not None:
                candidates.append(detected)
        except Exception:  # noqa: BLE001
            pass

        return self._normalize_existing_dirs(candidates)

    @staticmethod
    def _normalize_existing_dirs(paths: Iterable[str | Path]) -> list[Path]:
        results: list[Path] = []
        seen: set[str] = set()
        for raw in paths:
            path = Path(raw)
            key = str(path).strip().lower()
            if not key or key in seen:
                continue
            try:
                is_existing_dir = path.exists() and path.is_dir()
            except OSError as exc:
                logger.warning("font inventory skipped inaccessible directory %s: %s", path, exc)
                continue
            if not is_existing_dir:
                continue
            seen.add(key)
            results.append(path)
        return results

    def _list_autocad_shx_options(self, *, kind: str) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        for fonts_dir in self.autocad_fonts_dirs:
            try:
                candidates = sorted(fonts_dir.iterdir(), key=lambda item: item.name.lower())
            except OSError as exc:
                logger.warning("font inventory skipped AutoCAD font directory %s: %s", fonts_dir, exc)
                continue
            for path in candidates:
                try:
                    if not path.is_file() or path.suffix.lower() not in _SHX_EXTENSIONS:
                        continue
                except OSError as exc:
                    logger.warning("font inventory skipped AutoCAD font file %s: %s", path, exc)
                    continue
                suffix = "AutoCAD BigFont" if kind == "bigfont" else "AutoCAD SHX"
                entries.append(
                    {
                        "label": f"{path.name} ({suffix})",
                        "value": path.name,
                        "family": path.stem,
                        "path": str(path),
                        "kind": kind,
                        "source": "autocad_fonts",
                    }
                )
        return entries

    def _list_windows_ttf_options(self) -> list[dict[str, str]]:
        if not self.include_windows_fonts:
            return []

        entries: list[dict[str, str]] = []
        if self.include_registry:
            try:
                entries.extend(self._iter_registry_entries())
            except OSError as exc:
                logger.warning("font inventory skipped Windows font registry: %s", exc)
        try:
            entries.extend(self._iter_windows_font_files())
        except OSError as exc:
            logger.warning("font inventory skipped Windows font directory %s: %s", self.windows_fonts_dir, exc)
        return entries

    def _iter_registry_entries(self) -> list[dict[str, str]]:
        if winreg is None:
            return []
        results: list[dict[str, str]] = []
        registry_paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        ]
        for hive, key_path in registry_paths:
            try:
                key = winreg.OpenKey(hive, key_path)
            except OSError:
                continue
            with key:
                index = 0
                while True:
                    try:
                        name, raw_value, _ = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    index += 1
                    value = str(raw_value or "").strip()
                    if not value:
                        continue
                    resolved = Path(value)
                    if not resolved.is_absolute():
                        resolved = self.windows_fonts_dir / value
                    if resolved.suffix.lower() not in _TTF_EXTENSIONS:
                        continue
                    results.append(
                        {
                            "label": f"{name} ({resolved.name})",
                            "value": resolved.name,
                            "family": self._normalize_registry_family_name(name),
                            "path": str(resolved),
                            "kind": "ttf",
                            "source": "windows_fonts",
                        }
                    )
        return results

    @staticmethod
    def _normalize_registry_family_name(name: str) -> str:
        return re.sub(
            r"\s+\((?:TrueType|OpenType)\)\s*$",
            "",
            str(name or "").strip(),
            flags=re.IGNORECASE,
        ).strip()

    def _iter_windows_font_files(self) -> list[dict[str, str]]:
        if not self.windows_fonts_dir.exists() or not self.windows_fonts_dir.is_dir():
            return []
        entries: list[dict[str, str]] = []
        for path in sorted(self.windows_fonts_dir.iterdir(), key=lambda item: item.name.lower()):
            try:
                if not path.is_file() or path.suffix.lower() not in _TTF_EXTENSIONS:
                    continue
            except OSError as exc:
                logger.warning("font inventory skipped Windows font file %s: %s", path, exc)
                continue
            entries.append(
                {
                    "label": f"{path.stem} ({path.name})",
                    "value": path.name,
                    "family": path.stem,
                    "path": str(path),
                    "kind": "ttf",
                    "source": "windows_fonts",
                }
            )
        return entries

    @staticmethod
    def _dedupe(options: list[dict[str, str]]) -> list[dict[str, str]]:
        seen: dict[str, dict[str, str]] = {}
        for option in options:
            key = "|".join(
                [
                    str(option.get("kind") or "").strip().lower(),
                    str(option.get("value") or "").strip().lower(),
                ]
            )
            if not key:
                continue
            seen.setdefault(key, option)
        return [seen[key] for key in sorted(seen)]
