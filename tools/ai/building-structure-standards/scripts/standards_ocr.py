"""OCR candidates and conservative page selection, independent of corpus building.

``usable`` means suitable for text retrieval, not human-reviewed evidence.
Only recognize_png imports OCR/image dependencies. Cache readers need none of them.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import io
import json
import math
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

CACHE_SCHEMA_VERSION = 2
PREPROCESSING_VERSION = "pillow-rgb-v1"
QUALITY_CONFIG = Path(__file__).resolve().parent.parent / "assets/ocr_quality.yaml"
_CLAUSE = re.compile(r"(?m)^[ \t]*([A-Z]?\d+(?:\.\d+){2,})(?![\d.])(?=\s|[^\w]|[\u3400-\u9fff]|$)")
_LOOSE_CLAUSE = re.compile(r"(?<!\d)[A-Z]?\d+(?:\s*[.\uff0e\u3002]\s*\d+){2,}(?!\d)")


class OcrQualityError(RuntimeError):
    pass


@dataclass(frozen=True)
class OcrCapability:
    available: bool
    engine: str
    version: str
    chinese_available: bool
    reason: str


@dataclass(frozen=True)
class OcrLineResult:
    text: str
    score: float
    box: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise ValueError("OCR line text must be a string")
        points = tuple(tuple(float(value) for value in point) for point in self.box)
        if len(points) != 4 or any(
            len(point) != 2 or not all(math.isfinite(value) for value in point) for point in points
        ):
            raise ValueError("OCR box must contain four finite coordinate pairs")
        object.__setattr__(self, "box", points)
        object.__setattr__(self, "score", _valid_score(self.score))


@dataclass(frozen=True)
class OcrPageResult:
    text: str
    confidence: float
    line_count: int
    lines: tuple[OcrLineResult, ...] = ()
    raw_text: str | None = None
    legacy_ocr: bool = False
    quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "lines", tuple(self.lines))
        if self.raw_text is None:
            object.__setattr__(self, "raw_text", self.text)
        flags = list(self.quality_flags)
        missing = bool(self.text.strip()) and (not self.lines or len(self.lines) != self.line_count)
        if missing:
            flags.append("missing_line_evidence")
        if missing or self.legacy_ocr:
            object.__setattr__(self, "legacy_ocr", True)
            flags.append("legacy_ocr_candidate")
        object.__setattr__(self, "quality_flags", tuple(dict.fromkeys(flags)))


@dataclass(frozen=True)
class PageTextDecision:
    native_text: str
    ocr_text: str
    selected_text: str
    text_source: str
    quality: str
    native_char_count: int
    ocr_char_count: int
    ocr_confidence: float
    quality_flags: tuple[str, ...] = ()


def detect_ocr_capability() -> OcrCapability:
    engine = "rapidocr_onnxruntime"
    if importlib.util.find_spec(engine) is None:
        return OcrCapability(False, engine, "", False, f"{engine} is not installed")
    try:
        version = importlib.metadata.version("rapidocr-onnxruntime")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    return OcrCapability(True, engine, version, True, "")


@lru_cache(maxsize=8)
def _quality_policy(path: Path) -> dict[str, Any]:
    import yaml

    policy = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(policy, dict) or policy.get("schema_version") != 1:
        raise ValueError("unsupported OCR quality policy schema")
    selection = policy["selection"]
    for name in ("native_min_chars", "ocr_min_chars"):
        if type(selection[name]) is not int or selection[name] < 1:
            raise ValueError(f"invalid OCR quality threshold: {name}")
    for name in (
        "native_max_replacement_ratio",
        "ocr_min_confidence",
        "ocr_review_confidence",
        "line_review_confidence",
        "structure_min_char_ratio",
    ):
        _valid_score(selection[name])
    if selection["ocr_min_confidence"] > selection["ocr_review_confidence"]:
        raise ValueError("OCR review confidence must not be below minimum confidence")
    policy["ocr_review_patterns"] = {
        name: re.compile(pattern) for name, pattern in policy["ocr_review_patterns"].items()
    }
    return policy


def _valid_score(value: Any) -> float:
    score = float(value)
    if not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("OCR confidence must be finite and between zero and one")
    return score


def _normalize_text(value: str) -> str:
    return "\n".join(
        line for raw in value.splitlines() if (line := re.sub(r"[ \t\u00a0]+", " ", raw).strip())
    )


def _meaningful_char_count(value: str) -> int:
    return len(re.sub(r"[\s\x00-\x1f]", "", value))


def _replacement_ratio(value: str) -> float:
    return (value.count("\ufffd") + value.count("\x00")) / max(1, _meaningful_char_count(value))


def _clause_structure(text: str) -> tuple[set[str], bool]:
    headings = set(_CLAUSE.findall(text))
    # Coverage includes recoverable line-start IDs; evidence text stays untouched.
    normalized_headings = {
        re.sub(r"\s+", "", match.group()).replace("\uff0e", ".").replace("\u3002", ".")
        for match in _LOOSE_CLAUSE.finditer(text)
        if not text[text.rfind("\n", 0, match.start()) + 1 : match.start()].strip(
            " \t.,;:\u3002\uff0c\uff1b\uff1a\u3001"
        )
    }
    return headings | normalized_headings, bool(normalized_headings - headings)


def select_page_text(
    *,
    native_text: str,
    ocr_text: str,
    ocr_confidence: float,
    parse_mode: str,
    blank_verified: bool = False,
    legacy_ocr: bool = False,
    quality_config: Path | str | None = None,
    ocr_lines: Sequence[OcrLineResult] = (),
) -> PageTextDecision:
    if parse_mode not in {"text_primary", "ocr_primary"}:
        raise ValueError(f"unsupported parse_mode: {parse_mode}")
    policy = _quality_policy(Path(quality_config) if quality_config is not None else QUALITY_CONFIG)
    thresholds = policy["selection"]
    native, recognized = _normalize_text(native_text), _normalize_text(ocr_text)
    native_chars, ocr_chars = _meaningful_char_count(native), _meaningful_char_count(recognized)
    try:
        confidence = _valid_score(ocr_confidence)
    except (ValueError, TypeError):
        confidence = 0.0
    native_clauses, native_damaged = _clause_structure(native)
    ocr_clauses, ocr_damaged = _clause_structure(recognized)
    missing_native_clauses = native_clauses - ocr_clauses if ocr_chars else set()
    native_clean = _replacement_ratio(native) <= thresholds["native_max_replacement_ratio"]
    ocr_clean = _replacement_ratio(recognized) <= thresholds["native_max_replacement_ratio"]
    native_usable = native_chars >= thresholds["native_min_chars"] and native_clean
    ocr_usable = (
        ocr_chars >= thresholds["ocr_min_chars"]
        and ocr_clean
        and confidence >= thresholds["ocr_min_confidence"]
    )
    structure_preferred = (
        ocr_usable
        and confidence >= thresholds["ocr_review_confidence"]
        and not ocr_damaged
        and native_clauses <= ocr_clauses
        and ocr_chars >= native_chars * thresholds["structure_min_char_ratio"]
        and (ocr_clauses > native_clauses or (native_damaged and bool(ocr_clauses)))
    )
    flags: list[str] = []
    if not native_chars and not ocr_chars:
        quality = "blank" if blank_verified else "failed"
        flags.append("blank_verified" if blank_verified else "empty_unverified")
        selected, source = "", "none"
    else:
        if missing_native_clauses:
            selected, source = native, "native"
        elif structure_preferred:
            selected, source = recognized, "ocr"
            flags.append("ocr_structure_preferred")
        elif parse_mode == "text_primary" and native_usable:
            selected, source = native, "native"
        elif ocr_usable:
            selected, source = recognized, "ocr"
        elif native_usable or (native_chars and native_clean):
            selected, source = native, "native"
        else:
            selected, source = (recognized, "ocr") if ocr_chars else (native, "native")
        review: list[str] = []
        if missing_native_clauses:
            review.extend(("clause_id_disagreement", "ocr_missing_native_clauses"))
        if blank_verified:
            review.append("blank_evidence_conflict")
        if source == "native":
            if not native_usable:
                review.append("short_native_text" if native_clean else "native_text_corrupt")
            if native_damaged:
                review.append("native_clause_structure")
        else:
            if ocr_chars < thresholds["ocr_min_chars"]:
                review.append("short_ocr_text")
            if confidence < thresholds["ocr_review_confidence"]:
                review.append("low_ocr_confidence")
            if not ocr_clean:
                review.append("ocr_text_corrupt")
            if ocr_damaged:
                review.append("ocr_clause_structure")
            if legacy_ocr:
                review.append("legacy_ocr_candidate")
            if any(line.score < thresholds["line_review_confidence"] for line in ocr_lines):
                review.append("low_confidence_line")
            review.extend(
                name
                for name, pattern in policy["ocr_review_patterns"].items()
                if pattern.search(recognized)
            )
        quality = "review_required" if review else "usable"
        flags.extend(review)
    return PageTextDecision(
        native_text,
        ocr_text,
        selected,
        source,
        quality,
        native_chars,
        ocr_chars,
        confidence,
        tuple(dict.fromkeys(flags)),
    )


class RapidOcrEngine:
    def __init__(
        self,
        *,
        intra_op_num_threads: int = 8,
        inter_op_num_threads: int = 1,
        **engine_options: Any,
    ) -> None:
        self._options = {
            **engine_options,
            "intra_op_num_threads": max(1, int(intra_op_num_threads)),
            "inter_op_num_threads": max(1, int(inter_op_num_threads)),
        }
        self._engine: Any = None

    @property
    def capability(self) -> OcrCapability:
        return detect_ocr_capability()

    def recognize_png(self, png_bytes: bytes) -> OcrPageResult:
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR(**self._options)
        import numpy as np
        from PIL import Image

        with Image.open(io.BytesIO(png_bytes)) as image:
            pixels = np.asarray(image.convert("RGB"))
        result, _elapsed = self._engine(pixels)
        lines = []
        for box, text, score in result or []:
            lines.append(OcrLineResult(text=str(text or ""), score=score, box=box))
        raw_text = "\n".join(line.text for line in lines)
        confidence = sum(line.score for line in lines) / len(lines) if lines else 0.0
        return OcrPageResult(raw_text, confidence, len(lines), tuple(lines), raw_text)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _read_result(payload: dict[str, Any], *, legacy: bool = False) -> OcrPageResult:
    if not isinstance(payload["text"], str) or type(payload["line_count"]) is not int:
        raise ValueError("invalid OCR cache text or line count")
    if payload["line_count"] < 0:
        raise ValueError("negative OCR line count")
    raw_text = payload["text"] if legacy else payload["raw_text"]
    if not isinstance(raw_text, str):
        raise ValueError("invalid raw OCR text")
    flags = payload.get("quality_flags", [])
    if not isinstance(flags, list) or any(not isinstance(flag, str) for flag in flags):
        raise ValueError("invalid OCR quality flags")
    lines = tuple(OcrLineResult(**line) for line in payload.get("lines", []))
    return OcrPageResult(
        payload["text"],
        _valid_score(payload["confidence"]),
        payload["line_count"],
        lines=lines,
        raw_text=raw_text,
        legacy_ocr=legacy or bool(payload.get("legacy_ocr", False)),
        quality_flags=tuple(flags),
    )


class CachedOcrEngine:
    """Persist identity-scoped candidates without importing the underlying engine.

    engine_identity must explicitly describe engine/version, model fingerprints and
    all recognition options. Without it, results are scoped to this instance only.
    Pass engine=None for cache-only access. Old PNG-only files are opt-in candidates,
    never migrated into an identity-scoped cache or treated as reviewed evidence.
    """

    def __init__(
        self,
        engine: Any,
        cache_root: Path | str,
        *,
        engine_identity: Mapping[str, Any] | None = None,
        preprocessing_version: str = PREPROCESSING_VERSION,
        allow_legacy_cache: bool = False,
    ) -> None:
        if engine_identity is not None and (
            not isinstance(engine_identity, Mapping) or not engine_identity
        ):
            raise ValueError("engine_identity must be a nonempty stable mapping")
        if not isinstance(preprocessing_version, str) or not preprocessing_version.strip():
            raise ValueError("preprocessing_version must be explicit")
        self._engine = engine
        self.cache_root = Path(cache_root)
        self._identity = (
            json.loads(_json(dict(engine_identity))) if engine_identity is not None else None
        )
        self._scope = None if self._identity is not None else uuid.uuid4().hex
        self._preprocessing_version = preprocessing_version
        self._allow_legacy_cache = allow_legacy_cache
        self.cache_hits = 0
        self.cache_misses = 0

    def recognize_png(self, png_bytes: bytes) -> OcrPageResult:
        png_hash = hashlib.sha256(png_bytes).hexdigest()
        metadata = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "png_sha256": png_hash,
            "engine_identity": self._identity,
            "preprocessing_version": self._preprocessing_version,
            "instance_scope": self._scope,
        }
        key = hashlib.sha256(_json(metadata).encode("utf-8")).hexdigest()
        cache_path = self.cache_root / f"{key}.json"
        candidates = [(cache_path, False)]
        if self._allow_legacy_cache:
            candidates.append((self.cache_root / f"{png_hash}.json", True))
        for path, legacy in candidates:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    continue
                expected = {"schema_version": 1} if legacy else metadata
                if any(payload.get(name) != value for name, value in expected.items()):
                    continue
                result = _read_result(payload, legacy=legacy)
            except (FileNotFoundError, KeyError, TypeError, ValueError):
                continue
            self.cache_hits += 1
            return result
        self.cache_misses += 1
        if self._engine is None:
            raise OcrQualityError("OCR cache miss; no recognition engine was supplied")
        raw = self._engine.recognize_png(png_bytes)
        result = OcrPageResult(
            text=raw.text,
            confidence=_valid_score(raw.confidence),
            line_count=raw.line_count,
            lines=tuple(getattr(raw, "lines", ())),
            raw_text=getattr(raw, "raw_text", raw.text),
            legacy_ocr=bool(getattr(raw, "legacy_ocr", False)),
            quality_flags=tuple(getattr(raw, "quality_flags", ())),
        )
        self.cache_root.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(_json({**metadata, **asdict(result)}), encoding="utf-8")
            temporary.replace(cache_path)
        finally:
            temporary.unlink(missing_ok=True)
        return result
