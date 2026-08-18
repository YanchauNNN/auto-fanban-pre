"""
配置层 - 加载业务规范与运行期配置

职责：
- 加载 documents/参数规范.yaml（业务规范）
- 加载 documents/参数规范_运行期.yaml（运行期参数）
- 提供类型安全的配置访问接口
"""

from .ai.ai_spec import AiSpec, AiSpecLoader, load_ai_spec, reload_ai_spec
from .mechanism_spec import (
    MechanismSpec,
    MechanismSpecLoader,
    append_audit_replace_factory_codes,
    expand_audit_replace_factory_codes,
    load_mechanism_spec,
    normalize_audit_replace_factory_codes,
)
from .runtime_config import RuntimeConfig, get_config, reload_config
from .spec_loader import BusinessSpec, SpecLoader, load_spec

__all__ = [
    "SpecLoader",
    "BusinessSpec",
    "load_spec",
    "MechanismSpec",
    "MechanismSpecLoader",
    "append_audit_replace_factory_codes",
    "expand_audit_replace_factory_codes",
    "load_mechanism_spec",
    "normalize_audit_replace_factory_codes",
    "AiSpec",
    "AiSpecLoader",
    "load_ai_spec",
    "reload_ai_spec",
    "RuntimeConfig",
    "get_config",
    "reload_config",
]
