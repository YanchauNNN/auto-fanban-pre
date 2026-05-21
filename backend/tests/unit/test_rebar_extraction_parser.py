from __future__ import annotations

from src.rebar_extraction.models import CircleFeature, LineFeature, Point2D, TextFeature
from src.rebar_extraction.parser import (
    associate_rebar_marks,
    is_rebar_mark_text,
    parse_rebar_text,
)


def test_rebar_mark_accepts_three_digits_or_three_digits_letter() -> None:
    assert is_rebar_mark_text("105") is True
    assert is_rebar_mark_text("301a") is True
    assert is_rebar_mark_text("301A") is True
    assert is_rebar_mark_text("11") is False
    assert is_rebar_mark_text("301AB") is False
    assert is_rebar_mark_text("ABC") is False


def test_parse_standard_rebar_spacing_text_with_garbled_grade_symbol() -> None:
    parsed = parse_rebar_text("8\x8520@200")

    assert parsed.quantity == 8
    assert parsed.grade_symbol_raw == "\x85"
    assert parsed.grade_symbol_normalized == "REBAR_GRADE"
    assert parsed.diameter == 20
    assert parsed.spacing == 200


def test_parse_standard_rebar_spacing_text_with_private_use_grade_symbol() -> None:
    parsed = parse_rebar_text("16\ue53340@200")

    assert parsed.quantity == 16
    assert parsed.grade_symbol_raw == "\ue533"
    assert parsed.grade_symbol_normalized == "REBAR_GRADE"
    assert parsed.diameter == 40
    assert parsed.spacing == 200


def test_parse_formula_rebar_text() -> None:
    parsed = parse_rebar_text("304X2=608\x8536 B1 B3")

    assert parsed.quantity == 608
    assert parsed.formula_text == "304X2=608"
    assert parsed.grade_symbol_raw == "\x85"
    assert parsed.grade_symbol_normalized == "REBAR_GRADE"
    assert parsed.diameter == 36
    assert parsed.note_text == "B1 B3"


def test_parse_radius_spacing_description_text() -> None:
    parsed = parse_rebar_text("半径R=5800处间距为250mm")

    assert parsed.radius == 5800
    assert parsed.spacing == 250
    assert parsed.note_text == "半径R=5800处间距为250mm"


def test_associate_horizontal_line_collects_upper_and_lower_texts() -> None:
    circles = [CircleFeature(handle="C1", center=Point2D(100, 100), radius=20)]
    lines = [LineFeature(handle="L1", start=Point2D(50, 100), end=Point2D(250, 100))]
    texts = [
        TextFeature(handle="T_MARK", raw_text="105", position=Point2D(100, 100)),
        TextFeature(handle="T_UP", raw_text="8\x8520@200", position=Point2D(150, 122)),
        TextFeature(handle="T_LOW", raw_text="半径R=5800处间距为250mm", position=Point2D(145, 78)),
    ]

    rows, debug = associate_rebar_marks(
        source_filename="新块.dwg",
        internal_code="TEST-002",
        layout_name="Model",
        circles=circles,
        lines=lines,
        texts=texts,
    )

    assert len(rows) == 1
    assert rows[0].bar_no == "105"
    assert rows[0].quantity == 8
    assert rows[0].diameter == 20
    assert rows[0].spacing == 200
    assert rows[0].radius == 5800
    assert rows[0].input_kind == "horizontal"
    assert rows[0].confidence == "high"
    assert rows[0].line_handle == "L1"
    assert set(rows[0].text_handles.split(";")) == {"T_UP", "T_LOW"}
    assert debug["mark_count"] == 1


def test_associate_slanted_line_uses_line_local_coordinates() -> None:
    circles = [CircleFeature(handle="C1", center=Point2D(100, 100), radius=15)]
    lines = [LineFeature(handle="L1", start=Point2D(50, 80), end=Point2D(250, 160))]
    texts = [
        TextFeature(handle="T_MARK", raw_text="301a", position=Point2D(100, 100)),
        TextFeature(handle="T_INFO", raw_text="8Φ20@200", position=Point2D(150, 150)),
    ]

    rows, _ = associate_rebar_marks(
        source_filename="新块.dwg",
        internal_code="TEST-004",
        layout_name="Model",
        circles=circles,
        lines=lines,
        texts=texts,
    )

    assert len(rows) == 1
    assert rows[0].bar_no == "301a"
    assert rows[0].quantity == 8
    assert rows[0].diameter == 20
    assert rows[0].spacing == 200
    assert rows[0].input_kind == "slanted"
    assert rows[0].confidence == "high"
