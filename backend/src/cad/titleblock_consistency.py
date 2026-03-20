from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..config import get_config, load_spec
from ..models import BBox, FrameMeta, SheetSet


@dataclass(frozen=True)
class TextReplacement:
    index: int
    old_text: str
    new_text: str


@dataclass(frozen=True)
class ReplacementTarget:
    old_text: str
    new_text: str
    x: float
    y: float


@dataclass
class FieldConsistencyPlan:
    frame_id: str
    field_name: str
    expected_text: str
    current_text: str
    roi_bbox: BBox
    replacements: list[TextReplacement]
    fragments: list[dict[str, Any]]

    @property
    def patch_targets(self) -> list[ReplacementTarget]:
        targets: list[ReplacementTarget] = []
        for replacement in self.replacements:
            if replacement.index < 0 or replacement.index >= len(self.fragments):
                continue
            fragment = self.fragments[replacement.index]
            try:
                x = float(fragment.get("x", 0.0))
                y = float(fragment.get("y", 0.0))
            except (TypeError, ValueError):
                continue
            targets.append(
                ReplacementTarget(
                    old_text=replacement.old_text,
                    new_text=replacement.new_text,
                    x=x,
                    y=y,
                ),
            )
        return targets


class TitleblockConsistencyService:
    _SCALE_RE = re.compile(r"1\s*:\s*\d+(?:\.\d+)?", re.IGNORECASE)
    _A4_MARKER_FULL_RE = re.compile(
        r"(?P<code>[A-Z0-9]{7}-[A-Z0-9]{5}-[0-9]{3})"
        r"\s*(?:\(\s*(?P<rev_paren>[A-Z0-9]+)\s*\)|(?P<colon>[：:])\s*(?P<rev_colon>[A-Z0-9]+))",
        re.IGNORECASE,
    )
    _A4_MARKER_PAREN_ONLY_RE = re.compile(r"^\(\s*(?P<rev>[A-Z0-9]+)\s*\)$", re.IGNORECASE)
    _A4_MARKER_COLON_ONLY_RE = re.compile(r"^(?P<colon>[：:])\s*(?P<rev>[A-Z0-9]+)$", re.IGNORECASE)

    def __init__(self) -> None:
        self.spec = load_spec()
        self.config = get_config()

    def paper_text_from_variant(self, variant_id: str | None) -> str:
        raw = str(variant_id or "").strip().upper()
        if raw.startswith("CNPE_"):
            raw = raw[5:]
        if raw == "A1+1/1":
            return "A1+1"
        if raw in {"A4", "A4H"}:
            return "A4"
        return raw

    @staticmethod
    def cover_paper_text() -> str:
        return "A4图纸"

    @staticmethod
    def catalog_paper_text() -> str:
        return "A4文件"

    def drawing_paper_text(self, frame: FrameMeta) -> str:
        variant_text = self.paper_text_from_variant(frame.runtime.paper_variant_id)
        if variant_text:
            return variant_text
        return self._compact_text(frame.titleblock.paper_size_text)

    @staticmethod
    def scale_text_from_factor(geom_scale_factor: float | None) -> str:
        if geom_scale_factor is None or geom_scale_factor <= 0:
            return ""
        return f"1:{int(round(float(geom_scale_factor)))}"

    def collect_document_frames(
        self,
        frames: list[FrameMeta],
        sheet_sets: list[SheetSet],
    ) -> list[FrameMeta]:
        by_id: dict[str, FrameMeta] = {frame.frame_id: frame for frame in frames}
        for sheet_set in sheet_sets:
            for page in getattr(sheet_set, "pages", []):
                frame = getattr(page, "frame_meta", None)
                if frame is not None:
                    by_id.setdefault(frame.frame_id, frame)
        return list(by_id.values())

    def build_frame_plans(self, frame: FrameMeta) -> list[FieldConsistencyPlan]:
        plans: list[FieldConsistencyPlan] = []

        paper_expected = self.drawing_paper_text(frame)
        paper_plan = self._build_plan(frame, field_name="paper_size_text", expected_text=paper_expected)
        if paper_plan is not None:
            plans.append(paper_plan)

        scale_expected = self.scale_text_from_factor(frame.runtime.geom_scale_factor)
        scale_plan = self._build_plan(frame, field_name="scale_text", expected_text=scale_expected)
        if scale_plan is not None:
            plans.append(scale_plan)

        return plans

    def build_sheet_set_plans(self, sheet_set: SheetSet) -> list[FieldConsistencyPlan]:
        master_page = sheet_set.master_page
        master_frame = getattr(master_page, "frame_meta", None)
        master_revision = str(getattr(master_frame.titleblock, "revision", "") or "").strip().upper() if master_frame else ""
        if not master_frame or not master_revision:
            return []

        plans: list[FieldConsistencyPlan] = []
        for page in sheet_set.pages:
            frame = getattr(page, "frame_meta", None)
            if frame is None or frame.frame_id == master_frame.frame_id:
                continue
            plan = self._build_a4_marker_revision_plan(frame, expected_revision=master_revision)
            if plan is not None:
                plans.append(plan)
        return plans

    def plan_replacements(
        self,
        fragments: list[dict[str, Any]],
        *,
        expected_text: str,
        field_name: str | None = None,
    ) -> list[TextReplacement]:
        ordered = self._select_relevant_fragments(field_name, self._sort_fragments(fragments))
        current_parts = [self._compact_text(fragment.get("text")) for fragment in ordered]
        expected_parts = self._tokenize_expected_text(expected_text)

        if not ordered:
            return []

        field_specific = self._plan_field_specific_replacements(
            ordered,
            expected_text=expected_text,
            field_name=field_name,
        )
        if field_specific is not None:
            return field_specific

        if len(ordered) == 1:
            old_text = str(ordered[0].get("text") or "")
            if self._compact_text(old_text) == self._compact_text(expected_text):
                return []
            return [TextReplacement(index=0, old_text=old_text, new_text=expected_text)]

        current_text = self._current_field_text(field_name, ordered)
        if self._compact_text(current_text) == self._compact_text(expected_text):
            return []

        if len(current_parts) != len(expected_parts):
            return []

        replacements: list[TextReplacement] = []
        for idx, (fragment, current, expected) in enumerate(zip(ordered, current_parts, expected_parts, strict=False)):
            if current == expected:
                continue
            replacements.append(
                TextReplacement(
                    index=idx,
                    old_text=str(fragment.get("text") or ""),
                    new_text=expected,
                )
            )
        return replacements

    def apply_expected_texts(
        self,
        frame: FrameMeta,
        plan: FieldConsistencyPlan | None = None,
    ) -> None:
        if plan is not None and plan.field_name == "a4_marker_revision":
            marker_meta = frame.raw_extracts.get("A4_page_marker_meta")
            if isinstance(marker_meta, dict):
                marker_meta["revision"] = plan.expected_text
            marker_fragments = frame.raw_extracts.get("A4_page_marker")
            if isinstance(marker_fragments, list):
                for replacement in plan.replacements:
                    if 0 <= replacement.index < len(marker_fragments):
                        fragment = marker_fragments[replacement.index]
                        if isinstance(fragment, dict):
                            fragment["text"] = replacement.new_text
            return

        paper_text = self.drawing_paper_text(frame)
        if paper_text:
            frame.titleblock.paper_size_text = paper_text

        scale_text = self.scale_text_from_factor(frame.runtime.geom_scale_factor)
        if scale_text:
            frame.titleblock.scale_text = scale_text
            frame.titleblock.scale_denominator = float(int(round(frame.runtime.geom_scale_factor or 0)))

    def _build_plan(
        self,
        frame: FrameMeta,
        *,
        field_name: str,
        expected_text: str,
    ) -> FieldConsistencyPlan | None:
        if not expected_text:
            return None

        roi_name = self._field_roi_name(field_name)
        fragments = self._select_relevant_fragments(
            field_name,
            self._sort_fragments(list(frame.raw_extracts.get(roi_name, []))),
        )
        if not fragments:
            return None

        current_text = self._current_field_text_from_frame(frame, field_name, fragments)
        if self._compact_text(current_text) == self._compact_text(expected_text):
            return None

        replacements = self.plan_replacements(
            fragments,
            expected_text=expected_text,
            field_name=field_name,
        )
        roi_bbox = self._resolve_roi_bbox(frame, field_name)
        if roi_bbox is None:
            return None

        return FieldConsistencyPlan(
            frame_id=frame.frame_id,
            field_name=field_name,
            expected_text=expected_text,
            current_text=current_text,
            roi_bbox=roi_bbox,
            replacements=replacements,
            fragments=fragments,
        )

    def _field_roi_name(self, field_name: str) -> str:
        field_def = self.spec.get_field_definitions().get(field_name)
        if field_def is None or not field_def.roi:
            raise KeyError(f"unknown titleblock field: {field_name}")
        return field_def.roi

    def _resolve_roi_bbox(self, frame: FrameMeta, field_name: str) -> BBox | None:
        profile_id = frame.runtime.roi_profile_id or "BASE10"
        profile = self.spec.get_roi_profile(profile_id)
        if profile is None:
            return None
        roi_name = self._field_roi_name(field_name)
        rb_offset = profile.fields.get(roi_name)
        if rb_offset is None:
            return None
        outer_bbox = frame.runtime.outer_bbox
        sx = frame.runtime.sx or 1.0
        sy = frame.runtime.sy or 1.0
        dx_right, dx_left, dy_bottom, dy_top = rb_offset
        return BBox(
            xmin=outer_bbox.xmax - dx_left * sx,
            xmax=outer_bbox.xmax - dx_right * sx,
            ymin=outer_bbox.ymin + dy_bottom * sy,
            ymax=outer_bbox.ymin + dy_top * sy,
        )

    @staticmethod
    def _sort_fragments(fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            [fragment for fragment in fragments if str(fragment.get("text") or "").strip()],
            key=lambda fragment: (
                round(float(fragment.get("x", 0.0)), 4),
                -round(float(fragment.get("y", 0.0)), 4),
            ),
        )

    @staticmethod
    def _join_fragments(fragments: list[dict[str, Any]]) -> str:
        return "".join(str(fragment.get("text") or "").strip() for fragment in fragments)

    def _current_field_text(
        self,
        field_name: str | None,
        fragments: list[dict[str, Any]],
    ) -> str:
        ordered = self._sort_fragments(list(fragments))
        if field_name == "paper_size_text":
            normalized = self._compose_overlay_paper_text(ordered)
            if normalized is not None:
                return normalized
        if field_name == "scale_text":
            scale_text = self._extract_scale_text_from_fragments(ordered)
            if scale_text:
                return scale_text
        return self._join_fragments(ordered)

    @staticmethod
    def _compact_text(value: Any) -> str:
        return "".join(str(value or "").split()).upper()

    def _current_field_text_from_frame(
        self,
        frame: FrameMeta,
        field_name: str,
        fragments: list[dict[str, Any]],
    ) -> str:
        if field_name == "paper_size_text":
            return frame.titleblock.paper_size_text or self._current_field_text(field_name, fragments)
        if field_name == "scale_text":
            return frame.titleblock.scale_text or self._current_field_text(field_name, fragments)
        return self._current_field_text(field_name, fragments)

    @staticmethod
    def _tokenize_expected_text(value: str) -> list[str]:
        tokens: list[str] = []
        text = str(value or "").strip()
        idx = 0
        while idx < len(text):
            ch = text[idx]
            if ch.isspace():
                idx += 1
                continue
            if ch.isalpha():
                start = idx
                while idx < len(text) and text[idx].isalpha():
                    idx += 1
                tokens.append(text[start:idx])
                continue
            if ch.isdigit():
                start = idx
                idx += 1
                while idx < len(text) and text[idx].isdigit():
                    idx += 1
                if idx < len(text) and text[idx] == "/":
                    idx += 1
                    while idx < len(text) and text[idx].isdigit():
                        idx += 1
                tokens.append(text[start:idx])
                continue
            tokens.append(ch)
            idx += 1
        return tokens

    @staticmethod
    def _compose_overlay_paper_text(fragments: list[dict[str, Any]]) -> str | None:
        if len(fragments) != 2:
            return None

        first, second = fragments
        first_text = TitleblockConsistencyService._compact_text(first.get("text"))
        second_text = TitleblockConsistencyService._compact_text(second.get("text"))
        second_bbox = second.get("bbox") or {}
        first_bbox = first.get("bbox") or {}

        if (
            re.fullmatch(r"[A-Z]\+\d+/\d+", first_text)
            and re.fullmatch(r"\d", second_text)
            and float(first_bbox.get("xmin", 0.0)) <= float(second_bbox.get("xmin", 0.0))
            and float(first_bbox.get("xmax", 0.0)) >= float(second_bbox.get("xmax", 0.0))
        ):
            return f"{first_text[0]}{second_text}{first_text[1:]}"

        return None

    def _select_relevant_fragments(
        self,
        field_name: str | None,
        fragments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if field_name != "scale_text":
            return fragments

        scale_fragments = [
            fragment
            for fragment in fragments
            if self._extract_scale_text(str(fragment.get("text") or ""))
        ]
        return scale_fragments or fragments

    def _plan_field_specific_replacements(
        self,
        fragments: list[dict[str, Any]],
        *,
        expected_text: str,
        field_name: str | None,
    ) -> list[TextReplacement] | None:
        if field_name == "paper_size_text":
            return self._plan_prefix_preserving_replacements(fragments, expected_text)
        if field_name == "scale_text":
            return self._plan_scale_replacements(fragments, expected_text)
        if field_name == "a4_marker_revision":
            return self._plan_a4_marker_revision_replacements(fragments, expected_text)
        return None

    def _build_a4_marker_revision_plan(
        self,
        frame: FrameMeta,
        *,
        expected_revision: str,
    ) -> FieldConsistencyPlan | None:
        marker_meta = frame.raw_extracts.get("A4_page_marker_meta")
        if not isinstance(marker_meta, dict):
            return None

        current_revision = str(marker_meta.get("revision") or "").strip().upper()
        if not current_revision or current_revision == expected_revision:
            return None

        raw_fragments = frame.raw_extracts.get("A4_page_marker")
        if not isinstance(raw_fragments, list):
            return None
        fragments = self._sort_fragments(list(raw_fragments))
        if not fragments:
            return None

        replacements = self.plan_replacements(
            fragments,
            expected_text=expected_revision,
            field_name="a4_marker_revision",
        )
        roi_bbox = self._resolve_fragment_bbox(fragments)
        if roi_bbox is None:
            return None

        return FieldConsistencyPlan(
            frame_id=frame.frame_id,
            field_name="a4_marker_revision",
            expected_text=expected_revision,
            current_text=current_revision,
            roi_bbox=roi_bbox,
            replacements=replacements,
            fragments=fragments,
        )

    def _resolve_fragment_bbox(self, fragments: list[dict[str, Any]]) -> BBox | None:
        xs_min: list[float] = []
        ys_min: list[float] = []
        xs_max: list[float] = []
        ys_max: list[float] = []
        for fragment in fragments:
            bbox = fragment.get("bbox")
            if isinstance(bbox, dict):
                try:
                    xs_min.append(float(bbox["xmin"]))
                    ys_min.append(float(bbox["ymin"]))
                    xs_max.append(float(bbox["xmax"]))
                    ys_max.append(float(bbox["ymax"]))
                    continue
                except (KeyError, TypeError, ValueError):
                    pass
            try:
                x = float(fragment.get("x", 0.0))
                y = float(fragment.get("y", 0.0))
            except (TypeError, ValueError):
                continue
            xs_min.append(x)
            ys_min.append(y)
            xs_max.append(x)
            ys_max.append(y)
        if not xs_min or not ys_min or not xs_max or not ys_max:
            return None
        return BBox(xmin=min(xs_min), ymin=min(ys_min), xmax=max(xs_max), ymax=max(ys_max))

    def _plan_prefix_preserving_replacements(
        self,
        fragments: list[dict[str, Any]],
        expected_text: str,
    ) -> list[TextReplacement]:
        if len(fragments) == 1:
            original = str(fragments[0].get("text") or "")
            if self._compact_text(original) == self._compact_text(expected_text):
                return []
            return [
                TextReplacement(
                    index=0,
                    old_text=original,
                    new_text=self._apply_compact_rewrite(original, self._compact_text(expected_text)),
                )
            ]

        if len(fragments) < 2:
            return []

        expected_compact = self._compact_text(expected_text)
        remaining = expected_compact
        replacements: list[TextReplacement] = []

        for idx, fragment in enumerate(fragments):
            current_compact = self._compact_text(fragment.get("text"))
            if idx < len(fragments) - 1:
                if not remaining.startswith(current_compact):
                    return []
                expected_fragment_compact = current_compact
                remaining = remaining[len(current_compact) :]
            else:
                expected_fragment_compact = remaining

            if current_compact == expected_fragment_compact:
                continue

            replacements.append(
                TextReplacement(
                    index=idx,
                    old_text=str(fragment.get("text") or ""),
                    new_text=self._apply_compact_rewrite(str(fragment.get("text") or ""), expected_fragment_compact),
                )
            )

        return replacements

    def _plan_scale_replacements(
        self,
        fragments: list[dict[str, Any]],
        expected_text: str,
    ) -> list[TextReplacement]:
        replacements: list[TextReplacement] = []
        expected_compact = self._compact_text(expected_text)
        for idx, fragment in enumerate(fragments):
            original = str(fragment.get("text") or "")
            current_scale = self._extract_scale_text(original)
            if not current_scale or self._compact_text(current_scale) == expected_compact:
                continue

            rewritten = self._replace_scale_text(original, expected_text)
            replacements.append(
                TextReplacement(
                    index=idx,
                    old_text=original,
                    new_text=rewritten,
                )
            )
        return replacements

    def _plan_a4_marker_revision_replacements(
        self,
        fragments: list[dict[str, Any]],
        expected_revision: str,
    ) -> list[TextReplacement]:
        replacements: list[TextReplacement] = []
        for idx, fragment in enumerate(fragments):
            original = str(fragment.get("text") or "")
            rewritten = self._rewrite_a4_marker_revision(original, expected_revision)
            if rewritten is None or rewritten == original:
                continue
            replacements.append(
                TextReplacement(
                    index=idx,
                    old_text=original,
                    new_text=rewritten,
                )
            )
        return replacements

    @classmethod
    def _extract_scale_text(cls, text: str) -> str | None:
        match = cls._SCALE_RE.search(text or "")
        if match is None:
            return None
        return re.sub(r"\s+", "", match.group(0))

    @classmethod
    def _extract_scale_text_from_fragments(cls, fragments: list[dict[str, Any]]) -> str:
        for fragment in fragments:
            text = cls._extract_scale_text(str(fragment.get("text") or ""))
            if text:
                return text
        return ""

    @classmethod
    def _replace_scale_text(cls, original: str, expected_text: str) -> str:
        match = cls._SCALE_RE.search(original or "")
        if match is None:
            return expected_text
        return f"{original[:match.start()]}{expected_text}{original[match.end():]}"

    @classmethod
    def _rewrite_a4_marker_revision(cls, original: str, expected_revision: str) -> str | None:
        match = cls._A4_MARKER_FULL_RE.search(original or "")
        if match is not None:
            if match.group("rev_paren"):
                replacement = f"{match.group('code')}({expected_revision})"
            else:
                colon = match.group("colon") or "："
                replacement = f"{match.group('code')}{colon}{expected_revision}"
            return f"{original[:match.start()]}{replacement}{original[match.end():]}"

        match = cls._A4_MARKER_PAREN_ONLY_RE.fullmatch((original or "").strip())
        if match is not None:
            return f"({expected_revision})"

        match = cls._A4_MARKER_COLON_ONLY_RE.fullmatch((original or "").strip())
        if match is not None:
            colon = match.group("colon") or "："
            return f"{colon}{expected_revision}"

        return None

    @staticmethod
    def _apply_compact_rewrite(original: str, expected_compact: str) -> str:
        original_text = str(original or "")
        if not original_text:
            return expected_compact
        leading_ws = original_text[: len(original_text) - len(original_text.lstrip())]
        trailing_ws = original_text[len(original_text.rstrip()) :]
        return f"{leading_ws}{expected_compact}{trailing_ws}"
