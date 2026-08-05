from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator


class CalculationBookTemplate(StrEnum):
    INTERNAL_STRUCTURE = "internal_structure"
    NUCLEAR_ISLAND_PLANT = "nuclear_island_plant"


class ReinforcementSource(StrEnum):
    PROVIDED = "provided"
    AI_SUGGESTED = "ai_suggested"


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
    include_slab_stress: bool = False
    reinforcement_source: ReinforcementSource = ReinforcementSource.PROVIDED
    confirm_ai_normalization: bool = False
    manual_confirmations: dict[str, int] = Field(default_factory=dict)
    preflight_token: str = Field(default="", max_length=100)

    @field_validator("project_no", "version", "subproject_code")
    @classmethod
    def normalize_codes(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("manual_confirmations", mode="before")
    @classmethod
    def normalize_manual_confirmations(
        cls,
        value: object,
    ) -> dict[str, int]:
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise ValueError("人工确认映射必须是墙号到配筋表行号的对象")
        normalized: dict[str, int] = {}
        for wall_id, source_row in value.items():
            row_number = int(source_row)
            if row_number <= 0:
                raise ValueError("人工确认的配筋表行号必须大于 0")
            normalized[str(wall_id).strip().upper()] = row_number
        return normalized

    @model_validator(mode="after")
    def validate_relationships(self) -> CalculationBookParams:
        if self.factory_extreme_min_temperature >= self.factory_extreme_max_temperature:
            raise ValueError("历史最低温度必须小于历史最高温度")
        if self.raft_slab_top_elevation >= self.roof_top_elevation:
            raise ValueError("筏板顶标高必须小于屋面顶标高")
        if (
            self.reinforcement_source is ReinforcementSource.AI_SUGGESTED
            and self.confirm_ai_normalization
        ):
            raise ValueError("AI 推荐配筋不能同时确认配筋表 AI 规范化")
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
