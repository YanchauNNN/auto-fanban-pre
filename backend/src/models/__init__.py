"""
数据模型层 - 定义系统核心数据结构

所有模块通过这些模型交互，实现解耦：
- Job: 任务状态与生命周期
- FrameMeta: 单个图框的运行期+图签字段
- SheetSet: A4多页成组结构
- DocContext: 文档生成上下文
"""

from .doc_context import DerivedFields, DocContext, GlobalDocParams, normalize_global_doc_params
from .frame import BBox, FrameMeta, FrameRuntime, TitleblockFields
from .job import Job, JobStatus, JobType
from .sheet_set import PageInfo, SheetSet

__all__ = [
    "Job",
    "JobStatus",
    "JobType",
    "FrameMeta",
    "FrameRuntime",
    "TitleblockFields",
    "BBox",
    "SheetSet",
    "PageInfo",
    "DocContext",
    "GlobalDocParams",
    "DerivedFields",
    "normalize_global_doc_params",
]
