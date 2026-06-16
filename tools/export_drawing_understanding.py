from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def _setup_imports() -> Path:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "backend"))
    return root


ROOT = _setup_imports()

import ezdxf  # noqa: E402

from src.cad import FrameDetector, ODAConverter, TitleblockExtractor  # noqa: E402
from src.cad.drawing_understanding import (  # noqa: E402
    answer_package_question,
    classify_text_semantics,
    derive_project_unit_from_internal_codes,
    summarize_element_package,
)
from src.interfaces import ConversionError, DetectionError, ExtractionError  # noqa: E402
from src.pipeline.project_no_inference import infer_project_no_from_path, infer_unit_no_from_path  # noqa: E402


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
        default=20000,
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
            _process_source(
                source_path=source_path,
                dxf_dir=dxf_dir,
                oda=oda,
                detector=detector,
                extractor=extractor,
                max_geometry_elements=max(0, int(args.max_geometry_elements)),
            )
        )

    package["summary"] = summarize_element_package(package)
    qa_examples = _build_qa_examples(package)

    elements_path = output_dir / "drawing_elements.json"
    semantic_path = output_dir / "semantic_understanding.json"
    qa_path = output_dir / "qa_assistant_seed.json"

    _write_json(elements_path, package)
    _write_json(semantic_path, _build_semantic_output(package))
    _write_json(qa_path, qa_examples)

    print(f"[ok] wrote {elements_path}")
    print(f"[ok] wrote {semantic_path}")
    print(f"[ok] wrote {qa_path}")
    return 0


def _process_source(
    *,
    source_path: Path,
    dxf_dir: Path,
    oda: ODAConverter,
    detector: FrameDetector,
    extractor: TitleblockExtractor,
    max_geometry_elements: int,
) -> dict[str, Any]:
    drawing: dict[str, Any] = {
        "source_file": str(source_path),
        "source_name": source_path.name,
        "status": "ok",
        "project_no_inferred": infer_project_no_from_path(source_path.name),
        "unit_no_inferred": infer_unit_no_from_path(
            source_path.name, infer_project_no_from_path(source_path.name)
        ),
        "dxf_file": None,
        "conversion": {"required": source_path.suffix.lower() == ".dwg", "status": "skipped"},
        "entity_type_counts": [],
        "layers": [],
        "geometry_elements": [],
        "geometry_elements_truncated": False,
        "text_elements": [],
        "frames": [],
        "errors": [],
    }

    try:
        dxf_path = _ensure_dxf(source_path, dxf_dir, oda, drawing)
        drawing["dxf_file"] = str(dxf_path)
        doc = ezdxf.readfile(str(dxf_path))
        msp = doc.modelspace()

        drawing["entity_type_counts"] = _counter_items(Counter(entity.dxftype() for entity in msp))
        drawing["layers"] = _counter_items(
            Counter(str(getattr(entity.dxf, "layer", "")) for entity in msp)
        )
        geometry_elements = _collect_geometry_elements(msp, max_geometry_elements)
        drawing["geometry_elements"] = geometry_elements["items"]
        drawing["geometry_elements_truncated"] = geometry_elements["truncated"]

        project_no = drawing.get("project_no_inferred")
        detector.set_project_no(str(project_no or "") or None)
        extractor.set_project_no(str(project_no or "") or None)

        text_items = [extractor._text_item_to_dict(item) for item in extractor._load_text_items(dxf_path)]
        drawing["text_elements"] = classify_text_semantics(text_items)

        frames = detector.detect_frames(dxf_path)
        parsed_frames = []
        for frame in frames:
            extractor.extract_fields(dxf_path, frame)
            parsed_frames.append(_frame_to_dict(frame))
        drawing["frames"] = parsed_frames
        fallback_identity = derive_project_unit_from_internal_codes(parsed_frames)
        if not drawing.get("project_no_inferred"):
            drawing["project_no_inferred"] = fallback_identity.get("project_no")
            drawing["project_no_inference_source"] = (
                "titleblock_internal_code" if drawing.get("project_no_inferred") else None
            )
        else:
            drawing["project_no_inference_source"] = "filename"
        if not drawing.get("unit_no_inferred"):
            drawing["unit_no_inferred"] = fallback_identity.get("unit_no")
            drawing["unit_no_inference_source"] = (
                "titleblock_internal_code" if drawing.get("unit_no_inferred") else None
            )
        else:
            drawing["unit_no_inference_source"] = "filename"
        drawing["titleblock_identity_evidence_count"] = fallback_identity.get("evidence_count", 0)
        drawing["semantic_summary"] = summarize_element_package({"drawings": [drawing]})
    except (ConversionError, DetectionError, ExtractionError, OSError, ezdxf.DXFError) as exc:
        drawing["status"] = "failed"
        drawing["errors"].append({"stage": "parse", "message": str(exc)})
    except Exception as exc:  # noqa: BLE001
        drawing["status"] = "failed"
        drawing["errors"].append({"stage": "unexpected", "message": repr(exc)})

    return drawing


