"""
文档生成模块 - 封面/目录/设计文件/IED计划

子模块：
- derivation: 派生字段计算
- cover: 封面生成（Word+PDF）
- catalog: 目录生成（Excel+PDF）
- design: 设计文件生成（仅Excel）
- ied: IED计划生成（仅Excel）
- pdf_engine: PDF导出引擎
"""

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
