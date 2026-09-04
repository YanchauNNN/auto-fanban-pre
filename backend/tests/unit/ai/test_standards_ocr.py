from __future__ import annotations

import builtins
import copy
import hashlib
import importlib.util
import io
import json
import os
import sys
import types
from pathlib import Path

import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = WORKTREE_ROOT / "tools/ai/building-structure-standards/scripts/standards_ocr.py"
IDENTITY = {
    "engine": "test-ocr",
    "version": "1.0",
    "models": {"recognition_sha256": "model-a"},
    "parameters": {"threshold": 0.5},
}
BODY = "The structure shall satisfy all applicable safety requirements. "
BOX = ((1.0, 2.0), (20.0, 2.0), (20.0, 8.0), (1.0, 8.0))


@pytest.fixture
def ocr():
    path = Path(os.environ.get("STANDARDS_OCR_TEST_SCRIPT", str(SCRIPT)))
    spec = importlib.util.spec_from_file_location("standards_ocr_unit_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def decide(ocr, native="", recognized="", confidence=0.99, **kwargs):
    return ocr.select_page_text(
        native_text=native,
        ocr_text=recognized,
        ocr_confidence=confidence,
        parse_mode=kwargs.pop("parse_mode", "text_primary"),
        **kwargs,
    )


class CountingEngine:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def recognize_png(self, _png):
        self.calls += 1
        return self.result


def detailed_result(ocr):
    lines = (
        ocr.OcrLineResult(text=" 1.0.1  Original text\t", score=0.999, box=BOX),
        ocr.OcrLineResult(text="1000m\u00b0", score=0.48, box=BOX),
    )
    raw = "\n".join(line.text for line in lines)
    return ocr.OcrPageResult(raw, 0.7395, 2, lines=lines, raw_text=raw)


def block_ocr_imports(monkeypatch):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in {"rapidocr_onnxruntime", "onnxruntime", "numpy", "PIL"}:
            raise AssertionError(f"unexpected OCR dependency import: {name}")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)


def test_text_primary_retains_good_native_text(ocr):
    result = decide(ocr, BODY * 3, BODY * 4)
    assert result.text_source == "native"
    assert result.quality == "usable"
    assert isinstance(result.quality_flags, (list, tuple))


def test_decision_preserves_raw_inputs_separately_from_selected_text(ocr):
    native = "  1.0.1\t" + BODY * 3 + "\r\n\r\n"
    recognized = "  raw\tOCR\r\n"
    result = decide(ocr, native, recognized)
    assert result.native_text == native
    assert result.ocr_text == recognized
    assert result.selected_text != native
    assert result.native_char_count > 100
    assert result.ocr_confidence == 0.99


@pytest.mark.parametrize("standalone", [False, True])
def test_more_complete_ocr_wins_over_fragmented_native_clauses(ocr, standalone):
    native = "\n".join(f"1 \uff0e0 \uff0e\n{i}\n{BODY}" for i in range(1, 5))
    separator = "\n" if standalone else " "
    recognized = "\n".join(f"1.0.{i}{separator}{BODY}" for i in range(1, 5))
    result = decide(ocr, native, recognized)
    assert result.text_source == "ocr"
    assert "ocr_structure_preferred" in result.quality_flags
    assert "1.0.4" in result.selected_text


def test_ocr_with_additional_complete_clause_is_preferred(ocr):
    native = f"1.0.1 {BODY * 3}"
    result = decide(ocr, native, native + f"\n1.0.2 {BODY}")
    assert result.text_source == "ocr"


@pytest.mark.parametrize("mode", ["text_primary", "ocr_primary"])
@pytest.mark.parametrize("last_id", ["10. 10. 10", "10 \uff0e10 \uff0e10", "10. 10.\n10"])
def test_ocr_must_cover_all_native_clause_ids_before_replacing_text(ocr, mode, last_id):
    native = "\n".join(f"10. 10. {number} {BODY.strip()}" for number in range(2, 10))
    native += f"\n{last_id} Embedded parts must account for high temperature; see Appendix B."
    recognized = "\n".join(f"10.10.{number} OCR_ONLY_EVIDENCE {BODY}" for number in range(2, 10))

    result = decide(ocr, native, recognized, parse_mode=mode, legacy_ocr=True)

    assert result.text_source == "native"
    assert result.selected_text == native.strip()
    assert "Embedded parts must account for high temperature" in result.selected_text
    assert "OCR_ONLY_EVIDENCE" not in result.selected_text
    assert result.native_text == native and result.ocr_text == recognized
    assert result.quality == "review_required"
    assert "clause_id_disagreement" in result.quality_flags
    assert "ocr_missing_native_clauses" in result.quality_flags
    assert "ocr_structure_preferred" not in result.quality_flags


