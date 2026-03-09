"""
候选矩形查找器 - 从DXF模型空间提取闭合矩形

策略：
1. 优先: LWPOLYLINE/POLYLINE（闭合）
2. 兜底: LINE实体重建矩形（纯几何，无图层依赖）
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Iterable

from ...models import BBox


class CandidateFinder:
    """候选图框查找器"""

    def __init__(
        self,
        min_dim: float = 100.0,
        coord_tol: float = 0.5,
        orthogonality_tol_deg: float = 1.0,
        layer_order: list[str] | None = None,
        entity_order: list[str] | None = None,
        line_rebuild_limits: dict[str, int] | None = None,
        bbox_scale_validator: Callable[[BBox], bool] | None = None,
    ) -> None:
        self.min_dim = min_dim
        self.coord_tol = coord_tol
        self.orthogonality_tol_deg = orthogonality_tol_deg
        self._sin_tol = math.sin(math.radians(orthogonality_tol_deg))
        self.layer_order = [str(layer) for layer in (layer_order or []) if layer]
        default_entity_order = ["LWPOLYLINE", "POLYLINE", "LINE"]
        self.entity_order = (
            [str(e) for e in entity_order if e] if entity_order else default_entity_order
        )
        limits = line_rebuild_limits or {}
        self.line_rebuild_max_segments = (
            int(limits["max_segments"]) if limits.get("max_segments") else None
        )
        self.line_rebuild_max_coord_pairs = (
            int(limits["max_coord_pairs"]) if limits.get("max_coord_pairs") else None
        )
        self._bbox_scale_validator = bbox_scale_validator
        self.logger = logging.getLogger(__name__)

    def find_rectangles(self, msp) -> list[BBox]:
        """
        从模型空间提取所有候选矩形

        Args:
            msp: DXF模型空间

        Returns:
            候选矩形的BBox列表（按面积降序）
        """
        if self.layer_order:
            return self._find_rectangles_by_layer(msp)
        return self._find_rectangles_global(msp)

    def _find_rectangles_global(self, msp) -> list[BBox]:
        poly_candidates: list[BBox] = []
        # 1. 从LWPOLYLINE提取
        for entity in msp.query("LWPOLYLINE"):
            bbox = self._extract_bbox(entity)
            if bbox and self._is_valid_size(bbox):
                poly_candidates.append(bbox)

        # 2. 从POLYLINE提取
        for entity in msp.query("POLYLINE"):
            bbox = self._extract_bbox(entity)
            if bbox and self._is_valid_size(bbox):
                poly_candidates.append(bbox)

        if poly_candidates:
            candidates = self._dedupe_candidates(poly_candidates)
            candidates.sort(key=lambda b: b.width * b.height, reverse=True)
            return candidates

        # 3. LINE重建矩形（补强策略：仅在无poly候选时执行）
        line_candidates = [
            bbox for bbox in self._rebuild_from_lines(msp) if self._is_valid_size(bbox)
        ]

        candidates = self._dedupe_candidates(line_candidates)

        # 按面积降序排序
        candidates.sort(key=lambda b: b.width * b.height, reverse=True)

        return candidates

    def _find_rectangles_by_layer(self, msp) -> list[BBox]:
        poly_candidates: list[BBox] = []
        line_candidates: list[BBox] = []
        allow_line_rebuild = "LINE" in self.entity_order

        for layer in self.layer_order:
            layer_poly_candidates: list[BBox] = []
            layer_poly_segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
            layer_line_segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
            layer_hit = False
            for entity_type in self.entity_order:
                if entity_type in {"LWPOLYLINE", "POLYLINE"}:
                    for entity in self._iter_layer_entities(msp, layer, entity_type):
                        vertices = self._polyline_vertices(entity, entity_type)
                        if len(vertices) < 2:
                            continue
                        is_closed = self._is_polyline_closed(
                            entity, entity_type, vertices
                        )
                        if is_closed or (
                            len(vertices) >= 4 and self._is_axis_aligned(vertices)
                        ):
                            if not self._is_axis_aligned(vertices):
                                continue
                            bbox = self._bbox_from_vertices(vertices)
                            if self._is_valid_size(bbox):
                                layer_poly_candidates.append(bbox)
                            continue
                        if allow_line_rebuild:
                            layer_poly_segments.extend(self._polyline_segments(vertices))
                elif entity_type == "LINE" and allow_line_rebuild:
                    layer_line_segments.extend(self._line_segments(msp, layer))

            if layer_poly_candidates:
                if self._bbox_scale_validator:
                    valid = [
                        bbox for bbox in layer_poly_candidates if self._bbox_scale_validator(bbox)
                    ]
                    invalid_count = len(layer_poly_candidates) - len(valid)
                    poly_candidates.extend(valid)
                    layer_hit = layer_hit or bool(valid)
                    if invalid_count == 0:
                        if layer_hit:
                            return self._finalize_candidates(poly_candidates + line_candidates)
                        continue
                else:
                    poly_candidates.extend(layer_poly_candidates)
                    layer_hit = layer_hit or bool(layer_poly_candidates)
                    if layer_hit:
                        return self._finalize_candidates(poly_candidates + line_candidates)
                    continue
            if allow_line_rebuild and (layer_poly_segments or layer_line_segments):
                combined_segments = layer_poly_segments + layer_line_segments
                if (
                    self.line_rebuild_max_segments
                    and len(combined_segments) > self.line_rebuild_max_segments
                    and layer_poly_segments
                ):
                    poly_rects = self._rebuild_from_segments(
                        layer_poly_segments, context=f"layer={layer}:poly_only"
                    )
                    valid_poly_rects = [
                        bbox for bbox in poly_rects if self._is_valid_size(bbox)
                    ]
                    line_candidates.extend(valid_poly_rects)
                    layer_hit = layer_hit or bool(valid_poly_rects)
                    if valid_poly_rects:
                        return self._finalize_candidates(poly_candidates + line_candidates)
                    if layer_line_segments:
                        line_rects = self._rebuild_from_segments(
                            layer_line_segments, context=f"layer={layer}:line_only"
                        )
                        valid_line_rects = [
                            bbox for bbox in line_rects if self._is_valid_size(bbox)
                        ]
                        line_candidates.extend(valid_line_rects)
                        layer_hit = layer_hit or bool(valid_line_rects)
                else:
                    valid_line_rects = [
                        bbox
                        for bbox in self._rebuild_from_segments(
                            combined_segments, context=f"layer={layer}"
                        )
                        if self._is_valid_size(bbox)
                    ]
                    line_candidates.extend(valid_line_rects)
                    layer_hit = layer_hit or bool(valid_line_rects)

            if layer_hit:
                return self._finalize_candidates(poly_candidates + line_candidates)

        return self._finalize_candidates(poly_candidates + line_candidates)

    def _extract_bbox(self, entity) -> BBox | None:
        """从polyline提取外接矩形"""
        try:
            vertices = list(entity.get_points())
            if len(vertices) < 4:
                return None

            if not self._is_axis_aligned(vertices):
                return None

            xs = [p[0] for p in vertices]
            ys = [p[1] for p in vertices]

            return BBox(
                xmin=min(xs),
                ymin=min(ys),
                xmax=max(xs),
                ymax=max(ys),
            )
        except Exception:
            return None

    def _is_axis_aligned(self, vertices: Iterable[tuple[float, float, *tuple]]) -> bool:
        """判断polyline是否为轴对齐矩形"""
        xs = self._cluster_coords([p[0] for p in vertices])
        ys = self._cluster_coords([p[1] for p in vertices])
        return len(xs) == 2 and len(ys) == 2

    def _cluster_coords(self, values: list[float]) -> list[float]:
        """按容差聚类坐标值"""
        if not values:
            return []
        values = sorted(values)
        clusters = [[values[0]]]
        for v in values[1:]:
            if abs(v - clusters[-1][-1]) <= self.coord_tol:
                clusters[-1].append(v)
            else:
                clusters.append([v])
        return [sum(c) / len(c) for c in clusters]

    def _is_valid_size(self, bbox: BBox) -> bool:
        return bbox.width >= self.min_dim and bbox.height >= self.min_dim

    def _dedupe_candidates(self, candidates: list[BBox]) -> list[BBox]:
        seen: set[tuple[float, float, float, float]] = set()
        unique: list[BBox] = []
        for bbox in candidates:
            key = (
                round(bbox.xmin, 3),
                round(bbox.ymin, 3),
                round(bbox.xmax, 3),
                round(bbox.ymax, 3),
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(bbox)
        return unique

    def _finalize_candidates(self, candidates: list[BBox]) -> list[BBox]:
        finalized = self._dedupe_candidates(candidates)
        finalized.sort(key=lambda b: b.width * b.height, reverse=True)
        return finalized

    def _iter_layer_entities(self, msp, layer: str, entity_type: str):
        query = f'{entity_type}[layer=="{layer}"]'
        try:
            for entity in msp.query(query):
                yield entity
        except Exception:
            for entity in msp.query(entity_type):
                try:
                    if entity.dxf.layer == layer:
                        yield entity
                except Exception:
                    continue

        try:
            inserts = list(msp.query("INSERT"))
        except Exception:
            inserts = list(msp.query("INSERT"))

        for insert in inserts:
            insert_layer = getattr(insert.dxf, "layer", "0")
            yield from self._iter_insert_entities(
                insert,
                entity_type=entity_type,
                target_layer=layer,
                parent_layer=insert_layer,
                depth=0,
            )

    def _iter_insert_entities(
        self,
        insert,
        *,
        entity_type: str,
        target_layer: str,
        parent_layer: str,
        depth: int,
        max_depth: int = 8,
    ):
        if depth > max_depth:
            return
        insert_layer = getattr(insert.dxf, "layer", "0") or "0"
        effective_insert_layer = parent_layer if insert_layer == "0" else insert_layer
        try:
            virtuals = list(insert.virtual_entities())
        except Exception:
            return
        for ve in virtuals:
            tp = ve.dxftype()
            if tp == "INSERT":
                yield from self._iter_insert_entities(
                    ve,
                    entity_type=entity_type,
                    target_layer=target_layer,
                    parent_layer=effective_insert_layer,
                    depth=depth + 1,
                    max_depth=max_depth,
                )
                continue
            if tp != entity_type:
                continue
            try:
                ve_layer = ve.dxf.layer
            except Exception:
                ve_layer = "0"
            effective_layer = effective_insert_layer if ve_layer == "0" else ve_layer
            if effective_layer != target_layer:
                continue
            yield ve

    def _polyline_vertices(self, entity, tp: str) -> list[tuple[float, float]]:
        vertices: list[tuple[float, float]] = []
        if tp == "LWPOLYLINE":
            for p in entity.get_points():
                vertices.append((float(p[0]), float(p[1])))
        elif tp == "POLYLINE":
            for v in entity.vertices:
                loc = v.dxf.location
                vertices.append((float(loc.x), float(loc.y)))
        return vertices

    def _is_polyline_closed(
        self, entity, tp: str, vertices: list[tuple[float, float]]
    ) -> bool:
        if tp == "LWPOLYLINE":
            closed = bool(getattr(entity, "closed", False) or getattr(entity, "is_closed", False))
        elif tp == "POLYLINE":
            closed = bool(getattr(entity, "is_closed", False) or getattr(entity, "closed", False))
        else:
            closed = False
        if not closed and len(vertices) >= 3 and vertices[0] == vertices[-1]:
            return True
        return closed

    @staticmethod
    def _bbox_from_vertices(vertices: list[tuple[float, float]]) -> BBox:
        xs = [p[0] for p in vertices]
        ys = [p[1] for p in vertices]
        return BBox(xmin=min(xs), ymin=min(ys), xmax=max(xs), ymax=max(ys))

    @staticmethod
    def _polyline_segments(
        vertices: list[tuple[float, float]],
    ) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for idx in range(len(vertices) - 1):
            p1 = vertices[idx]
            p2 = vertices[idx + 1]
            if p1 == p2:
                continue
            segments.append((p1, p2))
        return segments

    def _line_segments(
        self, msp, layer: str
    ) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for entity in self._iter_layer_entities(msp, layer, "LINE"):
            start = entity.dxf.start
            end = entity.dxf.end
            segments.append(
                ((float(start.x), float(start.y)), (float(end.x), float(end.y)))
            )
        return segments

    def _rebuild_from_lines(self, msp) -> list[BBox]:
        """从LINE实体重建矩形（兜底方案）"""
        segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for entity in msp.query("LINE"):
            start = entity.dxf.start
            end = entity.dxf.end
            segments.append(
                ((float(start.x), float(start.y)), (float(end.x), float(end.y)))
            )
        for entity_type in ("LWPOLYLINE", "POLYLINE"):
            for entity in msp.query(entity_type):
                vertices = self._polyline_vertices(entity, entity_type)
                if not vertices:
                    continue
                if self._is_polyline_closed(entity, entity_type, vertices):
                    continue
                segments.extend(self._polyline_segments(vertices))
        return self._rebuild_from_segments(segments, context="global_lines")

    def _rebuild_from_segments(
        self,
        segments: list[tuple[tuple[float, float], tuple[float, float]]],
        *,
        context: str | None = None,
    ) -> list[BBox]:
        if not segments:
            return []
        if self.line_rebuild_max_segments and len(segments) > self.line_rebuild_max_segments:
            self.logger.warning(
                "LINE重建跳过: context=%s segments=%d max_segments=%d",
                context or "-",
                len(segments),
                self.line_rebuild_max_segments,
            )
            return []

        horizontal: list[tuple[float, float, float]] = []
        vertical: list[tuple[float, float, float]] = []
        for (x1, y1), (x2, y2) in segments:
            dx = x2 - x1
            dy = y2 - y1
            length = math.hypot(dx, dy)
            if length <= 0:
                continue

            if abs(dy) <= self.coord_tol or abs(dy) / length <= self._sin_tol:
                y = (y1 + y2) / 2.0
                left, right = sorted([x1, x2])
                horizontal.append((y, left, right))
            elif abs(dx) <= self.coord_tol or abs(dx) / length <= self._sin_tol:
                x = (x1 + x2) / 2.0
                bottom, top = sorted([y1, y2])
                vertical.append((x, bottom, top))

        h_segments = self._cluster_segments(horizontal)
        v_segments = self._cluster_segments(vertical)

        rectangles: list[BBox] = []
        seen: set[tuple[float, float, float, float]] = set()

        ys = sorted(h_segments.keys())
        xs = sorted(v_segments.keys())
        if (
            self.line_rebuild_max_coord_pairs
            and len(xs) * len(ys) > self.line_rebuild_max_coord_pairs
        ):
            self.logger.warning(
                "LINE重建跳过: context=%s coord_pairs=%d max_coord_pairs=%d xs=%d ys=%d",
                context or "-",
                len(xs) * len(ys),
                self.line_rebuild_max_coord_pairs,
                len(xs),
                len(ys),
            )
            return []

        for yi, y1 in enumerate(ys):
            for y2 in ys[yi + 1 :]:
                if (y2 - y1) < self.min_dim:
                    continue
                for xi, x1 in enumerate(xs):
                    for x2 in xs[xi + 1 :]:
                        if (x2 - x1) < self.min_dim:
                            continue
                        if not self._has_edge(h_segments[y1], x1, x2):
                            continue
                        if not self._has_edge(h_segments[y2], x1, x2):
                            continue
                        if not self._has_edge(v_segments[x1], y1, y2):
                            continue
                        if not self._has_edge(v_segments[x2], y1, y2):
                            continue
                        key = (
                            round(x1, 3),
                            round(y1, 3),
                            round(x2, 3),
                            round(y2, 3),
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        rectangles.append(BBox(xmin=x1, ymin=y1, xmax=x2, ymax=y2))

        return rectangles

    def _cluster_segments(
        self, segments: list[tuple[float, float, float]]
    ) -> dict[float, list[tuple[float, float]]]:
        """按主坐标聚类线段并合并区间"""
        if not segments:
            return {}
        segments.sort(key=lambda s: s[0])
        clusters: list[dict[str, object]] = []
        for coord, start, end in segments:
            if not clusters or abs(coord - clusters[-1]["coord"]) > self.coord_tol:
                clusters.append({"coord": coord, "count": 1, "segments": [(start, end)]})
            else:
                cluster = clusters[-1]
                cluster["segments"].append((start, end))
                count = cluster["count"] + 1
                cluster["coord"] = (cluster["coord"] * cluster["count"] + coord) / count
                cluster["count"] = count

        merged: dict[float, list[tuple[float, float]]] = {}
        for cluster in clusters:
            coord = float(cluster["coord"])
            intervals = self._merge_intervals(cluster["segments"])
            merged[coord] = intervals
        return merged

    def _merge_intervals(self, segments: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if not segments:
            return []
        sorted_segments = sorted((min(a, b), max(a, b)) for a, b in segments)
        merged = [[sorted_segments[0][0], sorted_segments[0][1]]]
        for start, end in sorted_segments[1:]:
            if start <= merged[-1][1] + self.coord_tol:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        return [(seg[0], seg[1]) for seg in merged]

    def _has_edge(self, intervals: list[tuple[float, float]], start: float, end: float) -> bool:
        for seg_start, seg_end in intervals:
            if seg_start <= start + self.coord_tol and seg_end >= end - self.coord_tol:
                return True
        return False
