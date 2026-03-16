"""
Frame-related runtime and titleblock models.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, Field


class BBox(BaseModel):
    """Axis-aligned bounding box."""

    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @property
    def width(self) -> float:
        return self.xmax - self.xmin

    @property
    def height(self) -> float:
        return self.ymax - self.ymin

    def intersects(self, other: BBox) -> bool:
        return not (
            self.xmax < other.xmin
            or self.xmin > other.xmax
            or self.ymax < other.ymin
            or self.ymin > other.ymax
        )


class TitleblockFields(BaseModel):
    """Titleblock fields extracted from DXF ROI regions."""

    internal_code: Annotated[str | None, Field(description="Internal code")] = None
    external_code: Annotated[str | None, Field(description="External code")] = None
    album_code: Annotated[str | None, Field(description="Album code")] = None
    engineering_no: Annotated[str | None, Field(description="Engineering number")] = None
    subitem_no: Annotated[str | None, Field(description="Subitem number")] = None
    paper_size_text: Annotated[str | None, Field(description="Paper size text")] = None
    discipline: Annotated[str | None, Field(description="Discipline")] = None
    scale_text: Annotated[str | None, Field(description="Scale text")] = None
    scale_denominator: Annotated[float | None, Field(description="Scale denominator")] = None
    page_total: Annotated[int | None, Field(description="Total pages")] = None
    page_index: Annotated[int | None, Field(description="Page index")] = None
    title_cn: Annotated[str | None, Field(description="Chinese title")] = None
    title_en: Annotated[str | None, Field(description="English title")] = None
    revision: Annotated[str | None, Field(description="Revision")] = None
    status: Annotated[str | None, Field(description="Status")] = None
    date: Annotated[str | None, Field(description="Date")] = None

    def get_seq_no(self) -> int | None:
        if self.internal_code and "-" in self.internal_code:
            suffix = self.internal_code.rsplit("-", 1)[-1]
            if suffix.isdigit():
                return int(suffix)
        return None


class FrameRuntime(BaseModel):
    """Per-frame runtime data generated during DXF processing."""

    frame_id: str = Field(..., description="Unique frame instance id")
    source_file: Path = Field(..., description="DXF source path")
    cad_source_file: Annotated[Path | None, Field(description="Preferred CAD source path")] = None
    outer_bbox: BBox = Field(..., description="Outer frame bbox")
    outer_vertices: list[tuple[float, float]] = Field(default_factory=list)

    paper_variant_id: Annotated[str | None, Field(description="Matched paper id")] = None
    sx: Annotated[float | None, Field(description="X scale factor")] = None
    sy: Annotated[float | None, Field(description="Y scale factor")] = None
    geom_scale_factor: Annotated[float | None, Field(description="Geometry scale factor")] = None
    roi_profile_id: Annotated[str | None, Field(description="ROI profile id")] = None

    scale_mismatch: bool = False
    flags: list[str] = Field(default_factory=list)

    pdf_path: Path | None = None
    dwg_path: Path | None = None

    model_config = {"arbitrary_types_allowed": True}


class FrameMeta(BaseModel):
    """Complete frame metadata combining runtime info and titleblock fields."""

    runtime: FrameRuntime
    titleblock: TitleblockFields = Field(default_factory=lambda: TitleblockFields())
    raw_extracts: dict[str, Any] = Field(default_factory=dict)

    @property
    def frame_id(self) -> str:
        return self.runtime.frame_id

    @property
    def internal_code(self) -> str | None:
        return self.titleblock.internal_code

    def add_flag(self, flag: str) -> None:
        if flag not in self.runtime.flags:
            self.runtime.flags.append(flag)
