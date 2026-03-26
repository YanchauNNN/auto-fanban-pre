from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from src.config import SpecLoader, reload_config
from src.config.runtime_config import RuntimeConfig


def test_runtime_config_defaults_align_with_eight_slot_baseline(
    monkeypatch,
) -> None:
    monkeypatch.delenv("FANBAN_CAD_RUNTIME__SLOT_COUNT", raising=False)
    monkeypatch.delenv("FANBAN_CONCURRENCY__MAX_JOBS", raising=False)

    config = RuntimeConfig()

    assert config.cad_runtime.slot_count == 8
    assert config.concurrency.max_jobs == 8


def test_deliverable_api_runtime_uses_configured_cad_slot_count(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    monkeypatch.setenv("FANBAN_SPEC_PATH", str(repo_root / "documents" / "参数规范.yaml"))
    monkeypatch.setenv(
        "FANBAN_RUNTIME_SPEC_PATH",
        str(repo_root / "documents" / "参数规范_运行期.yaml"),
    )
    monkeypatch.setenv("FANBAN_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("FANBAN_CAD_RUNTIME__SLOT_COUNT", "2")

    SpecLoader.clear_cache()
    reload_config()

    import API.app.runtime as runtime_mod

    class _FakeCADSlotPool:
        def __init__(self, *, config, slot_count):
            self.config = config
            self.slot_count = slot_count

    monkeypatch.setattr(runtime_mod, "CADSlotPool", _FakeCADSlotPool)

    runtime = runtime_mod.DeliverableApiRuntime(
        job_processor=lambda job: None,
        shared_prep_service=SimpleNamespace(),
        font_preflight_service=SimpleNamespace(),
    )
    try:
        assert runtime.cad_slot_pool.slot_count == 2
    finally:
        runtime.stop()


def test_deliverable_api_runtime_uses_configured_doc_max_jobs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    monkeypatch.setenv("FANBAN_SPEC_PATH", str(repo_root / "documents" / "参数规范.yaml"))
    monkeypatch.setenv(
        "FANBAN_RUNTIME_SPEC_PATH",
        str(repo_root / "documents" / "参数规范_运行期.yaml"),
    )
    monkeypatch.setenv("FANBAN_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("FANBAN_CONCURRENCY__DOC_MAX_JOBS", "3")

    SpecLoader.clear_cache()
    reload_config()

    import API.app.runtime as runtime_mod

    class _FakeCADSlotPool:
        def __init__(self, *, config, slot_count):
            self.config = config
            self.slot_count = slot_count

    monkeypatch.setattr(runtime_mod, "CADSlotPool", _FakeCADSlotPool)

    runtime = runtime_mod.DeliverableApiRuntime(
        job_processor=lambda job: None,
        shared_prep_service=SimpleNamespace(),
        font_preflight_service=SimpleNamespace(),
    )
    try:
        assert runtime._max_doc_jobs == 3
    finally:
        runtime.stop()
