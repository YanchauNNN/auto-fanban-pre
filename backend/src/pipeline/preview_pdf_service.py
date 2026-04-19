from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import fitz
from pypdf import PdfReader, PdfWriter

from ..audit_check.models import AuditFinding
from ..config import load_spec
from ..models import BBox, FrameMeta, SheetSet
from ..result_views import _sorted_frames, _sorted_sheet_sets

PreviewMode = Literal["plain", "annotated"]

_FIELD_CONTEXT_TO_FIELD_NAME = {
    "titleblock_engineering_no": "engineering_no",
    "titleblock_internal_code": "internal_code",
    "titleblock_external_code": "external_code",
}


@dataclass(frozen=True, slots=True)
class PreviewPdfBuildResult:
    pdf_path: Path
    mode: PreviewMode
    page_count: int
    annotation_count: int = 0


@dataclass(frozen=True, slots=True)
class _PreviewPageRegion:
    preview_page_index: int
    bbox: BBox
    internal_code: str | None
    frame: FrameMeta | None = None


class PreviewPdfService:
    def __init__(self) -> None:
        self.spec = load_spec()

    def build_preview(
        self,
        *,
        job_id: str,
        output_dir: Path,
        frames: list[FrameMeta],
        sheet_sets: list[SheetSet],
        findings: Sequence[AuditFinding] | None = None,
    ) -> PreviewPdfBuildResult:
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        merged_pdf = output_dir / f"{job_id}-preview.pdf"
        page_regions = self._merge_outputs(
            merged_pdf=merged_pdf,
            frames=frames,
            sheet_sets=sheet_sets,
        )
        if not findings:
            return PreviewPdfBuildResult(
                pdf_path=merged_pdf,
                mode="plain",
                page_count=len(page_regions),
            )

        annotated_pdf = output_dir / f"{job_id}-preview-annotated.pdf"
        annotation_count = self._annotate_preview(
            source_pdf=merged_pdf,
            output_pdf=annotated_pdf,
            page_regions=page_regions,
            findings=findings,
        )
        if annotation_count <= 0:
            return PreviewPdfBuildResult(
                pdf_path=merged_pdf,
                mode="plain",
                page_count=len(page_regions),
            )
        return PreviewPdfBuildResult(
            pdf_path=annotated_pdf,
            mode="annotated",
            page_count=len(page_regions),
            annotation_count=annotation_count,
        )

    def _merge_outputs(
        self,
        *,
        merged_pdf: Path,
        frames: list[FrameMeta],
        sheet_sets: list[SheetSet],
    ) -> list[_PreviewPageRegion]:
        writer = PdfWriter()
        page_regions: list[_PreviewPageRegion] = []

        for frame in _sorted_frames(frames):
            pdf_path = frame.runtime.pdf_path
            if pdf_path is None or not pdf_path.exists():
                continue
            reader = PdfReader(str(pdf_path))
            for page in reader.pages:
                writer.add_page(page)
                page_regions.append(
                    _PreviewPageRegion(
                        preview_page_index=len(page_regions),
                        bbox=frame.runtime.outer_bbox,
                        internal_code=frame.titleblock.internal_code,
                        frame=frame,
                    )
                )

        for sheet_set in _sorted_sheet_sets(sheet_sets):
            pdf_path = sheet_set.pdf_path
            if pdf_path is None or not pdf_path.exists():
                continue
            reader = PdfReader(str(pdf_path))
            inherited = sheet_set.get_inherited_titleblock()
            for page_index, page in enumerate(reader.pages):
                writer.add_page(page)
                page_bbox = self._sheet_page_bbox(sheet_set, page_index)
                page_frame = self._sheet_page_frame(sheet_set, page_index)
                page_regions.append(
                    _PreviewPageRegion(
                        preview_page_index=len(page_regions),
                        bbox=page_bbox,
                        internal_code=str(inherited.get("internal_code") or "") or None,
                        frame=page_frame,
                    )
                )

        if not page_regions:
            raise ValueError("no exported drawing pdfs available for preview")

        with merged_pdf.open("wb") as handle:
            writer.write(handle)
        return page_regions

    def _annotate_preview(
        self,
        *,
        source_pdf: Path,
        output_pdf: Path,
        page_regions: list[_PreviewPageRegion],
        findings: Sequence[AuditFinding],
    ) -> int:
        doc = fitz.open(source_pdf)
        annotation_count = 0
        try:
            for finding in findings:
                target = self._resolve_target_page(page_regions, finding)
                if target is None:
                    continue
                rect = self._resolve_annotation_rect(doc[target.preview_page_index], target, finding)
                if rect is None:
                    continue
                doc[target.preview_page_index].draw_rect(
                    rect,
                    color=(1, 0, 0),
                    width=1.25,
                    overlay=True,
                )
                annotation_count += 1
            if annotation_count > 0:
                doc.save(output_pdf)
        finally:
            doc.close()
        return annotation_count

    @staticmethod
    def _sheet_page_bbox(sheet_set: SheetSet, page_index: int) -> BBox:
        if 0 <= page_index < len(sheet_set.pages):
            return sheet_set.pages[page_index].outer_bbox
        if sheet_set.pages:
            return sheet_set.pages[-1].outer_bbox
        if sheet_set.master_page is not None:
            return sheet_set.master_page.outer_bbox
        raise ValueError("sheet set has no page bbox for preview mapping")

    @staticmethod
    def _sheet_page_frame(sheet_set: SheetSet, page_index: int) -> FrameMeta | None:
        if 0 <= page_index < len(sheet_set.pages):
            return sheet_set.pages[page_index].frame_meta
        if sheet_set.master_page is not None:
            return sheet_set.master_page.frame_meta
        return None

    def _resolve_target_page(
        self,
        page_regions: list[_PreviewPageRegion],
        finding: AuditFinding,
    ) -> _PreviewPageRegion | None:
        if finding.position_x is None or finding.position_y is None:
            return None

        exact_matches = [
            region
            for region in page_regions
            if self._contains(region.bbox, finding.position_x, finding.position_y)
            and (
                not finding.internal_code
                or not region.internal_code
                or region.internal_code == finding.internal_code
            )
        ]
        if exact_matches:
            exact_matches.sort(key=lambda item: item.preview_page_index)
            return exact_matches[0]

        if finding.internal_code:
            code_matches = [
                region for region in page_regions if region.internal_code == finding.internal_code
            ]
            if code_matches:
                code_matches.sort(key=lambda item: item.preview_page_index)
                return code_matches[0]
        return None

    def _resolve_annotation_rect(
        self,
        page: fitz.Page,
        page_region: _PreviewPageRegion,
        finding: AuditFinding,
    ) -> fitz.Rect | None:
        roi_bbox = self._resolve_field_roi_bbox(page_region.frame, finding.field_context)
        if roi_bbox is not None:
            rect = self._bbox_to_page_rect(page.rect, page_region.bbox, roi_bbox)
            return self._pad_rect(rect, 4.0)

        if finding.position_x is None or finding.position_y is None:
            return None
        fallback_bbox = self._fallback_bbox(page_region.bbox, finding.position_x, finding.position_y)
        rect = self._bbox_to_page_rect(page.rect, page_region.bbox, fallback_bbox)
        return self._pad_rect(rect, 3.0)

    def _resolve_field_roi_bbox(
        self,
        frame: FrameMeta | None,
        field_context: str | None,
    ) -> BBox | None:
        if frame is None or not field_context:
            return None
        field_name = _FIELD_CONTEXT_TO_FIELD_NAME.get(field_context)
        if not field_name:
            return None
        field_defs = self.spec.get_field_definitions()
        field_def = field_defs.get(field_name)
        if field_def is None:
            return None
        profile = self.spec.get_roi_profile(frame.runtime.roi_profile_id or "BASE10")
        if profile is None:
            return None
        rb_offset = profile.fields.get(field_def.roi)
        if not rb_offset:
            return None
        sx = frame.runtime.sx or 1.0
        sy = frame.runtime.sy or 1.0
        return self._restore_roi(frame.runtime.outer_bbox, rb_offset, sx, sy)

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
    def _fallback_bbox(page_bbox: BBox, x: float, y: float) -> BBox:
        dx = max(page_bbox.width * 0.03, 20.0)
        dy = max(page_bbox.height * 0.03, 20.0)
        return BBox(
            xmin=x - dx,
            xmax=x + dx,
            ymin=y - dy,
            ymax=y + dy,
        )

    @staticmethod
    def _bbox_to_page_rect(page_rect: fitz.Rect, frame_bbox: BBox, bbox: BBox) -> fitz.Rect | None:
        if frame_bbox.width <= 0 or frame_bbox.height <= 0:
            return None

        def map_x(value: float) -> float:
            return page_rect.x0 + ((value - frame_bbox.xmin) / frame_bbox.width) * page_rect.width

        def map_y(value: float) -> float:
            return page_rect.y0 + ((frame_bbox.ymax - value) / frame_bbox.height) * page_rect.height

        left = map_x(bbox.xmin)
        right = map_x(bbox.xmax)
        top = map_y(bbox.ymax)
        bottom = map_y(bbox.ymin)
        rect = fitz.Rect(min(left, right), min(top, bottom), max(left, right), max(top, bottom))
        if rect.is_empty or rect.width <= 0 or rect.height <= 0:
            return None
        return rect

    @staticmethod
    def _pad_rect(rect: fitz.Rect | None, padding: float) -> fitz.Rect | None:
        if rect is None:
            return None
        padded = fitz.Rect(rect.x0 - padding, rect.y0 - padding, rect.x1 + padding, rect.y1 + padding)
        if padded.is_empty or padded.width <= 0 or padded.height <= 0:
            return None
        return padded

    @staticmethod
    def _contains(bbox: BBox, x: float, y: float) -> bool:
        return bbox.xmin <= x <= bbox.xmax and bbox.ymin <= y <= bbox.ymax
