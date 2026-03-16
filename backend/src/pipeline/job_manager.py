"""
任务管理器 - 任务创建/查询/更新

职责：
1. 创建任务并分配ID
2. 任务状态持久化
3. 任务查询

测试要点：
- test_create_job: 创建任务
- test_get_job: 获取任务
- test_update_job: 更新任务
- test_cancel_job: 取消任务
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from ..config import get_config
from ..interfaces import IJobManager
from ..models import Job, JobStatus, JobType


class JobManager(IJobManager):
    """任务管理器实现"""

    def __init__(self):
        self.config = get_config()
        self._jobs: dict[str, Job] = {}  # 内存缓存

    def create_job(
        self,
        job_type: str,
        project_no: str,
        input_files: list[Path] | None = None,
        options: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        batch_id: str | None = None,
        source_filename: str | None = None,
        **kwargs: Any,
    ) -> Job:
        """创建任务"""
        input_files = kwargs.get("input_files", input_files)
        options = kwargs.get("options", options)
        params = kwargs.get("params", params)
        batch_id = kwargs.get("batch_id", batch_id)
        source_filename = kwargs.get("source_filename", source_filename)

        job_id = str(uuid.uuid4())

        job = Job(
            job_id=job_id,
            job_type=JobType(job_type),
            project_no=project_no,
            batch_id=batch_id,
            source_filename=source_filename,
            input_files=input_files or [],
            options=options or {},
            params=params or {},
        )

        # 保存到缓存
        self._jobs[job_id] = job

        # 持久化
        self._persist_job(job)

        return job

    def get_job(self, job_id: str) -> Job | None:
        """获取任务"""
        # 先查缓存
        if job_id in self._jobs:
            return self._jobs[job_id]

        # 尝试从磁盘加载
        job = self._load_job(job_id)
        if job:
            self._jobs[job_id] = job

        return job

    def update_job(self, job: Job) -> None:
        """更新任务状态"""
        self._jobs[job.job_id] = job
        self._persist_job(job)

    def cancel_job(self, job_id: str) -> bool:
        """取消任务"""
        job = self.get_job(job_id)
        if not job:
            return False

        if job.status in [JobStatus.QUEUED, JobStatus.RUNNING]:
            job.status = JobStatus.CANCELLED
            self.update_job(job)
            return True

        return False

    def list_jobs(
        self,
        status: JobStatus | None = None,
        limit: int = 100,
    ) -> list[Job]:
        """列出任务"""
        jobs = list(self._jobs.values())

        if status:
            jobs = [j for j in jobs if j.status == status]

        # 按创建时间降序
        jobs.sort(key=lambda j: j.created_at, reverse=True)

        return jobs[:limit]

    def load_all_jobs(self) -> list[Job]:
        """从磁盘加载全部任务并刷新内存缓存"""
        jobs_root = self.config.storage_dir / "jobs"
        if not jobs_root.exists():
            jobs = list(self._jobs.values())
            jobs.sort(key=lambda j: j.created_at, reverse=True)
            return jobs

        loaded_by_id: dict[str, Job] = dict(self._jobs)
        for job_file in sorted(jobs_root.glob("*/job.json")):
            try:
                with open(job_file, encoding="utf-8") as f:
                    data = json.load(f)
                job = Job(**data)
            except Exception:
                continue
            self._jobs[job.job_id] = job
            loaded_by_id[job.job_id] = job

        loaded = list(loaded_by_id.values())
        loaded.sort(key=lambda j: j.created_at, reverse=True)
        return loaded

    def _persist_job(self, job: Job) -> None:
        """持久化任务"""
        job_dir = self.config.get_job_dir(job.job_id)
        job_dir.mkdir(parents=True, exist_ok=True)

        job_file = job_dir / "job.json"
        tmp_file = job_dir / "job.json.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(job.model_dump(mode="json"), f, ensure_ascii=False, indent=2, default=str)
        for attempt in range(5):
            try:
                tmp_file.replace(job_file)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02)

    def _load_job(self, job_id: str) -> Job | None:
        """从磁盘加载任务"""
        job_file = self.config.get_job_dir(job_id) / "job.json"

        if not job_file.exists():
            return None

        try:
            with open(job_file, encoding="utf-8") as f:
                data = json.load(f)
            return Job(**data)
        except Exception:
            return None
