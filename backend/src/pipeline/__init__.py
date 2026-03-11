"""
流水线模块 - 任务编排与执行

子模块：
- stages: 流水线各阶段定义
- executor: 流水线执行器
- job_manager: 任务管理
- packager: 打包与 manifest 生成
"""

from .executor import PipelineExecutor
from .job_manager import JobManager
from .packager import Packager
from .project_no_inference import infer_project_no_from_path, resolve_project_no
from .stages import DELIVERABLE_STAGES, PipelineStage

__all__ = [
    "PipelineStage",
    "DELIVERABLE_STAGES",
    "PipelineExecutor",
    "JobManager",
    "Packager",
    "infer_project_no_from_path",
    "resolve_project_no",
]
