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
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, Field

DEFAULT_AI_SPEC_PATH = Path("documents") / "AI" / "参数规范_AI.yaml"
FALLBACK_AI_SPEC_PATH = Path("config") / "AI" / "参数规范_AI.yaml"
LEGACY_AI_SPEC_PATHS = (
    Path("documents") / "参数规范_AI.yaml",
    Path("config") / "参数规范_AI.yaml",
)
AI_SPEC_PATH_ENV_VAR = "FANBAN_AI_SPEC_PATH"
AI_GATEWAY_CONFIG_NAME = "ai_model_gateway.yaml"
AI_GATEWAY_CONFIG_PATH_ENV_VAR = "FANBAN_AI_GATEWAY_CONFIG_PATH"
AI_GATEWAY_PROFILE_ENV_VAR = "FANBAN_AI_GATEWAY_PROFILE"


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
    authorization_scheme: str = "bearer"
    timeout_sec: int = 60
    max_retries: int = 1
    retry_backoff_ms: int = 800


class AiModelGatewayProfileConfig(BaseModel):
    provider: str = "openai_compatible"
    protocol: str = "openai_compatible"
    network_mode: str = "intranet_only"
    base_url: str = ""
    allowed_hosts: list[str] = Field(default_factory=list)
    api_key_env_var: str = ""
    api_key_required: bool = False
    authorization_scheme: str = "none"
    chat_model: str = ""
    structured_model: str = ""
    timeout_sec: int | None = None


class AiModelGatewayProfilesSpec(BaseModel):
    schema_version: str = "0.1"
    active_profile: str = ""
    profiles: dict[str, AiModelGatewayProfileConfig] = Field(default_factory=dict)

    def select_profile(self) -> AiModelGatewayProfileConfig | None:
        profile_name = os.getenv(AI_GATEWAY_PROFILE_ENV_VAR) or self.active_profile
        if not profile_name:
            return None
        profile = self.profiles.get(profile_name)
        if profile is None:
            raise ValueError(f"Unknown AI gateway profile: {profile_name}")
        return profile


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


class AiChatConcurrencyConfig(BaseModel):
    max_global_requests: int = 4
    max_per_owner_requests: int = 1


class AiChatAgentConfig(BaseModel):
    agent_id: str
    name: str
    description: str = ""
    system_prompt: str = ""


class AiChatSkillConfig(BaseModel):
    skill_id: str
    name: str
    description: str = ""
    enabled: bool = True
    read_only: bool = True
    handler: str = "prompt_only"
    root: str = ""
    root_env_var: str = ""
    auto_trigger: bool = False
    trigger_terms: list[str] = Field(default_factory=list)
    max_results: int = 4
    max_context_chars: int = 16_000
    query_timeout_seconds: int = 20
    history_followup_messages: int = 6


class AiChatMcpServerConfig(BaseModel):
    server_id: str
    name: str
    description: str = ""
    enabled: bool = False
    read_only: bool = True
    transport: str = "disabled"
    endpoint: str = ""


class AiReadOnlyHostAccessConfig(BaseModel):
    enabled: bool = True
    allowed_roots: list[str] = Field(
        default_factory=lambda: [
            "storage",
            "documents",
            "documents_bin",
            "backend-runtime/backend/src/cad",
            "backend/src/cad",
        ],
    )
    denied_names: list[str] = Field(
        default_factory=lambda: [
            ".env",
            "ai_model_gateway.yaml",
            "runtime.env.ps1",
        ],
    )
    denied_suffixes: list[str] = Field(
        default_factory=lambda: [
            ".db",
            ".dll",
            ".exe",
            ".key",
            ".p12",
            ".pem",
            ".pfx",
            ".sqlite",
            ".sqlite3",
        ],
    )
    max_read_bytes: int = 262_144
    max_search_results: int = 50
    max_depth: int = 6
    max_tool_rounds: int = 3


DEFAULT_AI_CHAT_RESPONSE_FORMAT_PROMPT = (
    "使用 GitHub Flavored Markdown 组织回答。普通说明使用段落、列表和表格；"
    "命令、程序和配置使用围栏代码块。ANSYS Mechanical APDL、MAPDL 或 APDL "
    "命令流必须使用 ```apdl 语言标签。不要输出原始 HTML。"
)


