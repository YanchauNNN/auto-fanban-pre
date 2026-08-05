from __future__ import annotations

from pathlib import Path

from src.calculation_book.models import CalculationBookTemplate
from src.calculation_book.templates import (
    TEMPLATE_FILENAMES,
    get_template_variables,
    validate_template_context,
)

ASSET_ROOT = Path(__file__).resolve().parents[4] / "documents_bin" / "calculation_book"


def test_both_external_templates_are_present_and_have_known_variables() -> None:
    for template_type, filename in TEMPLATE_FILENAMES.items():
        path = ASSET_ROOT / filename
        assert path.is_file(), template_type
        variables = get_template_variables(path)
        assert "project_number" in variables
        assert "reinforcement_figures" in variables
        assert "wall_table_rows" in variables
        assert "ai_rebar_disclosure" in variables


def test_internal_template_accepts_a_complete_context() -> None:
    path = ASSET_ROOT / TEMPLATE_FILENAMES[CalculationBookTemplate.INTERNAL_STRUCTURE]
    context = dict.fromkeys(get_template_variables(path), "test")

    validate_template_context(path, context)
