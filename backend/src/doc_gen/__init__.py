"""
文档生成模块 - 封面/目录/设计文件/IED计划

这里保持惰性导出，避免只导入单个子模块时触发整条文档/CAD依赖链。
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .catalog import CatalogGenerator
    from .cover import CoverGenerator
    from .derivation import DerivationEngine
    from .design import DesignFileGenerator
    from .ied import IEDGenerator
    from .param_validator import DocParamValidator
    from .pdf_engine import PDFExporter

__all__ = [
    "DerivationEngine",
    "DocParamValidator",
    "CoverGenerator",
    "CatalogGenerator",
    "DesignFileGenerator",
    "IEDGenerator",
    "PDFExporter",
]

_LAZY_EXPORTS = {
    "DerivationEngine": (".derivation", "DerivationEngine"),
    "DocParamValidator": (".param_validator", "DocParamValidator"),
    "CoverGenerator": (".cover", "CoverGenerator"),
    "CatalogGenerator": (".catalog", "CatalogGenerator"),
    "DesignFileGenerator": (".design", "DesignFileGenerator"),
    "IEDGenerator": (".ied", "IEDGenerator"),
    "PDFExporter": (".pdf_engine", "PDFExporter"),
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _LAZY_EXPORTS[name]
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
