from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from src.models import Job, JobType
from src.pipeline.packager import Packager


def test_packager_flattens_zip_root_and_excludes_manifest(tmp_path: Path) -> None:
    job = Job(
        job_id="job-package-flat",
        job_type=JobType.DELIVERABLE,
        project_no="2026",
        work_dir=tmp_path,
        params={"project_no": "2026"},
    )

    drawings_dir = tmp_path / "output" / "drawings"
    drawings_dir.mkdir(parents=True)
    (drawings_dir / "drawing-001.dwg").write_text("dwg", encoding="utf-8")
    (drawings_dir / "drawing-001.pdf").write_text("pdf", encoding="utf-8")

    docs_dir = tmp_path / "output" / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "封面.docx").write_text("docx", encoding="utf-8")
    (docs_dir / "设计文件.xlsx").write_text("xlsx", encoding="utf-8")

    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")

    zip_path = Packager().package(job)

    with zipfile.ZipFile(zip_path) as zf:
        names = sorted(zf.namelist())

    assert names == [
        "drawing-001.dwg",
        "drawing-001.pdf",
        "封面.docx",
        "设计文件.xlsx",
    ]


def test_packager_rejects_duplicate_root_names(tmp_path: Path) -> None:
    job = Job(
        job_id="job-package-duplicate",
        job_type=JobType.DELIVERABLE,
        project_no="2026",
        work_dir=tmp_path,
        params={"project_no": "2026"},
    )

    drawings_dir = tmp_path / "output" / "drawings"
    drawings_dir.mkdir(parents=True)
    (drawings_dir / "目录.xlsx").write_text("drawing-xlsx", encoding="utf-8")

    docs_dir = tmp_path / "output" / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "目录.xlsx").write_text("doc-xlsx", encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate packaged filename"):
        Packager().package(job)
