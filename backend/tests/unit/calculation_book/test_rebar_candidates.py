from __future__ import annotations

import math
from dataclasses import FrozenInstanceError, fields
from types import SimpleNamespace

import pytest

from src.calculation_book.rebar_candidates import (
    RebarCandidate,
    generate_rebar_candidates,
)

XY_DIAMETERS = [16, 18, 20, 25, 28, 32, 36, 40]
XY_PRIORITIES = ["1@200", "1@150", "2@200", "2@150"]
Z_DIAMETERS = [6, 8, 10, 12, 14, 16]
Z_PRIORITIES = [
    "1@400x400",
    "1@200x400",
    "1@200x200",
    "2@400x400",
    "2@200x400",
    "2@200x200",
]


def _config(
    *,
    margin_ratio: float = 0.10,
    xy_diameters: list[int] | None = None,
    xy_priorities: list[str] | None = None,
    z_diameters: list[int] | None = None,
    z_priorities: list[str] | None = None,
    fixed_spec: str = "1C14@400x400",
) -> SimpleNamespace:
    return SimpleNamespace(
        margin_ratio=margin_ratio,
        xy=SimpleNamespace(
            diameters=xy_diameters or XY_DIAMETERS,
            hard_priority=xy_priorities or XY_PRIORITIES,
        ),
        z=SimpleNamespace(
            diameters=z_diameters or Z_DIAMETERS,
            hard_priority=z_priorities or Z_PRIORITIES,
        ),
        zero_or_missing_smx=SimpleNamespace(fixed_spec=fixed_spec),
    )


def _linear_area(*, layers: int, diameter: int, spacing: int) -> float:
    return layers * math.pi * (diameter / 2) ** 2 * (1000 / spacing)


def _grid_area(
    *,
    layers: int,
    diameter: int,
    spacing_primary: int,
    spacing_secondary: int,
) -> float:
    return _linear_area(
        layers=layers,
        diameter=diameter,
        spacing=spacing_primary,
    ) * (1000 / spacing_secondary)


def test_rebar_candidate_has_exact_frozen_contract() -> None:
    assert [field.name for field in fields(RebarCandidate)] == [
        "candidate_id",
        "profile",
        "direction",
        "layers",
        "diameter",
        "spacing_primary",
        "spacing_secondary",
        "priority_rank",
        "actual_area",
        "target_area",
        "excess_area",
        "canonical_specification",
        "narrative_specification",
    ]
    candidate = generate_rebar_candidates(smx=1.0, direction="X")[0]
    with pytest.raises(FrozenInstanceError):
        candidate.diameter = 99  # type: ignore[misc]


def test_generates_all_configured_xy_diameters_with_exact_formula() -> None:
    candidates = generate_rebar_candidates(smx=1.0, direction="x")

    assert [candidate.diameter for candidate in candidates] == XY_DIAMETERS
    assert {candidate.profile for candidate in candidates} == {"linear"}
    assert {candidate.direction for candidate in candidates} == {"X"}
    assert {candidate.priority_rank for candidate in candidates} == {1}
    for candidate in candidates:
        expected = _linear_area(
            layers=1,
            diameter=candidate.diameter,
            spacing=200,
        )
        assert candidate.actual_area == pytest.approx(expected)
        assert candidate.target_area == pytest.approx(1.1)
        assert candidate.excess_area == pytest.approx(expected - 1.1)
        assert candidate.candidate_id == f"linear-l1-d{candidate.diameter}-s200"


def test_generates_all_configured_z_diameters_with_exact_grid_formula() -> None:
    candidates = generate_rebar_candidates(smx=1.0, direction="Z")

    assert [candidate.diameter for candidate in candidates] == Z_DIAMETERS
    assert {candidate.profile for candidate in candidates} == {"grid"}
    assert {candidate.priority_rank for candidate in candidates} == {1}
    for candidate in candidates:
        expected = _grid_area(
            layers=1,
            diameter=candidate.diameter,
            spacing_primary=400,
            spacing_secondary=400,
        )
        assert candidate.actual_area == pytest.approx(expected)
        assert candidate.target_area == pytest.approx(1.1)
        assert candidate.excess_area == pytest.approx(expected - 1.1)
        assert candidate.candidate_id == (
            f"grid-l1-d{candidate.diameter}-s400x400"
        )


@pytest.mark.parametrize("priority", XY_PRIORITIES)
def test_each_xy_priority_obeys_its_exact_capacity_boundary(priority: str) -> None:
    layers_text, spacing_text = priority.split("@", maxsplit=1)
    capacity = _linear_area(
        layers=int(layers_text),
        diameter=max(XY_DIAMETERS),
        spacing=int(spacing_text),
    )
    config = _config(xy_priorities=[priority])

    before = generate_rebar_candidates(
        smx=(capacity - 1e-6) / 1.1,
        direction="X",
        config=config,
    )
    after = generate_rebar_candidates(
        smx=(capacity + 1e-6) / 1.1,
        direction="X",
        config=config,
    )

    assert before[-1].diameter == 40
    assert after == ()


