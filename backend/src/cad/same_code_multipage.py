from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re
from uuid import uuid4

from ..config import BusinessSpec, load_spec
from ..models import FrameMeta

_META_KEY = "same_code_multipage"


@dataclass(frozen=True, slots=True)
class SameCodeMultipagePage:
    frame_id: str
    page_index: int
    page_total: int
    marker_mode: str = "index_then_total"


@dataclass(frozen=True, slots=True)
class SameCodeMultipageFamily:
    family_id: str
    internal_code: str
    external_code: str
    revision: str
    status: str
    page_total: int
    pages: tuple[SameCodeMultipagePage, ...]


def get_same_code_multipage_meta(frame: FrameMeta) -> dict[str, int | str] | None:
    raw = frame.raw_extracts.get(_META_KEY)
    if isinstance(raw, dict):
        return raw
    return None


def get_same_code_output_suffix(frame: FrameMeta) -> str:
    meta = get_same_code_multipage_meta(frame)
    if not meta:
        return ""
    page_index = int(meta.get("page_index", 0) or 0)
    page_total = int(meta.get("page_total", 0) or 0)
    if page_index <= 0 or page_total <= 1:
        return ""
    spec = _load_default_spec()
    pattern = (
        spec.get_same_code_multipage_suffix_pattern()
        if spec is not None
        else "{page_index}@{page_total}"
    )
    try:
        return pattern.format(page_index=page_index, page_total=page_total)
    except Exception:
        return f"{page_index}@{page_total}"


def _load_default_spec() -> BusinessSpec | None:
    try:
        return load_spec()
    except FileNotFoundError:
        return None


class SameCodeMultipageGrouper:
    """Recognize non-A4 same-code multi-page families without changing split semantics."""

    def group_frames(self, frames: list[FrameMeta]) -> list[SameCodeMultipageFamily]:
        families: list[SameCodeMultipageFamily] = []
        grouped: dict[tuple[str, str, str, str], list[FrameMeta]] = defaultdict(list)

        for frame in frames:
            if not self._is_eligible(frame):
                continue
            tb = frame.titleblock
            key = (
                str(tb.internal_code or "").strip(),
                str(tb.external_code or "").strip(),
                str(tb.revision or "").strip(),
                str(tb.status or "").strip(),
            )
            grouped[key].append(frame)

        for (internal, external, revision, status), items in grouped.items():
            family = self._build_family(
                internal_code=internal,
                external_code=external,
                revision=revision,
                status=status,
                frames=items,
            )
            if family is None:
                continue
            families.append(family)
            self._annotate_family(items, family)

        return families

    @staticmethod
    def _is_eligible(frame: FrameMeta) -> bool:
        paper_id = str(frame.runtime.paper_variant_id or "")
        if "A4" in paper_id:
            return False
        tb = frame.titleblock
        if not str(tb.internal_code or "").strip():
            return False
        if not str(tb.external_code or "").strip():
            return False
        if re.search(r"-001$", str(tb.internal_code or "").strip()):
            return False
        page_index = int(tb.page_index or 0)
        page_total = int(tb.page_total or 0)
        return page_index > 0 and page_total > 0 and max(page_index, page_total) > 1

    @staticmethod
    def _build_family(
        *,
        internal_code: str,
        external_code: str,
        revision: str,
        status: str,
        frames: list[FrameMeta],
    ) -> SameCodeMultipageFamily | None:
        if len(frames) < 2:
            return None

        candidates = [
            family
            for family in (
                SameCodeMultipageGrouper._build_family_with_marker_mode(
                    internal_code=internal_code,
                    external_code=external_code,
                    revision=revision,
                    status=status,
                    frames=frames,
                    marker_mode="index_then_total",
                ),
                SameCodeMultipageGrouper._build_family_with_marker_mode(
                    internal_code=internal_code,
                    external_code=external_code,
                    revision=revision,
                    status=status,
                    frames=frames,
                    marker_mode="total_then_index",
                ),
            )
            if family is not None
        ]
        if len(candidates) != 1:
            return None
        return candidates[0]

    @staticmethod
    def _build_family_with_marker_mode(
        *,
        internal_code: str,
        external_code: str,
        revision: str,
        status: str,
        frames: list[FrameMeta],
        marker_mode: str,
    ) -> SameCodeMultipageFamily | None:
        pages: list[SameCodeMultipagePage] = []
        for frame in frames:
            raw_index = int(frame.titleblock.page_index or 0)
            raw_total = int(frame.titleblock.page_total or 0)
            if marker_mode == "total_then_index":
                page_index = raw_total
                page_total = raw_index
            else:
                page_index = raw_index
                page_total = raw_total
            pages.append(
                SameCodeMultipagePage(
                    frame_id=frame.frame_id,
                    page_index=page_index,
                    page_total=page_total,
                    marker_mode=marker_mode,
                )
            )

        totals = {page.page_total for page in pages}
        totals.discard(0)
        if len(totals) != 1:
            return None

        page_total = totals.pop()
        if page_total < 2 or len(frames) != page_total:
            return None

        pages.sort(key=lambda item: item.page_index)
        expected = list(range(1, page_total + 1))
        actual = [page.page_index for page in pages]
        if actual != expected:
            return None

        return SameCodeMultipageFamily(
            family_id=str(uuid4()),
            internal_code=internal_code,
            external_code=external_code,
            revision=revision,
            status=status,
            page_total=page_total,
            pages=tuple(pages),
        )

    @staticmethod
    def _annotate_family(frames: list[FrameMeta], family: SameCodeMultipageFamily) -> None:
        page_map = {page.frame_id: page for page in family.pages}
        for frame in frames:
            page = page_map.get(frame.frame_id)
            if page is None:
                continue
            frame.raw_extracts[_META_KEY] = {
                "family_id": family.family_id,
                "page_index": page.page_index,
                "page_total": family.page_total,
                "marker_mode": page.marker_mode,
            }
