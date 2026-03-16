"""
任务模型 - 定义任务状态与生命周期

对应架构文档 3.1 节 Job 结构
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    """任务状态枚举"""
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(StrEnum):
    """任务类型"""
    DELIVERABLE = "deliverable"       # 流水线A: 交付包生成
    AUDIT_REPLACE = "audit_replace"   # 流水线B: 词库检查/替换


class JobArtifacts(BaseModel):
    """任务产物路径"""
    package_zip: Path | None = None
    ied_xlsx: Path | None = None
    drawings_dir: Path | None = None
    docs_dir: Path | None = None
    reports_dir: Path | None = None
    report_xlsx: Path | None = None
    report_json: Path | None = None
    replaced_dwg: Path | None = None


class JobProgress(BaseModel):
    """任务进度"""
    stage: str = "INIT"
    percent: int = 0
    current_file: str | None = None
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class Job(BaseModel):
    """任务实体"""
    job_id: str = Field(..., description="UUID")
    job_type: JobType
    project_no: str
    batch_id: str | None = None
    source_filename: str | None = None
    group_id: str | None = None
    task_role: str | None = None
    shared_run_id: str | None = None

    # ????
    slot_id: str | None = None
    cad_version: str | None = None
    accoreconsole_exe: str | None = None
    profile_arg: str | None = None
    pc3_path: str | None = None
    pmp_path: str | None = None
    ctb_path: str | None = None

    # 输入
    input_files: list[Path] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)

    # 状态
    status: JobStatus = JobStatus.QUEUED
    progress: JobProgress = Field(default_factory=JobProgress)

    # 产物
    artifacts: JobArtifacts = Field(default_factory=JobArtifacts)

    # 结果
    flags: list[str] = Field(default_factory=list, description="告警标记")
    errors: list[str] = Field(default_factory=list, description="错误信息")

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    # 工作目录（运行时设置）
    work_dir: Path | None = None

    model_config = {"arbitrary_types_allowed": True}

    def mark_running(self, stage: str = "INGEST") -> None:
        """标记为运行中"""
        self.status = JobStatus.RUNNING
        self.started_at = datetime.now()
        self.progress.stage = stage

    def mark_succeeded(self) -> None:
        """标记为成功"""
        self.status = JobStatus.SUCCEEDED
        self.finished_at = datetime.now()
        self.progress.percent = 100

    def mark_failed(self, error: str) -> None:
        """标记为失败"""
        self.status = JobStatus.FAILED
        self.finished_at = datetime.now()
        self.errors.append(error)

    def add_flag(self, flag: str) -> None:
        """添加告警标记（不中断）"""
        if flag not in self.flags:
            self.flags.append(flag)
