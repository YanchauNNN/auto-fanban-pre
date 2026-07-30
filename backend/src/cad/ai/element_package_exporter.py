from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Protocol

import ezdxf

from src.cad import FrameDetector, ODAConverter, TitleblockExtractor
from src.cad.ai.drawing_understanding import (
    classify_text_semantics,
    derive_project_unit_from_internal_codes,
    summarize_element_package,
)
from src.interfaces import ConversionError, DetectionError, ExtractionError
from src.pipeline.project_no_inference import (
    infer_project_no_from_path,
    infer_unit_no_from_path,
)


class DwgToDxfConverter(Protocol):
    def dwg_to_dxf(self, dwg_path: Path, output_dir: Path) -> Path: ...


def process_source(
    *,
    source_path: Path,
    dxf_dir: Path,
    oda: DwgToDxfConverter | None = None,
    detector: FrameDetector | None = None,
    extractor: TitleblockExtractor | None = None,
    max_geometry_elements: int = 20_000,
) -> dict[str, Any]:
    source_path = Path(source_path)
    dxf_dir = Path(dxf_dir)
    dxf_dir.mkdir(parents=True, exist_ok=True)
    drawing: dict[str, Any] = {
        "source_file": str(source_path),
        "source_name": source_path.name,
        "status": "ok",
        "project_no_inferred": infer_project_no_from_path(source_path.name),
        "unit_no_inferred": infer_unit_no_from_path(
            source_path.name,
            infer_project_no_from_path(source_path.name),
        ),
        "dxf_file": None,
        "conversion": {
            "required": source_path.suffix.lower() == ".dwg",
            "status": "skipped",
        },
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
        document = ezdxf.readfile(str(dxf_path))
        modelspace = document.modelspace()

        drawing["entity_type_counts"] = _counter_items(
            Counter(entity.dxftype() for entity in modelspace)
        )
        drawing["layers"] = _counter_items(
            Counter(str(getattr(entity.dxf, "layer", "")) for entity in modelspace)
        )
        geometry = _collect_geometry_elements(
            modelspace,
            max(0, int(max_geometry_elements)),
        )
        drawing["geometry_elements"] = geometry["items"]
        drawing["geometry_elements_truncated"] = geometry["truncated"]

        active_detector = detector or FrameDetector()
        active_extractor = extractor or TitleblockExtractor()
        project_no = drawing.get("project_no_inferred")
        active_detector.set_project_no(str(project_no or "") or None)
        active_extractor.set_project_no(str(project_no or "") or None)

        text_items = [
            active_extractor._text_item_to_dict(item)
            for item in active_extractor._load_text_items(dxf_path)
        ]
        drawing["text_elements"] = classify_text_semantics(text_items)

        parsed_frames = []
        for frame in active_detector.detect_frames(dxf_path):
            active_extractor.extract_fields(dxf_path, frame)
            parsed_frames.append(_frame_to_dict(frame))
        drawing["frames"] = parsed_frames
        fallback_identity = derive_project_unit_from_internal_codes(parsed_frames)
        if not drawing.get("project_no_inferred"):
            drawing["project_no_inferred"] = fallback_identity.get("project_no")
            drawing["project_no_inference_source"] = (
                "titleblock_internal_code"
                if drawing.get("project_no_inferred")
                else None
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
        drawing["titleblock_identity_evidence_count"] = fallback_identity.get(
            "evidence_count",
            0,
        )
        drawing["semantic_summary"] = summarize_element_package(
            {"drawings": [drawing]}
        )
    except (ConversionError, DetectionError, ExtractionError, OSError, ezdxf.DXFError) as exc:
        drawing["status"] = "failed"
        drawing["errors"].append({"stage": "parse", "message": str(exc)})
    except Exception as exc:  # noqa: BLE001
        drawing["status"] = "failed"
        drawing["errors"].append({"stage": "unexpected", "message": repr(exc)})

    return drawing


def _ensure_dxf(
    source_path: Path,
    dxf_dir: Path,
    oda: DwgToDxfConverter | None,
    drawing: dict[str, Any],
) -> Path:
    if source_path.suffix.lower() == ".dxf":
        return source_path
    if source_path.suffix.lower() != ".dwg":
        raise ConversionError(f"Unsupported CAD source: {source_path.suffix}")

    expected = dxf_dir / f"{source_path.stem}.dxf"
    if expected.exists():
        drawing["conversion"] = {
            "required": True,
            "status": "reused",
            "message": "Existing converted DXF reused.",
        }
        return expected

    converter = oda or ODAConverter()
    dxf_path = converter.dwg_to_dxf(source_path, dxf_dir)
    drawing["conversion"] = {
        "required": True,
        "status": "converted",
        "message": "Converted from DWG via ODA File Converter.",
    }
    return Path(dxf_path)


def _collect_geometry_elements(modelspace: Any, max_items: int) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    truncated = False
    for entity in modelspace:
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
            points = [
                (float(vertex.dxf.location.x), float(vertex.dxf.location.y))
                for vertex in entity.vertices
            ]
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
            base["center"] = _point(center)
            base["radius"] = float(entity.dxf.radius)
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


def _counter_items(counter: Counter[str]) -> list[dict[str, Any]]:
    return [
        {"name": name, "count": count}
        for name, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
        if name
    ]


def _point(value: Any) -> dict[str, float]:
    return {"x": float(value.x), "y": float(value.y)}


def _bbox_from_points(points: list[Any]) -> dict[str, float]:
    return _bbox_from_xy(
        [(float(point.x), float(point.y)) for point in points]
    ) or {"xmin": 0.0, "ymin": 0.0, "xmax": 0.0, "ymax": 0.0}


def _bbox_from_xy(points: list[tuple[float, float]]) -> dict[str, float] | None:
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return {"xmin": min(xs), "ymin": min(ys), "xmax": max(xs), "ymax": max(ys)}
