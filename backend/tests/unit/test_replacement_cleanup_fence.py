from __future__ import annotations

import multiprocessing
from pathlib import Path

from src.task_groups.replacement_cleanup_fence import ReplacementCleanupFence


def _hold_cleanup_fence(
    storage_dir: str,
    replaced_group_id: str,
    attempting,
    acquired,
    release,
) -> None:
    fence = ReplacementCleanupFence(
        storage_dir=Path(storage_dir),
        lock_timeout_seconds=5.0,
        lock_poll_interval_seconds=0.01,
    )
    attempting.set()
    with fence.operation(replaced_group_id):
        acquired.set()
        if not release.wait(timeout=5):
            raise RuntimeError("test cleanup fence release timed out")


def _attempt_cleanup_fence(
    storage_dir: str,
    replaced_group_id: str,
    attempting,
    result_queue,
) -> None:
    fence = ReplacementCleanupFence(
        storage_dir=Path(storage_dir),
        lock_timeout_seconds=0.2,
        lock_poll_interval_seconds=0.01,
    )
    attempting.set()
    try:
        with fence.operation(replaced_group_id):
            result_queue.put("acquired")
    except TimeoutError:
        result_queue.put("timeout")


def test_operation_lock_is_shared_by_independent_windows_processes(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    first_attempting = context.Event()
    first_acquired = context.Event()
    first_release = context.Event()
    second_attempting = context.Event()
    second_result = context.Queue()
    first = context.Process(
        target=_hold_cleanup_fence,
        args=(
            str(tmp_path),
            " GROUP-shared-predecessor ",
            first_attempting,
            first_acquired,
            first_release,
        ),
    )
    second = context.Process(
        target=_attempt_cleanup_fence,
        args=(
            str(tmp_path),
            "group-SHARED-predecessor",
            second_attempting,
            second_result,
        ),
    )

    first.start()
    second_started = False
    try:
        assert first_acquired.wait(timeout=5)
        second.start()
        second_started = True
        assert second_attempting.wait(timeout=5)
        assert second_result.get(timeout=5) == "timeout"
        second.join(timeout=5)
        assert second.exitcode == 0
        assert first.is_alive()

        first_release.set()
        first.join(timeout=5)
        assert first.exitcode == 0
    finally:
        first_release.set()
        if first.is_alive():
            first.terminate()
            first.join(timeout=5)
        if second_started and second.is_alive():
            second.terminate()
            second.join(timeout=5)
        second_result.close()
        second_result.join_thread()


def test_record_deletion_succeeds_from_a_real_deep_windows_path(tmp_path: Path) -> None:
    component_length = max(8, 190 - len(str(tmp_path)) - 1)
    storage_dir = tmp_path / ("d" * component_length)
    storage_dir.mkdir(parents=True)
    assert len(str(storage_dir)) >= 185
    fence = ReplacementCleanupFence(
        storage_dir=storage_dir,
        lock_timeout_seconds=1.0,
        lock_poll_interval_seconds=0.01,
    )
    normalized_id = fence.normalize_replaced_group_id("group-deep-path")

    fence.record_deletion(normalized_id)

    assert fence.has_deletion_receipt(normalized_id) is True
