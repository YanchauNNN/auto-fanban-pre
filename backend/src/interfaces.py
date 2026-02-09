"""
模块接口契约 - 定义各模块的抽象接口

设计原则：
1. 模块间通过接口通信，不直接依赖具体实现
2. 每个接口定义清晰的输入输出类型
3. 便于单元测试和mock替换

使用方式：
    from src.interfaces import IFrameDetector

    class MyFrameDetector(IFrameDetector):
        def detect_frames(self, dxf_path: Path) -> list[FrameMeta]:
            ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from .models import DocContext, FrameMeta, Job, SheetSet


# ============================================================================
# CAD 处理模块接口
# ============================================================================

class IODAConverter(ABC):
    """ODA 转换器接口 - DWG↔DXF 转换"""

    @abstractmethod
    def dwg_to_dxf(self, dwg_path: Path, output_dir: Path) -> Path:
        """
        DWG 转 DXF

        Args:
            dwg_path: 输入DWG文件路径
            output_dir: 输出目录

        Returns:
            生成的DXF文件路径

        Raises:
            ConversionError: 转换失败
        """
        ...

    @abstractmethod
    def dxf_to_dwg(self, dxf_path: Path, output_dir: Path) -> Path:
        """
        DXF 转 DWG

        Args:
            dxf_path: 输入DXF文件路径
            output_dir: 输出目录

        Returns:
            生成的DWG文件路径
        """
        ...


class IFrameDetector(ABC):
    """图框检测器接口 - 识别DXF中的图框"""

    @abstractmethod
    def detect_frames(self, dxf_path: Path) -> list[FrameMeta]:
        """
        检测DXF中的所有图框

        流程：
        1. 解析DXF找到候选矩形（闭合polyline优先，LINE重建兜底）
        2. 锚点验证（CNPE/中国核电工程有限公司）
        3. 纸张尺寸拟合（确定paper_variant/sx/sy）

        Args:
            dxf_path: DXF文件路径

        Returns:
            检测到的图框元数据列表（runtime部分已填充）
        """
        ...


class ITitleblockExtractor(ABC):
    """图签提取器接口 - 从图框中提取字段"""

    @abstractmethod
    def extract_fields(self, dxf_path: Path, frame: FrameMeta) -> FrameMeta:
        """
        提取单个图框的图签字段

        Args:
            dxf_path: DXF文件路径
            frame: 图框元数据（runtime部分已填充）

        Returns:
            更新后的图框元数据（titleblock部分已填充）
        """
        ...


class IA4MultipageGrouper(ABC):
    """A4多页成组器接口 - 处理001说明图"""

    @abstractmethod
    def group_a4_pages(self, frames: list[FrameMeta]) -> tuple[list[FrameMeta], list[SheetSet]]:
        """
        对A4图框进行成组处理

        Args:
            frames: 所有检测到的图框

        Returns:
            (非A4多页的图框列表, A4多页成组列表)
        """
        ...


class IFrameSplitter(ABC):
    """图框拆分器接口 - 裁切输出子图"""

    @abstractmethod
    def split_frame(
        self,
        dxf_path: Path,
        frame: FrameMeta,
        output_dir: Path
    ) -> tuple[Path, Path]:
        """
        拆分单个图框并输出PDF+DWG

        Args:
            dxf_path: 源DXF文件路径
            frame: 图框元数据
            output_dir: 输出目录

        Returns:
            (PDF路径, DWG路径)
        """
        ...

    @abstractmethod
    def split_sheet_set(
        self,
        dxf_path: Path,
        sheet_set: SheetSet,
        output_dir: Path
    ) -> tuple[Path, Path]:
        """
        拆分A4多页成组并输出多页PDF+DWG

        Args:
            dxf_path: 源DXF文件路径
            sheet_set: A4多页成组
            output_dir: 输出目录

        Returns:
            (多页PDF路径, DWG路径)
        """
        ...


# ============================================================================
# 文档生成模块接口
# ============================================================================

class ICoverGenerator(ABC):
    """封面生成器接口"""

    @abstractmethod
    def generate(self, ctx: DocContext, output_dir: Path) -> tuple[Path, Path]:
        """
        生成封面文档

        Args:
            ctx: 文档生成上下文
            output_dir: 输出目录

        Returns:
            (docx路径, pdf路径)
        """
        ...


class ICatalogGenerator(ABC):
    """目录生成器接口"""

    @abstractmethod
    def generate(self, ctx: DocContext, output_dir: Path) -> tuple[Path, Path, int]:
        """
        生成目录文档

        Args:
            ctx: 文档生成上下文
            output_dir: 输出目录

        Returns:
            (xlsx路径, pdf路径, 页数)
        """
        ...


class IDesignFileGenerator(ABC):
    """设计文件生成器接口"""

    @abstractmethod
    def generate(self, ctx: DocContext, output_dir: Path) -> tuple[Path, Path]:
        """
        生成设计文件

        Args:
            ctx: 文档生成上下文
            output_dir: 输出目录

        Returns:
            (xlsx路径, pdf路径)
        """
        ...


class IIEDGenerator(ABC):
    """IED计划生成器接口"""

    @abstractmethod
    def generate(self, ctx: DocContext, output_dir: Path) -> Path:
        """
        生成IED计划（仅Excel，不导出PDF）

        Args:
            ctx: 文档生成上下文
            output_dir: 输出目录

        Returns:
            xlsx路径
        """
        ...


class IPDFExporter(ABC):
    """PDF导出器接口"""

    @abstractmethod
    def export_docx_to_pdf(self, docx_path: Path, pdf_path: Path) -> None:
        """Word文档导出PDF"""
        ...

    @abstractmethod
    def export_xlsx_to_pdf(self, xlsx_path: Path, pdf_path: Path) -> None:
        """Excel文档导出PDF"""
        ...

    @abstractmethod
    def count_pdf_pages(self, pdf_path: Path) -> int:
        """计算PDF页数"""
        ...


# ============================================================================
# 流水线与任务管理接口
# ============================================================================

class IPipelineStage(Protocol):
    """流水线阶段协议"""

    name: str

    def execute(self, job: Job) -> None:
        """执行阶段"""
        ...


class IJobManager(ABC):
    """任务管理器接口"""

    @abstractmethod
    def create_job(self, job_type: str, project_no: str, **kwargs: Any) -> Job:
        """创建任务"""
        ...

    @abstractmethod
    def get_job(self, job_id: str) -> Job | None:
        """获取任务"""
        ...

    @abstractmethod
    def update_job(self, job: Job) -> None:
        """更新任务状态"""
        ...

    @abstractmethod
    def cancel_job(self, job_id: str) -> bool:
        """取消任务"""
        ...


class IPackager(ABC):
    """打包器接口"""

    @abstractmethod
    def package(self, job: Job) -> Path:
        """
        打包交付产物

        Args:
            job: 任务对象

        Returns:
            package.zip 路径
        """
        ...

    @abstractmethod
    def generate_manifest(self, job: Job) -> Path:
        """
        生成manifest.json

        Args:
            job: 任务对象

        Returns:
            manifest.json 路径
        """
        ...


# ============================================================================
# 异常定义
# ============================================================================

class AutoFanbanError(Exception):
    """基础异常"""
    pass


class ConversionError(AutoFanbanError):
    """转换错误"""
    pass


class DetectionError(AutoFanbanError):
    """检测错误"""
    pass


class ExtractionError(AutoFanbanError):
    """提取错误"""
    pass


class GenerationError(AutoFanbanError):
    """生成错误"""
    pass


class ExportError(AutoFanbanError):
    """导出错误"""
    pass
