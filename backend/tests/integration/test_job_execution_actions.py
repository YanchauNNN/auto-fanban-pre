from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from pathlib import Path
from threading import Event, get_ident
from time import sleep
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.models import AccountSnapshot, JobStatus, JobType
from src.pipeline.job_manager import JobManager
from src.workflow.models import WorkflowStatus

from API.app.runtime import DeliverableApiRuntime

from ..management_test_helpers import configure_management_env

OWNER = AccountSnapshot(account_id="zhangsan", display_name="张三", role="设计人员")
OTHER = AccountSnapshot(account_id="lisi", display_name="李四", role="室主任")
ADMIN = AccountSnapshot(account_id="admin", display_name="管理员", role="管理员")


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    configure_management_env(monkeypatch, tmp_path)
    monkeypatch.setattr("API.app.runtime.CADSlotPool", lambda **_: SimpleNamespace(slot_count=1))
    value = DeliverableApiRuntime(process_jobs_in_api=False)
    value.queue_store.initialize()
    yield value
    value.stop()


def service(runtime):
    return import_module("API.app.job_actions").JobActionService(runtime)


def seed(runtime, *, status=JobStatus.QUEUED, owner=OWNER, group=None):
    job = runtime.job_manager.create_job(
        job_type="change_page_extract",
        project_no="2016",
        creator_snapshot=owner,
        group_id=group.group_id if group else None,
        source_filename="source.zip",
        params={"project_no": "2016", "cad_slot_id": "old-slot", "shared_prep_dir": "old-cache"},
    )
    source = runtime.config.get_job_dir(job.job_id) / "input" / "source.zip"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"original-upload")
    job.input_files = [source]
    job.status = status
    runtime.job_manager.update_job(job)
    if group:
        group.child_job_ids.append(job.job_id)
        runtime.group_manager.update_group(group)
    runtime._enqueue_job(job.job_id)
    return job


def test_queued_cancel_fences_claim_and_stale_job_save(runtime):
    job = seed(runtime)
    stale = job.model_copy(deep=True)
    result = service(runtime).cancel(job.job_id, OWNER)
    assert result["can_cancel"] is False
    assert runtime.queue_store.claim_next(worker_id="worker") is None
    stale.mark_succeeded()
    runtime.job_manager.update_job(stale)
    assert runtime.job_manager.reload_job(job.job_id).status == JobStatus.CANCELLED


def test_running_cancel_waits_for_safe_boundary_and_cannot_be_overwritten(runtime):
    job = seed(runtime)
    entered, release = Event(), Event()

    def processor(current):
        current.mark_running()
        runtime.job_manager.update_job(current)
        entered.set()
        assert release.wait(10)
        current.mark_succeeded()
        runtime.job_manager.update_job(current)

    runtime.job_processor = processor
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runtime._run_job, job.job_id)
        try:
            assert entered.wait(10)
            result = service(runtime).cancel(job.job_id, OWNER)
            assert result["cancel_requested"] is True
            assert runtime.job_manager.reload_job(job.job_id).status == JobStatus.RUNNING
        finally:
            release.set()
        future.result(timeout=10)
    assert runtime.job_manager.reload_job(job.job_id).status == JobStatus.CANCELLED


def test_cancelled_job_does_not_execute_even_if_worker_already_claimed(runtime):
    job = seed(runtime)
    claim = runtime.queue_store.claim_next(worker_id="worker")
    assert claim is not None
    service(runtime).cancel(job.job_id, OWNER)
    calls = []
    runtime.job_processor = lambda _: calls.append("called")
    runtime._run_job(job.job_id)
    assert calls == []
    assert runtime.job_manager.reload_job(job.job_id).status == JobStatus.CANCELLED


def test_action_permissions_are_owner_or_admin_not_office_visibility(runtime):
    job = seed(runtime)
    assert service(runtime).get_actions(job.job_id, OTHER)["can_cancel"] is False
    with pytest.raises(PermissionError, match="创建人或管理员"):
        service(runtime).cancel(job.job_id, OTHER)
    unknown = seed(runtime, owner=None)
    with pytest.raises(PermissionError, match="创建人或管理员"):
        service(runtime).cancel(unknown.job_id, OWNER)
    service(runtime).cancel(unknown.job_id, ADMIN)


