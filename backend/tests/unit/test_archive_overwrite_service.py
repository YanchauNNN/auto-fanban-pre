from __future__ import annotations

import pytest

from src.archive.overwrite_service import ArchiveOverwriteService
from src.models import TaskGroup


class _GroupManager:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def get_group(self, _group_id: str):
        return None

    def delete_group(self, group_id: str) -> None:
        self.deleted.append(group_id)


class _JobManager:
    def delete_job(self, _job_id: str) -> None:
        raise AssertionError("no child jobs should be deleted for a missing group")


def test_delete_group_records_removes_stale_summary_when_group_file_is_missing() -> None:
    group_manager = _GroupManager()
    removed: list[tuple[str, str]] = []
    service = ArchiveOverwriteService(
        group_manager,
        _JobManager(),
        remove_summary_index=lambda item_type, item_id: removed.append((item_type, item_id)),
    )

    service.delete_group_records_by_id("group-old")

    assert group_manager.deleted == ["group-old"]
    assert removed == [("group", "group-old")]


def test_summary_delete_failure_preserves_group_and_child_jobs() -> None:
    group = TaskGroup(
        group_id="group-old",
        project_no="2016",
        child_job_ids=["job-old"],
    )

    class _ExistingGroupManager(_GroupManager):
        def get_group(self, _group_id: str):
            return group

    class _RecordingJobManager:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        def delete_job(self, job_id: str) -> None:
            self.deleted.append(job_id)

    group_manager = _ExistingGroupManager()
    job_manager = _RecordingJobManager()

    def _fail_summary_delete(_item_type: str, _item_id: str) -> None:
        raise RuntimeError("sqlite unavailable")

    service = ArchiveOverwriteService(
        group_manager,
        job_manager,
        remove_summary_index=_fail_summary_delete,
    )

    with pytest.raises(RuntimeError, match="sqlite unavailable"):
        service.delete_group_records_by_id(group.group_id)

    assert job_manager.deleted == []
    assert group_manager.deleted == []


def test_child_delete_failure_restores_summary_before_reraising() -> None:
    group = TaskGroup(
        group_id="group-old",
        project_no="2016",
        child_job_ids=["job-old"],
    )

    class _ExistingGroupManager(_GroupManager):
        def get_group(self, _group_id: str):
            return group

    class _FailingJobManager:
        def delete_job(self, _job_id: str) -> None:
            raise RuntimeError("job delete failed")

    removed: list[tuple[str, str]] = []
    restored: list[tuple[str, str]] = []
    group_manager = _ExistingGroupManager()
    service = ArchiveOverwriteService(
        group_manager,
        _FailingJobManager(),
        remove_summary_index=lambda item_type, item_id: removed.append((item_type, item_id)),
        restore_summary_index=lambda item_type, item_id: restored.append((item_type, item_id)),
    )

    with pytest.raises(RuntimeError, match="job delete failed"):
        service.delete_group_records_by_id(group.group_id)

    assert removed == [("group", group.group_id)]
    assert restored == [("group", group.group_id)]
    assert group_manager.deleted == []
