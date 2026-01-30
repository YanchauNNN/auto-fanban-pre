"""
锚点校准定位器 - 通过锚点文本直推外框位置

流程：
1) 扫描锚点文本，获取字高与文本参考点
2) 根据1:1校准数据推算比例与锚点ROI
3) 反解外框右下角坐标
4) 在候选矩形中匹配最接近的外框
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ...interfaces import DetectionError
from ...models import BBox, FrameMeta, FrameRuntime
from .anchor_first_locator import AnchorFirstLocator, TextItem


@dataclass(frozen=True)
class CandidateFrame:
    bbox: BBox
    paper_variant_id: str
    sx: float
    sy: float
    roi_profile_id: str
    fit_error: float

    @property
    def area(self) -> float:
        return self.bbox.width * self.bbox.height


class AnchorCalibratedLocator:
    """基于锚点校准数据的图框定位器"""

    def __init__(
        self,
        spec,
        candidate_finder,
        paper_fitter,
        max_candidates: int | None = None,
    ) -> None:
        self.spec = spec
        self.candidate_finder = candidate_finder
        self.paper_fitter = paper_fitter
        self.paper_variants = self.spec.get_paper_variants()
        self.max_candidates = max_candidates

        anchor_cfg = self.spec.titleblock_extract.get("anchor", {})
        texts = anchor_cfg.get("search_text", [])
        if isinstance(texts, str):
            texts = [texts]
        self.anchor_texts = [t for t in texts if t]
        self.calibration = anchor_cfg.get("calibration", {})
        self.reference_point = self.calibration.get("reference_point", "text_bbox_right_bottom")

        tolerances = self.spec.titleblock_extract.get("tolerances", {})
        scale_mismatch = tolerances.get("scale_mismatch", {})
        self.scale_tol_rel = float(scale_mismatch.get("rel_tol", 0.02))
        self.rb_tol = 0.1

        outer_frame_cfg = self.spec.titleblock_extract.get("outer_frame", {})
        layer_priority = outer_frame_cfg.get("layer_priority", {})
        self.primary_layer = str(layer_priority.get("primary_layer", "_TSZ-PLOT_MARK"))
        self.secondary_layer = str(layer_priority.get("secondary_layer", "0"))
        self.primary_entities = set(
            layer_priority.get("primary_entities", ["LWPOLYLINE", "POLYLINE"])
        )
        self.secondary_entities = set(layer_priority.get("secondary_entities", ["LINE"]))

        a4_cfg = self.spec.a4_multipage.get("cluster_building", {})
        self.a4_gap_factor = float(a4_cfg.get("gap_threshold_factor", 0.5))

        self.logger = logging.getLogger(__name__)

    def locate_frames(self, msp, dxf_path: Path) -> list[FrameMeta]:
        """执行锚点直推定位，返回FrameMeta列表"""
        text_items = list(AnchorFirstLocator._iter_text_items(msp))
        anchor_items = [t for t in text_items if self._match_any_text(t.text, self.anchor_texts)]
        if not anchor_items:
            raise DetectionError(f"DETECT_FRAMES/ANCHOR_SCAN: 未找到锚点文本 dxf={dxf_path.name}")

        polylines = self._collect_polylines(msp)
        lines = self._collect_lines(msp)

        frames: list[FrameMeta] = []
        used_candidates: set[tuple[float, float, float, float]] = set()
        found_rb = False
        found_geom = False
        a4_candidates: list[CandidateFrame] | None = None
        a4_cluster_map: dict[tuple[float, float, float, float], list[CandidateFrame]] = {}

        for idx, anchor_item in enumerate(anchor_items, start=1):
            for profile_id, calib in self._iter_calibrations():
                scale = self._scale_from_text(anchor_item, calib)
                if scale is None:
                    continue
                found_rb = True
                outer_xmax, outer_ymin = self._outer_rb_from_anchor(anchor_item, scale, calib)

                matches = self._match_polylines(
                    polylines,
                    outer_xmax,
                    outer_ymin,
                    scale,
                    profile_id,
                )
                if not matches:
                    matches = self._match_lines(
                        lines,
                        outer_xmax,
                        outer_ymin,
                        scale,
                        profile_id,
                    )

                if not matches:
                    continue

                found_geom = True
                selected = min(matches, key=lambda c: (c.fit_error, c.area))
                self.logger.info(
                    "锚点直推: index=%d variant=%s sx=%.4f sy=%.4f profile=%s bbox=(%.3f,%.3f,%.3f,%.3f)",
                    idx,
                    selected.paper_variant_id,
                    selected.sx,
                    selected.sy,
                    selected.roi_profile_id,
                    selected.bbox.xmin,
                    selected.bbox.ymin,
                    selected.bbox.xmax,
                    selected.bbox.ymax,
                )
                self._append_candidate_frame(selected, dxf_path, frames, used_candidates)

                # A4扩展：加入同簇外框（无需锚点）
                if self._is_a4_candidate(selected):
                    if a4_candidates is None:
                        a4_candidates = self._build_a4_candidates(polylines)
                        a4_cluster_map = self._cluster_lookup(
                            self._build_a4_clusters(a4_candidates)
                        )
                    cluster = a4_cluster_map.get(self._candidate_key(selected), [])
                    for cand in cluster:
                        self._append_candidate_frame(cand, dxf_path, frames, used_candidates)

        if frames:
            return frames
        if not found_rb:
            raise DetectionError(f"DETECT_FRAMES/RB_LOCATE: 无法定位图框右下角 dxf={dxf_path.name}")
        if not found_geom:
            raise DetectionError(
                f"DETECT_FRAMES/GEOM_MATCH: RB附近无矩形/线段匹配 dxf={dxf_path.name}"
            )
        raise DetectionError(f"DETECT_FRAMES/GEOM_MATCH: 未找到可用图框 dxf={dxf_path.name}")

    def _find_matching_candidates(
        self,
        anchor_item: TextItem,
        candidates: list[CandidateFrame],
    ) -> list[tuple[CandidateFrame, float]]:
        matches: list[tuple[CandidateFrame, float]] = []
        for profile_id, calib in self._iter_calibrations():
            scale = self._scale_from_text(anchor_item, calib)
            if scale is None:
                continue
            outer_xmax, outer_ymin = self._outer_rb_from_anchor(anchor_item, scale, calib)
            pos_tol = max(2.0, 2.0 * scale)

            for cand in candidates:
                if cand.roi_profile_id != profile_id:
                    continue
                dx = abs(cand.bbox.xmax - outer_xmax)
                dy = abs(cand.bbox.ymin - outer_ymin)
                if dx > pos_tol or dy > pos_tol:
                    continue
                if not self._scale_close(cand, scale):
                    continue
                pos_error = max(dx, dy) / max(1.0, min(cand.bbox.width, cand.bbox.height))
                score = cand.fit_error + pos_error
                matches.append((cand, score))
        return matches

    def _iter_calibrations(self) -> Iterable[tuple[str, dict]]:
        for profile_id, calib in self.calibration.items():
            if profile_id in {"reference_point"}:
                continue
            if isinstance(calib, dict):
                yield profile_id, calib

    def _scale_from_text(self, item: TextItem, calib: dict) -> float | None:
        text_h = item.text_height
        if text_h is None and item.bbox is not None:
            text_h = item.bbox.height / 1.2
        if text_h is None:
            return None
        base_h = calib.get("text_height_1to1_mm")
        if not base_h:
            return None
        return float(text_h) / float(base_h)

    def _outer_rb_from_anchor(
        self, item: TextItem, scale: float, calib: dict
    ) -> tuple[float, float]:
        ref_x, ref_y = self._anchor_ref_point(item)
        ref_cfg = calib.get("text_ref_in_anchor_roi_1to1", {})
        dx_right = float(ref_cfg.get("dx_right", 0.0))
        dy_bottom = float(ref_cfg.get("dy_bottom", 0.0))
        roi_xmax = ref_x + dx_right * scale
        roi_ymin = ref_y - dy_bottom * scale

        anchor_rb = calib.get("anchor_roi_rb_offset_1to1", [0.0, 0.0, 0.0, 0.0])
        outer_xmax = roi_xmax + float(anchor_rb[0]) * scale
        outer_ymin = roi_ymin - float(anchor_rb[2]) * scale
        return outer_xmax, outer_ymin

    def _anchor_ref_point(self, item: TextItem) -> tuple[float, float]:
        if self.reference_point == "text_bbox_right_bottom" and item.bbox is not None:
            return item.bbox.xmax, item.bbox.ymin
        return item.x, item.y

    def _scale_close(self, cand: CandidateFrame, scale: float) -> bool:
        return (
            abs(cand.sx - scale) / max(scale, 1e-9) <= self.scale_tol_rel
            and abs(cand.sy - scale) / max(scale, 1e-9) <= self.scale_tol_rel
        )

    def _collect_polylines(self, msp) -> list[dict]:
        polylines: list[dict] = []
        for entity in msp:
            tp = entity.dxftype()
            if tp not in self.primary_entities:
                continue
            try:
                if entity.dxf.layer != self.primary_layer:
                    continue
            except Exception:
                continue
            if not self._is_polyline_closed(entity, tp):
                continue
            vertices = self._polyline_vertices(entity, tp)
            if not vertices:
                continue
            if not self._is_axis_aligned(vertices):
                continue
            bbox = self._bbox_from_vertices(vertices)
            polylines.append({"bbox": bbox, "vertices": vertices})
        return polylines

    def _collect_lines(self, msp) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        if "LINE" not in self.secondary_entities:
            return []
        lines: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for entity in msp.query("LINE"):
            try:
                if entity.dxf.layer != self.secondary_layer:
                    continue
            except Exception:
                continue
            start = entity.dxf.start
            end = entity.dxf.end
            lines.append(((float(start.x), float(start.y)), (float(end.x), float(end.y))))
        return lines

    def _match_polylines(
        self,
        polylines: list[dict],
        rb_x: float,
        rb_y: float,
        scale: float,
        profile_id: str,
    ) -> list[CandidateFrame]:
        matches: list[CandidateFrame] = []
        for item in polylines:
            if not self._any_vertex_near(item["vertices"], rb_x, rb_y):
                continue
            bbox = item["bbox"]
            if not self._bbox_matches_rb(bbox, rb_x, rb_y):
                continue
            matches.extend(self._fit_bbox_candidates(bbox, scale, profile_id))
        return matches

    def _match_lines(
        self,
        lines: list[tuple[tuple[float, float], tuple[float, float]]],
        rb_x: float,
        rb_y: float,
        scale: float,
        profile_id: str,
    ) -> list[CandidateFrame]:
        max_w = 0.0
        max_h = 0.0
        for p1, p2 in lines:
            p_near, p_other = self._pick_rb_endpoint(p1, p2, rb_x, rb_y)
            if p_near is None:
                continue
            x1, y1 = p_near
            x2, y2 = p_other
            dx = x2 - x1
            dy = y2 - y1
            if abs(dy) <= self.rb_tol:
                if x2 <= rb_x + self.rb_tol:
                    max_w = max(max_w, rb_x - x2)
            elif abs(dx) <= self.rb_tol:
                if y2 >= rb_y - self.rb_tol:
                    max_h = max(max_h, y2 - rb_y)
        if max_w <= 0 or max_h <= 0:
            return []
        bbox = BBox(xmin=rb_x - max_w, ymin=rb_y, xmax=rb_x, ymax=rb_y + max_h)
        return self._fit_bbox_candidates(bbox, scale, profile_id)

    def _fit_bbox_candidates(
        self, bbox: BBox, scale: float, profile_id: str
    ) -> list[CandidateFrame]:
        matches: list[CandidateFrame] = []
        for paper_id, sx, sy, fit_profile_id, error in self.paper_fitter.fit_all(
            bbox, self.paper_variants
        ):
            if fit_profile_id != profile_id:
                continue
            cand = CandidateFrame(
                bbox=bbox,
                paper_variant_id=paper_id,
                sx=sx,
                sy=sy,
                roi_profile_id=fit_profile_id,
                fit_error=error,
            )
            if not self._scale_close(cand, scale):
                continue
            matches.append(cand)
        return matches

    def _build_a4_candidates(self, polylines: list[dict]) -> list[CandidateFrame]:
        candidates: list[CandidateFrame] = []
        for item in polylines:
            bbox = item["bbox"]
            for paper_id, sx, sy, profile_id, error in self.paper_fitter.fit_all(
                bbox, self.paper_variants
            ):
                if "A4" not in paper_id:
                    continue
                candidates.append(
                    CandidateFrame(
                        bbox=bbox,
                        paper_variant_id=paper_id,
                        sx=sx,
                        sy=sy,
                        roi_profile_id=profile_id,
                        fit_error=error,
                    )
                )
        return candidates

    def _is_axis_aligned(self, vertices: list[tuple[float, float]]) -> bool:
        return self.candidate_finder._is_axis_aligned(vertices)

    def _is_polyline_closed(self, entity, tp: str) -> bool:
        if tp == "LWPOLYLINE":
            return bool(getattr(entity, "closed", False) or getattr(entity, "is_closed", False))
        if tp == "POLYLINE":
            return bool(getattr(entity, "is_closed", False) or getattr(entity, "closed", False))
        return False

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

    def _bbox_from_vertices(self, vertices: list[tuple[float, float]]) -> BBox:
        xs = [p[0] for p in vertices]
        ys = [p[1] for p in vertices]
        return BBox(xmin=min(xs), ymin=min(ys), xmax=max(xs), ymax=max(ys))

    def _any_vertex_near(
        self, vertices: list[tuple[float, float]], rb_x: float, rb_y: float
    ) -> bool:
        return any(self._point_near_rb(x, y, rb_x, rb_y) for x, y in vertices)

    def _bbox_matches_rb(self, bbox: BBox, rb_x: float, rb_y: float) -> bool:
        return abs(bbox.xmax - rb_x) <= self.rb_tol and abs(bbox.ymin - rb_y) <= self.rb_tol

    def _point_near_rb(self, x: float, y: float, rb_x: float, rb_y: float) -> bool:
        return abs(x - rb_x) <= self.rb_tol and abs(y - rb_y) <= self.rb_tol

    def _pick_rb_endpoint(
        self,
        p1: tuple[float, float],
        p2: tuple[float, float],
        rb_x: float,
        rb_y: float,
    ) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
        if self._point_near_rb(p1[0], p1[1], rb_x, rb_y):
            return p1, p2
        if self._point_near_rb(p2[0], p2[1], rb_x, rb_y):
            return p2, p1
        return None, None

    def _build_candidates(self, msp) -> list[CandidateFrame]:
        candidates: list[CandidateFrame] = []
        bboxes = self.candidate_finder.find_rectangles(msp)
        for bbox in bboxes:
            for paper_id, sx, sy, profile_id, error in self.paper_fitter.fit_all(
                bbox, self.paper_variants
            ):
                candidates.append(
                    CandidateFrame(
                        bbox=bbox,
                        paper_variant_id=paper_id,
                        sx=sx,
                        sy=sy,
                        roi_profile_id=profile_id,
                        fit_error=error,
                    )
                )

        candidates.sort(key=lambda c: c.area, reverse=True)
        if self.max_candidates:
            top_keys = {
                AnchorFirstLocator._bbox_key(b)
                for b in sorted(bboxes, key=lambda b: b.width * b.height, reverse=True)[
                    : self.max_candidates
                ]
            }
            candidates = [c for c in candidates if self._candidate_key(c) in top_keys]
        return candidates

    def _append_candidate_frame(
        self,
        cand: CandidateFrame,
        dxf_path: Path,
        frames: list[FrameMeta],
        used_candidates: set[tuple[float, float, float, float]],
    ) -> None:
        key = self._candidate_key(cand)
        if key in used_candidates:
            return
        used_candidates.add(key)
        frames.append(self._to_frame_meta(cand, dxf_path))

    def _to_frame_meta(self, cand: CandidateFrame, dxf_path: Path) -> FrameMeta:
        runtime = FrameRuntime(
            frame_id=str(self._uuid()),
            source_file=dxf_path,
            outer_bbox=cand.bbox,
            paper_variant_id=cand.paper_variant_id,
            sx=cand.sx,
            sy=cand.sy,
            geom_scale_factor=(cand.sx + cand.sy) / 2,
            roi_profile_id=cand.roi_profile_id,
        )
        return FrameMeta(runtime=runtime)

    @staticmethod
    def _uuid() -> str:
        import uuid

        return str(uuid.uuid4())

    @staticmethod
    def _candidate_key(cand: CandidateFrame) -> tuple[float, float, float, float]:
        return AnchorFirstLocator._bbox_key(cand.bbox)

    def _build_a4_clusters(self, a4_candidates: list[CandidateFrame]) -> list[list[CandidateFrame]]:
        if not a4_candidates:
            return []
        n = len(a4_candidates)
        adj = [[] for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                if self._are_neighbors(a4_candidates[i], a4_candidates[j]):
                    adj[i].append(j)
                    adj[j].append(i)
        visited = [False] * n
        clusters: list[list[CandidateFrame]] = []
        for i in range(n):
            if not visited[i]:
                cluster: list[CandidateFrame] = []
                self._dfs(i, adj, visited, a4_candidates, cluster)
                clusters.append(cluster)
        return clusters

    def _cluster_lookup(
        self, clusters: list[list[CandidateFrame]]
    ) -> dict[tuple[float, float, float, float], list[CandidateFrame]]:
        lookup: dict[tuple[float, float, float, float], list[CandidateFrame]] = {}
        for cluster in clusters:
            for cand in cluster:
                lookup[self._candidate_key(cand)] = cluster
        return lookup

    def _are_neighbors(self, c1: CandidateFrame, c2: CandidateFrame) -> bool:
        b1 = c1.bbox
        b2 = c2.bbox
        min_size = min(b1.width, b1.height, b2.width, b2.height)
        threshold = self.a4_gap_factor * min_size
        dx = max(0.0, max(b1.xmin, b2.xmin) - min(b1.xmax, b2.xmax))
        dy = max(0.0, max(b1.ymin, b2.ymin) - min(b1.ymax, b2.ymax))
        return dx < threshold and dy < threshold

    def _dfs(
        self,
        node: int,
        adj: list[list[int]],
        visited: list[bool],
        frames: list[CandidateFrame],
        cluster: list[CandidateFrame],
    ) -> None:
        visited[node] = True
        cluster.append(frames[node])
        for nxt in adj[node]:
            if not visited[nxt]:
                self._dfs(nxt, adj, visited, frames, cluster)

    @staticmethod
    def _is_a4_candidate(cand: CandidateFrame) -> bool:
        return "A4" in cand.paper_variant_id

    @staticmethod
    def _short_text(text: str, max_len: int = 60) -> str:
        if not text:
            return ""
        compact = " ".join(text.split())
        if len(compact) <= max_len:
            return compact
        return f"{compact[:max_len]}..."

    def _match_any_text(self, text: str, patterns: Iterable[str]) -> bool:
        normalized = AnchorFirstLocator._normalize_anchor(text)
        for pattern in patterns:
            if not pattern:
                continue
            if pattern.isascii():
                if pattern.upper() in normalized.upper():
                    return True
            else:
                if pattern in text:
                    return True
        return False
