from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO


@contextmanager
def exclusive_file_lock(
    lock_path: Path,
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> Iterator[None]:
    """Hold a one-byte advisory lock that the OS releases on process exit."""

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as handle:
        _ensure_lock_byte(handle)
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                _lock_nonblocking(handle)
            except OSError as exc:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"file_lock_timeout:{lock_path}") from exc
                time.sleep(min(poll_interval_seconds, remaining))
            else:
                break
        try:
            yield
        finally:
            _unlock(handle)


def _ensure_lock_byte(handle: BinaryIO) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)


if os.name == "nt":
    import msvcrt

    def _lock_nonblocking(handle: BinaryIO) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(handle: BinaryIO) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock_nonblocking(handle: BinaryIO) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(handle: BinaryIO) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
