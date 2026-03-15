"""
规范加载器 - 读取 documents/参数规范.yaml

职责：
- 解析YAML并提供类型安全访问
- 提供派生规则、映射表、模板落点等配置
- 缓存加载结果（避免重复解析）

使用方式：
    spec = SpecLoader.load("documents/参数规范.yaml")
    roi_profile = spec.get_roi_profile("BASE10")
    cover_bindings = spec.get_cover_bindings("1818")
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


DEFAULT_SPEC_PATH = Path("documents/参数规范.yaml")
SPEC_PATH_ENV_VAR = "FANBAN_SPEC_PATH"


class PaperVariant(BaseModel):
    """标准图幅尺寸"""
    W: float
    H: float
    profile: str


class ROIProfile(BaseModel):
    """ROI配置"""
    description: str
    tolerance: float
    outer_frame: list[float]
    fields: dict[str, list[float]]


class FieldDefinition(BaseModel):
    """字段解析定义"""
    roi: str
    parse: dict[str, Any]


class CoverBinding(BaseModel):
    """封面落点配置"""
    cell: str
    label: str | None = None
    desc: str | None = None
    split_rule: str | None = None
    merge: bool = False
    write_mode: str | None = None
    note: str | None = None


class BusinessSpec(BaseModel):
    """业务规范（参数规范.yaml 的结构化表示）"""
    schema_version: str

    # 枚举定义
    enums: dict[str, Any] = Field(default_factory=dict)

    # 文档生成模块配置
    doc_generation: dict[str, Any] = Field(default_factory=dict)

    # 图签提取模块配置
    titleblock_extract: dict[str, Any] = Field(default_factory=dict)

    # A4多页规则
    a4_multipage: dict[str, Any] = Field(default_factory=dict)

    # === 便捷访问方法 ===

    def get_paper_variants(self) -> dict[str, PaperVariant]:
        """获取标准图幅配置"""
        raw = self.titleblock_extract.get("paper_variants", {})
        return {k: PaperVariant(**v) for k, v in raw.items()}

    def get_roi_profile(self, profile_id: str) -> ROIProfile | None:
        """获取ROI配置"""
        profiles = self.titleblock_extract.get("roi_profiles", {})
        if profile_id in profiles:
            return ROIProfile(**profiles[profile_id])
        return None

    def get_field_definitions(self) -> dict[str, FieldDefinition]:
        """获取字段解析定义"""
        raw = self.titleblock_extract.get("field_definitions", {})
        return {k: FieldDefinition(**v) for k, v in raw.items()}

    def get_cover_bindings(self, project_no: str) -> dict[str, CoverBinding]:
        """获取封面落点配置"""
        bindings = self.doc_generation.get("templates", {}).get("cover_bindings", {})
        key = "1818" if project_no == "1818" else "common"
        raw = bindings.get(key, {})
        return {k: CoverBinding(**v) if isinstance(v, dict) else CoverBinding(cell=str(v))
                for k, v in raw.items() if not k.startswith("split_")}

    def get_catalog_bindings(self) -> dict[str, Any]:
        """获取目录落点配置"""
        return self.doc_generation.get("templates", {}).get("catalog_bindings", {})

    def get_design_bindings(self) -> dict[str, Any]:
        """获取设计文件落点配置"""
        return self.doc_generation.get("templates", {}).get("design_bindings", {})

    def get_ied_bindings(self) -> dict[str, Any]:
        """获取IED计划落点配置"""
        return self.doc_generation.get("templates", {}).get("ied_bindings", {})

    def get_derivation_rules(self) -> dict[str, Any]:
        """获取派生规则"""
        return self.doc_generation.get("derivations", {})

    def get_mappings(self) -> dict[str, dict[str, str]]:
        """获取映射表"""
        return self.doc_generation.get("rules", {}).get("mappings", {})

    def get_defaults(self) -> dict[str, Any]:
        """获取默认值"""
        return self.doc_generation.get("rules", {}).get("defaults", {})

    def get_template_path(self, doc_type: str, project_no: str, variant: str = "") -> str:
        """获取模板路径"""
        selection = self.doc_generation.get("templates", {}).get("selection", {})

        if doc_type == "cover":
            if project_no == "1818":
                cover_1818 = selection.get("cover", {}).get("1818", "")
                if isinstance(cover_1818, dict):
                    normalized_variant = str(variant or "").strip()
                    return str(
                        cover_1818.get(normalized_variant)
                        or cover_1818.get("default")
                        or ""
                    )
                return str(cover_1818)
            template = selection.get("cover", {}).get("default", "")
            return template.replace("{variant}", variant)

        if doc_type == "catalog":
            if project_no == "1818":
                return selection.get("catalog", {}).get("1818", "")
            return selection.get("catalog", {}).get("default", "")

        return selection.get(doc_type, "")


class SpecLoader:
    """规范加载器（单例模式+缓存）"""

    _instance: SpecLoader | None = None
    _spec: BusinessSpec | None = None

    def __new__(cls) -> SpecLoader:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    @lru_cache(maxsize=8)
    def _load_cached(cls, resolved_path: str) -> BusinessSpec:
        """按解析后的真实路径缓存规范，避免默认参数缓存污染环境覆盖场景。"""
        path = Path(resolved_path)
        if not path.exists():
            raise FileNotFoundError(f"规范文件不存在: {path}")

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return BusinessSpec(**data)

    @classmethod
    def load(cls, spec_path: str | Path = DEFAULT_SPEC_PATH) -> BusinessSpec:
        """加载并缓存规范"""
        path = _resolve_spec_path(spec_path)
        return cls._load_cached(_cache_key(path))

    @classmethod
    def reload(cls, spec_path: str | Path = DEFAULT_SPEC_PATH) -> BusinessSpec:
        """强制重新加载（清除缓存）"""
        cls.clear_cache()
        return cls.load(spec_path)

    @classmethod
    def clear_cache(cls) -> None:
        """清空内部缓存。"""
        cls._load_cached.cache_clear()


# 便捷函数
def load_spec(spec_path: str | Path = DEFAULT_SPEC_PATH) -> BusinessSpec:
    """加载业务规范"""
    return SpecLoader.load(spec_path)


def _resolve_spec_path(spec_path: str | Path) -> Path:
    path = Path(spec_path)
    if path == DEFAULT_SPEC_PATH:
        env_path = os.getenv(SPEC_PATH_ENV_VAR)
        if env_path:
            return Path(env_path)
    return path


def _cache_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except Exception:
        return str(path.absolute())
