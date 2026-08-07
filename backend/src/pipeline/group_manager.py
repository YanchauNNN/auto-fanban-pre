from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from ..config import get_config
from ..models import AccountSnapshot, JobStatus, TaskGroup, TaskOwnerSnapshot
from .cross_process_lock import exclusive_file_lock


class TaskGroupVersionConflict(ValueError):
    def __init__(self, group_id: str, *, expected: int, actual: int | None) -> None:
        actual_text = "missing" if actual is None else str(actual)
        super().__init__(
            f"task_group_version_conflict:{group_id}:expected={expected}:actual={actual_text}"
        )


class TaskGroupLockTimeout(ValueError):
    def __init__(self, group_id: str) -> None:
        super().__init__(f"task_group_lock_timeout:{group_id}")


class TaskGroupPersistenceError(RuntimeError):
    pass


class GroupManager:
    def __init__(self) -> None:
        self.config = get_config()
        self._groups: dict[str, TaskGroup] = {}
        self._cache_lock = threading.RLock()

    def create_group(
        self,
        *,
        batch_id: str | None,
        source_filenames: list[str],
        project_no: str,
        run_audit_check: bool,
        shared_run_id: str | None = None,
        creator_snapshot: AccountSnapshot | None = None,
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
        if creator_snapshot is not None:
            group.owner_snapshot = TaskOwnerSnapshot(
                creator_account=creator_snapshot.account_id,
                creator_name=creator_snapshot.display_name,
                creator_role=creator_snapshot.role,
                creator_office=creator_snapshot.office_name,
            )
        self.update_group(group)
        return group

    def get_group(self, group_id: str) -> TaskGroup | None:
        with self._cache_lock:
            cached = self._groups.get(group_id)
            if cached is not None:
                return cached.model_copy(deep=True)
        group = self._load_group(group_id)
        if group is not None:
            self._cache_group(group)
            return group.model_copy(deep=True)
        return None

    def reload_group(self, group_id: str) -> TaskGroup | None:
        """Reload a group from disk and refresh the in-memory cache."""
        group = self._load_group(group_id)
        if group is None:
            with self._cache_lock:
                self._groups.pop(group_id, None)
            return None
        self._cache_group(group)
        return group.model_copy(deep=True)

    def update_group(self, group: TaskGroup) -> None:
        candidate = group.model_copy(deep=True)
        expected_version = candidate.state_version
        with self._group_file_lock(candidate.group_id):
            persisted = self._load_group_strict(candidate.group_id)
            actual_version = persisted.state_version if persisted is not None else None
            if actual_version is None:
                if expected_version != 0:
                    raise TaskGroupVersionConflict(
                        candidate.group_id,
                        expected=expected_version,
                        actual=None,
                    )
                next_version = 1
            else:
                if expected_version != actual_version:
                    raise TaskGroupVersionConflict(
                        candidate.group_id,
                        expected=expected_version,
                        actual=actual_version,
                    )
                next_version = actual_version + 1
            candidate.state_version = next_version
            self._persist_group_unlocked(candidate)

        group.state_version = next_version
        self._cache_group(candidate)

    def list_groups(self, status: JobStatus | None = None, limit: int = 100) -> list[TaskGroup]:
        groups = self.load_all_groups()
        if status is not None:
            groups = [group for group in groups if group.status == status]
        groups.sort(key=lambda item: item.created_at, reverse=True)
        return groups[:limit]

    def load_all_groups(self) -> list[TaskGroup]:
        groups_root = self.config.storage_dir / "groups"
        if not groups_root.exists():
            with self._cache_lock:
                groups = [group.model_copy(deep=True) for group in self._groups.values()]
            groups.sort(key=lambda group: group.created_at, reverse=True)
            return groups

        loaded: list[TaskGroup] = []
        loaded_ids: set[str] = set()
        for group_file in sorted(groups_root.glob("*/group.json")):
            try:
                data = json.loads(group_file.read_text(encoding="utf-8"))
                group = TaskGroup(**data)
            except Exception:  # noqa: BLE001
                continue
            self._cache_group(group)
            loaded.append(group.model_copy(deep=True))
            loaded_ids.add(group.group_id)
        with self._cache_lock:
            for group_id in tuple(self._groups):
                if group_id not in loaded_ids:
                    self._groups.pop(group_id, None)
        loaded.sort(key=lambda group: group.created_at, reverse=True)
        return loaded

    def _persist_group_unlocked(self, group: TaskGroup) -> None:
        group_dir = self.config.get_group_dir(group.group_id)
        group_dir.mkdir(parents=True, exist_ok=True)
        group_file = group_dir / "group.json"
        tmp_file = group_dir / (
            f"group.json.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            tmp_file.write_text(
                json.dumps(
                    group.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
            for attempt in range(5):
                try:
                    tmp_file.replace(group_file)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.02)
        finally:
            tmp_file.unlink(missing_ok=True)

    def _load_group(self, group_id: str) -> TaskGroup | None:
        try:
            return self._load_group_strict(group_id)
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _load_group_strict(self, group_id: str) -> TaskGroup | None:
        group_file = self.config.get_group_dir(group_id) / "group.json"
        if not group_file.exists():
            return None
        try:
            data = json.loads(group_file.read_text(encoding="utf-8"))
            return TaskGroup(**data)
        except Exception as exc:  # noqa: BLE001
            raise TaskGroupPersistenceError(f"task_group_state_unreadable:{group_id}") from exc

    def delete_group(self, group_id: str) -> None:
        with self._group_file_lock(group_id):
            group_dir = self.config.get_group_dir(group_id)
            if group_dir.exists():
                shutil.rmtree(group_dir)
        with self._cache_lock:
            self._groups.pop(group_id, None)

    def _cache_group(self, group: TaskGroup) -> None:
        with self._cache_lock:
            cached = self._groups.get(group.group_id)
            if cached is not None and cached.state_version > group.state_version:
                return
            self._groups[group.group_id] = group.model_copy(deep=True)

    @contextmanager
    def _group_file_lock(self, group_id: str) -> Iterator[None]:
        digest = hashlib.sha256(group_id.encode("utf-8")).hexdigest()
        lock_path = self.config.storage_dir / "locks" / "task-groups" / f"{digest}.lock"
        try:
            with exclusive_file_lock(
                lock_path,
                timeout_seconds=float(self.config.management.task_group_lock_timeout_seconds),
                poll_interval_seconds=float(
                    self.config.management.task_group_lock_poll_interval_seconds
                ),
            ):
                yield
        except TimeoutError as exc:
            raise TaskGroupLockTimeout(group_id) from exc
