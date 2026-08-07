from __future__ import annotations

import pytest
from API.app.management_services import ManagementServices
from API.app.runtime import DeliverableApiRuntime

from src.archive.models import ArchiveStatus
from src.models import JobStatus
from src.pipeline.group_manager import GroupManager
from src.task_groups.state_writer import SUMMARY_PUBLICATION_PENDING_KEY
from src.workflow.models import WorkflowStatus
from src.workload.models import WorkloadSettlementStatus

from ..management_test_helpers import configure_management_env


def _summary(runtime: DeliverableApiRuntime, group_id: str):
    return next(
        (
            item
            for item in runtime.queue_store.list_summaries()["items"]
            if item["item_id"] == group_id
        ),
        None,
    )


def test_rebuilt_reconciliation_worker_converges_failed_complete_summary_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    configure_management_env(monkeypatch, tmp_path)
    first_runtime = DeliverableApiRuntime(process_jobs_in_api=False)
    first_runtime.queue_store.initialize()
    first_management = ManagementServices.build(first_runtime)
    try:
        group = first_runtime.group_manager.create_group(
            batch_id=None,
            source_filenames=["input.dwg"],
            project_no="2016",
            run_audit_check=False,
        )
        first_runtime.refresh_summary_index("group", group.group_id)
        before = _summary(first_runtime, group.group_id)
        assert before is not None
        assert before["status"] == JobStatus.QUEUED.value

        group.archive.status = ArchiveStatus.SUCCEEDED
        group.workflow.status = WorkflowStatus.ARCHIVED
        group.workload.settlement_status = WorkloadSettlementStatus.SETTLED
        group.mark_succeeded()

        def _fail_publish(_item_type: str, _item_id: str) -> None:
            raise RuntimeError("sqlite unavailable")

        monkeypatch.setattr(first_runtime, "refresh_summary_index", _fail_publish)
        with pytest.raises(RuntimeError, match="sqlite unavailable"):
            first_management.task_group_state_writer.write(group)

        stale = _summary(first_runtime, group.group_id)
        assert stale is not None
        assert stale["status"] == JobStatus.QUEUED.value
        assert group.metadata[SUMMARY_PUBLICATION_PENDING_KEY] is True
    finally:
        first_runtime.stop()

    # Rebuild without runtime.start(): no startup backfill is allowed to mask
    # the durable marker recovery exercised below.
    rebuilt_runtime = DeliverableApiRuntime(process_jobs_in_api=False)
    rebuilt_runtime.queue_store.initialize()
    rebuilt_management = ManagementServices.build(rebuilt_runtime)
    try:
        report = rebuilt_management.task_group_reconciliation_worker.run_once()

        assert report.publication_attempted == 1
        assert report.failed_group_ids == ()
        summary = _summary(rebuilt_runtime, group.group_id)
        assert summary is not None
        assert summary["status"] == JobStatus.SUCCEEDED.value
        assert summary["workflow_status"] == WorkflowStatus.ARCHIVED.value
        assert summary["archive_status"] == ArchiveStatus.SUCCEEDED.value
        assert summary["workload"]["settlement_status"] == (WorkloadSettlementStatus.SETTLED.value)
        reloaded = rebuilt_runtime.group_manager.reload_group(group.group_id)
        assert reloaded is not None
        assert SUMMARY_PUBLICATION_PENDING_KEY not in reloaded.metadata
    finally:
        rebuilt_runtime.stop()


def test_refresh_summary_does_not_resurrect_group_deleted_by_another_manager(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    configure_management_env(monkeypatch, tmp_path)
    runtime = DeliverableApiRuntime(process_jobs_in_api=False)
    runtime.queue_store.initialize()
    try:
        group = runtime.group_manager.create_group(
            batch_id=None,
            source_filenames=["input.dwg"],
            project_no="2016",
            run_audit_check=False,
        )
        runtime.refresh_summary_index("group", group.group_id)
        assert _summary(runtime, group.group_id) is not None
        assert runtime.group_manager.get_group(group.group_id) is not None

        GroupManager().delete_group(group.group_id)
        runtime.refresh_summary_index("group", group.group_id)

        assert _summary(runtime, group.group_id) is None
        assert runtime.group_manager.get_group(group.group_id) is None
    finally:
        runtime.stop()
