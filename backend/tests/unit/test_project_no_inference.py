from __future__ import annotations

import yaml

from src.pipeline.project_no_inference import (
    infer_project_no_from_path,
    infer_replace_batch_identity,
    infer_unit_no_from_path,
    resolve_project_no,
)


def test_project_no_inference_reads_defaults_and_patterns_from_mechanism_yaml(tmp_path, monkeypatch) -> None:
    mechanism_spec = tmp_path / "documents" / "参数规范-3.yaml"
    mechanism_spec.parent.mkdir(parents=True, exist_ok=True)
    mechanism_spec.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "backend_mechanism": {
                    "project_inference": {
                        "project_no_prefix_regex": r"^FB-(\d{4})",
                        "unit_no_by_project_prefix_regex": r"^FB-(?P<project_no>\d{4})-U(?P<unit_no>[1-9])",
                        "default_project_no": "2026",
                    },
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FANBAN_MECHANISM_SPEC_PATH", str(mechanism_spec))

    assert resolve_project_no(None, "no-project.dwg") == "2026"
    assert resolve_project_no(None, "FB-1818-U3-JG001.dwg") == "1818"
    assert infer_unit_no_from_path("FB-1818-U3-JG001.dwg", "1818") == "3"


def test_project_no_inference_default_pattern_accepts_zero_unit() -> None:
    assert infer_unit_no_from_path("20260RB-JGS11-A.dwg", "2026") == "0"


def test_project_no_inference_finds_album_code_not_at_filename_start() -> None:
    filename = "出图版--18185NR-JGS50-A.dwg"

    assert infer_project_no_from_path(filename) == "1818"
    assert infer_unit_no_from_path(filename, "1818") == "5"


def test_replace_batch_identity_reads_project_unit_and_factory_code() -> None:
    assert infer_replace_batch_identity("出图版--20260SC2JGS01-A.dwg") == (
        infer_replace_batch_identity("20260SC2-JGS01-A.dwg")
    )
    assert infer_replace_batch_identity("出图版--20260SC2JGS01-A.dwg").project_no == "2026"
    assert infer_replace_batch_identity("出图版--20260SC2JGS01-A.dwg").unit_no == "0"
    assert infer_replace_batch_identity("出图版--20260SC2JGS01-A.dwg").factory_code == "SC2"

    numeric_factory = infer_replace_batch_identity("19150003JGS01-202603.dwg")
    assert numeric_factory is not None
    assert numeric_factory.project_no == "1915"
    assert numeric_factory.unit_no == "0"
    assert numeric_factory.factory_code == "003"
