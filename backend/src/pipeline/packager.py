"""
打包器 - 生成交付包和manifest

职责：
1. 打包output目录为package.zip
2. 生成manifest.json（含drawing级追溯条目）
3. IED单独输出（不入zip）

测试要点：
- test_package_zip: ZIP打包
- test_manifest_structure: manifest结构
- test_ied_separate: IED单独输出
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..cad.splitter import output_name_for_frame, output_name_for_sheet_set
from ..config import load_spec
from ..interfaces import IPackager
from ..result_views import build_deliverable_outputs, normalize_user_flags

if TYPE_CHECKING:
    from ..models import Job


class Packager(IPackager):
    """打包器实现"""

    def __init__(self, spec_path: str | None = None):
        self.spec = load_spec(spec_path) if spec_path else load_spec()

    def package(self, job: Job) -> Path:
        """打包交付产物"""
        if not job.work_dir:
            raise ValueError("Job work_dir not set")

        output_dir = job.work_dir / "output"
        zip_path = job.work_dir / "package.zip"

        packaged_names: set[str] = set()
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in self._iter_packaged_files(output_dir):
                arcname = file.name
                if arcname in packaged_names:
                    raise ValueError(f"Duplicate packaged filename: {arcname}")
                zf.write(file, arcname)
                packaged_names.add(arcname)

        return zip_path

    def generate_manifest(
        self,
        job: Job,
        *,
        context: dict[str, Any] | None = None,
    ) -> Path:
        """生成manifest.json（含drawing级追溯）"""
        if not job.work_dir:
            raise ValueError("Job work_dir not set")

        manifest: dict[str, Any] = {
            "schema_version": "1.0",
            "job_id": job.job_id,
            "job_type": job.job_type.value,
            "project_no": job.project_no,
            "spec_version": f"documents/参数规范.yaml@{self.spec.schema_version}",
            "inputs": {
                "dwg_files": [str(f.name) for f in job.input_files],
                "options": job.options,
                "params": job.params,
            },
            "derived": {},
            "artifacts": {
                "package_zip": (
                    str(job.artifacts.package_zip)
                    if job.artifacts.package_zip
                    else None
                ),
                "ied_xlsx": (
                    str(job.artifacts.ied_xlsx) if job.artifacts.ied_xlsx else None
                ),
                "drawings_dir": (
                    str(job.artifacts.drawings_dir)
                    if job.artifacts.drawings_dir
                    else None
                ),
                "docs_dir": (
                    str(job.artifacts.docs_dir) if job.artifacts.docs_dir else None
                ),
            },
            "flags": normalize_user_flags(job.flags),
            "errors": job.errors,
            "timestamps": {
                "created_at": (
                    job.created_at.isoformat() if job.created_at else None
                ),
                "started_at": (
                    job.started_at.isoformat() if job.started_at else None
                ),
                "finished_at": (
                    job.finished_at.isoformat() if job.finished_at else None
                ),
            },
        }

        # Drawing级追溯条目
        if context:
            manifest["drawings"] = self._build_drawing_entries(context)
            docs_dir = job.artifacts.docs_dir or (job.work_dir / "output" / "docs")
            manifest["deliverable_outputs"] = build_deliverable_outputs(
                context=context,
                docs_dir=Path(docs_dir) if docs_dir else None,
            )

        manifest_path = job.work_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        return manifest_path

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    @staticmethod
    def _build_drawing_entries(context: dict) -> list[dict]:
        """构建 drawing 级追溯条目"""
        entries: list[dict] = []

        for frame in context.get("frames", []):
            name = output_name_for_frame(frame)
            entries.append(
                {
                    "name": name,
                    "type": "single_frame",
                    "frame_id": frame.frame_id,
                    "internal_code": frame.titleblock.internal_code,
                    "external_code": frame.titleblock.external_code,
                    "pdf_path": str(frame.runtime.pdf_path) if frame.runtime.pdf_path else None,
                    "dwg_path": str(frame.runtime.dwg_path) if frame.runtime.dwg_path else None,
                    "flags": normalize_user_flags(frame.runtime.flags),
                }
            )

        for ss in context.get("sheet_sets", []):
            name = output_name_for_sheet_set(ss)
            master_tb = ss.get_inherited_titleblock()
            entries.append(
                {
                    "name": name,
                    "type": "a4_sheet_set",
                    "cluster_id": ss.cluster_id,
                    "page_total": ss.generated_page_count or ss.page_total,
                    "internal_code": master_tb.get("internal_code"),
                    "external_code": master_tb.get("external_code"),
                    "pdf_path": str(ss.pdf_path) if ss.pdf_path else None,
                    "dwg_path": str(ss.dwg_path) if ss.dwg_path else None,
                    "flags": normalize_user_flags(ss.flags),
                }
            )

        return entries

    @staticmethod
    def _iter_packaged_files(output_dir: Path) -> list[Path]:
        packaged_files: list[Path] = []
        for subdir_name in ("drawings", "docs"):
            subdir = output_dir / subdir_name
            if not subdir.exists():
                continue
            packaged_files.extend(
                file
                for file in sorted(subdir.rglob("*"))
                if file.is_file()
            )
        return packaged_files
