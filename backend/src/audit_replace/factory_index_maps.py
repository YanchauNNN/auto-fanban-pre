from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf import bbox as dxf_bbox

DEGREE = "\u00b0"
ANGLE_RE = re.compile(
    r"(?P<deg>\d{1,3})\s*(?:\u00b0|\u5ea6|deg|d)"
    r"(?:\s*(?P<min>\d{1,2})\s*(?:'|\u2032|min|m))?"
    r"(?:\s*(?P<sec>\d{1,2}(?:\.\d+)?)\s*(?:\"|\u2033|sec|s))?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Point2D:
    x: float
    y: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class BBox2D:
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @property
    def width(self) -> float:
        return self.xmax - self.xmin

    @property
    def height(self) -> float:
        return self.ymax - self.ymin

    @property
    def center(self) -> Point2D:
        return Point2D((self.xmin + self.xmax) / 2.0, (self.ymin + self.ymax) / 2.0)

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class TextFeature:
    layout: str
    space: str
    entity_type: str
    handle: str | None
    raw_text: str
    text: str
    point: Point2D | None
    rotation: float | None
    source_block_name: str | None = None
    source_insert_handle: str | None = None
    source_insert_point: Point2D | None = None
    source_insert_bounds: BBox2D | None = None
    source: str = "entity"


@dataclass(frozen=True)
class CircleFeature:
    layout: str
    space: str
    handle: str | None
    center: Point2D
    radius: float
    source_block_name: str | None = None
    source_insert_handle: str | None = None
    source_insert_point: Point2D | None = None
    source_insert_bounds: BBox2D | None = None


@dataclass(frozen=True)
class FactoryIndexCandidate:
    layout: str
    angle_text: str
    angle_key: str
    angle_position: Point2D
    compass: CircleFeature
    score: float
    source_block_name: str | None
    source_insert_handle: str | None
    source_insert_point: Point2D | None
    source_bounds: BBox2D | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "layout": self.layout,
            "angle_text": self.angle_text,
            "angle_key": self.angle_key,
            "angle_position": self.angle_position.to_dict(),
            "compass": {
                "layout": self.compass.layout,
                "space": self.compass.space,
                "handle": self.compass.handle,
                "center": self.compass.center.to_dict(),
                "radius": self.compass.radius,
                "source_block_name": self.compass.source_block_name,
                "source_insert_handle": self.compass.source_insert_handle,
            },
            "score": self.score,
            "source_block_name": self.source_block_name,
            "source_insert_handle": self.source_insert_handle,
            "source_insert_point": (
                self.source_insert_point.to_dict() if self.source_insert_point else None
            ),
            "source_bounds": self.source_bounds.to_dict() if self.source_bounds else None,
        }


@dataclass(frozen=True)
class FactoryIndexMapTemplate:
    project_no: str
    template_dxf: Path
    angle_text: str | None
    angle_key: str | None
    compass: CircleFeature
    bounds: BBox2D

    @classmethod
    def from_dxf(cls, template_dxf: Path, *, project_no: str) -> FactoryIndexMapTemplate:
        doc = ezdxf.readfile(str(template_dxf))
        anchor = _template_anchor_from_dxf(template_dxf)
        if anchor is None:
            raise ValueError(f"factory index map template has no anchor: {template_dxf}")
        return cls(
            project_no=project_no,
            template_dxf=Path(template_dxf),
            angle_text=anchor.angle_text,
            angle_key=anchor.angle_key,
            compass=anchor.compass,
            bounds=_modelspace_bounds(doc),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_no": self.project_no,
            "template_dxf": str(self.template_dxf),
            "angle_text": self.angle_text,
            "angle_key": self.angle_key,
            "compass": {
                "center": self.compass.center.to_dict(),
                "radius": self.compass.radius,
            },
            "bounds": self.bounds.to_dict(),
        }


