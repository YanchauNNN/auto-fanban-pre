from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import yaml

from src.config import SpecLoader, reload_config
from src.config.mechanism_spec import MechanismSpecLoader
from src.config.runtime_config import RuntimeConfig
from src.models import JobStatus
from src.pipeline.job_manager import JobManager


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


def test_runtime_health_counts_pending_doc_jobs_in_queue_depth(
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
        pending_doc_future: Future[None] = Future()
        with runtime._future_lock:
            runtime._doc_futures.add(pending_doc_future)

        health = runtime.health()

        assert health["pending_doc_jobs"] == 1
        assert health["active_doc_jobs"] == 0
        assert health["queue_depth"] == 1
    finally:
        runtime.stop()


def test_runtime_storage_health_probe_is_safe_under_concurrent_calls(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    import API.app.runtime as runtime_mod

    class _RuntimeConfig:
        storage_dir = tmp_path / "storage"

        def ensure_dirs(self) -> None:
            self.storage_dir.mkdir(parents=True, exist_ok=True)

    runtime = object.__new__(runtime_mod.DeliverableApiRuntime)
    runtime.config = _RuntimeConfig()

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(lambda _: runtime._storage_writable(), range(1000)))

    assert all(results)


def test_doc_phase_does_not_overwrite_newer_persisted_job_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    monkeypatch.setenv("FANBAN_STORAGE_DIR", str(tmp_path / "storage"))
    SpecLoader.clear_cache()
    reload_config()

    import API.app.runtime as runtime_mod

    job_manager = JobManager()
    job = job_manager.create_job(
        job_type="deliverable",
        project_no="2026",
        options={"enabled": True},
        params={},
    )
    job.mark_running(stage="EXPORT_PDF_AND_DWG")
    job.progress.percent = 85
    job_manager.update_job(job)

    stale_job = job.model_copy(deep=True)
    job_manager._jobs[job.job_id] = stale_job

    def _write_current_success() -> None:
        current = stale_job.model_copy(deep=True)
        current.progress.stage = "PACKAGE_ZIP"
        current.mark_succeeded()
        job_file = tmp_path / "storage" / "jobs" / job.job_id / "job.json"
        job_file.write_text(
            json.dumps(current.model_dump(mode="json"), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    runtime = object.__new__(runtime_mod.DeliverableApiRuntime)
    runtime.job_manager = job_manager
    runtime._future_lock = threading.Lock()
    runtime._running_doc_job_ids = set()
    runtime._job_completion_lock = threading.Lock()
    runtime._job_completion_events = {}

    runtime_mod.DeliverableApiRuntime._run_doc_job(
        runtime,
        job.job_id,
        _write_current_success,
    )

    persisted = json.loads(
        (tmp_path / "storage" / "jobs" / job.job_id / "job.json").read_text(encoding="utf-8")
    )
    assert persisted["status"] == JobStatus.SUCCEEDED
    assert persisted["progress"]["stage"] == "PACKAGE_ZIP"
    assert persisted["finished_at"] is not None


def test_runtime_stage_labels_read_from_mechanism_yaml(monkeypatch, tmp_path: Path) -> None:
    mechanism_spec = tmp_path / "documents" / "参数规范-3.yaml"
    mechanism_spec.parent.mkdir(parents=True, exist_ok=True)
    mechanism_spec.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "backend_mechanism": {
                    "api_runtime": {
                        "stage_labels": {
                            "CUSTOM_STAGE": "自定义阶段",
                        },
                    },
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FANBAN_MECHANISM_SPEC_PATH", str(mechanism_spec))
    MechanismSpecLoader.clear_cache()

    import API.app.runtime as runtime_mod

    assert runtime_mod.DeliverableApiRuntime._display_stage_label("CUSTOM_STAGE") == "自定义阶段"