def test_succeeded_job_cannot_cancel_or_retry(runtime):
    job = seed(runtime, status=JobStatus.SUCCEEDED)
    actions = service(runtime).get_actions(job.job_id, OWNER)
    assert not actions["can_cancel"] and not actions["can_retry"]
    with pytest.raises(ValueError, match="排队或运行"):
        service(runtime).cancel(job.job_id, OWNER)
    with pytest.raises(ValueError, match="失败或已取消"):
        service(runtime).retry(job.job_id, OWNER)


def test_retry_creates_independent_input_and_preserves_original_diagnostics(runtime):
    old = seed(runtime, status=JobStatus.FAILED)
    old.errors = ["original-failure"]
    artifact = runtime.config.get_job_dir(old.job_id) / "old-report.json"
    artifact.write_text("original-report", encoding="utf-8")
    old.artifacts.report_json = artifact
    runtime.job_manager.update_job(old)
    result = service(runtime).retry(old.job_id, OWNER)
    new = runtime.job_manager.reload_job(result["job_id"])
    assert new.job_id != old.job_id and result["group_id"] is None
    assert new.status == JobStatus.QUEUED and new.errors == []
    assert new.artifacts.report_json is None
    assert new.input_files[0] != old.input_files[0]
    assert new.input_files[0].read_bytes() == b"original-upload"
    assert "cad_slot_id" not in new.params and "shared_prep_dir" not in new.params
    original = runtime.job_manager.reload_job(old.job_id)
    assert original.status == JobStatus.FAILED and original.errors == ["original-failure"]
    assert artifact.read_text(encoding="utf-8") == "original-report"
    assert service(runtime).retry(old.job_id, OWNER) == result


def test_child_cancel_targets_whole_execution_group(runtime):
    group = runtime.group_manager.create_group(
        batch_id="batch",
        source_filenames=["source.zip"],
        project_no="2016",
        run_audit_check=True,
        creator_snapshot=OWNER,
    )
    first = seed(runtime, group=group)
    second = seed(runtime, group=group)
    runtime._enqueue_group(group.group_id)
    service(runtime).cancel(first.job_id, OWNER)
    assert runtime.group_manager.reload_group(group.group_id).status == JobStatus.CANCELLED
    assert runtime.job_manager.reload_job(first.job_id).status == JobStatus.CANCELLED
    assert runtime.job_manager.reload_job(second.job_id).status == JobStatus.CANCELLED
    assert runtime.queue_store.claim_next(worker_id="worker") is None


def test_retry_rejects_active_workflow_even_for_failed_child(runtime):
    group = runtime.group_manager.create_group(
        batch_id="batch",
        source_filenames=["source.zip"],
        project_no="2016",
        run_audit_check=False,
        creator_snapshot=OWNER,
    )
    job = seed(runtime, status=JobStatus.FAILED, group=group)
    group.status = JobStatus.FAILED
    group.workflow.status = WorkflowStatus.IN_REVIEW
    runtime.group_manager.update_group(group)
    with pytest.raises(ValueError, match="审批"):
        service(runtime).retry(job.job_id, OWNER)


def test_retry_missing_input_does_not_create_or_enqueue_new_job(runtime):
    job = seed(runtime, status=JobStatus.FAILED)
    Path(job.input_files[0]).unlink()
    before = len(runtime.job_manager.load_all_jobs())
    with pytest.raises(ValueError, match="原始上传文件"):
        service(runtime).retry(job.job_id, OWNER)
    assert len(runtime.job_manager.load_all_jobs()) == before


@pytest.mark.parametrize("early_signal", [False, True])
def test_completion_wait_does_not_return_before_executor_cleanup(runtime, early_signal):
    job = seed(runtime)
    runtime.queue_store.begin_execution("job", job.job_id)
    job.mark_succeeded()
    runtime.job_manager.update_job(job)
    if early_signal:
        runtime._signal_job_completion(job.job_id)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runtime._wait_for_job_completion, job.job_id, 3)
        sleep(0.1)
        premature = future.done()
        runtime.queue_store.finish_execution("job", job.job_id)
        runtime._signal_job_completion(job.job_id)
        future.result(timeout=5)
    assert premature is False


