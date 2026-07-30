from __future__ import annotations

import math
import os
import re
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import pytesseract
from PIL import Image, ImageOps, UnidentifiedImageError
from pytesseract import Output


class OcrRecognitionError(RuntimeError):
    pass


@dataclass(frozen=True)
class StressLegendReading:
    smn: float
    smx: float
    legend_values: tuple[float, ...]
    is_zero_result: bool = False


TextOcrRunner = Callable[[Image.Image, str], str]
DataOcrRunner = Callable[[Image.Image, str], Mapping[str, Sequence[object]]]

HEADER_OCR_CONFIG = "--oem 3 --psm 6"
LEGEND_OCR_CONFIG = (
    "--oem 3 --psm 6 "
    "-c tessedit_char_whitelist=0123456789.+-Ee"
)
_LEGEND_VALUE_COUNT = 10
_HEADER_CROP = (0.025, 0.02, 0.20, 0.24)
_LEGEND_CROP = (0.06, 0.84, 0.88, 1.0)
_HEADER_SCALE = 4
_LEGEND_SCALE = 3
_MIN_LEGEND_CONFIDENCE = 50.0
_MIN_LEGEND_VERTICAL_RATIO = 0.35
_ENDPOINT_ABSOLUTE_TOLERANCE = 1.0
_ENDPOINT_RELATIVE_TOLERANCE = 0.002
_NUMBER_PATTERN = re.compile(
    r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?$"
)
_HEADER_PATTERN = re.compile(
    r"\b(SMN|SMX)\s*=\s*"
    r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:E[+-]?\d+)?)",
    re.IGNORECASE,
)
_LEGACY_SM_PATTERN = re.compile(
    r"SM[Xx]\s*[^0-9]{0,3}\s*(\d[\d\s]*)",
    re.IGNORECASE,
)
_TESSDATA_ENV_LOCK = Lock()
_MISSING_ENV = object()


def _number(value: object) -> float | None:
    text = (
        str(value)
        .strip()
        .replace("—", "-")
        .replace("−", "-")
        .replace("–", "-")
        .replace(",", ".")
        .replace("O", "0")
        .replace("o", "0")
    )
    if not _NUMBER_PATTERN.fullmatch(text):
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _format_values(values: Sequence[float]) -> str:
    return ", ".join(f"{value:g}" for value in values)


def parse_stress_header(text: str) -> dict[str, float]:
    matches: dict[str, list[float]] = {}
    for label, raw_value in _HEADER_PATTERN.findall(text or ""):
        value = _number(raw_value)
        if value is not None:
            matches.setdefault(label.upper(), []).append(value)

    parsed: dict[str, float] = {}
    for label, values in matches.items():
        unique = set(values)
        if len(unique) != 1:
            raise OcrRecognitionError(
                f"识别到多个不一致的 {label} 数值：{_format_values(sorted(unique))}"
            )
        parsed[label] = unique.pop()
    return parsed


def parse_sm_text(text: str) -> int:
    """Compatibility parser for the original upper-left SMX-only contract."""

    values: list[int] = []
    for match in _LEGACY_SM_PATTERN.finditer(text or ""):
        digits = re.sub(r"\s+", "", match.group(1))
        if digits.isdigit():
            value = int(digits)
            if value > 0:
                values.append(value)
    unique = set(values)
    if not unique:
        raise OcrRecognitionError("未识别到有效的 SM 配筋面积")
    if len(unique) != 1:
        raise OcrRecognitionError(f"识别到多个不一致的 SM 配筋面积：{sorted(unique)}")
    return unique.pop()


def _data_column(
    data: Mapping[str, Sequence[object]],
    key: str,
    count: int,
) -> Sequence[object]:
    values = data.get(key, ())
    if len(values) != count:
        raise OcrRecognitionError(f"OCR 图例数据列长度不一致：{key}")
    return values


def _legend_candidates(
    data: Mapping[str, Sequence[object]],
    *,
    image_height: int,
    min_confidence: float,
    min_vertical_ratio: float,
) -> list[tuple[float, float]]:
    texts = data.get("text", ())
    count = len(texts)
    confidences = _data_column(data, "conf", count)
    lefts = _data_column(data, "left", count)
    widths = _data_column(data, "width", count)
    tops = _data_column(data, "top", count)
    heights = _data_column(data, "height", count)

    candidates: list[tuple[float, float]] = []
    minimum_y = image_height * min_vertical_ratio
    for index, raw_text in enumerate(texts):
        value = _number(raw_text)
        if value is None:
            continue
        try:
            confidence = float(confidences[index])
            center_x = float(lefts[index]) + float(widths[index]) / 2
            center_y = float(tops[index]) + float(heights[index]) / 2
        except (TypeError, ValueError):
            continue
        if confidence < min_confidence or center_y < minimum_y:
            continue
        candidates.append((center_x, value))
    return candidates


