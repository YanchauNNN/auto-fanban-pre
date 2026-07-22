from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _setup_imports() -> Path:
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "backend"))
    return root


ROOT = _setup_imports()

from src.cad import FrameDetector, ODAConverter, TitleblockExtractor  # noqa: E402
from src.cad.ai.drawing_understanding import (  # noqa: E402
    answer_package_question,
    summarize_element_package,
)
from src.cad.ai.element_package_exporter import process_source  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export structured drawing elements and a first-pass semantic package."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=ROOT / "test" / "李帅反馈",
        help="Directory containing DWG/DXF files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "outputs" / "drawing-understanding" / "李帅反馈",
        help="Directory for JSON outputs.",
    )
    parser.add_argument(
        "--max-geometry-elements",
        type=int,
        default=20_000,
        help="Maximum geometry elements to include per drawing; summaries are always complete.",
    )
    args = parser.parse_args()

    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    dxf_dir = output_dir / "dxf"
    output_dir.mkdir(parents=True, exist_ok=True)
    dxf_dir.mkdir(parents=True, exist_ok=True)

    source_paths = sorted(
        [
            path
            for path in input_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in {".dwg", ".dxf"}
        ],
        key=lambda path: str(path).lower(),
    )
    if not source_paths:
        raise SystemExit(f"No DWG/DXF files found under {input_dir}")

    oda = ODAConverter()
    detector = FrameDetector()
    extractor = TitleblockExtractor()
    package: dict[str, Any] = {
        "schema_version": "drawing-understanding@0.1",
        "source_dir": str(input_dir),
        "output_dir": str(output_dir),
        "drawings": [],
    }

    for source_path in source_paths:
        print(f"[drawing] {source_path.name}", flush=True)
        package["drawings"].append(
            process_source(
                source_path=source_path,
                dxf_dir=dxf_dir,
                oda=oda,
                detector=detector,
                extractor=extractor,
                max_geometry_elements=max(0, int(args.max_geometry_elements)),
            )
        )

    package["summary"] = summarize_element_package(package)
    elements_path = output_dir / "drawing_elements.json"
    semantic_path = output_dir / "semantic_understanding.json"
    qa_path = output_dir / "qa_assistant_seed.json"
    _write_json(elements_path, package)
    _write_json(semantic_path, _build_semantic_output(package))
    _write_json(qa_path, _build_qa_examples(package))

    print(f"[ok] wrote {elements_path}")
    print(f"[ok] wrote {semantic_path}")
    print(f"[ok] wrote {qa_path}")
    return 0


def _build_semantic_output(package: dict[str, Any]) -> dict[str, Any]:
    drawings = []
    for drawing in package["drawings"]:
        titles = []
        for frame in drawing.get("frames", []):
            titleblock = frame.get("titleblock", {})
            title = titleblock.get("title_cn") or titleblock.get("title_en")
            if title:
                titles.append(
                    {
                        "internal_code": titleblock.get("internal_code"),
                        "title": title,
                        "paper_variant_id": frame.get("paper_variant_id"),
                        "flags": frame.get("flags", []),
                    }
                )
        drawings.append(
            {
                "source_name": drawing.get("source_name"),
                "status": drawing.get("status"),
                "project_no_inferred": drawing.get("project_no_inferred"),
                "unit_no_inferred": drawing.get("unit_no_inferred"),
                "frame_count": len(drawing.get("frames", [])),
                "titleblocks": titles,
                "semantic_summary": drawing.get("semantic_summary", {}),
                "errors": drawing.get("errors", []),
            }
        )
    return {
        "schema_version": "drawing-semantic-understanding@0.1",
        "source_dir": package.get("source_dir"),
        "summary": package.get("summary", {}),
        "drawings": drawings,
    }


def _build_qa_examples(package: dict[str, Any]) -> dict[str, Any]:
    questions = ["这个元素包里有多少图框？", "有哪些图纸标题？"]
    return {
        "schema_version": "drawing-qa-assistant-seed@0.1",
        "mode": "local_rule_based_seed",
        "questions": [
            {"question": question, **answer_package_question(package, question)}
            for question in questions
        ],
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