@dataclass(frozen=True)
class FactoryIndexReplacementAction:
    action_id: str
    layout: str
    source_angle_key: str
    target_angle_key: str
    source_compass_center: Point2D
    source_compass_radius: float
    target_compass_center: Point2D
    target_compass_radius: float
    source_bounds: BBox2D | None
    target_bounds: BBox2D
    source_block_name: str | None
    source_insert_handle: str | None
    source_insert_point: Point2D | None

    @property
    def scale(self) -> float:
        if self.target_compass_radius <= 0:
            return 1.0
        return self.source_compass_radius / self.target_compass_radius

    @property
    def fit_bbox_scale(self) -> float:
        if (
            self.source_bounds is None
            or self.source_bounds.width <= 0
            or self.source_bounds.height <= 0
            or self.target_bounds.width <= 0
            or self.target_bounds.height <= 0
        ):
            return self.scale
        return min(
            self.source_bounds.width / self.target_bounds.width,
            self.source_bounds.height / self.target_bounds.height,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "layout": self.layout,
            "source_angle_key": self.source_angle_key,
            "target_angle_key": self.target_angle_key,
            "source_compass_center": self.source_compass_center.to_dict(),
            "source_compass_radius": self.source_compass_radius,
            "target_compass_center": self.target_compass_center.to_dict(),
            "target_compass_radius": self.target_compass_radius,
            "source_bounds": self.source_bounds.to_dict() if self.source_bounds else None,
            "target_bounds": self.target_bounds.to_dict(),
            "scale": self.scale,
            "fit_bbox_scale": self.fit_bbox_scale,
            "scale_mode": "fit_source_block_bbox",
            "source_block_name": self.source_block_name,
            "source_insert_handle": self.source_insert_handle,
            "source_insert_point": (
                self.source_insert_point.to_dict() if self.source_insert_point else None
            ),
        }


@dataclass(frozen=True)
class FactoryIndexReplacementPlan:
    enabled: bool
    source_project_no: str
    target_project_no: str
    target_template_dwg: Path
    target_template: FactoryIndexMapTemplate
    actions: list[FactoryIndexReplacementAction]

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "source_project_no": self.source_project_no,
            "target_project_no": self.target_project_no,
            "target_template_dwg": str(self.target_template_dwg),
            "target_template": self.target_template.to_dict(),
            "actions": [action.to_dict() for action in self.actions],
        }

    def to_bridge_payload(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "source_project_no": self.source_project_no,
            "target_project_no": self.target_project_no,
            "target_template_dwg": str(self.target_template_dwg),
            "target_template": self.target_template.to_dict(),
            "actions": [action.to_dict() for action in self.actions],
        }


class FactoryIndexMapDetector:
    def detect(self, dxf_path: Path) -> list[FactoryIndexCandidate]:
        texts, circles = self.collect_features(dxf_path)
        return _build_candidates(texts, circles)

    def collect_features(self, dxf_path: Path) -> tuple[list[TextFeature], list[CircleFeature]]:
        doc = ezdxf.readfile(str(dxf_path))
        texts: list[TextFeature] = []
        circles: list[CircleFeature] = []
        for layout_name, space_kind, space in _iter_spaces(doc):
            for entity in space:
                self._collect_entity(
                    layout_name=layout_name,
                    space_kind=space_kind,
                    entity=entity,
                    texts=texts,
                    circles=circles,
                    source_block_name=None,
                    source_insert_handle=None,
                    source_insert_point=None,
                    source_insert_bounds=None,
                    source="entity",
                    depth=0,
                )
        return texts, circles

    def _collect_entity(
        self,
        *,
        layout_name: str,
        space_kind: str,
        entity: Any,
        texts: list[TextFeature],
        circles: list[CircleFeature],
        source_block_name: str | None,
        source_insert_handle: str | None,
        source_insert_point: Point2D | None,
        source_insert_bounds: BBox2D | None,
        source: str,
        depth: int,
    ) -> None:
        dxftype = entity.dxftype().upper()
        if dxftype == "INSERT":
            block_name = source_block_name or str(getattr(entity.dxf, "name", "") or "") or None
            insert_point = source_insert_point or _entity_point(entity)
            insert_handle = source_insert_handle or _entity_handle(entity)
            insert_bounds = source_insert_bounds or _entity_virtual_bounds(entity)
            for attrib in getattr(entity, "attribs", []):
                feature = _text_feature_from_entity(
                    layout_name,
                    space_kind,
                    attrib,
                    source_block_name=block_name,
                    source_insert_handle=insert_handle,
                    source_insert_point=insert_point,
                    source_insert_bounds=insert_bounds,
                    source="insert_attrib",
                )
                if feature:
                    texts.append(feature)
            self._collect_virtual_entities(
                layout_name=layout_name,
                space_kind=space_kind,
                entity=entity,
                texts=texts,
                circles=circles,
                source_block_name=block_name,
                source_insert_handle=insert_handle,
                source_insert_point=insert_point,
                source_insert_bounds=insert_bounds,
                source=f"{source}_insert",
                depth=depth,
            )
            return
        if dxftype == "DIMENSION":
            self._collect_virtual_entities(
                layout_name=layout_name,
                space_kind=space_kind,
                entity=entity,
                texts=texts,
                circles=circles,
                source_block_name=source_block_name,
                source_insert_handle=source_insert_handle,
                source_insert_point=source_insert_point,
                source_insert_bounds=source_insert_bounds,
                source=f"{source}_dimension",
                depth=depth,
            )
            return
        if dxftype in {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}:
            feature = _text_feature_from_entity(
                layout_name,
                space_kind,
                entity,
                source_block_name=source_block_name,
                source_insert_handle=source_insert_handle,
                source_insert_point=source_insert_point,
                source_insert_bounds=source_insert_bounds,
                source=source,
            )
            if feature:
                texts.append(feature)
            return
        if dxftype == "CIRCLE":
            circle = _circle_feature_from_entity(
                layout_name,
                space_kind,
                entity,
                source_block_name=source_block_name,
                source_insert_handle=source_insert_handle,
                source_insert_point=source_insert_point,
                source_insert_bounds=source_insert_bounds,
            )
            if circle:
                circles.append(circle)

    def _collect_virtual_entities(
        self,
        *,
        layout_name: str,
        space_kind: str,
        entity: Any,
        texts: list[TextFeature],
        circles: list[CircleFeature],
        source_block_name: str | None,
        source_insert_handle: str | None,
        source_insert_point: Point2D | None,
        source_insert_bounds: BBox2D | None,
        source: str,
        depth: int,
    ) -> None:
        if depth >= 5 or not hasattr(entity, "virtual_entities"):
            return
        try:
            virtual_entities = list(entity.virtual_entities())
        except Exception:
            return
        for virtual_entity in virtual_entities:
            self._collect_entity(
                layout_name=layout_name,
                space_kind=space_kind,
                entity=virtual_entity,
                texts=texts,
                circles=circles,
                source_block_name=source_block_name,
                source_insert_handle=source_insert_handle,
                source_insert_point=source_insert_point,
                source_insert_bounds=source_insert_bounds,
                source=source,
                depth=depth + 1,
            )


