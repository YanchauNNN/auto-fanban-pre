from __future__ import annotations

from pathlib import Path

from src.pipeline.project_no_inference import (
    infer_project_no_from_path,
    resolve_project_no,
)


def test_infer_project_no_from_dwg_name_prefix() -> None:
    assert infer_project_no_from_path(Path("20261RS-JGS65.dwg")) == "2026"
    assert infer_project_no_from_path("19076NH-JGS45") == "1907"


def test_infer_project_no_returns_none_when_name_has_no_four_digit_prefix() -> None:
    assert infer_project_no_from_path(Path("A20261RS-JGS65.dwg")) is None
    assert infer_project_no_from_path("JGS65-2026") is None


def test_resolve_project_no_prefers_explicit_value() -> None:
    assert resolve_project_no("2016", Path("20261RS-JGS65.dwg")) == "2016"


def test_resolve_project_no_uses_inferred_value_when_explicit_blank() -> None:
    assert resolve_project_no("", Path("20261RS-JGS65.dwg")) == "2026"


def test_resolve_project_no_falls_back_to_default_when_not_inferable() -> None:
    assert resolve_project_no("", Path("sample.dwg")) == "2016"
