"""
流水线阶段定义。

职责：
1. 定义各阶段名称与执行顺序
2. 提供进度区间配置
3. 作为 PipelineExecutor 的统一阶段源
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import Job


class StageEnum(StrEnum):
    INGEST = "INGEST"
    FONT_PREFLIGHT_AND_REPLACE = "FONT_PREFLIGHT_AND_REPLACE"
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
    name: str
    progress_start: int
    progress_end: int
    handler: Callable[[Job], None] | None = None

    def execute(self, job: Job) -> None:
        if self.handler is not None:
            self.handler(job)


DELIVERABLE_STAGES: list[PipelineStage] = [
    PipelineStage(StageEnum.INGEST.value, 0, 5),
    PipelineStage(StageEnum.FONT_PREFLIGHT_AND_REPLACE.value, 5, 12),
    PipelineStage(StageEnum.CONVERT_DWG_TO_DXF.value, 12, 20),
    PipelineStage(StageEnum.DETECT_FRAMES.value, 20, 30),
    PipelineStage(StageEnum.VERIFY_FRAMES_BY_ANCHOR.value, 30, 35),
    PipelineStage(StageEnum.SCALE_FIT_AND_CHECK.value, 35, 40),
    PipelineStage(StageEnum.EXTRACT_TITLEBLOCK_FIELDS.value, 40, 55),
    PipelineStage(StageEnum.A4_MULTIPAGE_GROUPING.value, 55, 60),
    PipelineStage(StageEnum.FIX_TITLEBLOCK_CONSISTENCY.value, 60, 65),
    PipelineStage(StageEnum.SPLIT_AND_RENAME.value, 65, 75),
    PipelineStage(StageEnum.EXPORT_PDF_AND_DWG.value, 75, 85),
    PipelineStage(StageEnum.GENERATE_DOCS.value, 85, 95),
    PipelineStage(StageEnum.PACKAGE_ZIP.value, 95, 100),
]

