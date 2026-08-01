from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config.mechanism_spec import MechanismSpecLoader
from src.config.runtime_config import (
    CalculationBookAiNormalizationRuntimeConfig,
    RuntimeConfig,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_calculation_book_runtime_assets_come_from_runtime_yaml() -> None:
    config = RuntimeConfig.from_yaml(REPO_ROOT / "documents" / "参数规范_运行期.yaml")

    assert config.calculation_book.template_dir == (
        REPO_ROOT / "documents_bin" / "calculation_book"
    ).resolve()
    assert config.calculation_book.rebar_table.name == "钢筋的公称直径、公称面积表.xlsx"
    assert config.calculation_book.max_archive_mb == 1024
    assert config.calculation_book.max_archive_files == 500
    assert config.calculation_book.max_compression_ratio == 250.0
    assert config.calculation_book.ai_normalization.enabled is True
    assert config.calculation_book.ai_normalization.skill_root == (
        REPO_ROOT / "tools" / "ai" / "reinforcement-table-normalizer"
    ).resolve()
    assert config.calculation_book.ai_normalization.max_non_empty_cells == 10_000
    assert config.calculation_book.ai_normalization.max_snapshot_chars == 500_000
    assert config.calculation_book.ai_normalization.max_skill_chars == 100_000
    assert config.calculation_book.ai_normalization.request_timeout_seconds == 120
    assert config.calculation_book.ai_normalization.max_output_tokens == 32_768
    assert config.calculation_book.ai_normalization.temperature == 0
    assert config.calculation_book.ai_normalization.max_retries == 0


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("max_non_empty_cells", 0),
        ("max_snapshot_chars", 0),
        ("max_skill_chars", 0),
        ("request_timeout_seconds", 0),
        ("max_output_tokens", 0),
        ("max_retries", -1),
        ("temperature", -0.01),
        ("temperature", 2.01),
    ],
)
def test_calculation_book_ai_normalization_rejects_unsafe_limits(
    field_name: str,
    invalid_value: int | float,
) -> None:
    with pytest.raises(ValidationError):
        CalculationBookAiNormalizationRuntimeConfig(
            **{field_name: invalid_value}
        )


def test_calculation_book_ai_normalization_rejects_invalid_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "FANBAN_CALCULATION_BOOK__AI_NORMALIZATION__REQUEST_TIMEOUT_SECONDS",
        "0",
    )

    try:
        with pytest.raises(ValidationError):
            RuntimeConfig.from_yaml(REPO_ROOT / "documents" / "参数规范_运行期.yaml")
    finally:
        monkeypatch.delenv(
            "FANBAN_CALCULATION_BOOK__AI_NORMALIZATION__REQUEST_TIMEOUT_SECONDS"
        )


def test_calculation_book_ai_normalization_accepts_valid_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "FANBAN_CALCULATION_BOOK__AI_NORMALIZATION__REQUEST_TIMEOUT_SECONDS",
        "45",
    )

    config = RuntimeConfig.from_yaml(REPO_ROOT / "documents" / "参数规范_运行期.yaml")

    assert config.calculation_book.ai_normalization.request_timeout_seconds == 45


def test_calculation_book_ocr_settings_come_from_mechanism_yaml() -> None:
    spec = MechanismSpecLoader.load(REPO_ROOT / "documents" / "参数规范-3.yaml")

    assert spec.calculation_book.ocr_threshold == 160
    assert spec.calculation_book.ocr_legend_value_count == 10
    assert spec.calculation_book.ocr_min_confidence == 50.0
    assert spec.calculation_book.ocr_endpoint_relative_tolerance == 0.002
    assert spec.calculation_book.ocr_legend_crop == [0.06, 0.84, 0.88, 1.0]


def test_calculation_book_runtime_paths_resolve_in_terminal_package_layout(
    tmp_path: Path,
) -> None:
    deploy_root = tmp_path / "FanBanServer"
    runtime_spec = deploy_root / "documents" / "参数规范_运行期.yaml"
    runtime_spec.parent.mkdir(parents=True)
    runtime_spec.write_text(
        """
runtime_options:
  calculation_book:
    template_dir: { type: str, default: "documents_bin/calculation_book" }
    rebar_table: { type: str, default: "documents_bin/calculation_book/rebar.xlsx" }
    tesseract_exe: { type: str, default: "documents_bin/calculation_book/Tesseract-OCR/tesseract.exe" }
    tessdata_dir: { type: str, default: "documents_bin/calculation_book/Tesseract-OCR/tessdata" }
""".strip(),
        encoding="utf-8",
    )

    config = RuntimeConfig.from_yaml(runtime_spec)

    assert config.calculation_book.template_dir == (
        deploy_root / "documents_bin" / "calculation_book"
    ).resolve()
    assert config.calculation_book.tesseract_exe == (
        deploy_root
        / "documents_bin"
        / "calculation_book"
        / "Tesseract-OCR"
        / "tesseract.exe"
    ).resolve()
