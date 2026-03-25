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
        self.delete_group_records_by_id(replaced_group_id)

    def delete_group_records_by_id(self, group_id: str) -> None:
        replaced_group = self.group_manager.get_group(group_id)
        if replaced_group is None:
            self.group_manager.delete_group(group_id)
            return
        self.delete_group_records(replaced_group)

    def delete_group_records(self, group: TaskGroup) -> None:
        for child_job_id in group.child_job_ids:
            self.job_manager.delete_job(child_job_id)
        self.group_manager.delete_group(group.group_id)
