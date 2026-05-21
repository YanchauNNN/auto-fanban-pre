from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .models import RebarRow

CSV_COLUMNS = [
    "source_filename",
    "internal_code",
    "layout_name",
    "bar_no",
    "quantity",
    "grade_symbol_raw",
    "grade_symbol_normalized",
    "diameter",
    "spacing",
    "radius",
    "formula_text",
    "note_text",
    "input_kind",
    "confidence",
    "circle_handle",
    "line_handle",
    "text_handles",
    "position_x",
    "position_y",
]


def write_rebar_summary_csv(rows: list[RebarRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(getattr(row, column)) for column in CSV_COLUMNS})


def write_rebar_debug_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    return value
