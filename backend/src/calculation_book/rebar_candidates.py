from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

from ..config import load_mechanism_spec
from ..config.mechanism_spec import (
    CalculationBookAiSuggestionDirectionConfig,
    CalculationBookAiSuggestionMechanismConfig,
)
from .reinforcement_input import RebarConfiguration, build_rebar_configuration, parse_rebar_cell


@dataclass(frozen=True)
class RebarCandidate:
    candidate_id: str
    profile: Literal["linear", "grid"]
    direction: str
    layers: int
    diameter: int
    spacing_primary: int
    spacing_secondary: int | None
    priority_rank: int
    actual_area: float
    target_area: float
    excess_area: float
    canonical_specification: str
    narrative_specification: str


_PRIORITY_PATTERN = re.compile(
    r"^(?P<layers>[12])@(?P<primary>\d+)(?:x(?P<secondary>\d+))?$"
)


def _normalized_direction(direction: str) -> str:
    normalized = str(direction).strip().upper()
    if normalized not in {"X", "Y", "Z"}:
        raise ValueError(f"不支持的配筋方向：{direction}")
    return normalized


def _parse_priority(priority: str, *, direction: str) -> tuple[int, int, int | None]:
    normalized = (
        str(priority)
        .strip()
        .lower()
        .replace(" ", "")
        .replace("×", "x")
        .replace("*", "x")
    )
    match = _PRIORITY_PATTERN.fullmatch(normalized)
    if match is None:
        raise ValueError(f"无法识别配筋候选优先级：{priority}")
    layers = int(match.group("layers"))
    spacing_primary = int(match.group("primary"))
    secondary_text = match.group("secondary")
    spacing_secondary = int(secondary_text) if secondary_text is not None else None
    if direction == "Z":
        if spacing_secondary is None:
            raise ValueError(f"Z 向候选优先级必须包含两个间距：{priority}")
        spacing_primary, spacing_secondary = sorted(
            (spacing_primary, spacing_secondary)
        )
    elif spacing_secondary is not None:
        raise ValueError(f"X/Y 向候选优先级只能包含一个间距：{priority}")
    return layers, spacing_primary, spacing_secondary


def _validated_direction_rules(
    direction_config: CalculationBookAiSuggestionDirectionConfig,
    *,
    direction: str,
) -> tuple[tuple[int, ...], tuple[tuple[int, int, int | None], ...]]:
    diameters = tuple(int(value) for value in direction_config.diameters)
    if len(set(diameters)) != len(diameters):
        raise ValueError("配筋候选配置包含重复直径")

    priorities: list[tuple[int, int, int | None]] = []
    seen_priorities: set[tuple[int, int, int | None]] = set()
    for value in direction_config.hard_priority:
        parsed = _parse_priority(value, direction=direction)
        if parsed in seen_priorities:
            raise ValueError(f"配筋候选配置包含重复候选优先级：{value}")
        seen_priorities.add(parsed)
        priorities.append(parsed)
    return diameters, tuple(priorities)


def _candidate_from_configuration(
    configuration: RebarConfiguration,
    *,
    direction: str,
    priority_rank: int,
    target_area: float,
) -> RebarCandidate:
    profile: Literal["linear", "grid"] = "grid" if direction == "Z" else "linear"
    spacing_suffix = str(configuration.spacing_primary)
    if configuration.spacing_secondary is not None:
        spacing_suffix += f"x{configuration.spacing_secondary}"
    candidate_id = (
        f"{profile}-l{configuration.layers}-d{configuration.diameter}"
        f"-s{spacing_suffix}"
    )
    return RebarCandidate(
        candidate_id=candidate_id,
        profile=profile,
        direction=direction,
        layers=configuration.layers,
        diameter=configuration.diameter,
        spacing_primary=configuration.spacing_primary,
        spacing_secondary=configuration.spacing_secondary,
        priority_rank=priority_rank,
        actual_area=configuration.actual_area,
        target_area=target_area,
        excess_area=configuration.actual_area - target_area,
        canonical_specification=configuration.canonical_specification,
        narrative_specification=configuration.narrative_specification,
    )


def _fixed_z_candidate(
    fixed_specification: str,
) -> RebarCandidate:
    parsed = parse_rebar_cell(fixed_specification, direction="Z").selected
    spacing_secondary = parsed.spacing_secondary
    if spacing_secondary is None:
        raise ValueError("Z 向固定候选必须包含两个间距")
    spacing_primary, spacing_secondary = sorted(
        (parsed.spacing_primary, spacing_secondary)
    )
    configuration = build_rebar_configuration(
        layers=parsed.layers,
        diameter=parsed.diameter,
        spacing_primary=spacing_primary,
        spacing_secondary=spacing_secondary,
        direction="Z",
    )
    return _candidate_from_configuration(
        configuration,
        direction="Z",
        priority_rank=1,
        target_area=0.0,
    )


def generate_rebar_candidates(
    *,
    smx: float | int | str | None,
    direction: str,
    config: CalculationBookAiSuggestionMechanismConfig | None = None,
) -> tuple[RebarCandidate, ...]:
    normalized_direction = _normalized_direction(direction)
    if isinstance(smx, bool):
        raise ValueError("SMX 不接受布尔值")
    if smx is None or (isinstance(smx, str) and not smx.strip()):
        smx_value = 0.0
    else:
        try:
            smx_value = float(smx)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"SMX 必须是数值：{smx}") from exc
    if not math.isfinite(smx_value) or smx_value < 0:
        raise ValueError(f"SMX 必须是非负有限数值：{smx}")

    mechanism = config or load_mechanism_spec().calculation_book.ai_suggestion
    direction_config = (
        mechanism.z if normalized_direction == "Z" else mechanism.xy
    )
    diameters, priorities = _validated_direction_rules(
        direction_config,
        direction=normalized_direction,
    )
    if smx_value == 0:
        if normalized_direction != "Z":
            return ()
        return (_fixed_z_candidate(mechanism.zero_or_missing_smx.fixed_spec),)

    target_area = smx_value * (1 + float(mechanism.margin_ratio))
    for priority_rank, (
        layers,
        spacing_primary,
        spacing_secondary,
    ) in enumerate(
        priorities,
        start=1,
    ):
        qualifying: list[RebarCandidate] = []
        for diameter in diameters:
            configuration = build_rebar_configuration(
                layers=layers,
                diameter=diameter,
                spacing_primary=spacing_primary,
                spacing_secondary=spacing_secondary,
                direction=normalized_direction,
            )
            if configuration.actual_area < target_area:
                continue
            qualifying.append(
                _candidate_from_configuration(
                    configuration,
                    direction=normalized_direction,
                    priority_rank=priority_rank,
                    target_area=target_area,
                )
            )
        if qualifying:
            return tuple(
                sorted(
                    qualifying,
                    key=lambda candidate: (
                        candidate.excess_area,
                        candidate.actual_area,
                        candidate.diameter,
                        candidate.candidate_id,
                    ),
                )
            )
    return ()
