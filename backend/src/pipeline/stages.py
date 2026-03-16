"""
流水线阶段定义

职责：
1. 定义各阶段的名称和执行逻辑
2. 提供进度更新钩子
3. 失败隔离（单图失败不影响全局）

测试要点：
- test_stage_execution: 阶段执行
- test_stage_progress_update: 进度更新
- test_stage_failure_isolation: 失败隔离
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import Job


class StageEnum(StrEnum):
    """流水线阶段枚举"""
    INGEST = "INGEST"
    CONVERT_DWG_TO_DXF = "CONVERT_DWG_TO_DXF"
    DETECT_FRAMES = "DETECT_FRAMES"
    VERIFY_FRAMES_BY_ANCHOR = "VERIFY_FRAMES_BY_ANCHOR"
    SCALE_FIT_AND_CHECK = "SCALE_FIT_AND_CHECK"
    EXTRACT_TITLEBLOCK_FIELDS = "EXTRACT_TITLEBLOCK_FIELDS"
    A4_MULTIPAGE_GROUPING = "A4_MULTIPAGE_GROUPING"
    FIX_TITLEBLOCK_CONSISTENCY = "FIX_TITLEBLOCK_CONSISTENCY"
    SPLIT_AND_RENAME = "SPLIT_AND_RENAME"
    EXPORT_PDF_AND_DWG = "EXPORT_PDF_AND_DWG"
    GENERATE_DOCS = "GENERATE_DOCS"
    PACKAGE_ZIP = "PACKAGE_ZIP"


@dataclass
class PipelineStage:
    """流水线阶段"""
    name: str
    progress_start: int  # 进度起点（0-100）
    progress_end: int    # 进度终点
    handler: Callable[[Job], None] | None = None  # 执行函数

    def execute(self, job: Job) -> None:
        """执行阶段"""
        if self.handler:
            self.handler(job)


# 交付包生成流水线各阶段配置
DELIVERABLE_STAGES: list[PipelineStage] = [
    PipelineStage(StageEnum.INGEST.value, 0, 5),
    PipelineStage(StageEnum.CONVERT_DWG_TO_DXF.value, 5, 15),
    PipelineStage(StageEnum.DETECT_FRAMES.value, 15, 25),
    PipelineStage(StageEnum.VERIFY_FRAMES_BY_ANCHOR.value, 25, 30),
    PipelineStage(StageEnum.SCALE_FIT_AND_CHECK.value, 30, 35),
    PipelineStage(StageEnum.EXTRACT_TITLEBLOCK_FIELDS.value, 35, 50),
    PipelineStage(StageEnum.A4_MULTIPAGE_GROUPING.value, 50, 55),
    PipelineStage(StageEnum.FIX_TITLEBLOCK_CONSISTENCY.value, 55, 60),
    PipelineStage(StageEnum.SPLIT_AND_RENAME.value, 60, 72),
    PipelineStage(StageEnum.EXPORT_PDF_AND_DWG.value, 72, 82),
    PipelineStage(StageEnum.GENERATE_DOCS.value, 82, 95),
    PipelineStage(StageEnum.PACKAGE_ZIP.value, 95, 100),
]