def test_equal_clause_counts_do_not_substitute_for_id_coverage(ocr):
    native = "\n".join(f"10. 10. {number} {BODY}" for number in (2, 3, 10))
    recognized = "\n".join(f"10.10.{number} {BODY}" for number in (2, 3, 11))

    result = decide(ocr, native, recognized)

    assert result.text_source == "native"
    assert result.quality == "review_required"
    assert "clause_id_disagreement" in result.quality_flags


def test_short_native_clause_cannot_be_discarded_by_ocr_fallback(ocr):
    result = decide(ocr, native="10. 10. 10 Native only clause.", recognized=f"10.10.9 {BODY}")

    assert result.text_source == "native"
    assert result.selected_text == "10. 10. 10 Native only clause."
    assert result.quality == "review_required"
    assert "ocr_missing_native_clauses" in result.quality_flags


def test_ocr_fullwidth_and_spaced_ids_count_as_coverage(ocr):
    native = "\n".join(f"10.10.{number} {BODY}" for number in (2, 3, 10))
    recognized = "\n".join(f"10 \uff0e10 \uff0e{number} {BODY}" for number in (2, 3, 10))

    result = decide(ocr, native, recognized, parse_mode="ocr_primary")

    assert result.text_source == "ocr"
    assert "clause_id_disagreement" not in result.quality_flags
    assert "ocr_missing_native_clauses" not in result.quality_flags


def test_inline_references_do_not_expand_native_heading_coverage(ocr):
    native = f"10. 10. 2 {BODY}\nAccording to 10.10.10, {BODY}"
    recognized = f"10.10.2 {BODY * 2}"

    result = decide(ocr, native, recognized)

    assert result.text_source == "ocr"
    assert "clause_id_disagreement" not in result.quality_flags


def test_chinese_clause_numbers_need_no_space_before_body(ocr):
    body = "\u6297\u9707\u8bbe\u9632\u533a\u7684\u6240\u6709\u5efa\u7b51\u5de5\u7a0b\u5e94\u786e\u5b9a\u5176\u6297\u9707\u8bbe\u9632\u7c7b\u522b\u3002"
    native = "\n".join(f"\u30021 \uff0e0 \uff0e{i} {body * 2}" for i in range(1, 5))
    recognized = "\n".join(f"1.0.{i}{body * 2}" for i in range(1, 5))
    result = decide(ocr, native, recognized, legacy_ocr=True)
    assert result.text_source == "ocr"
    assert "ocr_structure_preferred" in result.quality_flags
    assert result.quality == "review_required"


def test_inline_clause_reference_is_not_damaged_native_structure(ocr):
    result = decide(ocr, native=f"According to 1.0.2, {BODY * 3}")
    assert result.quality == "usable"
    assert "native_clause_structure" not in result.quality_flags


def test_damaged_native_without_reliable_ocr_requires_review(ocr):
    native = f"1 \uff0e0 \uff0e\n1\n{BODY * 3}"
    result = decide(ocr, native, f"1.0.1 {BODY}", 0.1)
    assert result.text_source == "native"
    assert result.quality == "review_required"
    assert "native_clause_structure" in result.quality_flags


@pytest.mark.parametrize("mode", ["text_primary", "ocr_primary"])
def test_empty_unverified_page_is_not_success_or_an_exception(ocr, mode):
    result = decide(ocr, parse_mode=mode)
    assert result.selected_text == ""
    assert result.text_source == "none"
    assert result.quality == "failed"
    assert "empty_unverified" in result.quality_flags


