from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.config.runtime_config import RuntimeConfig


def test_load_ai_spec_reads_defaults_from_yaml() -> None:
    from src.config.ai.ai_spec import AiSpecLoader

    repo_root = Path(__file__).resolve().parents[4]
    spec = AiSpecLoader.load(repo_root / "documents" / "AI" / "参数规范_AI.yaml")

    assert spec.schema_version == "0.1"
    assert spec.ai_layer.enabled is True
    assert spec.model_gateway.provider == "openai_compatible"
    assert spec.model_gateway.base_url == "https://api.minimaxi.com/v1"
    assert spec.model_gateway.api_key_env_var == "MiniMax-API"
    assert spec.models.chat.model == "MiniMax-M3"
    assert spec.ai_layer.deployment_profile.network_mode == "intranet_only"
    assert spec.ai_layer.deployment_profile.allow_external_network is False
    assert spec.ai_layer.model_gateway.base_url == "http://127.0.0.1:8001/v1"
    assert spec.ai_layer.bootstrap_contract.api_key_env_var == "FANBAN_AI_API_KEY"
    assert spec.drawing_understanding.element_package.output_root == (
        "outputs/drawing-understanding"
    )
    assert spec.template_understanding.enabled is True
    assert spec.template_understanding.output_root == "outputs/template-understanding"
    assert spec.template_understanding.office.parse_docx_embedded_xlsx is True
    assert spec.template_understanding.factory_index_maps.source_root == (
        "documents_bin/factory_index_maps"
    )