def test_group_retry_clones_original_source_and_all_children_without_workflow(runtime):
    group = runtime.group_manager.create_group(
        batch_id="batch",
        source_filenames=["source.zip"],
        project_no="2016",
        run_audit_check=True,
        creator_snapshot=OWNER,
    )
    first = seed(runtime, status=JobStatus.FAILED, group=group)
    seed(runtime, status=JobStatus.SUCCEEDED, group=group)
    group.metadata["source_input_path"] = str(first.input_files[0])
    group.metadata["group_mode"] = "replace_then_deliverable"
    group.mark_failed("old failure")
    runtime.group_manager.update_group(group)
    result = service(runtime).retry(first.job_id, OWNER)
    new_group = runtime.group_manager.reload_group(result["group_id"])
    assert new_group.group_id != group.group_id
    assert len(new_group.child_job_ids) == 2
    assert new_group.workflow.status == WorkflowStatus.DRAFT
    assert new_group.metadata["group_mode"] == "replace_then_deliverable"
    for child_id in new_group.child_job_ids:
        child = runtime.job_manager.reload_job(child_id)
        assert child.group_id == new_group.group_id
        assert child.input_files[0] != first.input_files[0]
        assert child.input_files[0].read_bytes() == b"original-upload"


def test_retry_recovers_enqueue_after_api_interruption(runtime, monkeypatch):
    old = seed(runtime, status=JobStatus.FAILED)
    enqueue = runtime._enqueue_job
    monkeypatch.setattr(
        runtime, "_enqueue_job", lambda _: (_ for _ in ()).throw(RuntimeError("lost connection"))
    )
    with pytest.raises(RuntimeError, match="lost connection"):
        service(runtime).retry(old.job_id, OWNER)
    monkeypatch.setattr(runtime, "_enqueue_job", enqueue)
    result = service(runtime).retry(old.job_id, OWNER)
    assert any(
        item["item_id"] == result["job_id"] for item in runtime.queue_store.list_queue_items()
    )


def test_rest_execution_actions_enforce_auth_and_status(runtime):
    from API.app.auth_helpers import require_current_account

    router = import_module("API.app.routers.job_actions").router
    app = FastAPI()
    app.state.runtime = runtime
    app.include_router(router)
    app.dependency_overrides[require_current_account] = lambda: OWNER
    job = seed(runtime)
    with TestClient(app) as client:
        path = f"/api/jobs/{job.job_id}"
        assert client.get(path + "/execution-actions").json()["can_cancel"] is True
        assert client.post(path + "/cancel").status_code == 200
        assert client.post(path + "/retry").status_code == 200
        app.dependency_overrides[require_current_account] = lambda: OTHER
        assert client.post(path + "/retry").status_code == 403
        assert client.get("/api/jobs/missing/execution-actions").status_code == 404


def test_unrelated_account_cannot_read_action_state(runtime):
    job = seed(runtime)
    stranger = AccountSnapshot(
        account_id="stranger", display_name="其他人", role="设计人员", office_name="另一室"
    )
    with pytest.raises(LookupError, match="任务不存在"):
        service(runtime).get_actions(job.job_id, stranger)


def test_retry_refuses_source_outside_original_job(runtime):
    job = seed(runtime, status=JobStatus.FAILED)
    outside = runtime.config.storage_dir / "private-file.zip"
    outside.write_bytes(b"do-not-copy")
    job.input_files = [outside]
    runtime.job_manager.update_job(job)
    with pytest.raises(ValueError, match="原始上传文件"):
        service(runtime).retry(job.job_id, OWNER)