def test_verified_blank_page_is_explicit(ocr):
    result = decide(ocr, " \r\n", "\t", 0, blank_verified=True)
    assert result.quality == "blank"
    assert result.text_source == "none"
    assert "blank_verified" in result.quality_flags


def test_blank_assertion_cannot_suppress_actual_content(ocr):
    result = decide(ocr, BODY * 3, blank_verified=True)
    assert result.selected_text
    assert result.quality != "blank"
    assert "blank_evidence_conflict" in result.quality_flags


@pytest.mark.parametrize("text,score", [("Cover title", 0.98), (BODY * 3, 0.2)])
def test_short_or_low_confidence_text_is_preserved_for_review(ocr, text, score):
    result = decide(ocr, recognized=text, confidence=score, parse_mode="ocr_primary")
    assert result.selected_text == text.strip()
    assert result.quality == "review_required"


def test_short_native_clause_without_ocr_is_retained_for_query_smoke(ocr):
    result = decide(ocr, native="1.1.1 cached evidence", confidence=0)
    assert result.text_source == "native"
    assert result.selected_text == "1.1.1 cached evidence"
    assert result.quality == "review_required"
    assert "short_native_text" in result.quality_flags


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -0.1])
def test_invalid_confidence_never_passes_quality_gate(ocr, score):
    result = decide(ocr, recognized=BODY * 3, confidence=score)
    assert result.quality == "review_required"
    assert 0 <= result.ocr_confidence <= 1


def test_high_confidence_wrong_area_unit_requires_review_without_correction(ocr):
    reference = json.loads(
        (
            WORKTREE_ROOT / "documents/AI/reviews/standards_pilot_20260903_reference_cases.json"
        ).read_text(encoding="utf-8")
    )
    case = next(sample for sample in reference["samples"] if sample["id"] == "ocr-area-unit")
    text = "4.1.3 " + BODY * 3 + case["known_wrong_fragment"]
    result = decide(ocr, recognized=text, confidence=0.9759234177138143)
    assert result.quality == "review_required"
    assert "suspicious_unit" in result.quality_flags
    assert case["known_wrong_fragment"] in result.selected_text
    assert case["expected_fragment"] not in result.selected_text


@pytest.mark.parametrize("fragment", ["1000m\u00b2", "F <= 10kN", "\u88683.2.2 6 7 25"])
def test_critical_units_comparisons_and_tables_require_review(ocr, fragment):
    result = decide(ocr, recognized=BODY * 3 + fragment)
    assert result.quality == "review_required"
    assert result.quality_flags


def test_legacy_ocr_is_only_a_candidate(ocr):
    result = decide(ocr, recognized=BODY * 3, legacy_ocr=True)
    assert result.quality == "review_required"
    assert "legacy_ocr_candidate" in result.quality_flags
    native = decide(ocr, BODY * 3, BODY * 3, legacy_ocr=True)
    assert native.text_source == "native"
    assert native.quality == "usable"


def test_low_confidence_line_is_not_hidden_by_high_page_average(ocr):
    line = ocr.OcrLineResult(BODY, 0.4, BOX)
    result = decide(ocr, recognized=BODY * 3, ocr_lines=(line,))
    assert result.quality == "review_required"
    assert "low_confidence_line" in result.quality_flags


def test_old_positional_result_and_decision_fields_remain_supported(ocr):
    result = ocr.OcrPageResult("legacy", 0.9, 1)
    assert (result.text, result.confidence, result.line_count) == ("legacy", 0.9, 1)
    decision = ocr.PageTextDecision("native", "ocr", "native", "native", "usable", 6, 3, 0.9)
    assert decision.quality_flags == ()


@pytest.mark.parametrize("field", ["engine", "version", "models", "parameters"])
def test_cache_identity_changes_invalidate_results(ocr, tmp_path, field):
    identity = copy.deepcopy(IDENTITY)
    first = CountingEngine(ocr.OcrPageResult("old", 0.99, 1))
    ocr.CachedOcrEngine(first, tmp_path, engine_identity=identity).recognize_png(b"png")
    identity[field] = {"changed": True} if isinstance(identity[field], dict) else "changed"
    second = CountingEngine(ocr.OcrPageResult("new", 0.99, 1))
    result = ocr.CachedOcrEngine(second, tmp_path, engine_identity=identity).recognize_png(b"png")
    assert result.text == "new"
    assert second.calls == 1