def build_factory_index_replacement_plan(
    *,
    source_project_no: str,
    target_project_no: str,
    source_dxf: Path,
    target_template_dxf: Path,
    target_template_dwg: Path,
) -> FactoryIndexReplacementPlan:
    source_candidates = FactoryIndexMapDetector().detect(source_dxf)
    source_candidates = _replacement_ready_candidates(source_candidates)
    target_template = FactoryIndexMapTemplate.from_dxf(
        target_template_dxf,
        project_no=target_project_no,
    )
    actions = [
        FactoryIndexReplacementAction(
            action_id=f"factory-index-map-{index:03d}",
            layout=candidate.layout,
            source_angle_key=candidate.angle_key,
            target_angle_key=target_template.angle_key,
            source_compass_center=candidate.compass.center,
            source_compass_radius=candidate.compass.radius,
            target_compass_center=target_template.compass.center,
            target_compass_radius=target_template.compass.radius,
            source_bounds=candidate.source_bounds,
            target_bounds=target_template.bounds,
            source_block_name=candidate.source_block_name,
            source_insert_handle=candidate.source_insert_handle,
            source_insert_point=candidate.source_insert_point,
        )
        for index, candidate in enumerate(source_candidates, start=1)
    ]
    return FactoryIndexReplacementPlan(
        enabled=bool(actions),
        source_project_no=source_project_no,
        target_project_no=target_project_no,
        target_template_dwg=Path(target_template_dwg),
        target_template=target_template,
        actions=actions,
    )


def _replacement_ready_candidates(
    candidates: list[FactoryIndexCandidate],
) -> list[FactoryIndexCandidate]:
    ready: dict[str, FactoryIndexCandidate] = {}
    for candidate in candidates:
        if (
            not candidate.source_block_name
            or not candidate.source_insert_handle
            or candidate.source_bounds is None
            or candidate.source_bounds.width <= 0
            or candidate.source_bounds.height <= 0
        ):
            continue
        existing = ready.get(candidate.source_insert_handle)
        if existing is None or candidate.score > existing.score:
            ready[candidate.source_insert_handle] = candidate
    return sorted(
        ready.values(),
        key=lambda item: (item.score, item.compass.center.y, item.compass.center.x),
        reverse=True,
    )


@dataclass(frozen=True)
class _TemplateAnchor:
    angle_text: str | None
    angle_key: str | None
    compass: CircleFeature


