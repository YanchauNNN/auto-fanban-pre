from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic, sleep

import pytest

from src.archive.models import ArchiveStatus
from src.models import JobStatus
from src.pipeline.group_manager import GroupManager, TaskGroupVersionConflict
from src.task_groups.archive_coordinator import (
    REPLACEMENT_CLEANUP_CLAIM_KEY,
    TASK_GROUP_RECONCILIATION_ERROR_KEY,
    TaskGroupArchiveCoordinator,
)
from src.task_groups.state_writer import TaskGroupStateWriter
from src.workflow.models import WorkflowStatus
from src.workload.models import WorkloadSettlementStatus


def _manager(storage_dir: Path) -> GroupManager:
    manager = GroupManager()
    manager.config.storage_dir = storage_dir
    manager.config.management.task_group_lock_timeout_seconds = 2.0
    manager.config.management.task_group_lock_poll_interval_seconds = 0.01
    return manager


def _complete_replacement(
    manager: GroupManager,
    *,
    replaced_group_id: str | None = "group-old",
):
    group = manager.create_group(
        batch_id=None,
        source_filenames=["input.dwg"],
        project_no="2016",
        run_audit_check=False,
    )
    group.archive.status = ArchiveStatus.SUCCEEDED
    group.workflow.status = WorkflowStatus.ARCHIVED
    group.workload.settlement_status = WorkloadSettlementStatus.SETTLED
    group.status = JobStatus.SUCCEEDED
    group.replacement.replaced_group_id = replaced_group_id
    group.replacement.replaced_record_pending_delete = True
    manager.update_group(group)
    return group


def _coordinator(
    manager: GroupManager,
    overwrite_service,
    *,
    owner: str,
    ttl_seconds: float = 30.0,
) -> TaskGroupArchiveCoordinator:
    return TaskGroupArchiveCoordinator(
        archive_service=object(),
        workload_settlement_service=object(),
        state_writer=TaskGroupStateWriter(
            group_manager=manager,
            publisher=lambda _group_id: None,
        ),
        settlement_trigger="archive_success",
        overwrite_service=overwrite_service,
        cleanup_claim_ttl_seconds=ttl_seconds,
        cleanup_owner_id=owner,
    )


def test_two_workers_can_claim_pending_cleanup_only_once(tmp_path: Path) -> None:
    creator = _manager(tmp_path)
    group = _complete_replacement(creator)
    first_manager = _manager(tmp_path)
    second_manager = _manager(tmp_path)
    first = first_manager.reload_group(group.group_id)
    assert first is not None
    cleanup_started = threading.Event()
    release_cleanup = threading.Event()

    class _BlockingOverwrite:
        def __init__(self) -> None:
            self.calls = 0
            self.lock = threading.Lock()

        def cleanup_replaced_group(self, _group) -> None:
            with self.lock:
                self.calls += 1
            cleanup_started.set()
            assert release_cleanup.wait(timeout=5)

    overwrite = _BlockingOverwrite()
    first_coordinator = _coordinator(first_manager, overwrite, owner="worker-1")
    second_coordinator = _coordinator(second_manager, overwrite, owner="worker-2")

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(
            first_coordinator.retry_pending_replacement_cleanup,
            first,
        )
        assert cleanup_started.wait(timeout=5)
        second = second_manager.reload_group(group.group_id)
        assert second is not None
        second_future = executor.submit(
            second_coordinator.retry_pending_replacement_cleanup,
            second,
        )
        assert second_future.result(timeout=5) is False
        assert second.metadata[REPLACEMENT_CLEANUP_CLAIM_KEY]["owner"] == "worker-1"
        release_cleanup.set()
        assert first_future.result(timeout=5) is True

    assert overwrite.calls == 1
    final = creator.reload_group(group.group_id)
    assert final is not None
    assert final.replacement.replaced_record_pending_delete is False
    assert REPLACEMENT_CLEANUP_CLAIM_KEY not in final.metadata


