from __future__ import annotations

from pathlib import Path

from src.config.mechanism_spec import MechanismSpecLoader
from src.config.runtime_config import RuntimeConfig


REPO_ROOT = Path(__file__).resolve().parents[4]


def test_calculation_book_runtime_assets_come_from_runtime_yaml() -> None:
    config = RuntimeConfig.from_yaml(REPO_ROOT / "documents" / "参数规范_运行期.yaml")

    assert config.calculation_book.template_dir == (
        REPO_ROOT / "documents_bin" / "calculation_book"
    ).resolve()
    assert config.calculation_book.rebar_table.name == "钢筋的公称直径、公称面积表.xlsx"
    assert config.calculation_book.max_archive_mb == 500
    assert config.calculation_book.max_archive_files == 500


def test_calculation_book_formula_and_ocr_settings_come_from_mechanism_yaml() -> None:
    spec = MechanismSpecLoader.load(REPO_ROOT / "documents" / "参数规范-3.yaml")

    assert spec.calculation_book.extra_ratio == 0.2
    assert spec.calculation_book.row_counts == [1, 2]
    assert spec.calculation_book.spacings == [200, 250]
    assert spec.calculation_book.max_diameter == 40
    assert spec.calculation_book.ocr_threshold == 160


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
    tesseract_exe: { type: str, default: "backend/jisuanshu/Tesseract-OCR/tesseract.exe" }
    tessdata_dir: { type: str, default: "backend/jisuanshu/Tesseract-OCR/tessdata" }
""".strip(),
        encoding="utf-8",
    )

    config = RuntimeConfig.from_yaml(runtime_spec)

    assert config.calculation_book.template_dir == (
        deploy_root / "documents_bin" / "calculation_book"
    ).resolve()
    assert config.calculation_book.tesseract_exe == (
        deploy_root / "backend" / "jisuanshu" / "Tesseract-OCR" / "tesseract.exe"
    ).resolve()