def test_ai_chat_defaults_to_two_single_agent_modes_with_read_only_host_access() -> None:
    from src.config.ai.ai_spec import AiSpecLoader

    repo_root = Path(__file__).resolve().parents[4]
    AiSpecLoader.clear_cache()

    spec = AiSpecLoader.load(repo_root / "documents" / "AI" / "参数规范_AI.yaml")
    chat = spec.ai_layer.chat

    assert chat.default_agent == "general_assistant"
    assert [(agent.agent_id, agent.name) for agent in chat.agents] == [
        ("general_assistant", "通用对话"),
        ("business_agent", "业务 Agent"),
    ]
    assert [(skill.skill_id, skill.handler, skill.auto_trigger) for skill in chat.skills] == [
        ("ansys_mapdl_18_2", "ansys_mapdl_18_2", True),
        (
            "building_structure_standards",
            "building_structure_standards",
            True,
        ),
        (
            "reinforcement_table_normalizer",
            "reinforcement_table_normalizer",
            False,
        ),
    ]
    assert chat.skills[0].root == "storage/ai/skills/ansys-mapdl-18-2"
    assert chat.skills[0].root_env_var == "FANBAN_ANSYS_MAPDL_SKILL_ROOT"
    assert chat.skills[1].root == (
        "storage/ai/skills/building-structure-standards"
    )
    assert chat.skills[1].root_env_var == (
        "FANBAN_BUILDING_STANDARDS_SKILL_ROOT"
    )
    assert chat.skills[1].source_access.primary_root == "documents/规范下载"
    assert chat.skills[1].source_access.primary_root_env_var == (
        "FANBAN_BUILDING_STANDARDS_SOURCE_ROOT"
    )
    assert chat.skills[1].source_access.fallback_roots == [
        r"\\10.102.2.7\文件服务器\建筑结构所\14-自开发软件\规范下载"
    ]
    assert chat.skills[1].source_access.per_file_fallback is True
    assert chat.skills[1].source_access.preview_enabled is True
    assert chat.skills[1].source_access.download_enabled is True
    assert chat.skills[2].root == "tools/ai/reinforcement-table-normalizer"
    assert chat.skills[2].root_env_var == ""
    assert chat.mcp_servers == []
    assert chat.response_format.enabled is True
    assert "GitHub Flavored Markdown" in chat.response_format.system_prompt_suffix
    assert "```apdl" in chat.response_format.system_prompt_suffix

    attachments = chat.attachments
    assert attachments.enabled is True
    assert attachments.allowed_extensions == [
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
    assert attachments.max_files_per_message == 5
    assert attachments.max_image_size_mb == 10
    assert attachments.max_file_size_mb == 50
    assert attachments.max_total_size_mb_per_message == 100
    assert attachments.max_extracted_chars_per_file == 20_000
    assert attachments.max_context_chars_per_message == 60_000
    assert attachments.retention_days == 30

    access = chat.read_only_host_access
    assert access.enabled is True
    assert access.allowed_roots == [
        "storage",
        "documents",
        "documents_bin",
        "backend-runtime/backend/src/cad",
        "backend/src/cad",
    ]
    assert ".env" in access.denied_names
    assert ".sqlite3" in access.denied_suffixes
    assert ".exe" in access.denied_suffixes
    assert access.max_read_bytes == 262_144
    assert access.max_search_results == 50
    assert access.max_tool_rounds == 3


def test_load_ai_spec_default_path_resolves_from_backend_cwd(monkeypatch) -> None:
    from src.config.ai.ai_spec import AiSpecLoader, load_ai_spec

    repo_root = Path(__file__).resolve().parents[4]
    monkeypatch.chdir(repo_root / "backend")
    AiSpecLoader.clear_cache()

    spec = load_ai_spec()

    assert spec.source_path == (repo_root / "documents" / "AI" / "参数规范_AI.yaml").resolve()


def test_load_ai_spec_uses_env_override_when_default_path_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from src.config.ai.ai_spec import AiSpecLoader, load_ai_spec

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    spec_file = tmp_path / "bundle" / "documents" / "参数规范_AI.yaml"
    spec_file.parent.mkdir(parents=True)
    spec_file.write_text(
        yaml.safe_dump(
            {
                "schema_version": "9.9",
                "ai_layer": {
                    "enabled": {"type": "bool", "default": True},
                    "model_gateway": {
                        "base_url": {"type": "str", "default": "https://api.example/v1"},
                    },
                    "models": {
                        "chat": {
                            "model": {"type": "str", "default": "chat-test"},
                        },
                    },
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(run_dir)
    monkeypatch.setenv("FANBAN_AI_SPEC_PATH", str(spec_file))
    AiSpecLoader.clear_cache()

    spec = load_ai_spec()

    assert spec.schema_version == "9.9"
    assert spec.ai_layer.enabled is True
    assert spec.model_gateway.base_url == "https://api.example/v1"
    assert spec.models.chat.model == "chat-test"


def test_gateway_runtime_overrides_and_redacts_api_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from src.config.ai.ai_spec import AiSpecLoader

    spec_file = tmp_path / "参数规范_AI.yaml"
    spec_file.write_text(
        yaml.safe_dump(
            {
                "schema_version": "0.1",
                "ai_layer": {
                    "bootstrap_contract": {
                        "api_key_env_var": {
                            "type": "str",
                            "default": "MiniMax-API",
                        },
                        "base_url_env_var": {
                            "type": "str",
                            "default": "MINIMAX_BASE_URL",
                        },
                    },
                    "model_gateway": {
                        "base_url": {"type": "str", "default": "https://yaml.example/v1"},
                    },
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MiniMax-API", "secret-for-test")
    monkeypatch.setenv("MINIMAX_BASE_URL", "https://env.example/v1")
    AiSpecLoader.clear_cache()

    spec = AiSpecLoader.load(spec_file)
    gateway = spec.resolve_gateway()
    public_dict = gateway.safe_public_dict()

    assert gateway.base_url == "https://env.example/v1"
    assert gateway.api_key == "secret-for-test"
    assert public_dict["api_key"] == "s***t"
    assert "secret-for-test" not in repr(gateway)
    assert "secret-for-test" not in repr(public_dict)


def test_gateway_profile_env_switches_to_terminal_intranet_chain(monkeypatch) -> None:
    from src.config.ai.ai_spec import AiSpecLoader

    repo_root = Path(__file__).resolve().parents[4]
    monkeypatch.setenv("FANBAN_AI_GATEWAY_PROFILE", "terminal_cnpe_intranet_qwen_fast")
    monkeypatch.delenv("FANBAN_AI_BASE_URL", raising=False)
    AiSpecLoader.clear_cache()

    spec = AiSpecLoader.load(repo_root / "documents" / "AI" / "参数规范_AI.yaml")
    gateway = spec.resolve_gateway()

    assert gateway.base_url == "http://models.ai.cnpe.cc/qwen_medium/v1"
    assert gateway.api_key_env_var == ""
    assert gateway.api_key is None
    assert gateway.api_key_policy == "none"
    assert spec.models.chat.model == "Qwen3.8-27B"
    assert spec.models.structured.model == "Qwen3.8-27B"
    profile = spec.resolve_gateway_profile()
    assert profile is not None
    assert profile.network_mode == "intranet_only"
    assert profile.allowed_hosts == ["models.ai.cnpe.cc"]
    spec.validate_gateway_network_policy(required_network_mode="intranet_only")


def test_terminal_network_policy_rejects_public_base_url_override(monkeypatch) -> None:
    from src.config.ai.ai_spec import AiSpecLoader

    repo_root = Path(__file__).resolve().parents[4]
    monkeypatch.setenv("FANBAN_AI_GATEWAY_PROFILE", "terminal_cnpe_intranet_qwen_fast")
    monkeypatch.setenv("FANBAN_AI_BASE_URL", "https://api.minimaxi.com/v1")
    AiSpecLoader.clear_cache()

    spec = AiSpecLoader.load(repo_root / "documents" / "AI" / "参数规范_AI.yaml")

    with pytest.raises(ValueError, match="not allowed"):
        spec.validate_gateway_network_policy(required_network_mode="intranet_only")


def test_terminal_network_policy_requires_host_allowlist(monkeypatch) -> None:
    from src.config.ai.ai_spec import AiSpecLoader

    repo_root = Path(__file__).resolve().parents[4]
    monkeypatch.setenv("FANBAN_AI_GATEWAY_PROFILE", "terminal_cnpe_intranet_qwen_fast")
    monkeypatch.delenv("FANBAN_AI_BASE_URL", raising=False)
    AiSpecLoader.clear_cache()

    spec = AiSpecLoader.load(repo_root / "documents" / "AI" / "参数规范_AI.yaml")
    profile = spec.resolve_gateway_profile()
    assert profile is not None
    profile.allowed_hosts = []

    with pytest.raises(ValueError, match="allowlist"):
        spec.validate_gateway_network_policy(required_network_mode="intranet_only")


def test_unknown_gateway_profile_fails_instead_of_falling_back(monkeypatch) -> None:
    from src.config.ai.ai_spec import AiSpecLoader

    repo_root = Path(__file__).resolve().parents[4]
    monkeypatch.setenv("FANBAN_AI_GATEWAY_PROFILE", "missing-profile")
    AiSpecLoader.clear_cache()

    spec = AiSpecLoader.load(repo_root / "documents" / "AI" / "参数规范_AI.yaml")

    with pytest.raises(ValueError, match="missing-profile"):
        spec.resolve_gateway()


def test_runtime_config_tracks_ai_spec_path(tmp_path: Path) -> None:
    runtime_spec = tmp_path / "documents" / "参数规范_运行期.yaml"
    runtime_spec.parent.mkdir(parents=True)
    runtime_spec.write_text(
        """
runtime_options:
  paths:
    ai_spec_path:
      type: str
      default: "documents/AI/参数规范_AI.yaml"
""".strip(),
        encoding="utf-8",
    )

    config = RuntimeConfig.from_yaml(runtime_spec)

    assert config.ai_spec_path == (tmp_path / "documents" / "AI" / "参数规范_AI.yaml").resolve()
