from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from ..config import get_config
from ..models import JobStatus, TaskGroup


class GroupManager:
    def __init__(self) -> None:
        self.config = get_config()
        self._groups: dict[str, TaskGroup] = {}

    def create_group(
        self,
        *,
        batch_id: str | None,
        source_filenames: list[str],
        project_no: str,
        run_audit_check: bool,
        shared_run_id: str | None = None,
    ) -> TaskGroup:
        group_id = f"group-{uuid.uuid4().hex}"
        group = TaskGroup(
            group_id=group_id,
            batch_id=batch_id,
            source_filenames=source_filenames,
            project_no=project_no,
            run_audit_check=run_audit_check,
            shared_run_id=shared_run_id or group_id,
        )
        self._groups[group_id] = group
        self.update_group(group)
        return group

    def get_group(self, group_id: str) -> TaskGroup | None:
        if group_id in self._groups:
            return self._groups[group_id]
        group = self._load_group(group_id)
        if group is not None:
            self._groups[group_id] = group
        return group

    def update_group(self, group: TaskGroup) -> None:
        self._groups[group.group_id] = group
        self._persist_group(group)

    def list_groups(self, status: JobStatus | None = None, limit: int = 100) -> list[TaskGroup]:
        groups = self.load_all_groups()
        if status is not None:
            groups = [group for group in groups if group.status == status]
        groups.sort(key=lambda item: item.created_at, reverse=True)
        return groups[:limit]

    def load_all_groups(self) -> list[TaskGroup]:
        groups_root = self.config.storage_dir / 'groups'
        if not groups_root.exists():
            groups = list(self._groups.values())
            groups.sort(key=lambda g: g.created_at, reverse=True)
            return groups

        loaded_by_id: dict[str, TaskGroup] = dict(self._groups)
        for group_file in sorted(groups_root.glob('*/group.json')):
            try:
                with open(group_file, encoding='utf-8') as f:
                    data = json.load(f)
                group = TaskGroup(**data)
            except Exception:
                continue
            self._groups[group.group_id] = group
            loaded_by_id[group.group_id] = group
        groups = list(loaded_by_id.values())
        groups.sort(key=lambda g: g.created_at, reverse=True)
        return groups

    def _persist_group(self, group: TaskGroup) -> None:
        group_dir = self.config.get_group_dir(group.group_id)
        group_dir.mkdir(parents=True, exist_ok=True)
        group_file = group_dir / 'group.json'
        tmp_file = group_dir / 'group.json.tmp'
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(group.model_dump(mode='json'), f, ensure_ascii=False, indent=2, default=str)
        for attempt in range(5):
            try:
                tmp_file.replace(group_file)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02)

    def _load_group(self, group_id: str) -> TaskGroup | None:
        group_file = self.config.get_group_dir(group_id) / 'group.json'
        if not group_file.exists():
            return None
        try:
            with open(group_file, encoding='utf-8') as f:
                data = json.load(f)
            return TaskGroup(**data)
        except Exception:
            return None
