from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.calculation_book import models as calculation_models
from src.calculation_book.models import CalculationBookParams, CalculationBookTemplate


def _valid_payload() -> dict[str, object]:
    return {
        "template_type": "internal_structure",
        "project_no": "JQ",
        "project_name": "浙江金七门核电厂1、2号机组",
        "internal_code": "JQ00-NN-001",
        "version": "A",
        "subproject_code": "RX",
        "level_code": "r",
        "subproject_name": "内部结构",
        "design_phase": "施工图设计",
        "document_name": "0.000m~15.000m配筋计算书",
        "workshop_length": 72.5,
        "workshop_width": 48.0,
        "raft_slab_top_elevation": -8.5,
        "roof_top_elevation": 31.2,
        "factory_extreme_min_temperature": -18.0,
        "factory_extreme_max_temperature": 39.0,
        "site_soil_temperature": 15.0,
    }


def test_calculation_params_are_strict_and_derive_template_values() -> None:
    params = CalculationBookParams.model_validate(_valid_payload())

    assert params.template_type is CalculationBookTemplate.INTERNAL_STRUCTURE
    assert params.reinforcement_source is calculation_models.ReinforcementSource.PROVIDED
    assert params.include_slab_stress is False
    assert params.project_number == "JQ"
    assert params.document_serial_number == "01"
    assert params.plant_elevation_range == "0.000m~15.000m"
    assert "RX" not in params.other_plants
    assert params.level_code == "R"


@pytest.mark.parametrize("value", ["", "RR", "1", "层"])
def test_calculation_params_reject_invalid_level_code(value: str) -> None:
    payload = _valid_payload()
    payload["level_code"] = value

    with pytest.raises(ValidationError, match="层位码"):
        CalculationBookParams.model_validate(payload)


def test_calculation_params_accept_optional_slab_stress() -> None:
    payload = _valid_payload()
    payload["include_slab_stress"] = True

    params = CalculationBookParams.model_validate(payload)

    assert params.include_slab_stress is True


def test_calculation_params_accept_ai_suggested_reinforcement() -> None:
    payload = _valid_payload()
    payload["reinforcement_source"] = "ai_suggested"

    params = CalculationBookParams.model_validate(payload)

    assert params.reinforcement_source is calculation_models.ReinforcementSource.AI_SUGGESTED


def test_ai_suggested_reinforcement_rejects_ai_normalization_confirmation() -> None:
    payload = _valid_payload()
    payload.update(
        reinforcement_source="ai_suggested",
        confirm_ai_normalization=True,
    )

    with pytest.raises(ValidationError, match="AI 推荐配筋.*AI 规范化"):
        CalculationBookParams.model_validate(payload)


def test_provided_reinforcement_keeps_nonstandard_normalization_confirmation() -> None:
    payload = _valid_payload()
    payload["confirm_ai_normalization"] = True

    params = CalculationBookParams.model_validate(payload)

    assert params.reinforcement_source is calculation_models.ReinforcementSource.PROVIDED
    assert params.confirm_ai_normalization is True


@pytest.mark.parametrize(
    "request_only_override",
    [
        {"skill_root": "client/controlled"},
        {"xy_diameters": [99]},
        {"max_consecutive_base_failures": 99},
    ],
)
def test_calculation_params_reject_server_owned_ai_overrides(
    request_only_override: dict[str, object],
) -> None:
    payload = _valid_payload()
    payload.update(request_only_override)

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CalculationBookParams.model_validate(payload)


def test_persisted_params_exclude_computed_template_values_and_can_be_revalidated() -> None:
    params = CalculationBookParams.model_validate(_valid_payload())

    persisted = params.model_dump(mode="json", exclude_computed_fields=True)

    assert "project_number" not in persisted
    assert "document_serial_number" not in persisted
    assert CalculationBookParams.model_validate(persisted).project_no == "JQ"


def test_rejects_document_name_without_a_plant_elevation_range() -> None:
    payload = _valid_payload()
    payload["document_name"] = "内部结构配筋计算书"

    with pytest.raises(ValidationError, match="标高范围"):
        CalculationBookParams.model_validate(payload)


def test_rejects_inconsistent_temperature_range() -> None:
    payload = _valid_payload()
    payload["factory_extreme_min_temperature"] = 40

    with pytest.raises(ValidationError, match="最低温度"):
        CalculationBookParams.model_validate(payload)


def test_relationship_errors_are_collected_on_every_editable_field() -> None:
    payload = _valid_payload()
    payload.update(
        document_name="11111",
        raft_slab_top_elevation=15,
        roof_top_elevation=15,
        factory_extreme_min_temperature=15,
        factory_extreme_max_temperature=15,
    )

    with pytest.raises(ValidationError) as captured:
        CalculationBookParams.model_validate(payload)

    errors_by_field = {
        (str(error["loc"][-1]) if error["loc"] else "<root>"): str(error["msg"])
        for error in captured.value.errors(include_url=False)
    }
    assert set(errors_by_field) >= {
        "document_name",
        "roof_top_elevation",
        "factory_extreme_max_temperature",
    }
    assert "标高范围" in errors_by_field["document_name"]
    assert "筏板顶标高 15m" in errors_by_field["roof_top_elevation"]
    assert "历史最低温度 15℃" in errors_by_field["factory_extreme_max_temperature"]
