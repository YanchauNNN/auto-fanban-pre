"""
锚点优先定位器 - 先找锚点文本，再反推图框外框

流程：
1) 扫描文本实体（含块内文字）找到“主锚点”文本
2) 基于锚点ROI + 纸张拟合反推外框候选
3) 在锚点ROI内确认“次锚点”文本，满足双命中
4) 若外框为A4，则按A4规则扩展同簇外框
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ...models import BBox, FrameMeta, FrameRuntime


@dataclass(frozen=True)
class TextItem:
    x: float
    y: float
    text: str
    bbox: BBox | None
    text_height: float | None
    source: str


@dataclass(frozen=True)
class CandidateFrame:
    bbox: BBox
    paper_variant_id: str
    sx: float
    sy: float
    roi_profile_id: str
    anchor_roi: BBox
    fit_error: float

    @property
    def area(self) -> float:
        return self.bbox.width * self.bbox.height


class AnchorFirstLocator:
    """锚点优先的图框定位器"""

    def __init__(
        self,
        spec,
        candidate_finder,
        paper_fitter,
        max_candidates: int | None = None,
        project_no: str | None = None,
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
        primary_text = anchor_cfg.get("primary_text")
        if primary_text:
            texts = [primary_text, *texts]
        self.anchor_texts = [t for t in texts if t]
        self.roi_field_name = anchor_cfg.get("roi_field_name", "锚点")
        self.match_policy = anchor_cfg.get("match_policy", "single_hit_same_roi")
        self.anchor_calibration = anchor_cfg.get("calibration", {})
        self.project_no = project_no
        scale_fit_cfg = self.spec.titleblock_extract.get("scale_fit", {})
        self.size_match_tol = float(scale_fit_cfg.get("uniform_scale_tol", 0.02))
        self.base10_template_min_coverage = 0.6
        scale_candidates = anchor_cfg.get("scale_candidates")
        if isinstance(scale_candidates, list) and scale_candidates:
            self.anchor_scale_candidates = [float(v) for v in scale_candidates]
        else:
            self.anchor_scale_candidates = [1, 2, 5, 10, 20, 25, 50, 100, 200]
        self._scale_candidate_set: set[int] = {int(c) for c in self.anchor_scale_candidates}
        self.anchor_scale_tol = float(anchor_cfg.get("scale_match_rel_tol", 0.1))
        self.scale_candidate_match_tol = float(
            scale_fit_cfg.get("scale_candidate_match_tol", 0.015)
        )
        self._anchor_scale_range: tuple[float, float] | None = None

        tolerances = self.spec.titleblock_extract.get("tolerances", {})
        self.roi_margin_percent = float(tolerances.get("roi_margin_percent", 0.0))

        a4_cfg = self.spec.a4_multipage.get("cluster_building", {})
        self.a4_gap_factor = float(a4_cfg.get("gap_threshold_factor", 0.5))

        self.logger = logging.getLogger(__name__)

    def locate_frames(self, msp, dxf_path: Path) -> list[FrameMeta]:
        """执行锚点驱动定位，返回FrameMeta列表"""
        text_items = list(self._iter_text_items(msp))
        anchor_items = [t for t in text_items if self._match_any_text(t.text, self.anchor_texts)]
        self.logger.info(
            "锚点扫描: dxf=%s texts=%d anchors=%d",
            dxf_path.name,
            len(text_items),
            len(anchor_items),
        )

        if not anchor_items:
            self.logger.info("锚点定位结束: dxf=%s 未找到锚点文本", dxf_path.name)
            return []

        self._anchor_scale_range = None
        candidates = self._build_candidates(msp)
        self.logger.info(
            "候选外框: dxf=%s candidates=%d",
            dxf_path.name,
            len(candidates),
        )
        if not candidates:
            self.logger.info("锚点定位结束: dxf=%s 未找到候选外框", dxf_path.name)
            return []

        frames: list[FrameMeta] = []
        used_candidates: set[tuple[float, float, float, float]] = set()

        for idx, anchor_item in enumerate(anchor_items, start=1):
            matches = self._find_matching_candidates(anchor_item, candidates)
            self.logger.info(
                "锚点匹配: index=%d x=%.3f y=%.3f matches=%d text=%s",
                idx,
                anchor_item.x,
                anchor_item.y,
                len(matches),
                self._short_text(anchor_item.text),
            )
            if not matches:
                continue

            selected = min(matches, key=lambda c: (c.fit_error, c.area))
            self.logger.info(
                "锚点->外框: index=%d variant=%s sx=%.4f sy=%.4f profile=%s bbox=(%.3f,%.3f,%.3f,%.3f)",
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

        small5_templates = self._collect_size_templates(frames, "SMALL5")
        a4_candidates = [
            c
            for c in candidates
            if c.roi_profile_id == "SMALL5"
            and self._bbox_matches_templates(c.bbox, small5_templates)
        ]
        a4_clusters = self._build_a4_clusters(a4_candidates)
        a4_cluster_map = self._cluster_lookup(a4_clusters)
        if a4_candidates:
            self.logger.info(
                "A4簇统计: dxf=%s clusters=%d a4_candidates=%d",
                dxf_path.name,
                len(a4_clusters),
                len(a4_candidates),
            )
        for frame in frames:
            if frame.runtime.roi_profile_id != "SMALL5":
                continue
            cluster = a4_cluster_map.get(self._bbox_key(frame.runtime.outer_bbox), [])
            if not cluster:
                continue
            for cand in cluster:
                self._append_candidate_frame(cand, dxf_path, frames, used_candidates)

        self.logger.info(
            "锚点定位完成: dxf=%s frames=%d",
            dxf_path.name,
            len(frames),
        )
        return frames

    def _find_matching_candidates(
        self,
        anchor_item: TextItem,
        candidates: list[CandidateFrame],
    ) -> list[CandidateFrame]:
        roi_matches: list[CandidateFrame] = []
        for cand in candidates:
            if self._text_in_roi(anchor_item, cand.anchor_roi):
                if self.match_policy == "single_hit_same_roi":
                    pass
                roi_matches.append(cand)
        return roi_matches

    def _compute_anchor_scale_range(
        self, anchor_items: list[TextItem]
    ) -> tuple[float, float] | None:
        scales: list[float] = []
        for item in anchor_items:
            for _profile_id, calib in self._iter_calibrations():
                scale = self._scale_from_text(item, calib)
                if scale:
                    scales.append(scale)
        if not scales:
            return None
        return min(scales), max(scales)

    def _iter_calibrations(self):
        for profile_id, calib in self.anchor_calibration.items():
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
        overrides = calib.get("text_height_1to1_mm_by_project", {})
        if self.project_no and isinstance(overrides, dict):
            override = overrides.get(self.project_no)
            if override:
                base_h = override
        if not base_h:
            return None
        return float(text_h) / float(base_h)

    @staticmethod
    def _polyline_vertices(entity, tp: str) -> list[tuple[float, float]]:
        vertices: list[tuple[float, float]] = []
        if tp == "LWPOLYLINE":
            for p in entity.get_points():
                vertices.append((float(p[0]), float(p[1])))
        elif tp == "POLYLINE":
            for v in entity.vertices:
                loc = v.dxf.location
                vertices.append((float(loc.x), float(loc.y)))
        return vertices

    @staticmethod
    def _bbox_from_vertices(vertices: list[tuple[float, float]]) -> BBox:
        xs = [p[0] for p in vertices]
        ys = [p[1] for p in vertices]
        return BBox(xmin=min(xs), ymin=min(ys), xmax=max(xs), ymax=max(ys))

    def _collect_size_templates(
        self, frames: list[FrameMeta], profile_id: str
    ) -> list[tuple[float, float]]:
        templates: list[tuple[float, float]] = []
        for frame in frames:
            if frame.runtime.roi_profile_id != profile_id:
                continue
            bbox = frame.runtime.outer_bbox
            templates.append((bbox.width, bbox.height))
        unique: list[tuple[float, float]] = []
        seen: set[tuple[float, float]] = set()
        for w, h in templates:
            key = (round(w, 3), round(h, 3))
            if key in seen:
                continue
            seen.add(key)
            unique.append((w, h))
        return unique

    def _bbox_matches_templates(self, bbox: BBox, templates: list[tuple[float, float]]) -> bool:
        if not templates:
            return False
        for tw, th in templates:
            if (
                abs(bbox.width - tw) / max(tw, 1e-9) <= self.size_match_tol
                and abs(bbox.height - th) / max(th, 1e-9) <= self.size_match_tol
            ):
                return True
        return False

    @staticmethod
    def _pick_candidate_profile(
        candidates: list[CandidateFrame], profile_id: str
    ) -> CandidateFrame | None:
        matches = [cand for cand in candidates if cand.roi_profile_id == profile_id]
        if not matches:
            return None
        return min(matches, key=lambda c: (c.fit_error, c.area))

    def _build_candidates(self, msp) -> list[CandidateFrame]:
        candidates: list[CandidateFrame] = []
        bboxes = self.candidate_finder.find_rectangles(msp)
        for bbox in bboxes:
            candidates.extend(self._build_candidates_for_bbox(bbox, use_scale_filter=False))

        candidates.sort(key=lambda c: c.area, reverse=True)
        if self.max_candidates:
            top_keys = {
                self._bbox_key(b)
                for b in sorted(bboxes, key=lambda b: b.width * b.height, reverse=True)[
                    : self.max_candidates
                ]
            }
            candidates = [c for c in candidates if self._candidate_key(c) in top_keys]
        return candidates

    def _scale_matches_candidate(self, scale: float) -> bool:
        """检查 geom_scale_factor 是否为有效的整数比例候选。

        规则（始终生效，不受 use_scale_filter 控制）：
        1. round(scale) 必须存在于 scale_candidates 集合中
        2. |scale - round(scale)| / round(scale) 须 <= scale_candidate_match_tol

        用途：过滤误匹配的内层矩形（如 97.336 不是标准比例）。
        """
        if not self._scale_candidate_set:
            return True
        nearest_int = round(scale)
        if nearest_int < 1:
            return False
        # 检查该整数是否为已知候选比例
        if nearest_int not in self._scale_candidate_set:
            return False
        # 检查与整数的相对偏差
        rel_err = abs(scale - nearest_int) / nearest_int
        return rel_err <= self.scale_candidate_match_tol

    def _build_candidates_for_bbox(
        self, bbox: BBox, *, use_scale_filter: bool = True
    ) -> list[CandidateFrame]:
        candidates: list[CandidateFrame] = []
        for paper_id, sx, sy, profile_id, error in self.paper_fitter.fit_all(
            bbox, self.paper_variants
        ):
            scale = (sx + sy) / 2.0
            # ① 强制校验：比例必须接近 scale_candidates 中的某个整数值
            if not self._scale_matches_candidate(scale):
                self.logger.debug(
                    "候选矩形比例 %.3f 不在 scale_candidates 中，跳过 paper=%s",
                    scale,
                    paper_id,
                )
                continue
            # ② 可选的锚点范围/候选列表精细过滤（RB 兼容模式）
            if use_scale_filter and self._anchor_scale_range:
                min_scale, max_scale = self._anchor_scale_range
                margin = self.anchor_scale_tol
                if scale < min_scale * (1 - margin) or scale > max_scale * (1 + margin):
                    continue
            elif use_scale_filter and self.anchor_scale_candidates:
                rel_err = min(abs(scale - c) / max(c, 1e-9) for c in self.anchor_scale_candidates)
                if rel_err > self.anchor_scale_tol:
                    continue
            profile = self.spec.get_roi_profile(profile_id)
            if not profile:
                continue
            rb_offset = self._get_anchor_rb_offset(profile_id, profile)
            if not rb_offset:
                continue
            anchor_roi = self._restore_roi(bbox, rb_offset, sx, sy)
            anchor_roi = self._expand_roi(anchor_roi, self.roi_margin_percent)
            candidates.append(
                CandidateFrame(
                    bbox=bbox,
                    paper_variant_id=paper_id,
                    sx=sx,
                    sy=sy,
                    roi_profile_id=profile_id,
                    anchor_roi=anchor_roi,
                    fit_error=error,
                )
            )
        return candidates

    def _get_anchor_rb_offset(self, profile_id: str, profile) -> list[float] | None:
        rb_offset = None
        try:
            rb_offset = profile.fields.get(self.roi_field_name)
        except Exception:
            rb_offset = None
        if rb_offset:
            return rb_offset
        calib = self.anchor_calibration.get(profile_id, {})
        if isinstance(calib, dict):
            rb_offset = calib.get("anchor_roi_rb_offset_1to1")
            overrides = calib.get("anchor_roi_rb_offset_1to1_by_project", {})
            if self.project_no and isinstance(overrides, dict):
                override = overrides.get(self.project_no)
                if override:
                    rb_offset = override
        if rb_offset:
            return [float(v) for v in rb_offset]
        return rb_offset

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
        bbox = cand.bbox
        vertices = [
            (float(bbox.xmin), float(bbox.ymin)),
            (float(bbox.xmax), float(bbox.ymin)),
            (float(bbox.xmax), float(bbox.ymax)),
            (float(bbox.xmin), float(bbox.ymax)),
        ]
        runtime = FrameRuntime(
            frame_id=str(self._uuid()),
            source_file=dxf_path,
            outer_bbox=bbox,
            outer_vertices=vertices,
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

    @staticmethod
    def _bbox_key(bbox: BBox) -> tuple[float, float, float, float]:
        return (
            round(bbox.xmin, 3),
            round(bbox.ymin, 3),
            round(bbox.xmax, 3),
            round(bbox.ymax, 3),
        )

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
    def _normalize_anchor(text: str) -> str:
        return "".join(ch for ch in (text or "") if not ch.isspace())

    @staticmethod
    def _short_text(text: str, max_len: int = 60) -> str:
        if not text:
            return ""
        compact = " ".join(text.split())
        if len(compact) <= max_len:
            return compact
        return f"{compact[:max_len]}..."

    def _match_any_text(self, text: str, patterns: Iterable[str]) -> bool:
        normalized = self._normalize_anchor(text)
        for pattern in patterns:
            if not pattern:
                continue
            if pattern.isascii():
                if pattern.upper() in normalized.upper():
                    return True
            else:
                if pattern in normalized:
                    return True
        return False

    def _text_in_roi(self, item: TextItem, roi: BBox) -> bool:
        return self._point_in_bbox(item.x, item.y, roi) or (
            item.bbox is not None and roi.intersects(item.bbox)
        )

    def _is_in_any_anchor_roi(self, item: TextItem, candidates: list[CandidateFrame]) -> bool:
        return any(self._text_in_roi(item, cand.anchor_roi) for cand in candidates)

    def _roi_has_text(self, items: list[TextItem], roi: BBox) -> bool:
        return any(self._text_in_roi(item, roi) for item in items)

    @staticmethod
    def _point_in_bbox(x: float, y: float, bbox: BBox) -> bool:
        return bbox.xmin <= x <= bbox.xmax and bbox.ymin <= y <= bbox.ymax

    @staticmethod
    def _restore_roi(outer_bbox: BBox, rb_offset: list[float], sx: float, sy: float) -> BBox:
        dx_right, dx_left, dy_bottom, dy_top = rb_offset
        return BBox(
            xmin=outer_bbox.xmax - dx_left * sx,
            xmax=outer_bbox.xmax - dx_right * sx,
            ymin=outer_bbox.ymin + dy_bottom * sy,
            ymax=outer_bbox.ymin + dy_top * sy,
        )

    @staticmethod
    def _expand_roi(roi: BBox, margin_percent: float) -> BBox:
        if margin_percent <= 0:
            return roi
        dx = roi.width * margin_percent
        dy = roi.height * margin_percent
        return BBox(
            xmin=roi.xmin - dx,
            ymin=roi.ymin - dy,
            xmax=roi.xmax + dx,
            ymax=roi.ymax + dy,
        )

    @staticmethod
    def _iter_text_items(msp) -> Iterable[TextItem]:
        def add_text_entity(e, src: str) -> TextItem | None:
            tp = e.dxftype()
            if tp == "TEXT":
                text = (e.dxf.text or "").strip()
                p = e.dxf.insert
                x, y = float(p.x), float(p.y)
                height = float(getattr(e.dxf, "height", 2.5) or 2.5)
                bbox = AnchorFirstLocator._bbox_from_text(
                    text=text,
                    x=x,
                    y=y,
                    height=height,
                    halign=int(getattr(e.dxf, "halign", 0) or 0),
                    valign=int(getattr(e.dxf, "valign", 0) or 0),
                )
                return TextItem(
                    x=x,
                    y=y,
                    text=text,
                    bbox=bbox,
                    text_height=height,
                    source=src,
                )
            if tp == "MTEXT":
                try:
                    text = (e.plain_text() or "").strip()
                except Exception:
                    text = (e.text or "").strip()
                p = e.dxf.insert
                x, y = float(p.x), float(p.y)
                bbox = AnchorFirstLocator._bbox_from_mtext(e, text, x, y)
                try:
                    height = float(getattr(e.dxf, "char_height", getattr(e.dxf, "height", 2.5)))
                except Exception:
                    height = 2.5
                return TextItem(
                    x=x,
                    y=y,
                    text=text,
                    bbox=bbox,
                    text_height=height,
                    source=src,
                )
            if tp == "ATTRIB":
                text = (e.dxf.text or "").strip()
                p = e.dxf.insert
                x, y = float(p.x), float(p.y)
                height = float(getattr(e.dxf, "height", 2.5) or 2.5)
                bbox = AnchorFirstLocator._bbox_from_text(
                    text=text,
                    x=x,
                    y=y,
                    height=height,
                    halign=int(getattr(e.dxf, "halign", 0) or 0),
                    valign=int(getattr(e.dxf, "valign", 0) or 0),
                )
                return TextItem(
                    x=x,
                    y=y,
                    text=text,
                    bbox=bbox,
                    text_height=height,
                    source=src,
                )
            return None

        def walk_entity(ent, src_prefix: str, depth: int) -> Iterable[TextItem]:
            if depth > 8:
                return
            tp = ent.dxftype()
            if tp in {"TEXT", "MTEXT", "ATTRIB"}:
                item = add_text_entity(ent, f"{src_prefix}:{tp}")
                if item and item.text:
                    yield item
                return
            if tp == "INSERT":
                try:
                    for a in ent.attribs:
                        item = add_text_entity(a, f"{src_prefix}:attrib")
                        if item and item.text:
                            yield item
                except Exception:
                    pass
                try:
                    for ve in ent.virtual_entities():
                        yield from walk_entity(ve, f"{src_prefix}:virtual", depth + 1)
                except Exception:
                    pass

        for e in msp:
            yield from walk_entity(e, "msp", 0)

    @staticmethod
    def _bbox_from_text(
        *, text: str, x: float, y: float, height: float, halign: int, valign: int
    ) -> BBox:
        s0 = (text or "").replace(" ", "")
        w = max(1, len(s0)) * height * 0.6
        hh = height * 1.2
        if halign == 1:
            xmin, xmax = x - w / 2, x + w / 2
        elif halign == 2:
            xmin, xmax = x - w, x
        else:
            xmin, xmax = x, x + w
        if valign == 3:
            ymin, ymax = y - hh, y
        elif valign == 2:
            ymin, ymax = y - hh / 2, y + hh / 2
        else:
            ymin, ymax = y, y + hh
        return BBox(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax)

    @staticmethod
    def _bbox_from_mtext(e, text: str, x: float, y: float) -> BBox:
        try:
            char_h = float(getattr(e.dxf, "char_height", getattr(e.dxf, "height", 2.5)))
        except Exception:
            char_h = 2.5
        lines = [ln for ln in (text or "").splitlines() if ln.strip()] or [text]
        n_lines = max(1, len(lines))
        try:
            width = float(getattr(e.dxf, "width", 0.0) or 0.0)
        except Exception:
            width = 0.0
        if width <= 0:
            width = max(len(ln) for ln in lines) * char_h * 0.6
        height = n_lines * char_h * 1.2
        ap = int(getattr(e.dxf, "attachment_point", 1) or 1)
        if ap in (1, 2, 3):  # top
            ymax = y
            ymin = y - height
        elif ap in (4, 5, 6):  # middle
            ymin = y - height / 2
            ymax = y + height / 2
        else:  # bottom
            ymin = y
            ymax = y + height
        if ap in (1, 4, 7):  # left
            xmin = x
            xmax = x + width
        elif ap in (2, 5, 8):  # center
            xmin = x - width / 2
            xmax = x + width / 2
        else:  # right
            xmin = x - width
            xmax = x
        return BBox(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax)
