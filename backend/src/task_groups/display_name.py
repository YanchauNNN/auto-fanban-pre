from __future__ import annotations

from pathlib import Path

from ..doc_gen.derivation import DerivationEngine
from ..models import DocContext, GlobalDocParams, TaskGroup
from ..pipeline.shared_prep import SharedPrepService


def build_task_group_display_fields(group: TaskGroup) -> dict[str, str | None]:
    album_internal_code = resolve_album_internal_code(group)
    display_name = album_internal_code or _first_source_stem(group) or group.group_id
    return {
        "album_internal_code": album_internal_code,
        "display_name": display_name,
    }


def resolve_album_internal_code(group: TaskGroup) -> str | None:
    metadata_code = _clean(group.metadata.get("album_internal_code"))
    if metadata_code:
        return metadata_code

    replacement_code = _clean(group.replacement.album_internal_code)
    if replacement_code:
        return replacement_code

    shared_dir = group.shared_dir
    if shared_dir is None:
        return None

    try:
        prep = SharedPrepService.load(shared_dir)
        params = GlobalDocParams(project_no=group.project_no or "")
        derived = DerivationEngine().compute(
            DocContext(params=params, frames=prep.frames, sheet_sets=prep.sheet_sets),
        )
    except Exception:  # noqa: BLE001
        return None

    return _clean(derived.album_internal_code)


def _first_source_stem(group: TaskGroup) -> str | None:
    for filename in group.source_filenames:
        stem = _clean(Path(filename).stem)
        if stem:
            return stem
    return None


def _clean(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
