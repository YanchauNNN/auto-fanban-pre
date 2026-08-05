from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

from src.calculation_book.ocr import (
    OcrRecognitionError,
    StressLegendReading,
    parse_legend_data,
    parse_sm_text,
    parse_stress_header,
    recognize_stress_legend,
)


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
        recognize_stress_legend(
            image_path,
            direction="X",
            text_runner=failed_runner,
        )


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

    def legend_runner(_image: Image.Image, _config: str) -> dict[str, list[object]]:
        assert os.environ["TESSDATA_PREFIX"] == str(tessdata_dir)
        return _legend_data((0, 100, 200, 300, 400, 500, 600, 700, 750, 800))

    result = recognize_stress_legend(
        image_path,
        direction="X",
        text_runner=assert_environment,
        data_runner=legend_runner,
        tessdata_dir=tessdata_dir,
    )

    assert result.smx == 800
    assert os.environ["TESSDATA_PREFIX"] == "previous-value"


def _legend_data(
    values: tuple[int, ...],
    *,
    confidences: tuple[float, ...] | None = None,
    top: int = 200,
) -> dict[str, list[object]]:
    active_confidences = confidences or tuple(96.0 for _value in values)
    return {
        "text": [str(value) for value in values],
        "conf": list(active_confidences),
        "left": [index * 100 for index in range(len(values))],
        "width": [30 for _value in values],
        "top": [top for _value in values],
        "height": [30 for _value in values],
    }


def test_parses_stress_header_with_smn_and_smx() -> None:
    assert parse_stress_header("SMN =912\nSMX =6953") == {
        "SMN": 912.0,
        "SMX": 6953.0,
    }


def test_parses_ten_legend_values_by_horizontal_position() -> None:
    data = _legend_data((0, 260, 521, 781, 1042, 130, 391, 651, 912, 1172))
    data["left"] = [0, 200, 400, 600, 800, 100, 300, 500, 700, 900]

    values = parse_legend_data(data, image_height=400)

    assert values == (0.0, 130.0, 260.0, 391.0, 521.0, 651.0, 781.0, 912.0, 1042.0, 1172.0)


def test_accepts_non_decreasing_legend_values_after_integer_rounding() -> None:
    values = parse_legend_data(
        _legend_data((0, 1, 2, 2, 3, 4, 5, 5, 6, 7)),
        image_height=400,
    )

    assert values == (0.0, 1.0, 2.0, 2.0, 3.0, 4.0, 5.0, 5.0, 6.0, 7.0)


def test_ignores_low_confidence_false_numeric_token() -> None:
    data = _legend_data(
        (0, 130, 260, 391, 521, 8, 651, 781, 912, 1042, 1172),
        confidences=(96, 96, 96, 96, 96, 0, 96, 96, 96, 96, 96),
    )

    values = parse_legend_data(data, image_height=400)

    assert values == (0.0, 130.0, 260.0, 391.0, 521.0, 651.0, 781.0, 912.0, 1042.0, 1172.0)


def test_z_figure_without_smx_is_an_explicit_zero_result(tmp_path: Path) -> None:
    image_path = tmp_path / "N5012-Z.png"
    Image.new("RGB", (1200, 800), "white").save(image_path)

    result = recognize_stress_legend(
        image_path,
        direction="Z",
        text_runner=lambda _image, _config: "EPJZ ABS (NOAVG)\nDMX=0",
        data_runner=lambda _image, _config: _legend_data(()),
    )

    assert result == StressLegendReading(
        smn=0.0,
        smx=0.0,
        legend_values=(),
        is_zero_result=True,
    )


def test_z_figure_without_smx_ignores_any_accidentally_read_legend_values(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "N5012-Z.png"
    Image.new("RGB", (1200, 800), "white").save(image_path)

    result = recognize_stress_legend(
        image_path,
        direction="Z",
        text_runner=lambda _image, _config: "EPJZ ABS (NOAVG)\nDMX=0",
        data_runner=lambda _image, _config: _legend_data(tuple(range(10))),
    )

    assert result == StressLegendReading(
        smn=0.0,
        smx=0.0,
        legend_values=(),
        is_zero_result=True,
    )


def test_x_or_y_figure_without_smx_remains_an_ocr_error(tmp_path: Path) -> None:
    image_path = tmp_path / "N5012-Y.png"
    Image.new("RGB", (1200, 800), "white").save(image_path)

    with pytest.raises(OcrRecognitionError, match="SMX"):
        recognize_stress_legend(
            image_path,
            direction="Y",
            text_runner=lambda _image, _config: "EPJY ABS (AVG)\nDMX=0",
            data_runner=lambda _image, _config: _legend_data(()),
        )


def test_rejects_legend_when_endpoint_does_not_match_smx(tmp_path: Path) -> None:
    image_path = tmp_path / "N5007-Y.png"
    Image.new("RGB", (1200, 800), "white").save(image_path)

    with pytest.raises(OcrRecognitionError, match="SMX"):
        recognize_stress_legend(
            image_path,
            direction="Y",
            text_runner=lambda _image, _config: "SMN=912\nSMX=6953",
            data_runner=lambda _image, _config: _legend_data(
                (912, 1583, 2254, 2925, 3597, 4268, 4939, 5610, 6281, 6900)
            ),
        )