def parse_legend_data(
    data: Mapping[str, Sequence[object]],
    *,
    image_height: int,
    expected_count: int = _LEGEND_VALUE_COUNT,
    min_confidence: float = _MIN_LEGEND_CONFIDENCE,
    min_vertical_ratio: float = _MIN_LEGEND_VERTICAL_RATIO,
) -> tuple[float, ...]:
    candidates = _legend_candidates(
        data,
        image_height=image_height,
        min_confidence=min_confidence,
        min_vertical_ratio=min_vertical_ratio,
    )
    candidates.sort(key=lambda item: item[0])
    values = tuple(value for _center_x, value in candidates)
    if len(values) != expected_count:
        raise OcrRecognitionError(
            f"底部图例应识别到 {expected_count} 个数值，实际识别到 {len(values)} 个"
        )
    if any(left > right for left, right in zip(values, values[1:], strict=False)):
        raise OcrRecognitionError(
            f"底部图例数值未按从左到右非递减排列：{_format_values(values)}"
        )
    return values


def _default_text_runner(image: Image.Image, config: str) -> str:
    return pytesseract.image_to_string(image, config=config)


def _default_data_runner(
    image: Image.Image,
    config: str,
) -> Mapping[str, Sequence[object]]:
    return pytesseract.image_to_data(image, config=config, output_type=Output.DICT)


@contextmanager
def _tessdata_environment(tessdata_dir: Path | None):
    if tessdata_dir is None:
        yield
        return
    with _TESSDATA_ENV_LOCK:
        previous = os.environ.get("TESSDATA_PREFIX", _MISSING_ENV)
        try:
            if tessdata_dir is not None:
                os.environ["TESSDATA_PREFIX"] = str(tessdata_dir)
            yield
        finally:
            if previous is _MISSING_ENV:
                os.environ.pop("TESSDATA_PREFIX", None)
            else:
                os.environ["TESSDATA_PREFIX"] = str(previous)


def _crop_scaled(
    image: Image.Image,
    bounds: tuple[float, float, float, float],
    scale: int,
) -> Image.Image:
    width, height = image.size
    left, top, right, bottom = bounds
    cropped = image.crop(
        (
            int(width * left),
            int(height * top),
            int(width * right),
            int(height * bottom),
        )
    )
    prepared = ImageOps.autocontrast(cropped.convert("L"))
    return prepared.resize(
        (max(prepared.width * scale, 1), max(prepared.height * scale, 1)),
        Image.Resampling.LANCZOS,
    )


