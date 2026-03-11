from __future__ import annotations

import re
from pathlib import Path

_PROJECT_NO_PREFIX_RE = re.compile(r"^(\d{4})")


def infer_project_no_from_path(path_or_name: str | Path | None) -> str | None:
    if path_or_name is None:
        return None
    stem = Path(str(path_or_name)).stem.strip()
    if not stem:
        return None
    match = _PROJECT_NO_PREFIX_RE.match(stem)
    if match is None:
        return None
    return match.group(1)


def resolve_project_no(
    explicit_project_no: str | None,
    dwg_path: str | Path | None,
    *,
    default: str = "2016",
) -> str:
    value = (explicit_project_no or "").strip()
    if value:
        return value
    inferred = infer_project_no_from_path(dwg_path)
    if inferred:
        return inferred
    return default