def _template_anchor_from_dxf(template_dxf: Path) -> _TemplateAnchor | None:
    detector = FactoryIndexMapDetector()
    candidates = detector.detect(template_dxf)
    if candidates:
        candidate = candidates[0]
        return _TemplateAnchor(
            angle_text=candidate.angle_text,
            angle_key=candidate.angle_key,
            compass=candidate.compass,
        )

    texts, circles = detector.collect_features(template_dxf)
    compass = _best_compass_from_direction_labels(texts, circles)
    if compass is None:
        return None
    return _TemplateAnchor(angle_text=None, angle_key=None, compass=compass)


def _best_compass_from_direction_labels(
    texts: list[TextFeature],
    circles: list[CircleFeature],
) -> CircleFeature | None:
    direction_points = [
        text
        for text in texts
        if text.point is not None and normalize_text(text.text).upper() in {"A", "B", "N"}
    ]
    if not direction_points:
        return None

    best: tuple[float, CircleFeature] | None = None
    for circle in circles:
        if circle.radius <= 0:
            continue
        nearby = 0
        distance_sum = 0.0
        for text in direction_points:
            assert text.point is not None
            distance = math.hypot(circle.center.x - text.point.x, circle.center.y - text.point.y)
            if distance <= max(circle.radius * 4.0, 500.0):
                nearby += 1
                distance_sum += distance / circle.radius
        if nearby < 2:
            continue
        score = nearby * 10.0 - distance_sum
        if best is None or score > best[0]:
            best = (score, circle)
    return best[1] if best else None


def normalize_text(value: str) -> str:
    text = str(value or "")
    text = text.replace("\\P", "\n")
    text = re.sub(
        r"\\U\+([0-9A-Fa-f]{4})",
        lambda match: chr(int(match.group(1), 16)),
        text,
    )
    text = re.sub(r"\\[A-Za-z][^;]*;", "", text)
    text = text.replace("%%D", DEGREE).replace("%%d", DEGREE)
    text = text.replace("\u63b3", DEGREE)
    text = text.replace("\u00ba", DEGREE)
    text = text.replace("\u2019", "'").replace("\u2032", "'")
    text = text.replace("\u201d", '"').replace("\u2033", '"')
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def angle_key(value: str) -> str | None:
    text = normalize_text(value)
    match = ANGLE_RE.search(text)
    if not match:
        return None
    deg = int(match.group("deg"))
    minute = int(match.group("min") or 0)
    second = float(match.group("sec") or 0)
    if deg > 360 or minute >= 60 or second >= 60:
        return None
    second_text = f"{int(second):02d}" if second.is_integer() else f"{second:05.2f}".rstrip("0").rstrip(".")
    return f"{deg:03d}-{minute:02d}-{second_text}"


def canonical_angle_text(value: str) -> str | None:
    key = angle_key(value)
    if key is None:
        return None
    deg, minute, second = key.split("-", 2)
    return f"{int(deg)}{DEGREE}{int(minute)}'{second}\""


def _iter_spaces(doc: Any) -> Iterable[tuple[str, str, Any]]:
    yield "Model", "modelspace", doc.modelspace()
    for layout in doc.layouts:
        if layout.name.lower() == "model":
            continue
        yield str(layout.name), "paperspace", layout


def _modelspace_bounds(doc: Any) -> BBox2D:
    box = dxf_bbox.extents(list(doc.modelspace()), fast=False)
    if not box.has_data:
        raise ValueError("factory index map template has no geometric bounds")
    return BBox2D(
        xmin=float(box.extmin.x),
        ymin=float(box.extmin.y),
        xmax=float(box.extmax.x),
        ymax=float(box.extmax.y),
    )


def _entity_virtual_bounds(entity: Any) -> BBox2D | None:
    if not hasattr(entity, "virtual_entities"):
        return None
    entities = list(_iter_leaf_virtual_entities(entity))
    if not entities:
        return None
    box = dxf_bbox.extents(entities, fast=False)
    if not box.has_data:
        return None
    return BBox2D(
        xmin=float(box.extmin.x),
        ymin=float(box.extmin.y),
        xmax=float(box.extmax.x),
        ymax=float(box.extmax.y),
    )


def _iter_leaf_virtual_entities(entity: Any, depth: int = 0) -> Iterable[Any]:
    if depth > 8 or not hasattr(entity, "virtual_entities"):
        yield entity
        return
    try:
        virtual_entities = list(entity.virtual_entities())
    except Exception:
        yield entity
        return
    if not virtual_entities:
        yield entity
        return
    for virtual_entity in virtual_entities:
        yield from _iter_leaf_virtual_entities(virtual_entity, depth + 1)