def test_preprocessing_version_and_png_content_are_in_cache_key(ocr, tmp_path):
    engine = CountingEngine(ocr.OcrPageResult("text", 0.9, 1))
    for version, png in [("rgb-v1", b"a"), ("rgb-v2", b"a"), ("rgb-v2", b"b")]:
        ocr.CachedOcrEngine(
            engine, tmp_path, engine_identity=IDENTITY, preprocessing_version=version
        ).recognize_png(png)
    assert engine.calls == 3


def test_no_identity_reuses_only_within_same_instance(ocr, tmp_path):
    first = CountingEngine(ocr.OcrPageResult("first", 0.9, 1))
    cache = ocr.CachedOcrEngine(first, tmp_path)
    assert cache.recognize_png(b"png") == cache.recognize_png(b"png")
    assert first.calls == 1
    assert (cache.cache_hits, cache.cache_misses) == (1, 1)
    second = CountingEngine(ocr.OcrPageResult("second", 0.9, 1))
    assert ocr.CachedOcrEngine(second, tmp_path).recognize_png(b"png").text == "second"
    assert second.calls == 1


def test_cache_identity_is_a_snapshot_of_caller_parameters(ocr, tmp_path):
    identity = copy.deepcopy(IDENTITY)
    engine = CountingEngine(ocr.OcrPageResult(BODY, 0.9, 1))
    cache = ocr.CachedOcrEngine(engine, tmp_path, engine_identity=identity)
    first = cache.recognize_png(b"png")
    identity["parameters"]["threshold"] = 0.8
    assert cache.recognize_png(b"png") == first
    assert engine.calls == 1


def test_recognition_failure_does_not_create_a_success_cache(ocr, tmp_path):
    class FailedEngine:
        def recognize_png(self, _png):
            raise RuntimeError("recognition failed")

    cache = ocr.CachedOcrEngine(FailedEngine(), tmp_path, engine_identity=IDENTITY)
    with pytest.raises(RuntimeError, match="recognition failed"):
        cache.recognize_png(b"png")
    assert not list(tmp_path.glob("*.json"))


def test_cache_persists_raw_text_boxes_and_individual_scores(ocr, tmp_path):
    expected = detailed_result(ocr)
    engine = CountingEngine(expected)
    cached = ocr.CachedOcrEngine(engine, tmp_path, engine_identity=IDENTITY)
    assert cached.recognize_png(b"png") == expected
    payload = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert payload["engine_identity"] == IDENTITY
    assert payload["png_sha256"] == hashlib.sha256(b"png").hexdigest()
    assert payload["preprocessing_version"]
    assert payload["raw_text"] == expected.raw_text
    assert payload["lines"][0]["box"] == [list(point) for point in BOX]
    assert payload["lines"][1]["score"] == 0.48
    assert payload["lines"][0]["text"] == expected.lines[0].text


def test_stable_cache_can_be_read_without_any_ocr_dependencies(ocr, tmp_path, monkeypatch):
    expected = detailed_result(ocr)
    ocr.CachedOcrEngine(CountingEngine(expected), tmp_path, engine_identity=IDENTITY).recognize_png(
        b"png"
    )
    block_ocr_imports(monkeypatch)
    reversed_identity = dict(reversed(list(IDENTITY.items())))
    cached = ocr.CachedOcrEngine(None, tmp_path, engine_identity=reversed_identity)
    assert cached.recognize_png(b"png") == expected
    assert (cached.cache_hits, cached.cache_misses) == (1, 0)


def test_old_png_cache_requires_explicit_candidate_opt_in(ocr, tmp_path):
    path = tmp_path / f"{hashlib.sha256(b'png').hexdigest()}.json"
    payload = {"schema_version": 1, "text": BODY, "confidence": 0.98, "line_count": 1}
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ocr.OcrQualityError, match="cache"):
        ocr.CachedOcrEngine(None, tmp_path).recognize_png(b"png")
    cache = ocr.CachedOcrEngine(None, tmp_path, allow_legacy_cache=True)
    result = cache.recognize_png(b"png")
    assert result.legacy_ocr is True
    assert "legacy_ocr_candidate" in result.quality_flags
    assert result.text == BODY
    assert path.read_text(encoding="utf-8") == json.dumps(payload)


