from __future__ import annotations

import errno
import math
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path


@contextmanager
def cache_writer_lock(cache_dir: Path | str) -> Iterator[None]:
    """Reject concurrent writers; the OS releases the lock when the handle closes."""
    root = Path(cache_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    # Keep the lock file: unlinking it could let writers lock different inodes.
    with (root / ".writer.lock").open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
        try:
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise
            raise RuntimeError(f"cache writer already active: {root}") from exc
        yield


@lru_cache(maxsize=1)
def _policy() -> tuple[int, float, float]:
    import yaml

    path = Path(__file__).resolve().parents[1] / "assets/corpus_build.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported corpus build policy")
    policy = payload["atomic_replace"]
    attempts = policy["attempts"]
    delay = float(policy["initial_delay_seconds"])
    maximum = float(policy["max_delay_seconds"])
    if type(attempts) is not int or not 1 <= attempts <= 10:
        raise ValueError("atomic replace attempts must be between 1 and 10")
    if not all(math.isfinite(value) for value in (delay, maximum)) or not 0 <= delay <= maximum <= 5:
        raise ValueError("invalid atomic replace backoff")
    return attempts, delay, maximum


def replace_atomic(source: Path, destination: Path) -> None:
    attempts, delay, maximum = _policy()
    for attempt in range(attempts):
        try:
            os.replace(source, destination)
            return
        except PermissionError as exc:
            # Windows readers/scanners can briefly deny rename while holding a handle.
            if getattr(exc, "winerror", None) not in {5, 32, 33} or attempt + 1 == attempts:
                raise
            time.sleep(min(delay * 2**attempt, maximum))
