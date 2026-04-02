from __future__ import annotations

from collections.abc import Iterable

KIND_ORDER = ("ttf", "shx", "bigfont", "unknown")


def normalize_kind(value: str | None) -> str:
    text = str(value or "").strip().lower()
    if text in {"ttf", "shx", "bigfont", "unknown"}:
        return text
    return "unknown"


def normalize_missing_kinds(kinds: Iterable[str] | None) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for kind in kinds or []:
        normalized = normalize_kind(kind)
        if normalized in seen:
            continue
        seen.add(normalized)
        results.append(normalized)
    if not results:
        return list(KIND_ORDER[:-1])
    return sorted(results, key=lambda item: KIND_ORDER.index(item) if item in KIND_ORDER else len(KIND_ORDER))


def normalize_replacement_map(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    result: dict[str, str] = {}
    for key, value in raw.items():
        kind = normalize_kind(str(key))
        font = str(value or "").strip()
        if not font:
            continue
        result[kind] = font
    return result