def test_workload_only_association_is_not_replayed_as_generation_group(runtime):
    group = runtime.group_manager.create_group(
        batch_id="batch",
        source_filenames=["source.zip"],
        project_no="2016",
        run_audit_check=False,
        creator_snapshot=OWNER,
    )
    child = seed(runtime, status=JobStatus.FAILED, group=group)
    group.status = JobStatus.FAILED
    group.metadata["workload_source_job_id"] = child.job_id
    runtime.group_manager.update_group(group)
    with pytest.raises(ValueError, match="工作量关联"):
        service(runtime).retry(child.job_id, OWNER)


def test_cancel_and_late_save_are_serialized(runtime, monkeypatch):
    job = seed(runtime)
    stale = job.model_copy(deep=True)
    stale.mark_succeeded()
    reached_write, release = Event(), Event()
    stale_thread = {}
    replace = Path.replace

    def blocked_replace(path, target):
        if get_ident() == stale_thread.get("id"):
            reached_write.set()
            assert release.wait(10)
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", blocked_replace)

    def late_save():
        stale_thread["id"] = get_ident()
        runtime.job_manager.update_job(stale)

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(late_save)
        assert reached_write.wait(10)
        cancellation = pool.submit(service(runtime).cancel, job.job_id, OWNER)
        sleep(0.1)
        premature = cancellation.done()
        release.set()
        writer.result(timeout=10)
        cancellation.result(timeout=10)
    assert premature is False
    assert runtime.job_manager.reload_job(job.job_id).status == JobStatus.CANCELLED


def test_separate_worker_finishes_cancelled_claim_as_cancelled(runtime):
    from API.app.worker import DeliverableWorkerRuntime

    job = seed(runtime)
    entered, release = Event(), Event()

    def processor(current):
        current.mark_running()
        JobManager().update_job(current)
        entered.set()
        assert release.wait(10)
        current.mark_succeeded()

    worker = DeliverableWorkerRuntime(job_processor=processor)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker.run_once)
            try:
                assert entered.wait(10)
                service(runtime).cancel(job.job_id, OWNER)
            finally:
                release.set()
            assert future.result(timeout=10)
        assert runtime.job_manager.reload_job(job.job_id).status == JobStatus.CANCELLED
        row = runtime.queue_store.list_queue_items()[0]
        assert row["status"] == "cancelled"
    finally:
        worker.stop()


def test_interrupted_worker_recovery_acknowledges_pending_cancel(runtime):
    from API.app.worker import DeliverableWorkerRuntime

    job = seed(runtime)
    claim = runtime.queue_store.claim_next(worker_id="dead-worker")
    runtime.queue_store.begin_execution("job", job.job_id)
    service(runtime).cancel(job.job_id, OWNER)
    worker = DeliverableWorkerRuntime(job_processor=lambda _: None)
    try:
        assert worker._finalize_interrupted_item(claim)
        assert runtime.job_manager.reload_job(job.job_id).status == JobStatus.CANCELLED
        assert service(runtime).get_actions(job.job_id, OWNER)["can_retry"] is True
    finally:
        worker.stop()


def test_cancel_during_group_preparation_stops_before_children(runtime):
    group = runtime.group_manager.create_group(
        batch_id="batch",
        source_filenames=["source.zip"],
        project_no="2016",
        run_audit_check=False,
        creator_snapshot=OWNER,
    )
    child = seed(runtime, group=group)
    entered, release = Event(), Event()

    def prepare(**_):
        entered.set()
        assert release.wait(10)
        return SimpleNamespace()

    runtime.shared_prep_service = SimpleNamespace(prepare=prepare)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runtime._process_group, group.group_id)
        try:
            assert entered.wait(10)
            service(runtime).cancel(group.group_id, OWNER)
            assert runtime.group_manager.reload_group(group.group_id).status == JobStatus.RUNNING
        finally:
            release.set()
        future.result(timeout=10)
    assert runtime.group_manager.reload_group(group.group_id).status == JobStatus.CANCELLED
    assert runtime.job_manager.reload_job(child.job_id).status == JobStatus.CANCELLED


