from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.calculation_book.models import CalculationBookParams, CalculationBookTemplate


def _valid_payload() -> dict[str, object]:
    return {
        "template_type": "internal_structure",
        "project_no": "JQ",
        "project_name": "浙江金七门核电厂1、2号机组",
        "internal_code": "JQ00-NN-001",
        "version": "A",
        "subproject_code": "RX",
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
    assert params.project_number == "JQ"
    assert params.document_serial_number == "01"
    assert params.plant_elevation_range == "0.000m~15.000m"
    assert "RX" not in params.other_plants


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
