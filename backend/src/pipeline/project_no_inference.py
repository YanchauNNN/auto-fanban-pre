from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..config import load_mechanism_spec


@dataclass(frozen=True)
class ReplaceBatchIdentity:
    project_no: str
    unit_no: str
    factory_code: str


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


def infer_replace_batch_identity(
    path_or_name: str | Path | None,
) -> ReplaceBatchIdentity | None:
    if path_or_name is None:
        return None
    stem = Path(str(path_or_name)).stem.strip()
    if not stem:
        return None
    pattern = str(
        load_mechanism_spec().audit_replace.batch_filename_identity_regex or ""
    ).strip()
    if not pattern:
        return None
    try:
        match = re.search(pattern, stem, flags=re.IGNORECASE)
    except re.error:
        return None
    if match is None or len(match.groups()) < 3:
        return None
    project_no, unit_no, factory_code = match.group(1, 2, 3)
    return ReplaceBatchIdentity(
        project_no=str(project_no).strip(),
        unit_no=str(unit_no).strip(),
        factory_code=str(factory_code).strip().upper(),
    )
