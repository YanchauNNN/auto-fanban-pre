from __future__ import annotations

from functools import partial
from pathlib import Path

import pytest

from src.models import Job, JobType, TaskGroup
from src.pipeline.group_manager import GroupManager
from src.pipeline.job_manager import JobManager


@pytest.mark.parametrize("manager_kind", ["group", "job"])
def test_delete_failure_is_visible_and_keeps_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    manager_kind: str,
) -> None:
    if manager_kind == "group":
        manager = GroupManager()
        manager.config.storage_dir = tmp_path
        item = TaskGroup(group_id="group-1", project_no="2016")
        manager.update_group(item)
        cache = manager._groups
        delete = partial(manager.delete_group, item.group_id)
        item_id = item.group_id
    else:
        manager = JobManager()
        manager.config.storage_dir = tmp_path
        item = Job(job_id="job-1", job_type=JobType.DELIVERABLE, project_no="2016")
        manager.update_job(item)
        cache = manager._jobs
        delete = partial(manager.delete_job, item.job_id)
        item_id = item.job_id

    def _fail_delete(_path: Path) -> None:
        raise PermissionError("directory locked")

    monkeypatch.setattr("shutil.rmtree", _fail_delete)

    with pytest.raises(PermissionError, match="directory locked"):
        delete()

    assert item_id in cache


def test_repeated_missing_record_deletion_is_idempotent(tmp_path: Path) -> None:
    group_manager = GroupManager()
    group_manager.config.storage_dir = tmp_path
    job_manager = JobManager()
    job_manager.config.storage_dir = tmp_path

    group_manager.delete_group("missing-group")
    group_manager.delete_group("missing-group")
    job_manager.delete_job("missing-job")
    job_manager.delete_job("missing-job")
