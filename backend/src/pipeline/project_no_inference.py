from __future__ import annotations

import re
from pathlib import Path

from ..config import load_mechanism_spec


def _project_no_prefix_re() -> re.Pattern[str]:
    return re.compile(load_mechanism_spec().project_inference.project_no_prefix_regex)


def _unit_no_by_project_prefix_re() -> re.Pattern[str]:
    return re.compile(load_mechanism_spec().project_inference.unit_no_by_project_prefix_regex)


def infer_project_no_from_path(path_or_name: str | Path | None) -> str | None:
    if path_or_name is None:
        return None
    stem = Path(str(path_or_name)).stem.strip()
    if not stem:
        return None
    match = _project_no_prefix_re().search(stem)
    if match is None:
        return None
    for name in ("project_no",):
        value = match.groupdict().get(name)
        if value:
            return value
    if match.lastindex:
        for index in range(1, match.lastindex + 1):
            value = match.group(index)
            if value:
                return value
    return match.group(0)


def resolve_project_no(
    explicit_project_no: str | None,
    dwg_path: str | Path | None,
    *,
    default: str | None = None,
) -> str:
    value = (explicit_project_no or "").strip()
    if value:
        return value
    inferred = infer_project_no_from_path(dwg_path)
    if inferred:
        return inferred
    return str(default or load_mechanism_spec().project_inference.default_project_no)


def infer_unit_no_from_path(
    path_or_name: str | Path | None,
    project_no: str | None = None,
) -> str | None:
    if path_or_name is None:
        return None
    stem = Path(str(path_or_name)).stem.strip()
    if not stem:
        return None
    match = _unit_no_by_project_prefix_re().search(stem)
    if match is None:
        return None
    expected_project_no = str(project_no or "").strip()
    if expected_project_no and match.group("project_no") != expected_project_no:
        return None
    return match.group("unit_no")
