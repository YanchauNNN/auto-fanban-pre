from __future__ import annotations

import os
from pathlib import Path

try:
    import winreg
except ImportError:  # pragma: no cover - windows only
    winreg = None  # type: ignore[assignment]


_FONT_EXTENSIONS = {".ttf", ".ttc", ".otf"}


class InstalledFontInventory:
    def __init__(self) -> None:
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        self.fonts_dir = windir / "Fonts"

    def list_options(self) -> list[dict[str, str]]:
        seen: dict[str, dict[str, str]] = {}
        for entry in self._iter_registry_entries():
            key = entry["value"].lower()
            seen.setdefault(key, entry)
        for path in self._iter_font_files():
            key = path.name.lower()
            seen.setdefault(
                key,
                {
                    "label": path.stem,
                    "value": path.name,
                    "family": path.stem,
                    "path": str(path),
                },
            )
        return [seen[key] for key in sorted(seen)]

    def is_valid_font(self, value: str) -> bool:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return False
        return any(option["value"].lower() == normalized for option in self.list_options())

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
                        resolved = self.fonts_dir / value
                    if resolved.suffix.lower() not in _FONT_EXTENSIONS:
                        continue
                    results.append(
                        {
                            "label": f"{name} ({resolved.name})",
                            "value": resolved.name,
                            "family": name,
                            "path": str(resolved),
                        }
                    )
        return results

    def _iter_font_files(self) -> list[Path]:
        if not self.fonts_dir.exists():
            return []
        return [
            path
            for path in self.fonts_dir.iterdir()
            if path.is_file() and path.suffix.lower() in _FONT_EXTENSIONS
        ]
