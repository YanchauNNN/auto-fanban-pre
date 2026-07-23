from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

from src.calculation_book.ocr import OcrRecognitionError, parse_sm_text, recognize_sm


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("SMX=1234", 1234),
        ("SMx : 987", 987),
        ("noise\nSMX- 1 234\n", 1234),
    ],
)
def test_parses_supported_sm_ocr_forms(text: str, expected: int) -> None:
    assert parse_sm_text(text) == expected


@pytest.mark.parametrize("text", ["", "SMX=", "1234", "SMX=0", "SMX=12\nSMX=13"])
def test_rejects_missing_zero_or_ambiguous_sm(text: str) -> None:
    with pytest.raises(OcrRecognitionError):
        parse_sm_text(text)


def test_recognize_sm_propagates_tesseract_failure(tmp_path: Path) -> None:
    image_path = tmp_path / "RX1-X.png"
    Image.new("RGB", (1200, 800), "white").save(image_path)

    def failed_runner(_image: Image.Image, _config: str) -> str:
        raise RuntimeError("tesseract crashed")

    with pytest.raises(OcrRecognitionError, match="tesseract crashed"):
        recognize_sm(image_path, runner=failed_runner)


def test_recognize_sm_passes_tessdata_through_environment_and_restores_it(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image_path = tmp_path / "RX1-X.png"
    tessdata_dir = tmp_path / "Tesseract OCR" / "tessdata"
    tessdata_dir.mkdir(parents=True)
    Image.new("RGB", (1200, 800), "white").save(image_path)
    monkeypatch.setenv("TESSDATA_PREFIX", "previous-value")

    def assert_environment(_image: Image.Image, config: str) -> str:
        assert os.environ["TESSDATA_PREFIX"] == str(tessdata_dir)
        assert "--tessdata-dir" not in config
        return "SMX=800"

    assert recognize_sm(
        image_path,
        runner=assert_environment,
        tessdata_dir=tessdata_dir,
    ) == 800
    assert os.environ["TESSDATA_PREFIX"] == "previous-value"
