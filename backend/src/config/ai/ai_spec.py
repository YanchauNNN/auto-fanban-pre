"""
AI layer configuration loader for documents/AI/参数规范_AI.yaml.

This module keeps AI/runtime parameters separate from the business spec and
the CAD/Office runtime spec. API keys are resolved at runtime and are never
included in public dumps or repr output.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

DEFAULT_AI_SPEC_PATH = Path("documents") / "AI" / "参数规范_AI.yaml"
FALLBACK_AI_SPEC_PATH = Path("config") / "AI" / "参数规范_AI.yaml"
LEGACY_AI_SPEC_PATHS = (
    Path("documents") / "参数规范_AI.yaml",
    Path("config") / "参数规范_AI.yaml",
)
AI_SPEC_PATH_ENV_VAR = "FANBAN_AI_SPEC_PATH"


class AiDeploymentProfileConfig(BaseModel):
    network_mode: str = "intranet_only"
    allow_external_network: bool = False
    frontend_direct_model_access: bool = False


class AiBootstrapContractConfig(BaseModel):
    ai_spec_path_env_var: str = AI_SPEC_PATH_ENV_VAR
    api_key_env_var: str = "FANBAN_AI_API_KEY"
    base_url_env_var: str = "FANBAN_AI_BASE_URL"


class AiModelGatewayConfig(BaseModel):
    provider: str = "openai_compatible"
    base_url: str = "http://127.0.0.1:8001/v1"
    api_key_policy: str = "env_only"
    api_key: str | None = Field(default=None, repr=False)
    timeout_sec: int = 60
    max_retries: int = 1
    retry_backoff_ms: int = 800


class AiChatModelConfig(BaseModel):
    model: str = "internal-chat"
    temperature: float = 0.1
    max_output_tokens: int = 2048


class AiStructuredModelConfig(BaseModel):
    model: str = "internal-chat"
    require_json_schema: bool = True


class AiEmbeddingModelConfig(BaseModel):
    model: str = "internal-embedding"
    dimensions: int = 1024
    batch_size: int = 64


class AiModelsConfig(BaseModel):
    chat: AiChatModelConfig = Field(default_factory=AiChatModelConfig)
    structured: AiStructuredModelConfig = Field(default_factory=AiStructuredModelConfig)
    embedding: AiEmbeddingModelConfig = Field(default_factory=AiEmbeddingModelConfig)


class AiElementPackageConfig(BaseModel):
    enabled: bool = True
    input_extensions: list[str] = Field(default_factory=lambda: [".dwg", ".dxf"])
    output_root: str = "outputs/drawing-understanding"
    dxf_cache_dir_name: str = "dxf"
    max_geometry_elements_per_drawing: int = 200000
    include_text_elements: bool = True
    include_geometry_elements: bool = True
    include_titleblock_frames: bool = True
    infer_identity_from_titleblock: bool = True


class AiSemanticTagsConfig(BaseModel):
    enabled: bool = True
    tag_set: list[str] = Field(default_factory=list)
    internal_code_pattern: str = (
        r"\b(?P<project_no>\d{4})(?P<unit_no>[1-9])?[A-Z]{2,4}-[A-Z]{2,5}\d{2}-\d{3}\b"
    )
    external_code_pattern: str = r"\b[A-Z0-9]{19}\b"
    known_project_nos: list[str] = Field(default_factory=list)
    title_keywords: list[str] = Field(default_factory=list)
    wall_keywords: list[str] = Field(default_factory=list)


class AiDrawingUnderstandingConfig(BaseModel):
    element_package: AiElementPackageConfig = Field(default_factory=AiElementPackageConfig)
    semantic_tags: AiSemanticTagsConfig = Field(default_factory=AiSemanticTagsConfig)


class AiOfficeTemplateParsingConfig(BaseModel):
    parse_docx_embedded_xlsx: bool = True
    parse_excel_headers: bool = True
    max_preview_cells: int = 220


class AiFactoryIndexMapParsingConfig(BaseModel):
    enabled: bool = True
    source_root: str = "documents_bin/factory_index_maps"
    required_anchor_types: list[str] = Field(default_factory=lambda: ["angle_text", "compass"])
    variant_discriminators: dict[str, dict[str, dict[str, list[str]]]] = Field(
        default_factory=dict,
    )


class AiTemplateUnderstandingConfig(BaseModel):
    enabled: bool = True
    output_root: str = "outputs/template-understanding"
    office: AiOfficeTemplateParsingConfig = Field(default_factory=AiOfficeTemplateParsingConfig)
    factory_index_maps: AiFactoryIndexMapParsingConfig = Field(
        default_factory=AiFactoryIndexMapParsingConfig,
    )


class AiVectorStoreConfig(BaseModel):
    backend: str = "local_jsonl"
    path: str = "storage/ai/vector-store"
    collection_name: str = "fanban_documents"


class AiChunkingConfig(BaseModel):
    max_chars: int = 1800
    overlap_chars: int = 200
    preserve_headings: bool = True


class AiKnowledgeBaseConfig(BaseModel):
    enabled: bool = False
    source_roots: list[str] = Field(default_factory=list)
    vector_store: AiVectorStoreConfig = Field(default_factory=AiVectorStoreConfig)
    chunking: AiChunkingConfig = Field(default_factory=AiChunkingConfig)


class AiQAAssistantConfig(BaseModel):
    enabled: bool = False
    mode: str = "rule_based_seed"
    max_evidence_items: int = 20
    max_context_chars: int = 12000
    unsupported_question_policy: str = "explicit_refusal"


class AiPromptInjectionGuardConfig(BaseModel):
    enabled: bool = True
    untrusted_content_fields: list[str] = Field(default_factory=list)


class AiSafetyConfig(BaseModel):
    model_output_must_be_grounded: bool = True
    allow_model_to_modify_dwg: bool = False
    allow_model_to_modify_yaml: bool = False
    allow_model_to_submit_workflow: bool = False
    sensitive_paths: list[str] = Field(default_factory=list)
    prompt_injection_guard: AiPromptInjectionGuardConfig = Field(
        default_factory=AiPromptInjectionGuardConfig,
    )


class AiAuditAndCacheConfig(BaseModel):
    request_log_enabled: bool = True
    request_log_dir: str = "storage/ai/logs"
    cache_enabled: bool = True
    cache_dir: str = "storage/ai/cache"
    redact_api_key_in_logs: bool = True


class AiLayerConfig(BaseModel):
    enabled: bool = False
    deployment_profile: AiDeploymentProfileConfig = Field(default_factory=AiDeploymentProfileConfig)
    bootstrap_contract: AiBootstrapContractConfig = Field(default_factory=AiBootstrapContractConfig)
    model_gateway: AiModelGatewayConfig = Field(default_factory=AiModelGatewayConfig)
    models: AiModelsConfig = Field(default_factory=AiModelsConfig)
    drawing_understanding: AiDrawingUnderstandingConfig = Field(
        default_factory=AiDrawingUnderstandingConfig,
    )
    template_understanding: AiTemplateUnderstandingConfig = Field(
        default_factory=AiTemplateUnderstandingConfig,
    )
    knowledge_base: AiKnowledgeBaseConfig = Field(default_factory=AiKnowledgeBaseConfig)
    qa_assistant: AiQAAssistantConfig = Field(default_factory=AiQAAssistantConfig)
    safety: AiSafetyConfig = Field(default_factory=AiSafetyConfig)
    audit_and_cache: AiAuditAndCacheConfig = Field(default_factory=AiAuditAndCacheConfig)


class ResolvedAiGatewayConfig(BaseModel):
    provider: str
    base_url: str
    api_key_env_var: str
    base_url_env_var: str
    api_key_policy: str
    api_key: str | None = Field(default=None, repr=False)
    timeout_sec: int
    max_retries: int
    retry_backoff_ms: int

    def safe_public_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "api_key_env_var": self.api_key_env_var,
            "base_url_env_var": self.base_url_env_var,
            "api_key_policy": self.api_key_policy,
            "api_key": _mask_secret(self.api_key),
            "timeout_sec": self.timeout_sec,
            "max_retries": self.max_retries,
            "retry_backoff_ms": self.retry_backoff_ms,
        }


class AiSpec(BaseModel):
    schema_version: str = "0.1"
    ai_layer: AiLayerConfig = Field(default_factory=AiLayerConfig)
    source_path: Path | None = None

    @property
    def model_gateway(self) -> ResolvedAiGatewayConfig:
        return self.resolve_gateway()

    @property
    def models(self) -> AiModelsConfig:
        return self.ai_layer.models

    @property
    def drawing_understanding(self) -> AiDrawingUnderstandingConfig:
        return self.ai_layer.drawing_understanding

    @property
    def template_understanding(self) -> AiTemplateUnderstandingConfig:
        return self.ai_layer.template_understanding

    def resolve_gateway(self) -> ResolvedAiGatewayConfig:
        gateway = self.ai_layer.model_gateway
        bootstrap = self.ai_layer.bootstrap_contract
        base_url = os.getenv(bootstrap.base_url_env_var) or gateway.base_url
        api_key = os.getenv(bootstrap.api_key_env_var)
        if not api_key and gateway.api_key_policy != "env_only":
            api_key = gateway.api_key
        return ResolvedAiGatewayConfig(
            provider=gateway.provider,
            base_url=base_url,
            api_key_env_var=bootstrap.api_key_env_var,
            base_url_env_var=bootstrap.base_url_env_var,
            api_key_policy=gateway.api_key_policy,
            api_key=api_key,
            timeout_sec=gateway.timeout_sec,
            max_retries=gateway.max_retries,
            retry_backoff_ms=gateway.retry_backoff_ms,
        )


class AiSpecLoader:
    @classmethod
    @lru_cache(maxsize=8)
    def _load_cached(cls, resolved_path: str) -> AiSpec:
        path = Path(resolved_path)
        if not path.exists():
            raise FileNotFoundError(f"AI 参数规范文件不存在: {path}")
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ValueError(f"AI 参数规范必须是 YAML mapping: {path}")
        extracted = dict(data)
        extracted["ai_layer"] = _extract_tree(data.get("ai_layer", {}))
        spec = AiSpec.model_validate(extracted)
        spec.source_path = path
        return spec

    @classmethod
    def load(cls, spec_path: str | Path = DEFAULT_AI_SPEC_PATH) -> AiSpec:
        path = _resolve_ai_spec_path(spec_path)
        return cls._load_cached(_cache_key(path))

    @classmethod
    def reload(cls, spec_path: str | Path = DEFAULT_AI_SPEC_PATH) -> AiSpec:
        cls.clear_cache()
        return cls.load(spec_path)

    @classmethod
    def clear_cache(cls) -> None:
        cls._load_cached.cache_clear()


def load_ai_spec(spec_path: str | Path = DEFAULT_AI_SPEC_PATH) -> AiSpec:
    return AiSpecLoader.load(spec_path)


def reload_ai_spec(spec_path: str | Path = DEFAULT_AI_SPEC_PATH) -> AiSpec:
    return AiSpecLoader.reload(spec_path)


def _resolve_ai_spec_path(spec_path: str | Path) -> Path:
    path = Path(spec_path)
    if path == DEFAULT_AI_SPEC_PATH:
        env_path = os.getenv(AI_SPEC_PATH_ENV_VAR)
        if env_path:
            return Path(env_path)
        default_path = _find_relative_path(DEFAULT_AI_SPEC_PATH)
        if default_path is not None:
            return default_path
        fallback_path = _find_relative_path(FALLBACK_AI_SPEC_PATH)
        if fallback_path is not None:
            return fallback_path
        for legacy_path in LEGACY_AI_SPEC_PATHS:
            resolved_legacy_path = _find_relative_path(legacy_path)
            if resolved_legacy_path is not None:
                return resolved_legacy_path
    return path


def _find_relative_path(relative_path: Path) -> Path | None:
    search_roots: list[Path] = []
    cwd = Path.cwd()
    search_roots.extend([cwd, *cwd.parents])
    try:
        module_repo_root = Path(__file__).resolve().parents[4]
        search_roots.append(module_repo_root)
    except IndexError:
        pass

    seen: set[Path] = set()
    for root in search_roots:
        try:
            normalized_root = root.resolve()
        except Exception:
            normalized_root = root.absolute()
        if normalized_root in seen:
            continue
        seen.add(normalized_root)
        candidate = normalized_root / relative_path
        if candidate.exists():
            return candidate
    return None


def _extract_tree(node: Any) -> Any:
    if isinstance(node, dict):
        if "default" in node and any(k in node for k in ("type", "desc", "required", "options")):
            return node["default"]
        if "default" not in node and "type" in node:
            has_nested_value = any(isinstance(v, (dict, list)) for v in node.values())
            if not has_nested_value:
                return None
        result: dict[str, Any] = {}
        for key, value in node.items():
            extracted = _extract_tree(value)
            if extracted is None and isinstance(value, dict):
                continue
            result[key] = extracted
        return result
    return node


def _cache_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except Exception:
        return str(path.absolute())


def _mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 2:
        return "*" * len(value)
    return f"{value[0]}***{value[-1]}"