@pytest.mark.parametrize("priority", Z_PRIORITIES)
def test_each_z_priority_obeys_its_exact_capacity_boundary(priority: str) -> None:
    layers_text, spacings_text = priority.split("@", maxsplit=1)
    primary_text, secondary_text = spacings_text.split("x", maxsplit=1)
    capacity = _grid_area(
        layers=int(layers_text),
        diameter=max(Z_DIAMETERS),
        spacing_primary=int(primary_text),
        spacing_secondary=int(secondary_text),
    )
    config = _config(z_priorities=[priority])

    before = generate_rebar_candidates(
        smx=(capacity - 1e-6) / 1.1,
        direction="Z",
        config=config,
    )
    after = generate_rebar_candidates(
        smx=(capacity + 1e-6) / 1.1,
        direction="Z",
        config=config,
    )

    assert before[-1].diameter == 16
    assert after == ()


def test_only_first_qualifying_priority_is_returned_even_if_next_is_closer() -> None:
    target = 7_000.0

    candidates = generate_rebar_candidates(
        smx=target / 1.1,
        direction="Y",
    )

    assert {candidate.priority_rank for candidate in candidates} == {2}
    assert candidates[0].canonical_specification == "1D40间距150"
    assert _linear_area(layers=2, diameter=32, spacing=200) < (
        candidates[0].actual_area
    )


def test_same_priority_uses_unrounded_excess_for_sorting() -> None:
    candidates = generate_rebar_candidates(
        smx=0.01,
        direction="X",
        config=_config(
            xy_diameters=[18, 16],
            xy_priorities=["1@1000000"],
        ),
    )

    assert round(candidates[0].actual_area) == round(candidates[1].actual_area)
    assert [candidate.diameter for candidate in candidates] == [16, 18]
    assert candidates[0].excess_area < candidates[1].excess_area


def test_grid_400x200_is_canonicalized_to_200x400() -> None:
    candidate = generate_rebar_candidates(
        smx=1.0,
        direction="Z",
        config=_config(z_diameters=[14], z_priorities=["1@400x200"]),
    )[0]

    assert (candidate.spacing_primary, candidate.spacing_secondary) == (200, 400)
    assert candidate.candidate_id == "grid-l1-d14-s200x400"
    assert candidate.canonical_specification == "1C14间距200*400"
    assert candidate.narrative_specification == "1排14@200x400"


@pytest.mark.parametrize("smx", [None, 0, 0.0])
def test_z_without_positive_smx_returns_only_the_configured_fixed_candidate(
    smx: float | None,
) -> None:
    candidates = generate_rebar_candidates(smx=smx, direction="Z")

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.candidate_id == "grid-l1-d14-s400x400"
    assert candidate.canonical_specification == "1C14间距400*400"
    assert candidate.target_area == 0


@pytest.mark.parametrize("smx", [None, 0, 0.0])
def test_xy_without_positive_smx_returns_no_candidates(smx: float | None) -> None:
    assert generate_rebar_candidates(smx=smx, direction="X") == ()


def test_returns_empty_instead_of_largest_fallback_when_all_are_insufficient() -> None:
    assert generate_rebar_candidates(smx=1_000_000, direction="X") == ()
    assert generate_rebar_candidates(smx=1_000_000, direction="Z") == ()


def test_uses_injected_mechanism_rules_instead_of_builtin_candidate_values() -> None:
    candidate = generate_rebar_candidates(
        smx=100,
        direction="X",
        config=_config(
            margin_ratio=0.25,
            xy_diameters=[22],
            xy_priorities=["2@175"],
        ),
    )[0]

    assert candidate.target_area == pytest.approx(125)
    assert (candidate.layers, candidate.diameter, candidate.spacing_primary) == (
        2,
        22,
        175,
    )
    assert candidate.candidate_id == "linear-l2-d22-s175"


def test_rejects_duplicate_configured_diameters() -> None:
    with pytest.raises(ValueError, match="重复直径"):
        generate_rebar_candidates(
            smx=1,
            direction="X",
            config=_config(
                xy_diameters=[16, 16],
                xy_priorities=["1@200"],
            ),
        )


def test_rejects_equivalent_grid_priorities_after_canonicalization() -> None:
    with pytest.raises(ValueError, match="重复候选优先级"):
        generate_rebar_candidates(
            smx=1,
            direction="Z",
            config=_config(
                z_diameters=[14],
                z_priorities=["1@400x200", "1@200x400"],
            ),
        )


@pytest.mark.parametrize("smx", [False, True])
def test_rejects_bool_smx(smx: bool) -> None:
    with pytest.raises(ValueError, match="SMX"):
        generate_rebar_candidates(smx=smx, direction="X")


def test_rejects_negative_smx_and_unknown_direction() -> None:
    with pytest.raises(ValueError, match="SMX"):
        generate_rebar_candidates(smx=-1, direction="X")
    with pytest.raises(ValueError, match="方向"):
        generate_rebar_candidates(smx=1, direction="Q")
