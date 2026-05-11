from __future__ import annotations

from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _first_dxf(folder: Path) -> Path:
    matches = sorted(folder.glob("*.dxf"))
    if not matches:
        pytest.skip(f"factory index map fixture missing: {folder}")
    return matches[0]


def _source_dxf() -> Path:
    return _first_dxf(
        _repo_root()
        / "test"
        / "block_replace_validation"
        / "20162PR-JGS01-B"
        / "dxf"
    )


def _template_2026_dxf() -> Path:
    folder = _repo_root() / "test" / "\u5382\u623f\u7d22\u5f15\u56fe-20260508" / "dxf"
    matches = sorted(folder.glob("2026*.dxf"))
    if not matches:
        pytest.skip(f"2026 factory index map template fixture missing: {folder}")
    return matches[0]


def _template_dxf(pattern: str) -> Path:
    folder = _repo_root() / "test" / "\u5382\u623f\u7d22\u5f15\u56fe-20260508" / "dxf"
    matches = sorted(folder.glob(pattern))
    if not matches:
        pytest.skip(f"factory index map template fixture missing: {folder}/{pattern}")
    return matches[0]


def test_detector_finds_two_2016_factory_index_maps() -> None:
    from src.audit_replace.factory_index_maps import FactoryIndexMapDetector

    candidates = FactoryIndexMapDetector().detect(_source_dxf())

    assert len(candidates) == 2
    assert {candidate.angle_text for candidate in candidates} == {'40\u00b044\'40"'}
    assert {candidate.angle_key for candidate in candidates} == {"040-44-40"}
    assert {candidate.source_block_name for candidate in candidates} == {"regfdfd"}
    assert [round(candidate.compass.radius, 3) for candidate in candidates] == [
        354.442,
        354.442,
    ]
    assert {round(candidate.source_bounds.height, 3) for candidate in candidates} == {5433.94}


def test_template_reader_identifies_2026_anchor_angle_and_compass() -> None:
    from src.audit_replace.factory_index_maps import FactoryIndexMapTemplate

    template = FactoryIndexMapTemplate.from_dxf(_template_2026_dxf(), project_no="2026")

    assert template.project_no == "2026"
    assert template.angle_key == "024-04-17.09"
    assert template.angle_text == "24\u00b04'17.09\""
    assert round(template.compass.radius, 3) == 498.137
    assert round(template.bounds.width, 3) == 6382.629
    assert round(template.bounds.height, 3) == 2627.611


def test_template_reader_accepts_1818_compass_without_angle() -> None:
    from src.audit_replace.factory_index_maps import FactoryIndexMapTemplate

    template = FactoryIndexMapTemplate.from_dxf(_template_dxf("1818*.dxf"), project_no="1818")

    assert template.project_no == "1818"
    assert template.angle_key is None
    assert template.angle_text is None
    assert round(template.compass.radius, 3) == 582.24
    assert template.bounds.width > 0
    assert template.bounds.height > 0


def test_replacement_plan_maps_each_source_candidate_to_2026_template() -> None:
    from src.audit_replace.factory_index_maps import build_factory_index_replacement_plan

    plan = build_factory_index_replacement_plan(
        source_project_no="2016",
        target_project_no="2026",
        source_dxf=_source_dxf(),
        target_template_dxf=_template_2026_dxf(),
        target_template_dwg=Path("documents_bin/factory_index_maps/2026.dwg"),
    )

    assert plan.enabled is True
    assert plan.source_project_no == "2016"
    assert plan.target_project_no == "2026"
    assert plan.target_template.angle_key == "024-04-17.09"
    assert len(plan.actions) == 2
    assert {action.source_angle_key for action in plan.actions} == {"040-44-40"}
    assert {action.target_angle_key for action in plan.actions} == {"024-04-17.09"}
    assert all(action.scale > 0 for action in plan.actions)
    assert {round(action.target_bounds.height, 3) for action in plan.actions} == {2627.611}
    assert {round(action.source_bounds.height, 3) for action in plan.actions} == {5433.94}
    expected_scales = {
        round(
            min(
                action.source_bounds.width / action.target_bounds.width,
                action.source_bounds.height / action.target_bounds.height,
            ),
            6,
        )
        for action in plan.actions
    }
    assert {round(action.fit_bbox_scale, 6) for action in plan.actions} == expected_scales


def test_replacement_plan_skips_non_block_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.audit_replace import factory_index_maps as maps

    non_block_candidate = maps.FactoryIndexCandidate(
        layout="Model",
        angle_text='49\u00b015\'00"',
        angle_key="049-15-00",
        angle_position=maps.Point2D(10.0, 10.0),
        compass=maps.CircleFeature(
            layout="Model",
            space="modelspace",
            handle="C1",
            center=maps.Point2D(0.0, 0.0),
            radius=372.164,
        ),
        score=10.0,
        source_block_name=None,
        source_insert_handle=None,
        source_insert_point=None,
        source_bounds=None,
    )
    template = maps.FactoryIndexMapTemplate(
        project_no="2026",
        template_dxf=Path("template.dxf"),
        angle_text='24\u00b04\'17.09"',
        angle_key="024-04-17.09",
        compass=maps.CircleFeature(
            layout="Model",
            space="modelspace",
            handle="TC1",
            center=maps.Point2D(0.0, 0.0),
            radius=498.137,
        ),
        bounds=maps.BBox2D(0.0, 0.0, 100.0, 50.0),
    )

    monkeypatch.setattr(
        maps.FactoryIndexMapDetector,
        "detect",
        lambda self, dxf_path: [non_block_candidate],
    )
    monkeypatch.setattr(
        maps.FactoryIndexMapTemplate,
        "from_dxf",
        classmethod(lambda cls, template_dxf, *, project_no: template),
    )

    plan = maps.build_factory_index_replacement_plan(
        source_project_no="2016",
        target_project_no="2026",
        source_dxf=Path("source.dxf"),
        target_template_dxf=Path("template.dxf"),
        target_template_dwg=Path("template.dwg"),
    )

    assert plan.enabled is False
    assert plan.actions == []


def test_angle_parser_normalizes_autocad_mtext_control_codes() -> None:
    from src.audit_replace.factory_index_maps import angle_key, canonical_angle_text

    value = "\\A1;24\\U+00B04'17.09\""

    assert angle_key(value) == "024-04-17.09"
    assert canonical_angle_text(value) == '24\u00b04\'17.09"'
