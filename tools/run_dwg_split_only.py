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
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="原生DWG切图（split-only）")
    parser.add_argument("dwg", type=Path, help="输入DWG路径")
    parser.add_argument("--project-no", default="2016", help="项目号，默认2016")
    parser.add_argument("--job-id", default="", help="可选：指定job_id")
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=None,
        help="可选：输出汇总JSON路径",
    )
    return parser.parse_args()


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

    backend_root = PROJECT_ROOT / "backend"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    from src.models import Job, JobType
    from src.pipeline.executor import PipelineExecutor

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    job_id = args.job_id or f"splitonly-{timestamp}-{uuid4().hex[:8]}"
    job = Job(
        job_id=job_id,
        job_type=JobType.DELIVERABLE,
        project_no=str(args.project_no),
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
    # 2016样例存在重复编码，测试切图路径时按告警处理，不中断整批执行。
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

    key_001 = drawings_dir / "JD1NHH11001B25C42SD(20161NH-JGS03-001).pdf"
    key_002 = drawings_dir / "JD1NHH11002B25C42SD(20161NH-JGS03-002).pdf"

    summary = {
        "job_id": job_id,
        "job_dir": str(job_dir),
        "drawings_dir": str(drawings_dir),
        "cad_tasks_dir": str(cad_tasks_dir),
        "pdf_count": len(pdf_files),
        "dwg_count": len(dwg_files),
        "job_flags": list(job.flags),
        "key_pdf_001": _pdf_meta(key_001),
        "key_pdf_002": _pdf_meta(key_002),
    }

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
