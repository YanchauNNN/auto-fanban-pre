from __future__ import annotations

import math
import re
from collections.abc import Iterable

from .models import CircleFeature, LineFeature, ParsedRebarText, Point2D, RebarRow, TextFeature

_MARK_RE = re.compile(r"^\d{3}[A-Za-z]?$")
_CONTROL_RE = re.compile(r"\\[A-Za-z][^;]*;")
_UNICODE_ESCAPE_RE = re.compile(r"\\U\+([0-9A-Fa-f]{4})")
_DESCRIPTION_RADIUS_RE = re.compile(r"半径\s*R\s*[=＝]\s*(\d+)", re.IGNORECASE)
_DESCRIPTION_SPACING_RE = re.compile(r"间距\s*(?:为|=|＝)?\s*(\d+)\s*(?:mm)?", re.IGNORECASE)
_STANDARD_RE = re.compile(
    r"(?P<head>(?P<formula>\d+[ \t\r\n]*[Xx×][ \t\r\n]*\d+[ \t\r\n]*[=＝][ \t\r\n]*(?P<formula_quantity>\d+))|(?P<quantity>\d+))"
    r"[ \t\r\n]*(?P<grade>[^\d@ \t\r\n]+)?[ \t\r\n]*(?P<diameter>\d{1,3})"
    r"(?:[ \t\r\n]*@[ \t\r\n]*(?P<spacing>\d{1,5}))?"
)

_SYMBOL_MAP = {
    "\x85": "REBAR_GRADE",
    "%%C": "REBAR_GRADE",
    "%%c": "REBAR_GRADE",
    "Φ": "REBAR_GRADE",
    "φ": "REBAR_GRADE",
    "￠": "REBAR_GRADE",
}


def is_rebar_mark_text(value: str) -> bool:
    return _MARK_RE.fullmatch(_clean_text(value)) is not None


def parse_rebar_text(value: str) -> ParsedRebarText:
    text = _clean_text(value)
    radius = _first_int(_DESCRIPTION_RADIUS_RE.search(text))
    desc_spacing = _first_int(_DESCRIPTION_SPACING_RE.search(text))

    standard = _STANDARD_RE.search(text)
    grade_raw = standard.group("grade") if standard else ""
    if standard and not _looks_like_grade_symbol(grade_raw) and "@" not in standard.group(0):
        standard = None
    if not standard:
        return ParsedRebarText(
            spacing=desc_spacing,
            radius=radius,
            note_text=text if radius is not None or desc_spacing is not None else "",
            parsed=radius is not None or desc_spacing is not None,
        )

    formula_text = _compact_formula(standard.group("formula") or "")
    quantity_text = standard.group("formula_quantity") or standard.group("quantity")
    grade_raw = standard.group("grade") or ""
    spacing = _to_int(standard.group("spacing")) or desc_spacing
    note_text = text[standard.end() :].strip()
    if radius is not None or desc_spacing is not None:
        note_text = text

    return ParsedRebarText(
        quantity=_to_int(quantity_text),
        grade_symbol_raw=grade_raw,
        grade_symbol_normalized=normalize_grade_symbol(grade_raw),
        diameter=_to_int(standard.group("diameter")),
        spacing=spacing,
        radius=radius,
        formula_text=formula_text,
        note_text=note_text,
        parsed=True,
    )


def normalize_grade_symbol(value: str) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    if text in _SYMBOL_MAP:
        return _SYMBOL_MAP[text]
    if any(char in text for char in _SYMBOL_MAP):
        return "REBAR_GRADE"
    if any(ord(char) < 32 or 0x7F <= ord(char) <= 0x9F for char in text):
        return "REBAR_GRADE"
    if any(0xE000 <= ord(char) <= 0xF8FF for char in text):
        return "REBAR_GRADE"
    return text


def _looks_like_grade_symbol(value: str | None) -> bool:
    text = _clean_text(value or "")
    if not text:
        return False
    return normalize_grade_symbol(text) == "REBAR_GRADE"


def associate_rebar_marks(
    *,
    source_filename: str,
    internal_code: str,
    layout_name: str,
    circles: list[CircleFeature],
    lines: list[LineFeature],
    texts: list[TextFeature],
) -> tuple[list[RebarRow], dict[str, object]]:
    rows: list[RebarRow] = []
    mark_pairs = _find_circle_marks(circles, texts)
    for circle, mark_text in mark_pairs:
        best_line = _nearest_line(circle, lines)
        nearby_texts = _nearby_rebar_texts(circle, best_line, texts, exclude_handle=mark_text.handle)
        combined = _combine_parsed([parse_rebar_text(item.raw_text) for item in nearby_texts])
        input_kind = _line_kind(best_line) if best_line else "unknown"
        confidence = _confidence(best_line, combined, nearby_texts)
        rows.append(
            RebarRow(
                source_filename=source_filename,
                internal_code=internal_code,
                layout_name=layout_name,
                bar_no=_clean_text(mark_text.raw_text),
                quantity=combined.quantity,
                grade_symbol_raw=combined.grade_symbol_raw,
                grade_symbol_normalized=combined.grade_symbol_normalized,
                diameter=combined.diameter,
                spacing=combined.spacing,
                radius=combined.radius,
                formula_text=combined.formula_text,
                note_text=combined.note_text,
                input_kind=input_kind,
                confidence=confidence,
                circle_handle=circle.handle,
                line_handle=best_line.handle if best_line else "",
                text_handles=";".join(item.handle for item in nearby_texts),
                position_x=circle.center.x,
                position_y=circle.center.y,
            )
        )
    return rows, {"mark_count": len(mark_pairs), "row_count": len(rows)}