def test_cancel_queued_doc_phase_skips_processor(runtime):
    job = seed(runtime)
    job.job_type = JobType.CALCULATION_BOOK
    runtime.job_manager.update_job(job)
    release = Event()
    blockers = [
        runtime._doc_executor.submit(release.wait, 10) for _ in range(runtime._max_doc_jobs)
    ]
    calls = []
    runtime.job_processor = lambda _: calls.append("called")
    try:
        runtime._run_job(job.job_id)
        assert service(runtime).cancel(job.job_id, OWNER)["cancel_requested"] is True
    finally:
        release.set()
        for blocker in blockers:
            blocker.result(timeout=10)
    assert runtime._wait_for_job_completion(job.job_id, 10).status == JobStatus.CANCELLED
    assert calls == []


def test_in_process_restart_releases_execution_control_for_retry(runtime):
    job = seed(runtime)
    runtime.queue_store.begin_execution("job", job.job_id)
    runtime._recover_groups_and_jobs()
    assert service(runtime).get_actions(job.job_id, OWNER)["can_retry"] is True


def test_late_enqueue_cannot_reactivate_cancelled_execution(runtime):
    job = seed(runtime)
    service(runtime).cancel(job.job_id, OWNER)
    runtime._enqueue_job(job.job_id)
    assert runtime.queue_store.claim_next(worker_id="late-worker") is None


def test_retry_copy_error_does_not_leave_queued_orphan(runtime, monkeypatch):
    old = seed(runtime, status=JobStatus.FAILED)

    def copy_error(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("API.app.job_actions.shutil.copy2", copy_error)
    with pytest.raises(ValueError, match="复制失败"):
        service(runtime).retry(old.job_id, OWNER)
    created = [job for job in runtime.job_manager.load_all_jobs() if job.job_id != old.job_id]
    assert len(created) == 1
    assert created[0].status == JobStatus.FAILED
    assert "disk full" in created[0].errors[0]
    assert runtime.job_manager.reload_job(old.job_id).status == JobStatus.FAILED


def test_group_retry_copy_error_does_not_leave_queued_orphan(runtime, monkeypatch):
    group = runtime.group_manager.create_group(
        batch_id="batch",
        source_filenames=["source.zip"],
        project_no="2016",
        run_audit_check=False,
        creator_snapshot=OWNER,
    )
    child = seed(runtime, status=JobStatus.FAILED, group=group)
    group.status = JobStatus.FAILED
    runtime.group_manager.update_group(group)

    def copy_error(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("API.app.job_actions.shutil.copy2", copy_error)
    with pytest.raises(ValueError, match="复制失败"):
        service(runtime).retry(child.job_id, OWNER)
    created = [
        item for item in runtime.group_manager.load_all_groups() if item.group_id != group.group_id
    ]
    assert len(created) == 1
    assert created[0].status == JobStatus.FAILED


def test_unrelated_account_cannot_discover_broken_group_link(runtime):
    job = seed(runtime)
    job.group_id = "missing-group"
    runtime.job_manager.update_job(job)
    stranger = AccountSnapshot(account_id="stranger", display_name="其他人", role="设计人员")
    with pytest.raises(LookupError, match="任务不存在"):
        service(runtime).get_actions(job.job_id, stranger)


def test_final_control_commit_cannot_overwrite_new_workload_association(runtime, monkeypatch):
    job = seed(runtime)
    runtime.queue_store.begin_execution("job", job.job_id)
    job.mark_succeeded()
    runtime.job_manager.update_job(job)
    entered, release = Event(), Event()
    finish = runtime.queue_store.finish_execution

    def paused_finish(*args):
        result = finish(*args)
        entered.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(runtime.queue_store, "finish_execution", paused_finish)
    linked = job.model_copy(deep=True)
    linked.group_id = "workload-linked-group"
    with ThreadPoolExecutor(max_workers=2) as pool:
        finishing = pool.submit(runtime._finish_job_execution, job)
        assert entered.wait(10)
        linking = pool.submit(JobManager().update_job, linked)
        sleep(0.1)
        premature = linking.done()
        release.set()
        finishing.result(timeout=10)
        linking.result(timeout=10)
    assert premature is False
    assert runtime.job_manager.reload_job(job.job_id).group_id == "workload-linked-group"
