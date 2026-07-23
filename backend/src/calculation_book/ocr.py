from __future__ import annotations

import os
import re
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

import pytesseract
from PIL import Image, UnidentifiedImageError


class OcrRecognitionError(RuntimeError):
    pass


OcrRunner = Callable[[Image.Image, str], str]
OCR_CONFIG = "--oem 3 --psm 6 -c tessedit_char_whitelist=SMXx=:-0123456789"
_SM_PATTERN = re.compile(r"SM[Xx]\s*[^0-9]{0,3}\s*(\d[\d\s]*)", re.IGNORECASE)
_TESSDATA_ENV_LOCK = Lock()
_MISSING_ENV = object()


def parse_sm_text(text: str) -> int:
    values: list[int] = []
    for match in _SM_PATTERN.finditer(text or ""):
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


def _default_runner(image: Image.Image, config: str) -> str:
    return pytesseract.image_to_string(image, config=config)


@contextmanager
def _tessdata_environment(tessdata_dir: Path | None):
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


def recognize_sm(
    image_path: Path,
    *,
    runner: OcrRunner | None = None,
    tesseract_exe: Path | None = None,
    tessdata_dir: Path | None = None,
    threshold: int = 160,
) -> int:
    if tesseract_exe is not None:
        if not tesseract_exe.is_file():
            raise OcrRecognitionError(f"Tesseract 不存在：{tesseract_exe}")
        pytesseract.pytesseract.tesseract_cmd = str(tesseract_exe)
    if tessdata_dir is not None and not tessdata_dir.is_dir():
        raise OcrRecognitionError(f"Tesseract tessdata 不存在：{tessdata_dir}")

    try:
        with Image.open(image_path) as source:
            resized = source.resize(
                (max(int(source.width * 0.8), 1), max(int(source.height * 0.8), 1))
            )
            cropped = resized.crop(
                (0, 0, max(int(resized.width * 0.5), 1), max(int(resized.height * 0.4), 1))
            )
            grayscale = cropped.convert("L")
            prepared = grayscale.point(lambda pixel: 0 if pixel < threshold else 255)
            with _tessdata_environment(tessdata_dir):
                text = (runner or _default_runner)(prepared, OCR_CONFIG)
    except OcrRecognitionError:
        raise
    except (OSError, UnidentifiedImageError, RuntimeError) as exc:
        raise OcrRecognitionError(f"OCR 识别失败（{image_path.name}）：{exc}") from exc

    try:
        return parse_sm_text(text)
    except OcrRecognitionError as exc:
        raise OcrRecognitionError(f"{image_path.name}：{exc}") from exc
