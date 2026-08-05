from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from src.config import mechanism_spec, runtime_config
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
    assert config.calculation_book.standard_reinforcement_template == (
        REPO_ROOT
        / "documents_bin"
        / "calculation_book"
        / "计算书模板文件.xlsx"
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
    assert config.calculation_book.ai_normalization.request_timeout_seconds == 600
    assert config.calculation_book.ai_normalization.max_output_tokens == 65_536
    assert config.calculation_book.ai_normalization.temperature == 0
    assert config.calculation_book.ai_normalization.max_retries == 0
    suggestion = config.calculation_book.ai_suggestion
    assert suggestion.enabled is True
    assert suggestion.skill_root == (
        REPO_ROOT / "tools" / "ai" / "recommend-rebar-from-smx"
    ).resolve()
    assert suggestion.skill_version == "1.0.0"
    assert suggestion.batch_size == 20
    assert suggestion.request_timeout_seconds == 600
    assert suggestion.max_output_tokens == 65_536
    assert suggestion.temperature == 0
    assert suggestion.max_skill_bytes == 131_072
    assert suggestion.max_reference_files == 8
    assert suggestion.max_request_bytes == 1_048_576
    assert suggestion.max_response_bytes == 1_048_576
    assert suggestion.max_identifier_chars == 200
    assert suggestion.max_consecutive_base_failures == 3
    assert suggestion.log_dir == (
        REPO_ROOT / "storage" / "logs" / "calculation-book-ai-suggestion"
    ).resolve()
    assert suggestion.log_max_bytes == 10_485_760
    assert suggestion.log_retention_days == 30


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


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("batch_size", 0),
        ("request_timeout_seconds", 0),
        ("max_output_tokens", 0),
        ("max_skill_bytes", 0),
        ("max_reference_files", 0),
        ("max_request_bytes", 0),
        ("max_response_bytes", 0),
        ("max_identifier_chars", 0),
        ("max_consecutive_base_failures", 0),
        ("log_max_bytes", 0),
        ("log_retention_days", 0),
        ("temperature", -0.01),
        ("temperature", 2.01),
    ],
)
def test_calculation_book_ai_suggestion_rejects_unsafe_limits(
    field_name: str,
    invalid_value: int | float,
) -> None:
    with pytest.raises(ValidationError):
        runtime_config.CalculationBookAiSuggestionRuntimeConfig(
            **{field_name: invalid_value}
        )


def test_calculation_book_ai_suggestion_paths_resolve_in_terminal_package_layout(
    tmp_path: Path,
) -> None:
    deploy_root = tmp_path / "FanBanServer"
    runtime_spec = deploy_root / "documents" / "参数规范_运行期.yaml"
    runtime_spec.parent.mkdir(parents=True)
    runtime_spec.write_text(
        """
runtime_options:
  calculation_book:
    ai_suggestion:
      skill_root: { type: str, default: "tools/ai/recommend-rebar-from-smx" }
      log_dir: { type: str, default: "storage/logs/calculation-book-ai-suggestion" }
""".strip(),
        encoding="utf-8",
    )

    config = RuntimeConfig.from_yaml(runtime_spec)

    assert config.calculation_book.ai_suggestion.skill_root == (
        deploy_root / "tools" / "ai" / "recommend-rebar-from-smx"
    ).resolve()
    assert config.calculation_book.ai_suggestion.log_dir == (
        deploy_root / "storage" / "logs" / "calculation-book-ai-suggestion"
    ).resolve()


def test_calculation_book_ocr_settings_come_from_mechanism_yaml() -> None:
    spec = MechanismSpecLoader.load(REPO_ROOT / "documents" / "参数规范-3.yaml")

    assert spec.calculation_book.ocr_threshold == 160
    assert spec.calculation_book.ocr_legend_value_count == 10
    assert spec.calculation_book.ocr_min_confidence == 50.0
    assert spec.calculation_book.ocr_endpoint_relative_tolerance == 0.002
    assert spec.calculation_book.ocr_legend_crop == [0.06, 0.84, 0.88, 1.0]


def test_calculation_book_ai_suggestion_rules_come_from_mechanism_yaml() -> None:
    spec = MechanismSpecLoader.load(REPO_ROOT / "documents" / "参数规范-3.yaml")

    suggestion = spec.calculation_book.ai_suggestion
    assert suggestion.margin_ratio == pytest.approx(0.10)
    assert suggestion.xy.diameters == [16, 18, 20, 25, 28, 32, 36, 40]
    assert suggestion.xy.hard_priority == ["1@200", "1@150", "2@200", "2@150"]
    assert suggestion.z.diameters == [6, 8, 10, 12, 14, 16]
    assert suggestion.z.hard_priority == [
        "1@400x400",
        "1@200x400",
        "1@200x200",
        "2@400x400",
        "2@200x400",
        "2@200x200",
    ]
    assert suggestion.zero_or_missing_smx.fixed_spec == "1C14@400x400"
    assert suggestion.slab_direction_mapping == {
        "top_x": "X",
        "middle_x": "X",
        "bottom_x": "X",
        "top_y": "Y",
        "middle_y": "Y",
        "bottom_y": "Y",
        "z": "Z",
    }
    assert suggestion.word_declaration == (
        "以下配筋建议由人工智能根据结果云图 SMX 值并保留不低于 10% 的面积裕度生成，"
        "供设计人员复核。"
    )


@pytest.mark.parametrize(
    ("payload", "error_field"),
    [
        ({"margin_ratio": -0.01}, "margin_ratio"),
        ({"xy": {"diameters": [0]}}, "diameters"),
        ({"z": {"diameters": []}}, "diameters"),
    ],
)
def test_calculation_book_ai_suggestion_rejects_invalid_mechanism_rules(
    payload: dict[str, object],
    error_field: str,
) -> None:
    with pytest.raises(ValidationError, match=error_field):
        mechanism_spec.CalculationBookAiSuggestionMechanismConfig(**payload)


def test_calculation_book_business_schema_exposes_reinforcement_source_enum() -> None:
    business_spec = yaml.safe_load(
        (REPO_ROOT / "documents" / "参数规范.yaml").read_text(encoding="utf-8")
    )
    fields = business_spec["calculation_book"]["fields"]

    field = next(item for item in fields if item["key"] == "reinforcement_source")

    assert field["type"] == "select"
    assert field["default"] == "provided"
    assert field["options"] == ["provided", "ai_suggested"]


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
    standard_reinforcement_template: { type: str, default: "documents_bin/calculation_book/计算书模板文件.xlsx" }
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
    assert config.calculation_book.standard_reinforcement_template == (
        deploy_root
        / "documents_bin"
        / "calculation_book"
        / "计算书模板文件.xlsx"
    ).resolve()
    assert config.calculation_book.tesseract_exe == (
        deploy_root
        / "documents_bin"
        / "calculation_book"
        / "Tesseract-OCR"
        / "tesseract.exe"
    ).resolve()