def test_same_owner_cannot_reenter_an_active_cleanup_claim(tmp_path: Path) -> None:
    creator = _manager(tmp_path)
    group = _complete_replacement(creator)
    first_manager = _manager(tmp_path)
    second_manager = _manager(tmp_path)
    first = first_manager.reload_group(group.group_id)
    assert first is not None
    cleanup_started = threading.Event()
    release_cleanup = threading.Event()

    class _BlockingOverwrite:
        def __init__(self) -> None:
            self.calls = 0
            self.lock = threading.Lock()

        def cleanup_replaced_group(self, _group) -> None:
            with self.lock:
                self.calls += 1
            cleanup_started.set()
            assert release_cleanup.wait(timeout=5)

    overwrite = _BlockingOverwrite()
    first_coordinator = _coordinator(first_manager, overwrite, owner="shared-worker")
    second_coordinator = _coordinator(second_manager, overwrite, owner="shared-worker")

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(
            first_coordinator.retry_pending_replacement_cleanup,
            first,
        )
        assert cleanup_started.wait(timeout=5)
        second = second_manager.reload_group(group.group_id)
        assert second is not None
        second_future = executor.submit(
            second_coordinator.retry_pending_replacement_cleanup,
            second,
        )
        try:
            assert second_future.result(timeout=1) is False
            assert overwrite.calls == 1
        finally:
            release_cleanup.set()
        assert first_future.result(timeout=5) is True


