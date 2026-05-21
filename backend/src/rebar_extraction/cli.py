from __future__ import annotations

import argparse
import json
from pathlib import Path

from .service import run_rebar_scan


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan rebar annotations from a DWG via AutoCAD .NET Bridge.")
    parser.add_argument("--source", required=True, type=Path, help="Source DWG path")
    parser.add_argument("--output-dir", required=True, type=Path, help="Report output directory")
    parser.add_argument("--job-id", default="rebar-scan-smoke", help="Job id for bridge task metadata")
    args = parser.parse_args()

    result = run_rebar_scan(job_id=args.job_id, source_dwg=args.source, output_dir=args.output_dir)
    print(
        json.dumps(
            {
                "rows_count": result.rows_count,
                "csv_path": str(result.csv_path),
                "debug_path": str(result.debug_path),
                "bridge_summary": result.bridge_summary,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