def _ensure_dxf(source_path: Path, dxf_dir: Path, oda: ODAConverter, drawing: dict[str, Any]) -> Path:
    if source_path.suffix.lower() == ".dxf":
        return source_path

    expected = dxf_dir / f"{source_path.stem}.dxf"
    if expected.exists():
        drawing["conversion"] = {
            "required": True,
            "status": "reused",
            "message": "Existing converted DXF reused.",
        }
        return expected

    dxf_path = oda.dwg_to_dxf(source_path, dxf_dir)
    drawing["conversion"] = {
        "required": True,
        "status": "converted",
        "message": "Converted from DWG via ODA File Converter.",
    }
    return dxf_path


def _collect_geometry_elements(msp: Any, max_items: int) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    truncated = False
    for entity in msp:
        if len(items) >= max_items:
            truncated = True
            break
        item = _geometry_entity_to_dict(entity)
        if item is not None:
            items.append(item)
    return {"items": items, "truncated": truncated}


def _geometry_entity_to_dict(entity: Any) -> dict[str, Any] | None:
    entity_type = entity.dxftype()
    base: dict[str, Any] = {
        "type": entity_type,
        "layer": str(getattr(entity.dxf, "layer", "")),
        "handle": str(getattr(entity.dxf, "handle", "")),
    }

    try:
        if entity_type == "LINE":
            start = entity.dxf.start
            end = entity.dxf.end
            base["start"] = _point(start)
            base["end"] = _point(end)
            base["bbox"] = _bbox_from_points([start, end])
        elif entity_type == "LWPOLYLINE":
            points = [(float(x), float(y)) for x, y, *_ in entity.get_points()]
            base["point_count"] = len(points)
            base["closed"] = bool(entity.closed)
            base["bbox"] = _bbox_from_xy(points)
        elif entity_type == "POLYLINE":
            points = [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices]
            base["point_count"] = len(points)
            base["closed"] = bool(entity.is_closed)
            base["bbox"] = _bbox_from_xy(points)
        elif entity_type == "CIRCLE":
            center = entity.dxf.center
            radius = float(entity.dxf.radius)
            base["center"] = _point(center)
            base["radius"] = radius
            base["bbox"] = {
                "xmin": float(center.x) - radius,
                "ymin": float(center.y) - radius,
                "xmax": float(center.x) + radius,
                "ymax": float(center.y) + radius,
            }
        elif entity_type == "ARC":
            center = entity.dxf.center
            radius = float(entity.dxf.radius)
            base["center"] = _point(center)
            base["radius"] = radius
            base["start_angle"] = float(entity.dxf.start_angle)
            base["end_angle"] = float(entity.dxf.end_angle)
        elif entity_type == "INSERT":
            base["name"] = str(entity.dxf.name)
            base["insert"] = _point(entity.dxf.insert)
        elif entity_type == "DIMENSION":
            base["dimension_type"] = int(getattr(entity.dxf, "dimtype", 0) or 0)
            base["text"] = str(getattr(entity.dxf, "text", "") or "")
        elif entity_type in {"TEXT", "MTEXT", "HATCH"}:
            return None
    except Exception as exc:  # noqa: BLE001
        base["extract_error"] = str(exc)

    return base


def _frame_to_dict(frame: Any) -> dict[str, Any]:
    runtime = frame.runtime
    return {
        "frame_id": frame.frame_id,
        "outer_bbox": runtime.outer_bbox.model_dump(mode="json"),
        "outer_vertices": list(runtime.outer_vertices),
        "paper_variant_id": runtime.paper_variant_id,
        "roi_profile_id": runtime.roi_profile_id,
        "sx": runtime.sx,
        "sy": runtime.sy,
        "geom_scale_factor": runtime.geom_scale_factor,
        "flags": list(runtime.flags),
        "titleblock": frame.titleblock.model_dump(mode="json"),
        "raw_extracts": frame.raw_extracts,
    }


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
    questions = [
        "这个元素包里有多少图框？",
        "有哪些图纸标题？",
    ]
    return {
        "schema_version": "drawing-qa-assistant-seed@0.1",
        "mode": "local_rule_based_seed",
        "questions": [
            {"question": question, **answer_package_question(package, question)}
            for question in questions
        ],
    }


def _counter_items(counter: Counter[str]) -> list[dict[str, Any]]:
    return [
        {"name": name, "count": count}
        for name, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
        if name
    ]


def _point(value: Any) -> dict[str, float]:
    return {"x": float(value.x), "y": float(value.y)}


def _bbox_from_points(points: list[Any]) -> dict[str, float]:
    return _bbox_from_xy([(float(point.x), float(point.y)) for point in points])


def _bbox_from_xy(points: list[tuple[float, float]]) -> dict[str, float] | None:
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return {"xmin": min(xs), "ymin": min(ys), "xmax": max(xs), "ymax": max(ys)}


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
