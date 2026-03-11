# -*- coding: utf-8 -*-
"""
从原生 DWG 执行模块5切图路径（仅到 drawings 产物）。

用法:
    python tools/run_dwg_split_only.py "2016仿真图.dwg"
    python tools/run_dwg_split_only.py "test/dwg/2016仿真图.dwg" --project-no 2016
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.pipeline.project_no_inference import resolve_project_no

_INTERNAL_CODE_RE = re.compile(r"\(([^()]+)\)$")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="原生DWG切图（split-only）")
    parser.add_argument("dwg", type=Path, help="输入DWG路径")
    parser.add_argument(
        "--project-no",
        default="",
        help="项目号；留空时自动从DWG文件名推断，否则回退2016",
    )
    parser.add_argument("--job-id", default="", help="可选：指定job_id")
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=None,
        help="可选：输出汇总JSON路径",
    )
    return parser.parse_args()


def resolve_cli_project_no(project_no: str | None, dwg_path: Path) -> str:
    return resolve_project_no(project_no, dwg_path)


def _extract_internal_code_from_output(pdf_path: Path) -> str | None:
    match = _INTERNAL_CODE_RE.search(pdf_path.stem)
    if match is None:
        return None
    return match.group(1).strip()


def find_probe_pdfs(drawings_dir: Path) -> dict[str, Path | None]:
    probes: dict[str, Path | None] = {"001": None, "002": None}
    for pdf_path in sorted(drawings_dir.glob("*.pdf")):
        internal_code = _extract_internal_code_from_output(pdf_path)
        if internal_code is None:
            continue
        for suffix in probes:
            if internal_code.endswith(f"-{suffix}") and probes[suffix] is None:
                probes[suffix] = pdf_path
    return probes


def _pdf_meta(pdf_path: Path) -> dict:
    if not pdf_path.exists():
        return {"exists": False}
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        pages = len(reader.pages)
        first_page = reader.pages[0] if pages > 0 else None
        if first_page is None:
            return {"exists": True, "pages": 0}
        mm_w = float(first_page.mediabox.width) * 25.4 / 72.0
        mm_h = float(first_page.mediabox.height) * 25.4 / 72.0
        return {
            "exists": True,
            "pages": pages,
            "size_mm": [round(mm_w, 3), round(mm_h, 3)],
        }
    except Exception as exc:  # noqa: BLE001
        return {"exists": True, "error": str(exc)}


def main() -> int:
    args = _parse_args()
    dwg_path = args.dwg.resolve()
    if not dwg_path.exists():
        print(f"[ERROR] DWG不存在: {dwg_path}")
        return 1

    from src.models import Job, JobType
    from src.pipeline.executor import PipelineExecutor

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    job_id = args.job_id or f"splitonly-{timestamp}-{uuid4().hex[:8]}"
    project_no = resolve_cli_project_no(args.project_no, dwg_path)
    job = Job(
        job_id=job_id,
        job_type=JobType.DELIVERABLE,
        project_no=project_no,
        input_files=[dwg_path],
        options={
            "enabled": True,
            "export_pdf": True,
            "split_only": True,
        },
        params={},
    )

    print(f"[INFO] job_id={job_id}")
    print(f"[INFO] 输入DWG: {dwg_path}")
    executor = PipelineExecutor()
    executor.config.multi_dwg_policy.code_conflict = "warn"
    executor.cad_dxf_executor.config.multi_dwg_policy.code_conflict = "warn"
    executor.execute(job)

    if job.status.value != "succeeded":
        print(f"[ERROR] 任务失败: {job.errors}")
        return 2

    job_dir = (PROJECT_ROOT / "storage" / "jobs" / job_id).resolve()
    drawings_dir = job_dir / "output" / "drawings"
    cad_tasks_dir = job_dir / "work" / "cad_tasks"
    pdf_files = sorted(drawings_dir.glob("*.pdf"))
    dwg_files = sorted(drawings_dir.glob("*.dwg"))
    probes = find_probe_pdfs(drawings_dir)
    key_001 = probes["001"]
    key_002 = probes["002"]

    summary = {
        "job_id": job_id,
        "job_dir": str(job_dir),
        "drawings_dir": str(drawings_dir),
        "cad_tasks_dir": str(cad_tasks_dir),
        "project_no": project_no,
        "pdf_count": len(pdf_files),
        "dwg_count": len(dwg_files),
        "job_flags": list(job.flags),
        "key_pdf_001": _pdf_meta(key_001) if key_001 is not None else {"exists": False},
        "key_pdf_002": _pdf_meta(key_002) if key_002 is not None else {"exists": False},
    }
    summary["plot_from_split_stats"] = {
        "from_split_hits": sum(1 for f in job.flags if "PLOT_FROM_SPLIT_DWG" in f),
        "extents_hits": sum(1 for f in job.flags if "PLOT_EXTENTS_USED" in f),
        "window_fallback_hits": sum(1 for f in job.flags if "PLOT_WINDOW_FALLBACK" in f),
    }
    summary["legacy_python_path_hits"] = sum(
        1 for f in job.flags if "PDF_PYTHON_FALLBACK" in f
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[INFO] 汇总已写入: {args.summary_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
