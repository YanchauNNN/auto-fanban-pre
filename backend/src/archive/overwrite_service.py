from __future__ import annotations

import shutil
from pathlib import Path

from ..models import TaskGroup
from ..pipeline.group_manager import GroupManager
from ..pipeline.job_manager import JobManager


class ArchiveOverwriteService:
    def __init__(
        self,
        group_manager: GroupManager,
        job_manager: JobManager,
    ) -> None:
        self.group_manager = group_manager
        self.job_manager = job_manager

    def clear_target_directory(self, target_dir: Path) -> None:
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)

    def cleanup_replaced_group(self, group: TaskGroup) -> None:
        replaced_group_id = str(group.replacement.replaced_group_id or "").strip()
        if not replaced_group_id:
            return
        replaced_group = self.group_manager.get_group(replaced_group_id)
        if replaced_group is None:
            return
        self._delete_group_records(replaced_group)

    def _delete_group_records(self, group: TaskGroup) -> None:
        group_dir = self.group_manager.config.get_group_dir(group.group_id)
        if group_dir.exists():
            shutil.rmtree(group_dir, ignore_errors=True)
        for child_job_id in group.child_job_ids:
            job_dir = self.job_manager.config.get_job_dir(child_job_id)
            if job_dir.exists():
                shutil.rmtree(job_dir, ignore_errors=True)