def test_new_cache_with_no_line_evidence_is_still_a_candidate(ocr, tmp_path):
    ocr.CachedOcrEngine(
        CountingEngine(ocr.OcrPageResult(BODY, 0.99, 1)), tmp_path, engine_identity=IDENTITY
    ).recognize_png(b"png")
    result = ocr.CachedOcrEngine(None, tmp_path, engine_identity=IDENTITY).recognize_png(b"png")
    assert result.legacy_ocr is True
    assert "missing_line_evidence" in result.quality_flags


@pytest.mark.parametrize(
    "corruption",
    ["invalid_json", "wrong_identity", "wrong_schema", "bad_box", "bad_line_text", "bad_flags"],
)
def test_corrupt_or_mismatched_cache_is_a_miss(ocr, tmp_path, corruption):
    engine = CountingEngine(detailed_result(ocr))
    cache = ocr.CachedOcrEngine(engine, tmp_path, engine_identity=IDENTITY)
    cache.recognize_png(b"png")
    path = next(tmp_path.glob("*.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    if corruption == "wrong_identity":
        payload["engine_identity"] = {"engine": "someone-else"}
    elif corruption == "wrong_schema":
        payload["schema_version"] = 999
    elif corruption == "bad_box":
        payload["lines"][0]["box"] = [[1, 2]]
    elif corruption == "bad_line_text":
        payload["lines"][0]["text"] = 123
    elif corruption == "bad_flags":
        payload["quality_flags"] = "usable"
    path.write_text("{" if corruption == "invalid_json" else json.dumps(payload), encoding="utf-8")
    cache.recognize_png(b"png")
    assert engine.calls == 2
    assert cache.cache_hits == 0


def test_rapidocr_constructor_and_module_import_are_lazy(ocr, monkeypatch):
    block_ocr_imports(monkeypatch)
    engine = ocr.RapidOcrEngine()
    assert engine is not None


def test_rapidocr_preserves_line_evidence_using_fake_runtime_only(ocr, monkeypatch):
    import numpy as np
    from PIL import Image

    captured = {}

    class FakeRapidOCR:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def __call__(self, image):
            assert image.shape == (4, 4, 3)
            return [(np.asarray(BOX), "  raw\ttext ", 0.9759)], None

    monkeypatch.setitem(
        sys.modules, "rapidocr_onnxruntime", types.SimpleNamespace(RapidOCR=FakeRapidOCR)
    )
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
    engine = ocr.RapidOcrEngine()
    assert captured == {}
    result = engine.recognize_png(buffer.getvalue())
    assert captured == {"intra_op_num_threads": 8, "inter_op_num_threads": 1}
    assert result.text == result.raw_text == "  raw\ttext "
    assert result.lines[0].box == BOX
    assert result.lines[0].score == 0.9759
    assert not result.legacy_ocr


def test_capability_missing_is_explicit_and_does_not_run_ocr(ocr, monkeypatch):
    monkeypatch.setattr(ocr.importlib.util, "find_spec", lambda _name: None)
    capability = ocr.detect_ocr_capability()
    assert not capability.available
    assert not capability.chinese_available
    assert "not installed" in capability.reason


def test_quality_thresholds_are_loaded_from_yaml(ocr, tmp_path):
    import yaml

    path = SCRIPT.parent.parent / "assets/ocr_quality.yaml"
    policy = yaml.safe_load(path.read_text(encoding="utf-8"))
    policy["selection"]["ocr_review_confidence"] = 0.995
    custom = tmp_path / "quality.yaml"
    custom.write_text(yaml.safe_dump(policy), encoding="utf-8")
    result = decide(ocr, recognized=BODY * 3, confidence=0.99, quality_config=custom)
    assert result.quality == "review_required"


def test_invalid_mode_remains_a_programming_error(ocr):
    with pytest.raises(ValueError, match="parse_mode"):
        decide(ocr, parse_mode="typo")
