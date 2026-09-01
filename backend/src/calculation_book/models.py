from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, computed_field, field_validator


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
    level_code: str
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

    @field_validator("project_no", "version", "subproject_code", "level_code")
    @classmethod
    def normalize_codes(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("level_code")
    @classmethod
    def validate_level_code(cls, value: str) -> str:
        if re.fullmatch(r"[A-Z]", value) is None:
            raise ValueError("层位码必须是单个英文字母")
        return value

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

    @field_validator("document_name")
    @classmethod
    def validate_document_elevation_range(cls, value: str) -> str:
        if _ELEVATION_RANGE.search(value) is None:
            raise ValueError("文件名称必须包含形如 11.450m~15.950m 的厂房标高范围")
        return value

    @field_validator("roof_top_elevation")
    @classmethod
    def validate_roof_above_raft(
        cls,
        value: float,
        info: ValidationInfo,
    ) -> float:
        raft = info.data.get("raft_slab_top_elevation")
        if isinstance(raft, int | float) and value <= float(raft):
            raise ValueError(f"屋面顶标高必须大于筏板顶标高 {float(raft):g}m（当前为 {value:g}m）")
        return value

    @field_validator("factory_extreme_max_temperature")
    @classmethod
    def validate_maximum_above_minimum(
        cls,
        value: float,
        info: ValidationInfo,
    ) -> float:
        minimum = info.data.get("factory_extreme_min_temperature")
        if isinstance(minimum, int | float) and value <= float(minimum):
            raise ValueError(
                f"历史最高温度必须大于历史最低温度 {float(minimum):g}℃（当前为 {value:g}℃）"
            )
        return value

    @field_validator("confirm_ai_normalization")
    @classmethod
    def validate_ai_mode_confirmation(
        cls,
        value: bool,
        info: ValidationInfo,
    ) -> bool:
        if info.data.get("reinforcement_source") is ReinforcementSource.AI_SUGGESTED and value:
            raise ValueError("AI 推荐配筋不能同时确认配筋表 AI 规范化")
        return value

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
