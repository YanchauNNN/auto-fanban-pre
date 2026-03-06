"""
CAD 处理模块 - DXF解析/图框检测/字段提取

子模块：
- oda_converter: DWG↔DXF 转换
- dxf_reader: ezdxf 解析与文本归一化
- frame_detector: 外框候选 + 几何拟合 + 锚点验证
- titleblock_extractor: ROI还原 + 字段解析
- a4_multipage: A4多页成组
- splitter: 裁切/拆分输出
- autocad_path_resolver: AutoCAD安装路径解析
"""

from .a4_multipage import A4MultipageGrouper
from .accoreconsole_runner import AcCoreConsoleRunner
from .autocad_path_resolver import AutoCADPathInfo, resolve_autocad_paths
from .cad_dxf_executor import CADDXFExecutor
from .dxf_pdf_exporter import DxfPdfExporter
from .frame_detector import FrameDetector
from .oda_converter import ODAConverter
from .plot_resource_manager import PlotResourceContext, ensure_plot_resources
from .splitter import FrameSplitter
from .titleblock_extractor import TitleblockExtractor

__all__ = [
    "ODAConverter",
    "FrameDetector",
    "TitleblockExtractor",
    "A4MultipageGrouper",
    "CADDXFExecutor",
    "AcCoreConsoleRunner",
    "FrameSplitter",
    "DxfPdfExporter",
    "AutoCADPathInfo",
    "resolve_autocad_paths",
    "PlotResourceContext",
    "ensure_plot_resources",
]
