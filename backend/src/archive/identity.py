from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ..config import BusinessSpec, MechanismSpec, load_mechanism_spec, load_spec
from ..models import GlobalDocParams


@dataclass(frozen=True, slots=True)
class ArchiveIdentity:
    engineering_no: str
    subitem_no: str
    album_internal_code: str
    revision: str
    relative_parts: tuple[str, ...]

    def target_dir(self, archive_root: Path) -> Path:
        target = archive_root
        for part in self.relative_parts:
            target = target / part
        return target


def build_archive_identity(
    params: GlobalDocParams,
    *,
    album_internal_code: str | None,
    document_revision: str | None,
    spec: BusinessSpec | None = None,
    mechanism_spec: MechanismSpec | None = None,
) -> ArchiveIdentity:
    business_spec = spec or load_spec()
    mechanism = mechanism_spec or load_mechanism_spec()
    archive_cfg = dict(business_spec.get_management_features().get("archive") or {})
    defaults = mechanism.archive_defaults
    values = {
        "engineering_no": _value_or_default(params.engineering_no, defaults.engineering_no),
        "subitem_no": _value_or_default(params.subitem_no, defaults.subitem_no),
        "album_internal_code": _value_or_default(album_internal_code, defaults.album_internal_code),
        "revision": _value_or_default(
            document_revision or params.revision,
            defaults.revision,
        ),
    }
    pattern = str(
        archive_cfg.get("level_pattern")
        or "{engineering_no}/{subitem_no}/{album_internal_code}/{revision}"
    )
    return ArchiveIdentity(
        engineering_no=values["engineering_no"],
        subitem_no=values["subitem_no"],
        album_internal_code=values["album_internal_code"],
        revision=values["revision"],
        relative_parts=_render_level_pattern(pattern, values),
    )


def _value_or_default(value: object, default: str) -> str:
    text = str(value or "").strip()
    return text or str(default)


def _render_level_pattern(pattern: str, values: Mapping[str, str]) -> tuple[str, ...]:
    rendered = pattern.format_map(values)
    parts = tuple(part.strip() for part in rendered.replace("\\", "/").split("/") if part.strip())
    if not parts:
        raise ValueError("archive level_pattern rendered to an empty path")
    return parts
