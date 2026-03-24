from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from src.config import SpecLoader, reload_config


def _configure_runtime_env(monkeypatch, tmp_path: Path, *, excel_limit: int = 1, word_limit: int = 1) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    monkeypatch.setenv("FANBAN_SPEC_PATH", str(repo_root / "documents" / "鍙傛暟瑙勮寖.yaml"))
    monkeypatch.setenv(
        "FANBAN_RUNTIME_SPEC_PATH",
        str(repo_root / "documents" / "鍙傛暟瑙勮寖_杩愯鏈?yaml"),
    )
    monkeypatch.setenv("FANBAN_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("FANBAN_CONCURRENCY__OFFICE_EXCEL_MAX_JOBS", str(excel_limit))
    monkeypatch.setenv("FANBAN_CONCURRENCY__OFFICE_WORD_MAX_JOBS", str(word_limit))
    SpecLoader.clear_cache()
    reload_config()


def test_office_automation_limiter_uses_configured_limits(monkeypatch, tmp_path: Path) -> None:
    _configure_runtime_env(monkeypatch, tmp_path, excel_limit=2, word_limit=3)

    from src.doc_gen.office_automation import (
        get_office_automation_limiter,
        reset_office_automation_limiter,
    )

    reset_office_automation_limiter()
    limiter = get_office_automation_limiter()

    assert limiter.excel_limit == 2
    assert limiter.word_limit == 3


def test_excel_session_serializes_threads_when_limit_is_one(monkeypatch, tmp_path: Path) -> None:
    _configure_runtime_env(monkeypatch, tmp_path, excel_limit=1, word_limit=1)

    from src.doc_gen.office_automation import (
        get_office_automation_limiter,
        reset_office_automation_limiter,
    )

    reset_office_automation_limiter()
    limiter = get_office_automation_limiter()

    state_lock = threading.Lock()
    active = 0
    peak_active = 0
    order: list[str] = []
    first_entered = threading.Event()

    def worker(label: str, hold_time: float) -> None:
        nonlocal active
        nonlocal peak_active
        with limiter.excel_session():
            with state_lock:
                active += 1
                peak_active = max(peak_active, active)
                order.append(f"enter-{label}")
                if label == "a":
                    first_entered.set()
            time.sleep(hold_time)
            with state_lock:
                order.append(f"leave-{label}")
                active -= 1

    thread_a = threading.Thread(target=worker, args=("a", 0.2), daemon=True)
    thread_b = threading.Thread(target=worker, args=("b", 0.01), daemon=True)

    thread_a.start()
    assert first_entered.wait(timeout=1.0) is True
    thread_b.start()

    thread_a.join(timeout=2.0)
    thread_b.join(timeout=2.0)

    assert peak_active == 1
    assert order == ["enter-a", "leave-a", "enter-b", "leave-b"]


def test_office_com_call_sites_are_guarded_by_limiter() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    pdf_engine = (repo_root / "backend" / "src" / "doc_gen" / "pdf_engine.py").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    catalog = (repo_root / "backend" / "src" / "doc_gen" / "catalog.py").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    cover = (repo_root / "backend" / "src" / "doc_gen" / "cover.py").read_text(
        encoding="utf-8",
        errors="ignore",
    )

    assert "get_office_automation_limiter().word_session()" in pdf_engine
    assert "get_office_automation_limiter().excel_session()" in pdf_engine
    assert "get_office_automation_limiter().excel_session()" in catalog
    assert "limiter = get_office_automation_limiter()" in cover
    assert "with limiter.word_session():" in cover
    assert "with limiter.excel_session():" in cover
