from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parents[4]
SKILL_ROOT = (
    WORKTREE_ROOT
    / "tools"
    / "ai"
    / "building-structure-standards"
)
SCRIPTS = SKILL_ROOT / "scripts"
GOLD_CASES = SKILL_ROOT / "references" / "gold_cases.json"
DATABASE = SKILL_ROOT / "assets" / "data" / "standards.sqlite"
CATALOG = SKILL_ROOT / "assets" / "data" / "audit_catalog.json"


def load_validator() -> object:
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "building_standards_validator",
        SCRIPTS / "validate_skill.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_gold_case_count_and_categories_meet_acceptance_range() -> None:
    payload = json.loads(GOLD_CASES.read_text(encoding="utf-8"))
    categories = Counter(case["category"] for case in payload["cases"])

    assert payload["case_count"] == 72
    assert 50 <= payload["case_count"] <= 100
    assert categories == {
        "精确条款": 36,
        "概念检索": 12,
        "版本与废止状态": 8,
        "证据不足": 10,
        "跨规范建议": 6,
    }


def test_all_gold_cases_pass_against_bundled_corpus() -> None:
    validator = load_validator()

    report = validator.validate(
        database=DATABASE,
        catalog=CATALOG,
        cases_path=GOLD_CASES,
    )

    assert report["case_count"] == 72
    assert report["passed_count"] == 72
    assert report["failed_count"] == 0
    assert report["pass_rate"] == 1.0
