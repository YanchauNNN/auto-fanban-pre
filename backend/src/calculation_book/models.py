from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator


class CalculationBookTemplate(StrEnum):
    INTERNAL_STRUCTURE = "internal_structure"
    NUCLEAR_ISLAND_PLANT = "nuclear_island_plant"


ALL_PLANTS = ("RX", "NH", "SD", "SU", "KA")
_ELEVATION_RANGE = re.compile(
    r"(?P<start>[+-]?\d+(?:\.\d+)?)\s*m\s*[~～—-]\s*(?P<end>[+-]?\d+(?:\.\d+)?)\s*m",
    re.IGNORECASE,
)


class CalculationBookParams(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    template_type: CalculationBookTemplate
    project_no: str = Field(min_length=1, max_length=32)
    project_name: str = Field(min_length=1, max_length=200)
    internal_code: str = Field(min_length=3, max_length=100)
    version: str = Field(default="A", min_length=1, max_length=16)
    subproject_code: str = Field(min_length=1, max_length=16)
    subproject_name: str = Field(min_length=1, max_length=100)
    design_phase: str = Field(min_length=1, max_length=100)
    document_name: str = Field(min_length=1, max_length=240)
    workshop_length: float = Field(gt=0, le=10_000)
    workshop_width: float = Field(gt=0, le=10_000)
    raft_slab_top_elevation: float = Field(ge=-1_000, le=10_000)
    roof_top_elevation: float = Field(ge=-1_000, le=10_000)
    factory_extreme_min_temperature: float = Field(ge=-100, le=100)
    factory_extreme_max_temperature: float = Field(ge=-100, le=100)
    site_soil_temperature: float = Field(ge=-100, le=100)

    @field_validator("project_no", "version", "subproject_code")
    @classmethod
    def normalize_codes(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_relationships(self) -> "CalculationBookParams":
        if self.factory_extreme_min_temperature >= self.factory_extreme_max_temperature:
            raise ValueError("历史最低温度必须小于历史最高温度")
        if self.raft_slab_top_elevation >= self.roof_top_elevation:
            raise ValueError("筏板顶标高必须小于屋面顶标高")
        if _ELEVATION_RANGE.search(self.document_name) is None:
            raise ValueError("文件名称必须包含形如 0.000m~15.000m 的厂房标高范围")
        return self

    @computed_field
    @property
    def project_number(self) -> str:
        return self.project_no

    @computed_field
    @property
    def document_serial_number(self) -> str:
        alphanumeric = re.sub(r"[^A-Za-z0-9]", "", self.internal_code)
        return alphanumeric[-2:] if len(alphanumeric) >= 2 else alphanumeric

    @computed_field
    @property
    def plant_elevation_range(self) -> str:
        match = _ELEVATION_RANGE.search(self.document_name)
        if match is None:  # guarded by model validation
            raise ValueError("文件名称中未识别到厂房标高范围")
        return f"{match.group('start')}m~{match.group('end')}m"

    @computed_field
    @property
    def other_plants(self) -> list[str]:
        current = self.subproject_code.upper()
        return [plant for plant in ALL_PLANTS if plant != current]
