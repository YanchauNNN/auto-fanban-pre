from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .font_replacement_plan import normalize_kind, normalize_replacement_map

_FONT_LIBRARY_EXTENSIONS = {".ttf", ".ttc", ".otf", ".shx"}


@dataclass(frozen=True, slots=True)
class FontMappingRuntimePlan:
    font_map_path: Path | None
    font_alt: str | None
    mappings: list[tuple[str, str]]
    runtime_overrides: dict[str, str]
    staged_library_fonts: list[Path]


def build_font_search_runtime_overrides(
    *,
    font_library_dirs: Sequence[str | Path] | None,
    existing_support_path: str | None = None,
) -> dict[str, str]:
    merged_dirs: list[Path] = []
    if str(existing_support_path or "").strip():
        merged_dirs.extend(
            Path(part)
            for part in str(existing_support_path).split(";")
            if str(part).strip()
        )
    normalized_dirs = _normalize_existing_dirs(font_library_dirs or [])
    merged_dirs.extend(normalized_dirs)
    final_dirs = _normalize_existing_dirs(merged_dirs)
    if not final_dirs:
        return {}
    return {"support_path": ";".join(str(path) for path in final_dirs)}


def materialize_font_library_files(
    *,
    workspace_dir: Path,
    font_library_dirs: Sequence[str | Path] | None,
) -> list[Path]:
    workspace_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    seen_names: set[str] = set()
    for font_dir in _normalize_existing_dirs(font_library_dirs or []):
        for path in sorted(font_dir.iterdir(), key=lambda item: item.name.lower()):
            if not path.is_file() or path.suffix.lower() not in _FONT_LIBRARY_EXTENSIONS:
                continue
            key = path.name.strip().lower()
            if not key or key in seen_names:
                continue
            seen_names.add(key)
            target = workspace_dir / path.name
            if target.resolve() != path.resolve():
                shutil.copy2(path, target)
            copied.append(target)
    return copied


def build_font_mapping_entries(
    *,
    missing_fonts: Sequence[Mapping[str, object]],
    replacement_fonts: dict[str, str] | None,
) -> list[tuple[str, str]]:
    normalized_replacements = normalize_replacement_map(replacement_fonts)
    entries: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for item in missing_fonts:
        kind = normalize_kind(str(item.get("kind") or ""))
        replacement = str(normalized_replacements.get(kind, "")).strip()
        if not replacement:
            continue
        raw_font_name = str(item.get("font_name") or "").strip()
        raw_bigfont_name = str(item.get("bigfont_name") or "").strip()
        missing_name = raw_bigfont_name if kind == "bigfont" and raw_bigfont_name else raw_font_name
        if not missing_name:
            continue
        pair = (missing_name, replacement)
        if pair in seen:
            continue
        seen.add(pair)
        entries.append(pair)
    return entries


def choose_fontalt_font(
    *,
    replacement_fonts: dict[str, str] | None,
    default_fontalt_by_kind: dict[str, str] | None,
) -> str | None:
    normalized_replacements = normalize_replacement_map(replacement_fonts)
    for kind in ("ttf", "shx", "bigfont"):
        candidate = str(normalized_replacements.get(kind, "")).strip()
        if candidate:
            return candidate

    defaults = normalize_replacement_map(default_fontalt_by_kind)
    for kind in ("ttf", "shx", "bigfont"):
        candidate = str(defaults.get(kind, "")).strip()
        if candidate:
            return candidate
    return None


def write_font_map_file(*, path: Path, mappings: list[tuple[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(f"{missing};{replacement}" for missing, replacement in mappings)
    path.write_text(content + ("\n" if content else ""), encoding="utf-8")
    return path


def build_font_runtime_plan(
    *,
    workspace_dir: Path,
    missing_fonts: Sequence[Mapping[str, object]],
    replacement_fonts: dict[str, str] | None,
    enable_fontmap: bool,
    default_fontalt_by_kind: dict[str, str] | None,
    font_library_dirs: Sequence[str | Path] | None = None,
) -> FontMappingRuntimePlan:
    mappings = build_font_mapping_entries(
        missing_fonts=missing_fonts,
        replacement_fonts=replacement_fonts,
    )
    font_alt = choose_fontalt_font(
        replacement_fonts=replacement_fonts,
        default_fontalt_by_kind=default_fontalt_by_kind,
    )
    staged_library_fonts = materialize_font_library_files(
        workspace_dir=workspace_dir,
        font_library_dirs=font_library_dirs,
    )
    runtime_overrides = build_font_search_runtime_overrides(
        font_library_dirs=font_library_dirs,
    )
    font_map_path: Path | None = None

    if enable_fontmap and mappings:
        font_map_path = write_font_map_file(
            path=workspace_dir / "fanban.fontmap.fmp",
            mappings=mappings,
        )
        runtime_overrides["font_map_path"] = str(font_map_path)

    if font_alt:
        runtime_overrides["font_alt"] = font_alt

    return FontMappingRuntimePlan(
        font_map_path=font_map_path,
        font_alt=font_alt,
        mappings=mappings,
        runtime_overrides=runtime_overrides,
        staged_library_fonts=staged_library_fonts,
    )


def _normalize_existing_dirs(paths: Sequence[str | Path]) -> list[Path]:
    results: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        path = Path(raw)
        key = str(path).strip().lower()
        if not key or key in seen or not path.exists() or not path.is_dir():
            continue
        seen.add(key)
        results.append(path)
    return results
