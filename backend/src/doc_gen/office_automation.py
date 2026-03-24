from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from ..config import get_config


class OfficeAutomationLimiter:
    """Coordinates headless Office COM access so batch runs stay stable."""

    def __init__(self, *, word_limit: int, excel_limit: int) -> None:
        self.word_limit = max(int(word_limit), 1)
        self.excel_limit = max(int(excel_limit), 1)
        self._word_semaphore = threading.BoundedSemaphore(self.word_limit)
        self._excel_semaphore = threading.BoundedSemaphore(self.excel_limit)

    @contextmanager
    def word_session(self) -> Iterator[None]:
        self._word_semaphore.acquire()
        try:
            yield
        finally:
            self._word_semaphore.release()

    @contextmanager
    def excel_session(self) -> Iterator[None]:
        self._excel_semaphore.acquire()
        try:
            yield
        finally:
            self._excel_semaphore.release()


_LIMITER_LOCK = threading.Lock()
_LIMITER: OfficeAutomationLimiter | None = None
_LIMITER_SIGNATURE: tuple[int, int] | None = None


def get_office_automation_limiter() -> OfficeAutomationLimiter:
    config = get_config()
    signature = (
        max(int(config.concurrency.office_word_max_jobs), 1),
        max(int(config.concurrency.office_excel_max_jobs), 1),
    )

    global _LIMITER
    global _LIMITER_SIGNATURE
    with _LIMITER_LOCK:
        if _LIMITER is None or _LIMITER_SIGNATURE != signature:
            _LIMITER = OfficeAutomationLimiter(
                word_limit=signature[0],
                excel_limit=signature[1],
            )
            _LIMITER_SIGNATURE = signature
        return _LIMITER


def reset_office_automation_limiter() -> None:
    global _LIMITER
    global _LIMITER_SIGNATURE
    with _LIMITER_LOCK:
        _LIMITER = None
        _LIMITER_SIGNATURE = None
