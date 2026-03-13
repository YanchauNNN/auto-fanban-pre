from __future__ import annotations

from dataclasses import dataclass

from ..config import load_spec
from ..models import BBox, FrameMeta, SheetSet
from .models import ScanTextItem


@dataclass(frozen=True, slots=True)
class _FieldRegion:
    bbox: BBox
    field_context: str
    internal_code: str | None


@dataclass(frozen=True, slots=True)
class _FrameRegion:
    bbox: BBox
    internal_code: str | None
    area: float


class AuditFieldContextMapper:
    def __init__(self, frames: list[FrameMeta], sheet_sets: list[SheetSet]) -> None:
        self.spec = load_spec()
        tolerances = self.spec.titleblock_extract.get("tolerances", {})
        self._roi_margin_percent = float(tolerances.get("roi_margin_percent", 0.0))
        self._frame_regions = self._build_frame_regions(frames, sheet_sets)
        self._field_regions = self._build_field_regions(frames)

    def annotate(self, item: ScanTextItem) -> ScanTextItem:
        x = item.position_x
        y = item.position_y
        internal_code = item.internal_code
        field_context = item.field_context

        if x is not None and y is not None:
            if internal_code is None:
                internal_code = self._resolve_internal_code(x, y)
            if field_context is None:
                field_context = self._resolve_field_context(x, y)

        return ScanTextItem(
            raw_text=item.raw_text,
            entity_type=item.entity_type,
            field_context=field_context,
            internal_code=internal_code,
            layout_name=item.layout_name,
            entity_handle=item.entity_handle,
            block_path=item.block_path,
            position_x=item.position_x,
            position_y=item.position_y,
        )

    def _resolve_internal_code(self, x: float, y: float) -> str | None:
        matches = [region for region in self._frame_regions if self._contains(region.bbox, x, y)]
        if not matches:
            return None
        matches.sort(key=lambda region: region.area)
        return matches[0].internal_code

    def _resolve_field_context(self, x: float, y: float) -> str | None:
        matches = [region for region in self._field_regions if self._contains(region.bbox, x, y)]
        if not matches:
            return None
        matches.sort(key=lambda region: (region.bbox.width * region.bbox.height))
        return matches[0].field_context

    def _build_frame_regions(self, frames: list[FrameMeta], sheet_sets: list[SheetSet]) -> list[_FrameRegion]:
        regions: list[_FrameRegion] = []
        for frame in frames:
            regions.append(
                _FrameRegion(
                    bbox=frame.runtime.outer_bbox,
                    internal_code=frame.titleblock.internal_code,
                    area=frame.runtime.outer_bbox.width * frame.runtime.outer_bbox.height,
                )
            )
        for sheet_set in sheet_sets:
            inherited = sheet_set.get_inherited_titleblock()
            internal_code = inherited.get("internal_code")
            for page in sheet_set.pages:
                regions.append(
                    _FrameRegion(
                        bbox=page.outer_bbox,
                        internal_code=internal_code,
                        area=page.outer_bbox.width * page.outer_bbox.height,
                    )
                )
        return regions

    def _build_field_regions(self, frames: list[FrameMeta]) -> list[_FieldRegion]:
        field_defs = self.spec.get_field_definitions()
        fields = {
            "engineering_no": "titleblock_engineering_no",
            "internal_code": "titleblock_internal_code",
            "external_code": "titleblock_external_code",
        }
        regions: list[_FieldRegion] = []
        for frame in frames:
            profile = self.spec.get_roi_profile(frame.runtime.roi_profile_id or "BASE10")
            if profile is None:
                continue
            sx = frame.runtime.sx or 1.0
            sy = frame.runtime.sy or 1.0
            for field_name, context_name in fields.items():
                field_def = field_defs.get(field_name)
                if field_def is None:
                    continue
                rb_offset = profile.fields.get(field_def.roi)
                if not rb_offset:
                    continue
                bbox = self._restore_roi(frame.runtime.outer_bbox, rb_offset, sx, sy)
                bbox = self._expand_roi(bbox, self._roi_margin_percent)
                regions.append(
                    _FieldRegion(
                        bbox=bbox,
                        field_context=context_name,
                        internal_code=frame.titleblock.internal_code,
                    )
                )
        return regions

    @staticmethod
    def _restore_roi(outer_bbox: BBox, rb_offset: list[float], sx: float, sy: float) -> BBox:
        dx_right, dx_left, dy_bottom, dy_top = rb_offset
        return BBox(
            xmin=outer_bbox.xmax - dx_left * sx,
            xmax=outer_bbox.xmax - dx_right * sx,
            ymin=outer_bbox.ymin + dy_bottom * sy,
            ymax=outer_bbox.ymin + dy_top * sy,
        )

    @staticmethod
    def _expand_roi(bbox: BBox, margin_percent: float) -> BBox:
        dx = bbox.width * margin_percent
        dy = bbox.height * margin_percent
        return BBox(
            xmin=bbox.xmin - dx,
            ymin=bbox.ymin - dy,
            xmax=bbox.xmax + dx,
            ymax=bbox.ymax + dy,
        )

    @staticmethod
    def _contains(bbox: BBox, x: float, y: float) -> bool:
        return bbox.xmin <= x <= bbox.xmax and bbox.ymin <= y <= bbox.ymax
