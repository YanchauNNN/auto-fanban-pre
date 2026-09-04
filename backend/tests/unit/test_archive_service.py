from __future__ import annotations

import json

from src.archive.admin_config_store import AdminConfigStore
from src.archive.service import ArchiveService
from src.models import Job, JobArtifacts, JobType, TaskGroup
from src.pipeline.group_manager import GroupManager
from src.pipeline.job_manager import JobManager
from src.pipeline.shared_prep import SharedPrepService

from ..management_test_helpers import configure_management_env


def test_archive_service_copies_outputs_to_archive_root(monkeypatch, tmp_path, sample_frame) -> None:
    project_root = configure_management_env(monkeypatch, tmp_path)
    group_manager = GroupManager()
    job_manager = JobManager()
    shared_prep_service = SharedPrepService()
    shared_dir = project_root / "storage/groups/group-archive/shared"
    group = TaskGroup(group_id="group-archive", project_no="2016", shared_dir=shared_dir)
    shared_dir.mkdir(parents=True, exist_ok=True)
    group_manager.update_group(group)

    job = Job(
        job_id="job-archive",
        job_type=JobType.DELIVERABLE,
        project_no="2016",
        group_id=group.group_id,
        task_role="deliverable_main",
        params={
            "project_no": "2016",
            "engineering_no": "2016",
            "subitem_no": "JG001",
            "subitem_name": "测试子项",
            "classification": "非密",
            "album_title_cn": "测试图册",
            "cover_variant": "通用",
        },
    )
    job_dir = job_manager.config.get_job_dir(job.job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    package_zip = job_dir / "package.zip"
    ied_xlsx = job_dir / "ied.xlsx"
    package_zip.write_bytes(b"zip")
    ied_xlsx.write_bytes(b"xlsx")
    job.artifacts = JobArtifacts(package_zip=package_zip, ied_xlsx=ied_xlsx)
    job_manager.update_job(job)

    group.child_job_ids = [job.job_id]
    group_manager.update_group(group)
    sample_frame.titleblock.internal_code = "2016-JG001-001"
    sample_frame.titleblock.revision = "A"
    (shared_dir / "prep_summary.json").write_text(
        json.dumps(
            {
                "source_input_dwg": str(shared_dir / "source_input.dwg"),
                "source_converted_dxf": str(shared_dir / "source_converted.dxf"),
            }
        ),
        encoding="utf-8",
    )
    (shared_dir / "source_input.dwg").write_text("dwg", encoding="utf-8")
    (shared_dir / "source_converted.dxf").write_text("dxf", encoding="utf-8")
    (shared_dir / "frames.json").write_text(
        json.dumps([sample_frame.model_dump(mode="json")], ensure_ascii=False),
        encoding="utf-8",
    )
    (shared_dir / "sheet_sets.json").write_text("[]", encoding="utf-8")

    config_store = AdminConfigStore()
    archive_root = project_root / "archive-root"
    config_store.update({"archive_root_path": str(archive_root)})
    service = ArchiveService(
        group_manager=group_manager,
        job_manager=job_manager,
        shared_prep_service=shared_prep_service,
        admin_config_store=config_store,
    )

    service.archive_group(group)

    target_dir = archive_root / "2016" / "JG001" / "2016-JG001" / "A"
    assert (target_dir / "package.zip").exists()
    assert (target_dir / "ied.xlsx").exists()
    assert group.archive.status.value == "succeeded"
    persisted = group_manager.reload_group(group.group_id)
    assert persisted is not None
    assert persisted.archive.status.value == "pending"
