from __future__ import annotations

import argparse
import json
from pathlib import Path

from standards_reviews import publish_reviewed_corpus


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay PDF-bound visual reviews into a separate candidate corpus."
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = publish_reviewed_corpus(
        database=args.database,
        reviews_path=args.reviews,
        source_root=args.source_root,
        output_path=args.output,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
