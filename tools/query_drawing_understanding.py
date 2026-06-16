from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _setup_imports() -> Path:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "backend"))
    return root


ROOT = _setup_imports()

from src.cad.drawing_understanding import answer_package_question  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask a local question against a drawing package.")
    parser.add_argument(
        "--package",
        type=Path,
        default=ROOT
        / "outputs"
        / "drawing-understanding"
        / "李帅反馈"
        / "drawing_elements.json",
        help="Path to drawing_elements.json.",
    )
    parser.add_argument("--question", required=True, help="Question to ask.")
    args = parser.parse_args()

    package = json.loads(args.package.read_text(encoding="utf-8"))
    answer = answer_package_question(package, args.question)
    print(json.dumps(answer, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
