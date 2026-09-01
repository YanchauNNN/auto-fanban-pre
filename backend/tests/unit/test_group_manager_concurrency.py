from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src.pipeline.group_manager import GroupManager, TaskGroupVersionConflict
from src.task_groups.state_writer import (
    SUMMARY_PUBLICATION_PENDING_KEY,
    TaskGroupStateWriter,
)


def _manager(storage_dir: Path) -> GroupManager:
    manager = GroupManager()
    manager.config.storage_dir = storage_dir
    manager.config.management.task_group_lock_timeout_seconds = 2.0
    manager.config.management.task_group_lock_poll_interval_seconds = 0.01
    return manager


def _create_group(manager: GroupManager):
    return manager.create_group(
        batch_id=None,
        source_filenames=["input.dwg"],
        project_no="2016",
        run_audit_check=False,
    )


def test_stale_snapshot_is_rejected_and_fresh_retry_preserves_new_fields(tmp_path: Path) -> None:
    first_manager = _manager(tmp_path)
    group = _create_group(first_manager)
    assert group.state_version == 1

    second_manager = _manager(tmp_path)
    first = first_manager.reload_group(group.group_id)
    stale = second_manager.reload_group(group.group_id)
    assert first is not None and stale is not None
    stale_version = stale.state_version

    first.metadata["approval_field"] = "approved"
    first_manager.update_group(first)

    stale.metadata["stale_writer_field"] = "must-not-win"
    with pytest.raises(TaskGroupVersionConflict, match="task_group_version_conflict"):
        second_manager.update_group(stale)

    assert stale.state_version == stale_version
    assert second_manager._groups[group.group_id].state_version == stale_version
    disk_payload = json.loads(
        (tmp_path / "groups" / group.group_id / "group.json").read_text(encoding="utf-8")
    )
    assert disk_payload["state_version"] == first.state_version
    assert disk_payload["metadata"]["approval_field"] == "approved"
    assert "stale_writer_field" not in disk_payload["metadata"]

    fresh = second_manager.reload_group(group.group_id)
    assert fresh is not None
    fresh.metadata["fresh_writer_field"] = "kept"
    second_manager.update_group(fresh)

    reloaded = first_manager.reload_group(group.group_id)
    assert reloaded is not None
    assert reloaded.metadata == {
        "approval_field": "approved",
        "fresh_writer_field": "kept",
    }


def test_two_managers_racing_same_version_have_exactly_one_winner(tmp_path: Path) -> None:
    creator = _manager(tmp_path)
    group = _create_group(creator)
    first_manager = _manager(tmp_path)
    second_manager = _manager(tmp_path)
    first = first_manager.reload_group(group.group_id)
    second = second_manager.reload_group(group.group_id)
    assert first is not None and second is not None
    first.metadata["winner_a"] = True
    second.metadata["winner_b"] = True
    barrier = threading.Barrier(2)

    def _update(manager: GroupManager, snapshot) -> str:
        barrier.wait(timeout=2)
        try:
            manager.update_group(snapshot)
        except TaskGroupVersionConflict:
            return "conflict"
        return "updated"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_update, first_manager, first),
            executor.submit(_update, second_manager, second),
        ]
        results = [future.result(timeout=5) for future in futures]

    assert sorted(results) == ["conflict", "updated"]
    payload = json.loads(
        (tmp_path / "groups" / group.group_id / "group.json").read_text(encoding="utf-8")
    )
    assert payload["state_version"] == 2
    assert sum(key in payload["metadata"] for key in ("winner_a", "winner_b")) == 1


def test_cached_reads_are_independent_snapshots(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    group = _create_group(manager)

    first = manager.get_group(group.group_id)
    second = manager.get_group(group.group_id)
    assert first is not None and second is not None
    first.metadata["uncommitted"] = True

    assert "uncommitted" not in second.metadata
    assert "uncommitted" not in manager._groups[group.group_id].metadata


def test_delayed_lower_version_cache_write_cannot_replace_newer_state(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    group = _create_group(manager)
    delayed_snapshot = manager.reload_group(group.group_id)
    assert delayed_snapshot is not None

    current = manager.reload_group(group.group_id)
    assert current is not None
    current.metadata["newer_field"] = "preserved"
    manager.update_group(current)
    assert current.state_version > delayed_snapshot.state_version

    # Simulate a delayed disk reader reaching the cache after the newer write.
    manager._cache_group(delayed_snapshot)

    cached = manager.get_group(group.group_id)
    assert cached is not None
    assert cached.state_version == current.state_version
    assert cached.metadata["newer_field"] == "preserved"


def test_publication_conflict_reloads_without_losing_concurrent_approval(tmp_path: Path) -> None:
    writer_manager = _manager(tmp_path)
    group = _create_group(writer_manager)
    approval_manager = _manager(tmp_path)
    writer_snapshot = writer_manager.reload_group(group.group_id)
    assert writer_snapshot is not None

    def _publish_with_concurrent_approval(_group_id: str) -> None:
        approval = approval_manager.reload_group(group.group_id)
        assert approval is not None
        approval.metadata["approval_field"] = "kept"
        approval_manager.update_group(approval)

    writer = TaskGroupStateWriter(
        group_manager=writer_manager,
        publisher=_publish_with_concurrent_approval,
    )
    with pytest.raises(TaskGroupVersionConflict):
        writer.write(writer_snapshot)

    after_conflict = approval_manager.reload_group(group.group_id)
    assert after_conflict is not None
    assert after_conflict.metadata["approval_field"] == "kept"
    assert after_conflict.metadata[SUMMARY_PUBLICATION_PENDING_KEY] is True

    retry = TaskGroupStateWriter(group_manager=writer_manager, publisher=lambda _group_id: None)
    report = retry.retry_pending_publications()

    assert report.succeeded == 1
    final = approval_manager.reload_group(group.group_id)
    assert final is not None
    assert final.metadata["approval_field"] == "kept"
    assert SUMMARY_PUBLICATION_PENDING_KEY not in final.metadata
