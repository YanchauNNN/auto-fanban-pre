from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Point2D:
    x: float
    y: float


@dataclass(frozen=True)
class CircleFeature:
    handle: str
    center: Point2D
    radius: float
    layout_name: str = "Model"
    block_path: str = ""


@dataclass(frozen=True)
class LineFeature:
    handle: str
    start: Point2D
    end: Point2D
    layout_name: str = "Model"
    block_path: str = ""


@dataclass(frozen=True)
class TextFeature:
    handle: str
    raw_text: str
    position: Point2D
    entity_type: str = "DBText"
    layout_name: str = "Model"
    bbox: dict[str, float] | None = None
    block_path: str = ""
    text_style: str = ""
    font: str = ""
    bigfont: str = ""
    codepoints: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedRebarText:
    quantity: int | None = None
    grade_symbol_raw: str = ""
    grade_symbol_normalized: str = ""
    diameter: int | None = None
    spacing: int | None = None
    radius: int | None = None
    formula_text: str = ""
    note_text: str = ""
    parsed: bool = False


@dataclass(frozen=True)
class RebarRow:
    source_filename: str
    internal_code: str
    layout_name: str
    bar_no: str
    quantity: int | None
    grade_symbol_raw: str
    grade_symbol_normalized: str
    diameter: int | None
    spacing: int | None
    radius: int | None
    formula_text: str
    note_text: str
    input_kind: str
    confidence: str
    circle_handle: str
    line_handle: str
    text_handles: str
    position_x: float
    position_y: float