def test_cleanup_operation_lock_serializes_delete_across_claim_ttl(tmp_path: Path) -> None:
    creator = _manager(tmp_path)
    group = _complete_replacement(creator)
    first_manager = _manager(tmp_path)
    second_manager = _manager(tmp_path)
    observer = _manager(tmp_path)
    first = first_manager.reload_group(group.group_id)
    assert first is not None
    first_started = threading.Event()
    release_first = threading.Event()
    second_has_operation_lock = threading.Event()
    allow_second_after_inspection = threading.Event()

    class _BlockingOverwrite:
        def __init__(self) -> None:
            self.calls = 0
            self.active = 0
            self.max_active = 0
            self.lock = threading.Lock()

        def cleanup_replaced_group(self, _group) -> None:
            with self.lock:
                self.calls += 1
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                call_number = self.calls
            try:
                if call_number == 1:
                    first_started.set()
                assert release_first.wait(timeout=5)
            finally:
                with self.lock:
                    self.active -= 1

    overwrite = _BlockingOverwrite()
    first_coordinator = _coordinator(
        first_manager,
        overwrite,
        owner="worker-before-ttl",
        ttl_seconds=1.0,
    )

    class _PausedTakeoverCoordinator(TaskGroupArchiveCoordinator):
        def _cleanup_replacement_under_operation_lock(self, *args, **kwargs):
            second_has_operation_lock.set()
            assert allow_second_after_inspection.wait(timeout=5)
            return super()._cleanup_replacement_under_operation_lock(*args, **kwargs)

    second_coordinator = _PausedTakeoverCoordinator(
        archive_service=object(),
        workload_settlement_service=object(),
        state_writer=TaskGroupStateWriter(
            group_manager=second_manager,
            publisher=lambda _group_id: None,
        ),
        settlement_trigger="archive_success",
        overwrite_service=overwrite,
        cleanup_claim_ttl_seconds=1.0,
        cleanup_owner_id="worker-after-ttl",
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(
            first_coordinator.retry_pending_replacement_cleanup,
            first,
        )
        assert first_started.wait(timeout=5)

        expired = observer.reload_group(group.group_id)
        assert expired is not None
        expired.metadata[REPLACEMENT_CLEANUP_CLAIM_KEY]["claimed_at"] = (
            datetime.now(UTC) - timedelta(seconds=10)
        ).isoformat()
        observer.update_group(expired)

        second = second_manager.reload_group(group.group_id)
        assert second is not None
        second_future = executor.submit(
            second_coordinator.retry_pending_replacement_cleanup,
            second,
        )

        deadline = monotonic() + 5
        while monotonic() < deadline:
            claimed = observer.reload_group(group.group_id)
            if (
                claimed is not None
                and claimed.metadata.get(REPLACEMENT_CLEANUP_CLAIM_KEY, {}).get("owner")
                == "worker-after-ttl"
            ):
                break
            sleep(0.01)
        else:
            raise AssertionError("takeover worker did not persist a replacement claim")

        assert overwrite.max_active == 1
        assert not second_future.done()
        release_first.set()
        assert first_future.result(timeout=5) is True
        assert second_has_operation_lock.wait(timeout=5)

        completed_by_original = observer.reload_group(group.group_id)
        assert completed_by_original is not None
        assert completed_by_original.replacement.replaced_record_pending_delete is False
        assert (
            completed_by_original.metadata[REPLACEMENT_CLEANUP_CLAIM_KEY]["owner"]
            == "worker-after-ttl"
        )

        allow_second_after_inspection.set()
        assert second_future.result(timeout=5) is True

    assert overwrite.calls == 1
    assert overwrite.max_active == 1
    final = observer.reload_group(group.group_id)
    assert final is not None
    assert final.replacement.replaced_record_pending_delete is False
    assert REPLACEMENT_CLEANUP_CLAIM_KEY not in final.metadata


def test_claim_token_mismatch_after_operation_lock_never_deletes(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    group = _complete_replacement(manager)

    class _Overwrite:
        calls = 0

        def cleanup_replaced_group(self, _group) -> None:
            self.calls += 1

    overwrite = _Overwrite()

    coordinator = TaskGroupArchiveCoordinator(
        archive_service=object(),
        workload_settlement_service=object(),
        state_writer=TaskGroupStateWriter(
            group_manager=manager,
            publisher=lambda _group_id: None,
        ),
        settlement_trigger="archive_success",
        overwrite_service=overwrite,
        cleanup_claim_ttl_seconds=30.0,
        cleanup_owner_id="original-worker",
    )
    real_fence = coordinator.cleanup_fence

    class _TokenMismatchFence:
        @contextmanager
        def operation(self, replaced_group_id):
            with real_fence.operation(replaced_group_id) as normalized_replaced_group_id:
                replacement = manager.reload_group(group.group_id)
                assert replacement is not None
                replacement.metadata[REPLACEMENT_CLEANUP_CLAIM_KEY] = {
                    "owner": "replacement-worker",
                    "token": "replacement-token",
                    "claimed_at": datetime.now(UTC).isoformat(),
                }
                manager.update_group(replacement)
                yield normalized_replaced_group_id

        def normalize_replaced_group_id(self, value):
            return real_fence.normalize_replaced_group_id(value)

        def has_deletion_receipt(self, normalized_replaced_group_id: str) -> bool:
            return real_fence.has_deletion_receipt(normalized_replaced_group_id)

        def record_deletion(self, normalized_replaced_group_id: str) -> None:
            real_fence.record_deletion(normalized_replaced_group_id)

    coordinator.cleanup_fence = _TokenMismatchFence()
    snapshot = manager.reload_group(group.group_id)
    assert snapshot is not None

    assert coordinator.retry_pending_replacement_cleanup(snapshot) is False
    assert overwrite.calls == 0
    final = manager.reload_group(group.group_id)
    assert final is not None
    assert final.replacement.replaced_record_pending_delete is True
    assert final.metadata[REPLACEMENT_CLEANUP_CLAIM_KEY]["token"] == "replacement-token"


def test_two_successors_for_same_predecessor_share_one_delete_fence(tmp_path: Path) -> None:
    creator = _manager(tmp_path)
    predecessor_id = "  GROUP-shared-predecessor  "
    first_group = _complete_replacement(
        creator,
        replaced_group_id=predecessor_id,
    )
    second_group = _complete_replacement(
        creator,
        replaced_group_id="group-SHARED-predecessor",
    )
    first_manager = _manager(tmp_path)
    second_manager = _manager(tmp_path)
    observer = _manager(tmp_path)
    first = first_manager.reload_group(first_group.group_id)
    second = second_manager.reload_group(second_group.group_id)
    assert first is not None and second is not None
    first_started = threading.Event()
    release_deletes = threading.Event()

    class _BlockingOverwrite:
        def __init__(self) -> None:
            self.calls = 0
            self.active = 0
            self.max_active = 0
            self.lock = threading.Lock()

        def cleanup_replaced_group(self, _group) -> None:
            with self.lock:
                self.calls += 1
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                if self.calls == 1:
                    first_started.set()
            try:
                assert release_deletes.wait(timeout=5)
            finally:
                with self.lock:
                    self.active -= 1

    overwrite = _BlockingOverwrite()
    first_coordinator = _coordinator(
        first_manager,
        overwrite,
        owner="first-successor-worker",
        ttl_seconds=1.0,
    )
    second_coordinator = _coordinator(
        second_manager,
        overwrite,
        owner="second-successor-worker",
        ttl_seconds=1.0,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(
            first_coordinator.retry_pending_replacement_cleanup,
            first,
        )
        assert first_started.wait(timeout=5)

        expired_first = observer.reload_group(first_group.group_id)
        assert expired_first is not None
        expired_first.metadata[REPLACEMENT_CLEANUP_CLAIM_KEY]["claimed_at"] = (
            datetime.now(UTC) - timedelta(seconds=10)
        ).isoformat()
        observer.update_group(expired_first)

        second_future = executor.submit(
            second_coordinator.retry_pending_replacement_cleanup,
            second,
        )
        deadline = monotonic() + 5
        while monotonic() < deadline:
            claimed = observer.reload_group(second_group.group_id)
            if (
                claimed is not None
                and claimed.metadata.get(REPLACEMENT_CLEANUP_CLAIM_KEY, {}).get("owner")
                == "second-successor-worker"
            ):
                break
            sleep(0.01)
        else:
            raise AssertionError("second successor did not persist its cleanup claim")

        try:
            assert overwrite.max_active == 1
            assert not second_future.done()
        finally:
            release_deletes.set()
        assert first_future.result(timeout=5) is True
        assert second_future.result(timeout=5) is True

    assert overwrite.calls == 1
    assert overwrite.max_active == 1
    for successor_id in (first_group.group_id, second_group.group_id):
        completed = observer.reload_group(successor_id)
        assert completed is not None
        assert completed.replacement.replaced_record_pending_delete is False
        assert REPLACEMENT_CLEANUP_CLAIM_KEY not in completed.metadata


def test_deletion_receipt_prevents_repeat_after_post_delete_cas_takeover(
    tmp_path: Path,
) -> None:
    creator = _manager(tmp_path)
    group = _complete_replacement(
        creator,
        replaced_group_id="group-shared-predecessor",
    )
    original_manager = _manager(tmp_path)
    takeover_manager = _manager(tmp_path)
    observer = _manager(tmp_path)
    original = original_manager.reload_group(group.group_id)
    assert original is not None

    class _Overwrite:
        def __init__(self) -> None:
            self.calls = 0

        def cleanup_replaced_group(self, _group) -> None:
            self.calls += 1

    overwrite = _Overwrite()
    takeover_future = None
    takeover_coordinator = _coordinator(
        takeover_manager,
        overwrite,
        owner="takeover-worker",
        ttl_seconds=1.0,
    )

    with ThreadPoolExecutor(max_workers=1) as executor:

        def _start_takeover_after_post_delete_reload() -> None:
            nonlocal takeover_future
            expired = observer.reload_group(group.group_id)
            assert expired is not None
            expired.metadata[REPLACEMENT_CLEANUP_CLAIM_KEY]["claimed_at"] = (
                datetime.now(UTC) - timedelta(seconds=10)
            ).isoformat()
            observer.update_group(expired)
            takeover = takeover_manager.reload_group(group.group_id)
            assert takeover is not None
            takeover_future = executor.submit(
                takeover_coordinator.retry_pending_replacement_cleanup,
                takeover,
            )
            deadline = monotonic() + 5
            while monotonic() < deadline:
                claimed = observer.reload_group(group.group_id)
                if (
                    claimed is not None
                    and claimed.metadata.get(REPLACEMENT_CLEANUP_CLAIM_KEY, {}).get("owner")
                    == "takeover-worker"
                ):
                    return
                sleep(0.01)
            raise AssertionError("takeover worker did not persist its cleanup claim")

        class _CompletionRaceWriter(TaskGroupStateWriter):
            def __init__(self) -> None:
                super().__init__(
                    group_manager=original_manager,
                    publisher=lambda _group_id: None,
                )
                self.triggered = False

            def write(self, current):
                if (
                    not self.triggered
                    and not current.replacement.replaced_record_pending_delete
                ):
                    self.triggered = True
                    _start_takeover_after_post_delete_reload()
                return super().write(current)

        original_coordinator = TaskGroupArchiveCoordinator(
            archive_service=object(),
            workload_settlement_service=object(),
            state_writer=_CompletionRaceWriter(),
            settlement_trigger="archive_success",
            overwrite_service=overwrite,
            cleanup_claim_ttl_seconds=1.0,
            cleanup_owner_id="original-worker",
        )

        with pytest.raises(TaskGroupVersionConflict):
            original_coordinator.retry_pending_replacement_cleanup(original)
        assert takeover_future is not None
        assert takeover_future.result(timeout=5) is True

    assert overwrite.calls == 1
    final = observer.reload_group(group.group_id)
    assert final is not None
    assert final.replacement.replaced_record_pending_delete is False
    assert REPLACEMENT_CLEANUP_CLAIM_KEY not in final.metadata


@pytest.mark.parametrize("missing_replaced_group_id", [None, "", "   "])
def test_missing_replaced_group_id_is_persisted_as_reconciliation_error(
    tmp_path: Path,
    missing_replaced_group_id: str | None,
) -> None:
    manager = _manager(tmp_path)
    group = _complete_replacement(
        manager,
        replaced_group_id=missing_replaced_group_id,
    )

    class _Overwrite:
        calls = 0

        def cleanup_replaced_group(self, _group) -> None:
            self.calls += 1

    overwrite = _Overwrite()
    coordinator = _coordinator(manager, overwrite, owner="worker-corrupt-state")
    snapshot = manager.reload_group(group.group_id)
    assert snapshot is not None

    assert coordinator.retry_pending_replacement_cleanup(snapshot) is False

    persisted = manager.reload_group(group.group_id)
    assert persisted is not None
    assert persisted.replacement.replaced_record_pending_delete is True
    assert persisted.metadata[TASK_GROUP_RECONCILIATION_ERROR_KEY] == {
        "stage": "replacement_cleanup",
        "message": "replacement_cleanup_missing_replaced_group_id",
    }
    assert REPLACEMENT_CLEANUP_CLAIM_KEY not in persisted.metadata
    assert overwrite.calls == 0
    assert not (tmp_path / "locks" / "replacement-cleanup-operations").exists()
    assert not (tmp_path / "rc").exists()


def test_expired_cleanup_claim_can_be_taken_over(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    group = _complete_replacement(manager)
    group.metadata[REPLACEMENT_CLEANUP_CLAIM_KEY] = {
        "owner": "dead-worker",
        "claimed_at": (datetime.now(UTC) - timedelta(seconds=10)).isoformat(),
    }
    manager.update_group(group)

    class _Overwrite:
        calls = 0

        def cleanup_replaced_group(self, _group) -> None:
            self.calls += 1

    overwrite = _Overwrite()
    snapshot = manager.reload_group(group.group_id)
    assert snapshot is not None

    assert (
        _coordinator(
            manager, overwrite, owner="new-worker", ttl_seconds=1.0
        ).retry_pending_replacement_cleanup(snapshot)
        is True
    )
    assert overwrite.calls == 1


def test_cleanup_failure_releases_claim_but_keeps_pending(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    group = _complete_replacement(manager)

    class _FailingOverwrite:
        def cleanup_replaced_group(self, _group) -> None:
            raise RuntimeError("old group locked")

    snapshot = manager.reload_group(group.group_id)
    assert snapshot is not None
    coordinator = _coordinator(manager, _FailingOverwrite(), owner="worker-1")

    assert coordinator.retry_pending_replacement_cleanup(snapshot) is False

    failed = manager.reload_group(group.group_id)
    assert failed is not None
    assert failed.replacement.replaced_record_pending_delete is True
    assert REPLACEMENT_CLEANUP_CLAIM_KEY not in failed.metadata
    assert failed.metadata[TASK_GROUP_RECONCILIATION_ERROR_KEY] == {
        "stage": "replacement_cleanup",
        "message": "old group locked",
    }