class AiChatResponseFormatConfig(BaseModel):
    enabled: bool = True
    system_prompt_suffix: str = DEFAULT_AI_CHAT_RESPONSE_FORMAT_PROMPT


class AiChatAttachmentsConfig(BaseModel):
    enabled: bool = True
    allowed_extensions: list[str] = Field(
        default_factory=lambda: [
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".pdf",
            ".txt",
            ".md",
            ".docx",
            ".xlsx",
            ".dwg",
            ".dxf",
        ]
    )
    max_files_per_message: int = Field(default=5, ge=1)
    max_image_size_mb: int = Field(default=10, ge=1)
    max_file_size_mb: int = Field(default=50, ge=1)
    max_total_size_mb_per_message: int = Field(default=100, ge=1)
    max_extracted_chars_per_file: int = Field(default=20_000, ge=1)
    max_context_chars_per_message: int = Field(default=60_000, ge=1)
    retention_days: int = Field(default=30, ge=1)


class AiChatConfig(BaseModel):
    enabled: bool = True
    default_agent: str = "general_assistant"
    max_history_messages: int = 20
    max_user_message_chars: int = 4000
    request_timeout_seconds: int = 60
    retention_days: int = 30
    response_format: AiChatResponseFormatConfig = Field(
        default_factory=AiChatResponseFormatConfig
    )
    attachments: AiChatAttachmentsConfig = Field(
        default_factory=AiChatAttachmentsConfig
    )
    concurrency: AiChatConcurrencyConfig = Field(default_factory=AiChatConcurrencyConfig)
    agents: list[AiChatAgentConfig] = Field(
        default_factory=lambda: [
            AiChatAgentConfig(
                agent_id="general_assistant",
                name="通用对话",
                description="进行正常知识问答、写作和日常交流",
                system_prompt="你是通用 AI 助手，可以进行正常、完整的知识问答和日常交流。",
            ),
            AiChatAgentConfig(
                agent_id="business_agent",
                name="业务 Agent",
                description="统一处理图纸理解、任务、模板规则和出图平台业务问题",
                system_prompt="你是出图平台业务 Agent，统一处理图纸理解、任务状态、模板规则和平台使用问题。",
            ),
        ],
    )
    skills: list[AiChatSkillConfig] = Field(default_factory=list)
    mcp_servers: list[AiChatMcpServerConfig] = Field(default_factory=list)
    read_only_host_access: AiReadOnlyHostAccessConfig = Field(
        default_factory=AiReadOnlyHostAccessConfig,
    )


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
    chat: AiChatConfig = Field(default_factory=AiChatConfig)
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
    authorization_scheme: str
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
            "authorization_scheme": self.authorization_scheme,
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
        return self.resolve_models()

    @property
    def drawing_understanding(self) -> AiDrawingUnderstandingConfig:
        return self.ai_layer.drawing_understanding

    @property
    def template_understanding(self) -> AiTemplateUnderstandingConfig:
        return self.ai_layer.template_understanding

    def resolve_gateway(self) -> ResolvedAiGatewayConfig:
        gateway = self.ai_layer.model_gateway
        bootstrap = self.ai_layer.bootstrap_contract
        gateway_profile = self.resolve_gateway_profile()
        base_url = os.getenv(bootstrap.base_url_env_var) or (
            gateway_profile.base_url if gateway_profile and gateway_profile.base_url else gateway.base_url
        )
        api_key_env_var = (
            gateway_profile.api_key_env_var
            if gateway_profile is not None
            else bootstrap.api_key_env_var
        )
        api_key = os.getenv(api_key_env_var) if api_key_env_var else None
        if not api_key and gateway.api_key_policy != "env_only":
            api_key = gateway.api_key
        api_key_policy = gateway.api_key_policy
        if gateway_profile is not None and not gateway_profile.api_key_required and not api_key_env_var:
            api_key_policy = "none"
        authorization_scheme = (
            gateway_profile.authorization_scheme
            if gateway_profile is not None
            else gateway.authorization_scheme
        )
        return ResolvedAiGatewayConfig(
            provider=gateway.provider,
            base_url=base_url,
            api_key_env_var=api_key_env_var,
            base_url_env_var=bootstrap.base_url_env_var,
            api_key_policy=api_key_policy,
            api_key=api_key,
            authorization_scheme=authorization_scheme,
            timeout_sec=(
                gateway_profile.timeout_sec
                if gateway_profile is not None and gateway_profile.timeout_sec is not None
                else gateway.timeout_sec
            ),
            max_retries=gateway.max_retries,
            retry_backoff_ms=gateway.retry_backoff_ms,
        )

    def resolve_models(self) -> AiModelsConfig:
        models = self.ai_layer.models.model_copy(deep=True)
        gateway_profile = self.resolve_gateway_profile()
        if gateway_profile is None:
            return models
        if gateway_profile.chat_model:
            models.chat.model = gateway_profile.chat_model
        if gateway_profile.structured_model:
            models.structured.model = gateway_profile.structured_model
        return models

    def resolve_gateway_profile(self) -> AiModelGatewayProfileConfig | None:
        gateway_profiles = _load_gateway_profiles_for_ai_spec(self.source_path)
        if gateway_profiles is None:
            return None
        return gateway_profiles.select_profile()

    def resolve_gateway_profile_name(self) -> str:
        gateway_profiles = _load_gateway_profiles_for_ai_spec(self.source_path)
        if gateway_profiles is None:
            return ""
        return os.getenv(AI_GATEWAY_PROFILE_ENV_VAR) or gateway_profiles.active_profile

    def validate_gateway_network_policy(self, *, required_network_mode: str) -> None:
        profile = self.resolve_gateway_profile()
        profile_name = self.resolve_gateway_profile_name()
        if profile is None:
            raise ValueError("AI gateway profile is required by the deployment network policy")
        if profile.network_mode != required_network_mode:
            raise ValueError(
                f"AI gateway profile {profile_name!r} network mode is not allowed: "
                f"expected {required_network_mode!r}, got {profile.network_mode!r}",
            )

        deployment = self.ai_layer.deployment_profile
        if required_network_mode == "intranet_only" and (
            deployment.network_mode != "intranet_only" or deployment.allow_external_network
        ):
            raise ValueError("AI deployment policy is not allowed for an intranet-only terminal")

        gateway_host = (urlsplit(self.resolve_gateway().base_url).hostname or "").lower()
        allowed_hosts = {host.strip().lower() for host in profile.allowed_hosts if host.strip()}
        if required_network_mode == "intranet_only" and not allowed_hosts:
            raise ValueError(
                f"AI gateway profile {profile_name!r} requires a non-empty host allowlist",
            )
        if not gateway_host or (allowed_hosts and gateway_host not in allowed_hosts):
            raise ValueError(
                f"AI gateway host {gateway_host or '<missing>'!r} is not allowed by "
                f"profile {profile_name!r}",
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
        _load_gateway_profiles_cached.cache_clear()


def load_ai_spec(spec_path: str | Path = DEFAULT_AI_SPEC_PATH) -> AiSpec:
    return AiSpecLoader.load(spec_path)


def reload_ai_spec(spec_path: str | Path = DEFAULT_AI_SPEC_PATH) -> AiSpec:
    return AiSpecLoader.reload(spec_path)


def _load_gateway_profiles_for_ai_spec(
    source_path: Path | None,
) -> AiModelGatewayProfilesSpec | None:
    config_path = _resolve_ai_gateway_config_path(source_path)
    if config_path is None:
        return None
    if not config_path.exists():
        if os.getenv(AI_GATEWAY_CONFIG_PATH_ENV_VAR):
            raise FileNotFoundError(f"AI model gateway config does not exist: {config_path}")
        return None
    return _load_gateway_profiles_cached(_cache_key(config_path))


@lru_cache(maxsize=8)
def _load_gateway_profiles_cached(resolved_path: str) -> AiModelGatewayProfilesSpec:
    path = Path(resolved_path)
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"AI model gateway config must be a YAML mapping: {path}")
    return AiModelGatewayProfilesSpec.model_validate(data)


def _resolve_ai_gateway_config_path(source_path: Path | None) -> Path | None:
    env_path = os.getenv(AI_GATEWAY_CONFIG_PATH_ENV_VAR)
    if env_path:
        return Path(env_path)
    if source_path is None:
        return _find_relative_path(Path("documents") / "AI" / AI_GATEWAY_CONFIG_NAME)

    source = Path(source_path)
    candidates = [
        source.parent / AI_GATEWAY_CONFIG_NAME,
        source.parent / "AI" / AI_GATEWAY_CONFIG_NAME,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


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
