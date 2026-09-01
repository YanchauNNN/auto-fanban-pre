"""
瑙勮寖鍔犺浇鍣?- 璇诲彇 documents/鍙傛暟瑙勮寖.yaml

鑱岃矗锛?
- 瑙ｆ瀽YAML骞舵彁渚涚被鍨嬪畨鍏ㄨ闂?
- 鎻愪緵娲剧敓瑙勫垯銆佹槧灏勮〃銆佹ā鏉胯惤鐐圭瓑閰嶇疆
- 缂撳瓨鍔犺浇缁撴灉锛堥伩鍏嶉噸澶嶈В鏋愶級

浣跨敤鏂瑰紡锛?
    spec = SpecLoader.load("documents/鍙傛暟瑙勮寖.yaml")
    roi_profile = spec.get_roi_profile("BASE10")
    cover_bindings = spec.get_cover_bindings("1818")
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, PrivateAttr

DEFAULT_SPEC_PATH = Path("documents") / "参数规范.yaml"
SPEC_PATH_ENV_VAR = "FANBAN_SPEC_PATH"


class PaperVariant(BaseModel):
    """鏍囧噯鍥惧箙灏哄"""

    W: float
    H: float
    profile: str


class ROIProfile(BaseModel):
    """ROI閰嶇疆"""

    description: str
    tolerance: float
    outer_frame: list[float]
    fields: dict[str, list[float]]


class FieldDefinition(BaseModel):
    """瀛楁瑙ｆ瀽瀹氫箟"""

    roi: str
    parse: dict[str, Any]


class CoverBinding(BaseModel):
    """灏侀潰钀界偣閰嶇疆"""

    cell: str
    label: str | None = None
    desc: str | None = None
    split_rule: str | None = None
    font_sizes: list[int] | None = None
    min_font_size: int | None = None
    max_chars_per_line: int | None = None
    shrink_to_fit_fallback: bool = False
    merge: bool = False
    write_mode: str | None = None
    note: str | None = None


class BusinessSpec(BaseModel):
    """Business spec loaded from ????.yaml."""

    schema_version: str
    _source_path: Path | None = PrivateAttr(default=None)

    # 鏋氫妇瀹氫箟
    enums: dict[str, Any] = Field(default_factory=dict)

    # 鏂囨。鐢熸垚妯″潡閰嶇疆
    doc_generation: dict[str, Any] = Field(default_factory=dict)

    # 鍥剧鎻愬彇妯″潡閰嶇疆
    titleblock_extract: dict[str, Any] = Field(default_factory=dict)

    # A4澶氶〉瑙勫垯
    a4_multipage: dict[str, Any] = Field(default_factory=dict)

    # 绠＄悊涓氬姟绾夸簨瀹炴簮
    management_features: dict[str, Any] = Field(default_factory=dict)

    # 任务提交契约（上传接口 form-data / params_json 结构）
    submission_contracts: dict[str, Any] = Field(default_factory=dict)

    # 计算书业务字段、枚举和界面契约
    calculation_book: dict[str, Any] = Field(default_factory=dict)

    # === 渚挎嵎璁块棶鏂规硶 ===

    def get_paper_variants(self) -> dict[str, PaperVariant]:
        """鑾峰彇鏍囧噯鍥惧箙閰嶇疆"""
        raw = self.titleblock_extract.get("paper_variants", {})
        return {k: PaperVariant(**v) for k, v in raw.items()}

    def get_roi_profile(self, profile_id: str) -> ROIProfile | None:
        """鑾峰彇ROI閰嶇疆"""
        profiles = self.titleblock_extract.get("roi_profiles", {})
        if profile_id in profiles:
            return ROIProfile(**profiles[profile_id])
        return None

    def get_field_definitions(self) -> dict[str, FieldDefinition]:
        """鑾峰彇瀛楁瑙ｆ瀽瀹氫箟"""
        raw = self.titleblock_extract.get("field_definitions", {})
        return {k: FieldDefinition(**v) for k, v in raw.items()}

    def get_cover_bindings(self, project_no: str) -> dict[str, CoverBinding]:
        """鑾峰彇灏侀潰钀界偣閰嶇疆"""
        bindings = self.doc_generation.get("templates", {}).get("cover_bindings", {})
        key = "1818" if project_no == "1818" else "common"
        raw = bindings.get(key, {})
        return {
            k: CoverBinding(**v) if isinstance(v, dict) else CoverBinding(cell=str(v))
            for k, v in raw.items()
            if not k.startswith("split_")
        }

    def get_catalog_bindings(self) -> dict[str, Any]:
        """鑾峰彇鐩綍钀界偣閰嶇疆"""
        return self.doc_generation.get("templates", {}).get("catalog_bindings", {})

    def get_design_bindings(self) -> dict[str, Any]:
        """鑾峰彇璁捐鏂囦欢钀界偣閰嶇疆"""
        return self.doc_generation.get("templates", {}).get("design_bindings", {})

    def get_ied_bindings(self) -> dict[str, Any]:
        """鑾峰彇IED璁″垝钀界偣閰嶇疆"""
        return self.doc_generation.get("templates", {}).get("ied_bindings", {})

    def get_derivation_rules(self) -> dict[str, Any]:
        """鑾峰彇娲剧敓瑙勫垯"""
        return self.doc_generation.get("derivations", {})

    def get_mappings(self) -> dict[str, dict[str, str]]:
        """Get field mappings."""
        return self.doc_generation.get("rules", {}).get("mappings", {})

    def get_defaults(self) -> dict[str, Any]:
        """Get default values."""
        return self.doc_generation.get("rules", {}).get("defaults", {})

    def get_same_code_multipage_suffix_pattern(self) -> str:
        """普通图纸同编码多页输出后缀模板。"""
        rules = self.doc_generation.get("rules", {})
        pattern = str(rules.get("same_code_multipage_suffix_pattern") or "").strip()
        return pattern or "{page_index}@{page_total}"

    def get_template_path(self, doc_type: str, project_no: str, variant: str = "") -> str:
        """鑾峰彇妯℃澘璺緞"""
        selection = self.doc_generation.get("templates", {}).get("selection", {})

        if doc_type == "cover":
            if project_no == "1818":
                cover_1818 = selection.get("cover", {}).get("1818", "")
                if isinstance(cover_1818, dict):
                    normalized_variant = str(variant or "").strip()
                    return str(
                        self.resolve_repo_path(
                            cover_1818.get(normalized_variant) or cover_1818.get("default") or ""
                        )
                    )
                return str(self.resolve_repo_path(cover_1818))
            template = selection.get("cover", {}).get("default", "")
            return str(self.resolve_repo_path(template.replace("{variant}", variant)))

        if doc_type == "catalog":
            if project_no == "1818":
                return str(self.resolve_repo_path(selection.get("catalog", {}).get("1818", "")))
            return str(self.resolve_repo_path(selection.get("catalog", {}).get("default", "")))

        return str(self.resolve_repo_path(selection.get(doc_type, "")))

    def get_project_name(self, project_no: str) -> str | None:
        """Return the configured project name for a project number."""
        for item in self.enums.get("project_no", []):
            if not isinstance(item, dict):
                continue
            if str(item.get("id") or "").strip() == str(project_no or "").strip():
                name = str(item.get("name") or "").strip()
                return name or None
        return None

    def get_project_property(
        self,
        project_no: str,
        property_name: str,
    ) -> str:
        """Return one YAML-backed project property without hard-coded mappings."""
        for item in self.enums.get("project_no", []):
            if not isinstance(item, dict):
                continue
            if str(item.get("id") or "").strip() != str(project_no or "").strip():
                continue
            return str(item.get(property_name) or "").strip()
        return ""

    def build_calculation_book_cover_cells(
        self,
        values: dict[str, Any],
    ) -> tuple[str, ...]:
        config = self.calculation_book.get("cover_code", {})
        if not isinstance(config, dict):
            return ()
        project_no_field = str(config.get("project_no_field") or "project_no")
        project_property = str(config.get("project_code_property") or "")
        project_code = self.get_project_property(
            str(values.get(project_no_field) or ""),
            project_property,
        ).upper()
        fixed_value = str(config.get("fixed_third_cell") or "").upper()
        plant_code = str(values.get(str(config.get("plant_code_field") or "")) or "").upper()
        level_code = str(values.get(str(config.get("level_code_field") or "")) or "").upper()
        return (
            *project_code[:2].ljust(2),
            fixed_value,
            *plant_code[:2].ljust(2),
            level_code,
        )

    def get_management_features(self) -> dict[str, Any]:
        return self.management_features

    def get_submission_contracts(self) -> dict[str, Any]:
        return self.submission_contracts

    def resolve_repo_path(self, path_value: str | Path) -> Path:
        path = Path(path_value)
        if path.is_absolute():
            return path
        if self._source_path is not None:
            config_dir = self._source_path.parent
            if config_dir.name.lower() == "documents":
                return (config_dir.parent / path).resolve()
            return (config_dir / path).resolve()
        return path


class SpecLoader:
    """Business spec loader with cached file reads."""

    _instance: SpecLoader | None = None
    _spec: BusinessSpec | None = None

    def __new__(cls) -> SpecLoader:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    @lru_cache(maxsize=8)
    def _load_cached(cls, resolved_path: str) -> BusinessSpec:
        """Load and cache the resolved spec file path."""
        path = Path(resolved_path)
        if not path.exists():
            raise FileNotFoundError(f"瑙勮寖鏂囦欢涓嶅瓨鍦? {path}")

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        spec = BusinessSpec(**data)
        spec._source_path = path
        return spec

    @classmethod
    def load(cls, spec_path: str | Path = DEFAULT_SPEC_PATH) -> BusinessSpec:
        """Load the business spec."""
        path = _resolve_spec_path(spec_path)
        return cls._load_cached(_cache_key(path))

    @classmethod
    def reload(cls, spec_path: str | Path = DEFAULT_SPEC_PATH) -> BusinessSpec:
        """寮哄埗閲嶆柊鍔犺浇锛堟竻闄ょ紦瀛橈級"""
        cls.clear_cache()
        return cls.load(spec_path)

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the internal spec cache."""
        cls._load_cached.cache_clear()


# 渚挎嵎鍑芥暟
def load_spec(spec_path: str | Path = DEFAULT_SPEC_PATH) -> BusinessSpec:
    """鍔犺浇涓氬姟瑙勮寖"""
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
