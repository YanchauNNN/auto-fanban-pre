from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .font_replacement_plan import normalize_kind, normalize_replacement_map


@dataclass(frozen=True, slots=True)
class FontMappingRuntimePlan:
    font_map_path: Path | None
    font_alt: str | None
    mappings: list[tuple[str, str]]
    runtime_overrides: dict[str, str]


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
) -> FontMappingRuntimePlan:
    mappings = build_font_mapping_entries(
        missing_fonts=missing_fonts,
        replacement_fonts=replacement_fonts,
    )
    font_alt = choose_fontalt_font(
        replacement_fonts=replacement_fonts,
        default_fontalt_by_kind=default_fontalt_by_kind,
    )
    runtime_overrides: dict[str, str] = {}
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
    )