def _find_circle_marks(
    circles: Iterable[CircleFeature],
    texts: Iterable[TextFeature],
) -> list[tuple[CircleFeature, TextFeature]]:
    result: list[tuple[CircleFeature, TextFeature]] = []
    text_list = list(texts)
    for circle in circles:
        matches = [
            text
            for text in text_list
            if is_rebar_mark_text(text.raw_text)
            and _distance(circle.center, text.position) <= max(circle.radius * 0.85, 1.0)
        ]
        if not matches:
            continue
        matches.sort(key=lambda item: _distance(circle.center, item.position))
        result.append((circle, matches[0]))
    return result


def _nearest_line(circle: CircleFeature, lines: Iterable[LineFeature]) -> LineFeature | None:
    candidates: list[tuple[float, LineFeature]] = []
    for line in lines:
        length = _line_length(line)
        if length <= 0:
            continue
        dist, t = _point_line_distance_and_t(circle.center, line)
        if -0.2 <= t <= 1.2 and dist <= max(circle.radius * 1.25, 5.0):
            candidates.append((dist, line))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _nearby_rebar_texts(
    circle: CircleFeature,
    line: LineFeature | None,
    texts: Iterable[TextFeature],
    *,
    exclude_handle: str,
) -> list[TextFeature]:
    candidates: list[tuple[float, TextFeature]] = []
    for text in texts:
        if text.handle == exclude_handle or is_rebar_mark_text(text.raw_text):
            continue
        parsed = parse_rebar_text(text.raw_text)
        if not parsed.parsed:
            continue
        if line is None:
            dist = _distance(circle.center, text.position)
            if dist <= max(circle.radius * 10.0, 120.0):
                candidates.append((dist, text))
            continue
        line_dist, t = _point_line_distance_and_t(text.position, line)
        along_distance = abs(t - _point_line_distance_and_t(circle.center, line)[1]) * _line_length(line)
        if -0.25 <= t <= 1.25 and line_dist <= max(circle.radius * 4.0, 60.0):
            candidates.append((line_dist + along_distance * 0.02, text))
    candidates.sort(key=lambda item: item[0])
    return [item for _, item in candidates]


def _combine_parsed(items: list[ParsedRebarText]) -> ParsedRebarText:
    result = ParsedRebarText()
    for item in items:
        if not item.parsed:
            continue
        result = ParsedRebarText(
            quantity=result.quantity if result.quantity is not None else item.quantity,
            grade_symbol_raw=result.grade_symbol_raw or item.grade_symbol_raw,
            grade_symbol_normalized=result.grade_symbol_normalized or item.grade_symbol_normalized,
            diameter=result.diameter if result.diameter is not None else item.diameter,
            spacing=_merge_spacing(result, item),
            radius=result.radius if result.radius is not None else item.radius,
            formula_text=result.formula_text or item.formula_text,
            note_text="; ".join(part for part in [result.note_text, item.note_text] if part),
            parsed=True,
        )
    return result


def _merge_spacing(current: ParsedRebarText, incoming: ParsedRebarText) -> int | None:
    if incoming.spacing is None:
        return current.spacing
    if current.spacing is None:
        return incoming.spacing
    if current.diameter is None and incoming.diameter is not None:
        return incoming.spacing
    return current.spacing


def _confidence(line: LineFeature | None, parsed: ParsedRebarText, text_items: list[TextFeature]) -> str:
    if line and parsed.quantity is not None and parsed.diameter is not None and text_items:
        return "high"
    if text_items and parsed.parsed:
        return "medium"
    return "low"


def _line_kind(line: LineFeature | None) -> str:
    if line is None:
        return "unknown"
    dx = line.end.x - line.start.x
    dy = line.end.y - line.start.y
    if abs(dy) <= max(abs(dx) * 0.05, 1e-6):
        return "horizontal"
    return "slanted"


def _point_line_distance_and_t(point: Point2D, line: LineFeature) -> tuple[float, float]:
    dx = line.end.x - line.start.x
    dy = line.end.y - line.start.y
    length_sq = dx * dx + dy * dy
    if length_sq <= 0:
        return _distance(point, line.start), 0.0
    t = ((point.x - line.start.x) * dx + (point.y - line.start.y) * dy) / length_sq
    px = line.start.x + t * dx
    py = line.start.y + t * dy
    return math.hypot(point.x - px, point.y - py), t


def _line_length(line: LineFeature) -> float:
    return _distance(line.start, line.end)


def _distance(a: Point2D, b: Point2D) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _clean_text(value: str) -> str:
    text = str(value or "")
    steel_placeholder = "\uE000"
    text = text.replace("\x85", steel_placeholder)
    text = text.replace("\\P", " ")
    text = _UNICODE_ESCAPE_RE.sub(lambda match: chr(int(match.group(1), 16)), text)
    text = _CONTROL_RE.sub("", text)
    text = text.replace("%%C", "Φ").replace("%%c", "Φ")
    text = re.sub(r"\s+", " ", text)
    text = text.replace(steel_placeholder, "\x85")
    return text.strip(" \t\r\n")


def _compact_formula(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").replace("＝", "=").replace("×", "X"))


def _first_int(match: re.Match[str] | None) -> int | None:
    if match is None:
        return None
    return _to_int(match.group(1))


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