def _endpoints_match(
    actual: float,
    expected: float,
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> bool:
    tolerance = max(absolute_tolerance, abs(expected) * relative_tolerance)
    return abs(actual - expected) <= tolerance


def recognize_stress_legend(
    image_path: Path,
    *,
    direction: str,
    text_runner: TextOcrRunner | None = None,
    data_runner: DataOcrRunner | None = None,
    tesseract_exe: Path | None = None,
    tessdata_dir: Path | None = None,
    threshold: int = 160,
    expected_count: int = _LEGEND_VALUE_COUNT,
    min_confidence: float = _MIN_LEGEND_CONFIDENCE,
    min_vertical_ratio: float = _MIN_LEGEND_VERTICAL_RATIO,
    endpoint_absolute_tolerance: float = _ENDPOINT_ABSOLUTE_TOLERANCE,
    endpoint_relative_tolerance: float = _ENDPOINT_RELATIVE_TOLERANCE,
    header_crop: tuple[float, float, float, float] = _HEADER_CROP,
    legend_crop: tuple[float, float, float, float] = _LEGEND_CROP,
    header_scale: int = _HEADER_SCALE,
    legend_scale: int = _LEGEND_SCALE,
) -> StressLegendReading:
    normalized_direction = direction.strip().upper()
    if normalized_direction not in {"X", "Y", "Z"}:
        raise ValueError(f"不支持的配筋方向：{direction}")
    if tesseract_exe is not None:
        if not tesseract_exe.is_file():
            raise OcrRecognitionError(f"Tesseract 不存在：{tesseract_exe}")
        pytesseract.pytesseract.tesseract_cmd = str(tesseract_exe)
    if tessdata_dir is not None and not tessdata_dir.is_dir():
        raise OcrRecognitionError(f"Tesseract tessdata 不存在：{tessdata_dir}")

    try:
        with Image.open(image_path) as source:
            header_image = _crop_scaled(source, header_crop, header_scale)
            legend_image = _crop_scaled(source, legend_crop, legend_scale)
            active_text_runner = text_runner or _default_text_runner
            active_data_runner = data_runner or _default_data_runner
            with _tessdata_environment(tessdata_dir):
                header_text = active_text_runner(header_image, HEADER_OCR_CONFIG)
                legend_data = active_data_runner(legend_image, LEGEND_OCR_CONFIG)
    except OcrRecognitionError:
        raise
    except (OSError, UnidentifiedImageError, RuntimeError) as exc:
        raise OcrRecognitionError(f"OCR 识别失败（{image_path.name}）：{exc}") from exc

    try:
        header = parse_stress_header(header_text)
        try:
            legend_values = parse_legend_data(
                legend_data,
                image_height=legend_image.height,
                expected_count=expected_count,
                min_confidence=min_confidence,
                min_vertical_ratio=min_vertical_ratio,
            )
        except OcrRecognitionError as first_error:
            if data_runner is not None:
                legend_values = ()
                legend_error = first_error
            else:
                binary_legend = legend_image.point(
                    lambda pixel: 0 if pixel < threshold else 255
                )
                with _tessdata_environment(tessdata_dir):
                    fallback_data = _default_data_runner(
                        binary_legend,
                        LEGEND_OCR_CONFIG,
                    )
                try:
                    legend_values = parse_legend_data(
                        fallback_data,
                        image_height=binary_legend.height,
                        expected_count=expected_count,
                        min_confidence=min_confidence,
                        min_vertical_ratio=min_vertical_ratio,
                    )
                    legend_error = None
                except OcrRecognitionError:
                    legend_values = ()
                    legend_error = first_error

        smx = header.get("SMX")
        if smx is None:
            if normalized_direction == "Z" and not legend_values:
                return StressLegendReading(
                    smn=0.0,
                    smx=0.0,
                    legend_values=(),
                    is_zero_result=True,
                )
            raise OcrRecognitionError("未识别到 SMX，不能校验底部图例")
        if not legend_values:
            raise legend_error or OcrRecognitionError("未识别到底部图例")

        smn = header.get("SMN", 0.0)
        if not _endpoints_match(
            legend_values[0],
            smn,
            absolute_tolerance=endpoint_absolute_tolerance,
            relative_tolerance=endpoint_relative_tolerance,
        ):
            raise OcrRecognitionError(
                f"底部图例首值 {legend_values[0]:g} 与 SMN {smn:g} 不一致"
            )
        if not _endpoints_match(
            legend_values[-1],
            smx,
            absolute_tolerance=endpoint_absolute_tolerance,
            relative_tolerance=endpoint_relative_tolerance,
        ):
            raise OcrRecognitionError(
                f"底部图例末值 {legend_values[-1]:g} 与 SMX {smx:g} 不一致"
            )
        return StressLegendReading(
            smn=smn,
            smx=smx,
            legend_values=legend_values,
        )
    except OcrRecognitionError as exc:
        raise OcrRecognitionError(f"{image_path.name}：{exc}") from exc


def recognize_sm(
    image_path: Path,
    *,
    runner: TextOcrRunner | None = None,
    tesseract_exe: Path | None = None,
    tessdata_dir: Path | None = None,
    threshold: int = 160,
) -> int:
    """Retain the original callable while callers migrate to legend readings."""

    try:
        direction = image_path.stem.rsplit("-", maxsplit=1)[1].upper()
    except IndexError as exc:
        raise OcrRecognitionError(f"图片文件名缺少 X/Y/Z 方向：{image_path.name}") from exc
    reading = recognize_stress_legend(
        image_path,
        direction=direction,
        text_runner=runner,
        tesseract_exe=tesseract_exe,
        tessdata_dir=tessdata_dir,
        threshold=threshold,
    )
    return int(round(reading.smx))