def _entity_handle(entity: Any) -> str | None:
    try:
        value = str(getattr(entity.dxf, "handle", "") or "")
    except Exception:
        return None
    return value or None


def _entity_point(entity: Any) -> Point2D | None:
    for attr in ("insert", "location", "center", "start"):
        try:
            point = getattr(entity.dxf, attr)
        except Exception:
            continue
        if point is None:
            continue
        try:
            return Point2D(float(point.x), float(point.y))
        except Exception:
            try:
                return Point2D(float(point[0]), float(point[1]))
            except Exception:
                continue
    return None


def _entity_rotation(entity: Any) -> float | None:
    try:
        return float(getattr(entity.dxf, "rotation", 0.0) or 0.0)
    except Exception:
        return None


def _text_feature_from_entity(
    layout_name: str,
    space_kind: str,
    entity: Any,
    *,
    source_block_name: str | None,
    source_insert_handle: str | None,
    source_insert_point: Point2D | None,
    source_insert_bounds: BBox2D | None,
    source: str,
) -> TextFeature | None:
    dxftype = entity.dxftype().upper()
    if dxftype == "MTEXT":
        raw = entity.plain_text() if hasattr(entity, "plain_text") else getattr(entity, "text", "")
    else:
        raw = getattr(entity.dxf, "text", "")
    text = normalize_text(raw)
    if not text:
        return None
    return TextFeature(
        layout=layout_name,
        space=space_kind,
        entity_type=dxftype,
        handle=_entity_handle(entity),
        raw_text=str(raw or ""),
        text=text,
        point=_entity_point(entity),
        rotation=_entity_rotation(entity),
        source_block_name=source_block_name,
        source_insert_handle=source_insert_handle,
        source_insert_point=source_insert_point,
        source_insert_bounds=source_insert_bounds,
        source=source,
    )


def _circle_feature_from_entity(
    layout_name: str,
    space_kind: str,
    entity: Any,
    *,
    source_block_name: str | None,
    source_insert_handle: str | None,
    source_insert_point: Point2D | None,
    source_insert_bounds: BBox2D | None,
) -> CircleFeature | None:
    try:
        center = entity.dxf.center
        radius = float(entity.dxf.radius)
        if radius <= 0:
            return None
        return CircleFeature(
            layout=layout_name,
            space=space_kind,
            handle=_entity_handle(entity),
            center=Point2D(float(center.x), float(center.y)),
            radius=radius,
            source_block_name=source_block_name,
            source_insert_handle=source_insert_handle,
            source_insert_point=source_insert_point,
            source_insert_bounds=source_insert_bounds,
        )
    except Exception:
        return None


def _build_candidates(
    texts: list[TextFeature],
    circles: list[CircleFeature],
) -> list[FactoryIndexCandidate]:
    circles_by_layout: dict[str, list[CircleFeature]] = {}
    for circle in circles:
        circles_by_layout.setdefault(circle.layout, []).append(circle)

    candidates: list[FactoryIndexCandidate] = []
    for text in texts:
        key = angle_key(text.text)
        if key is None or text.point is None:
            continue
        circle = _nearest_circle(text, circles_by_layout.get(text.layout, []))
        if circle is None:
            continue
        score = 10.0
        if text.source_block_name and circle.source_block_name == text.source_block_name:
            score += 3.0
        if text.source_insert_handle and circle.source_insert_handle == text.source_insert_handle:
            score += 2.0
        candidates.append(
            FactoryIndexCandidate(
                layout=text.layout,
                angle_text=canonical_angle_text(text.text) or text.text,
                angle_key=key,
                angle_position=text.point,
                compass=circle,
                score=score,
                source_block_name=text.source_block_name,
                source_insert_handle=text.source_insert_handle,
                source_insert_point=text.source_insert_point,
                source_bounds=text.source_insert_bounds,
            )
        )
    candidates.sort(key=lambda item: (item.score, item.compass.center.y, item.compass.center.x), reverse=True)
    return candidates


def _nearest_circle(text: TextFeature, circles: list[CircleFeature]) -> CircleFeature | None:
    if text.point is None:
        return None
    best: tuple[float, CircleFeature] | None = None
    for circle in circles:
        distance = math.hypot(circle.center.x - text.point.x, circle.center.y - text.point.y)
        if distance > max(circle.radius * 20.0, 200.0):
            continue
        if best is None or distance < best[0]:
            best = (distance, circle)
    return best[1] if best else None
