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
        self.coord_tol = float(getattr(self.candidate_finder, "coord_tol", 0.5))

        a4_cfg = self.spec.a4_multipage.get("cluster_building", {})
        self.a4_gap_factor = float(a4_cfg.get("gap_threshold_factor", 0.5))

        outer_frame_cfg = self.spec.titleblock_extract.get("outer_frame", {})
        layer_priority = outer_frame_cfg.get("layer_priority", {})
        global_layers = layer_priority.get("global_layers")
        local_only_layers = layer_priority.get("local_only_layers")
        if not global_layers and not local_only_layers:
            layers = layer_priority.get("layers")
            if not layers:
                primary = layer_priority.get("primary_layer", "_TSZ-PLOT_MARK")
                secondary = layer_priority.get("secondary_layer", "0")
                layers = [primary, secondary]
            global_layers = list(layers)
            local_only_layers = []
        self.global_layers = [str(layer) for layer in (global_layers or []) if layer]
        self.local_only_layers = [str(layer) for layer in (local_only_layers or []) if layer]
        self.last_detection_stats: dict[str, object] = {}

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
            self.logger.info("锚点定位结束: dxf=%s 未找到锚点文本，转几何fallback", dxf_path.name)
            frames = self._locate_without_anchors(msp, dxf_path)
            self.last_detection_stats = {
                "anchors_total": 0,
                "resolved_after_global_layers": len(frames),
                "unresolved_before_local_layers": 0,
                "local_windows_total": 0,
                "local_window_hits_by_layer": {},
                "used_local_only_layers": [],
            }
            return frames

        self._anchor_scale_range = self._compute_anchor_scale_range(anchor_items)
        selected_by_anchor: dict[int, CandidateFrame] = {}
        candidates: list[CandidateFrame] = []
        seen_candidates: set[tuple[float, float, float, float, str, str]] = set()

        for layer in self.global_layers:
            layer_candidates = self._build_candidates_for_layers(msp, [layer])
            self._merge_candidates(candidates, layer_candidates, seen_candidates)
            self._resolve_anchor_matches(anchor_items, candidates, selected_by_anchor)
            if len(selected_by_anchor) >= len(anchor_items):
                break

        resolved_after_global = len(selected_by_anchor)
        unresolved_ids = [
            idx for idx in range(1, len(anchor_items) + 1) if idx not in selected_by_anchor
        ]
        local_windows = self._build_local_windows(anchor_items, unresolved_ids)
        local_window_hits_by_layer: dict[str, int] = {}
        used_local_only_layers: list[str] = []

        if unresolved_ids and self.local_only_layers:
            self.logger.info(
                "进入低优先局部补检: dxf=%s unresolved=%d windows=%d layers=%s",
                dxf_path.name,
                len(unresolved_ids),
                len(local_windows),
                ",".join(self.local_only_layers),
            )
            for layer in self.local_only_layers:
                layer_hits = 0
                layer_used = False
                for window_info in local_windows:
                    layer_candidates = self._build_candidates_for_layers(
                        msp,
                        [layer],
                        window=window_info["window"],
                        localize_line_rebuild=True,
                    )
                    if not layer_candidates:
                        continue
                    layer_used = True
                    self._merge_candidates(candidates, layer_candidates, seen_candidates)
                    before = len(selected_by_anchor)
                    self._resolve_anchor_matches(
                        anchor_items,
                        candidates,
                        selected_by_anchor,
                        anchor_ids=window_info["anchor_ids"],
                    )
                    layer_hits += len(selected_by_anchor) - before
                    if len(selected_by_anchor) >= len(anchor_items):
                        break
                if layer_used:
                    used_local_only_layers.append(layer)
                local_window_hits_by_layer[layer] = layer_hits
                if len(selected_by_anchor) >= len(anchor_items):
                    break

        frames: list[FrameMeta] = []
        used_candidates: set[tuple[float, float, float, float]] = set()
        for idx in sorted(selected_by_anchor):
            self._append_candidate_frame(selected_by_anchor[idx], dxf_path, frames, used_candidates)

        small5_templates = self._collect_size_templates(frames, "SMALL5")
        a4_local_windows_total = 0
        if small5_templates and self.local_only_layers:
            (
                a4_local_windows_total,
                a4_local_window_hits_by_layer,
                a4_used_local_only_layers,
            ) = self._expand_local_a4_neighbors(
                msp,
                candidates,
                small5_templates,
                seen_candidates,
            )
            for layer, hits in a4_local_window_hits_by_layer.items():
                local_window_hits_by_layer[layer] = local_window_hits_by_layer.get(layer, 0) + hits
            for layer in a4_used_local_only_layers:
                if layer not in used_local_only_layers:
                    used_local_only_layers.append(layer)
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
        self.last_detection_stats = {
            "anchors_total": len(anchor_items),
            "resolved_after_global_layers": resolved_after_global,
            "unresolved_before_local_layers": len(unresolved_ids),
            "local_windows_total": len(local_windows) + a4_local_windows_total,
            "local_window_hits_by_layer": local_window_hits_by_layer,
            "used_local_only_layers": used_local_only_layers,
        }
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
        candidates = self._build_candidates_for_layers(
            msp,
            self.global_layers + self.local_only_layers or self.candidate_finder.layer_order,
        )
        return candidates

    def _build_candidates_for_layers(
        self,
        msp,
        layers: list[str],
        *,
        window: BBox | None = None,
        localize_line_rebuild: bool = False,
    ) -> list[CandidateFrame]:
        candidates: list[CandidateFrame] = []
        if hasattr(self.candidate_finder, "find_rectangles_in_layers"):
            bboxes = self.candidate_finder.find_rectangles_in_layers(
                msp,
                layers,
                window=window,
                localize_line_rebuild=localize_line_rebuild,
            )
        else:
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

    def _locate_without_anchors(self, msp, dxf_path: Path) -> list[FrameMeta]:
        candidate_layers = list(self.global_layers)
        candidates = self._build_candidates_for_layers(msp, candidate_layers)
        if not candidates and self.local_only_layers:
            candidate_layers = list(self.local_only_layers)
            candidates = self._build_candidates_for_layers(msp, candidate_layers)
        frames: list[FrameMeta] = []
        used_candidates: set[tuple[float, float, float, float]] = set()
        selected = self._select_best_candidates(candidates)
        for cand in selected:
            self._append_candidate_frame(cand, dxf_path, frames, used_candidates)
        self.logger.info(
            "几何fallback完成: dxf=%s frames=%d layers=%s",
            dxf_path.name,
            len(frames),
            ",".join(candidate_layers),
        )
        return frames

    def _select_best_candidates(self, candidates: list[CandidateFrame]) -> list[CandidateFrame]:
        best_by_bbox: dict[tuple[float, float, float, float], CandidateFrame] = {}
        for cand in candidates:
            key = self._candidate_key(cand)
            best = best_by_bbox.get(key)
            if best is None or (cand.fit_error, cand.area) < (best.fit_error, best.area):
                best_by_bbox[key] = cand
        return list(best_by_bbox.values())

    def _candidate_signature(
        self, cand: CandidateFrame
    ) -> tuple[float, float, float, float, str, str]:
        bbox_key = self._candidate_key(cand)
        return (*bbox_key, cand.paper_variant_id, cand.roi_profile_id)

    def _merge_candidates(
        self,
        target: list[CandidateFrame],
        incoming: list[CandidateFrame],
        seen: set[tuple[float, float, float, float, str, str]],
    ) -> None:
        for cand in incoming:
            signature = self._candidate_signature(cand)
            if signature in seen:
                continue
            seen.add(signature)
            target.append(cand)

    def _resolve_anchor_matches(
        self,
        anchor_items: list[TextItem],
        candidates: list[CandidateFrame],
        selected_by_anchor: dict[int, CandidateFrame],
        *,
        anchor_ids: list[int] | None = None,
    ) -> None:
        for idx in anchor_ids or list(range(1, len(anchor_items) + 1)):
            if idx in selected_by_anchor:
                continue
            anchor_item = anchor_items[idx - 1]
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
            selected_by_anchor[idx] = selected
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

    def _build_local_windows(
        self,
        anchor_items: list[TextItem],
        unresolved_ids: list[int],
    ) -> list[dict[str, object]]:
        windows: list[dict[str, object]] = []
        for idx in unresolved_ids:
            anchor_item = anchor_items[idx - 1]
            for bbox in self._predict_outer_bboxes(anchor_item):
                merged = False
                for window_info in windows:
                    if window_info["window"].intersects(bbox):
                        window_info["window"] = self._union_bbox(window_info["window"], bbox)
                        window_info["anchor_ids"].append(idx)
                        merged = True
                        break
                if not merged:
                    windows.append({"window": bbox, "anchor_ids": [idx]})
        return windows

    def _expand_local_a4_neighbors(
        self,
        msp,
        candidates: list[CandidateFrame],
        templates: list[tuple[float, float]],
        seen_candidates: set[tuple[float, float, float, float, str, str]],
    ) -> tuple[int, dict[str, int], list[str]]:
        seeds = [
            cand
            for cand in candidates
            if cand.roi_profile_id == "SMALL5"
            and self._is_a4_candidate(cand)
            and self._bbox_matches_templates(cand.bbox, templates)
        ]
        if not seeds:
            return 0, {}, []

        processed: set[tuple[float, float, float, float]] = set()
        queued = {self._candidate_key(cand) for cand in seeds}
        queue = list(seeds)
        local_windows_total = 0
        hits_by_layer: dict[str, int] = {}
        used_layers: list[str] = []

        while queue:
            seed = queue.pop(0)
            seed_key = self._candidate_key(seed)
            if seed_key in processed:
                continue
            processed.add(seed_key)
            search_window = self._build_a4_neighbor_window(seed.bbox)
            local_windows_total += 1
            for layer in self.local_only_layers:
                layer_candidates = self._build_candidates_for_layers(
                    msp,
                    [layer],
                    window=search_window,
                    localize_line_rebuild=True,
                )
                filtered = [
                    cand
                    for cand in layer_candidates
                    if cand.roi_profile_id == "SMALL5"
                    and self._is_a4_candidate(cand)
                    and self._bbox_matches_templates(cand.bbox, templates)
                ]
                if not filtered:
                    continue
                if layer not in used_layers:
                    used_layers.append(layer)
                new_hits = 0
                for cand in filtered:
                    signature = self._candidate_signature(cand)
                    if signature in seen_candidates:
                        continue
                    seen_candidates.add(signature)
                    candidates.append(cand)
                    new_hits += 1
                    cand_key = self._candidate_key(cand)
                    if cand_key not in queued:
                        queue.append(cand)
                        queued.add(cand_key)
                if new_hits:
                    hits_by_layer[layer] = hits_by_layer.get(layer, 0) + new_hits

        return local_windows_total, hits_by_layer, used_layers

    def _predict_outer_bboxes(self, item: TextItem) -> list[BBox]:
        predicted: list[BBox] = []
        ref_x, ref_y = self._anchor_ref_point(item)
        for profile_id, calib in self._iter_calibrations():
            ref_cfg = calib.get("text_ref_in_anchor_roi_1to1", {})
            dx_right = float(ref_cfg.get("dx_right", 0.0))
            dy_bottom = float(ref_cfg.get("dy_bottom", 0.0))
            for candidate in self._iter_scale_candidates(item, calib):
                scale = candidate["scale"]
                roi_xmax = ref_x + dx_right * scale
                roi_ymin = ref_y - dy_bottom * scale
                anchor_rb = self._resolve_anchor_rb_offset(calib, candidate["use_project_override"])
                outer_xmax = roi_xmax + float(anchor_rb[0]) * scale
                outer_ymin = roi_ymin - float(anchor_rb[2]) * scale
                for paper_variant in self.paper_variants.values():
                    if paper_variant.profile != profile_id:
                        continue
                    bbox = BBox(
                        xmin=outer_xmax - paper_variant.W * scale,
                        ymin=outer_ymin,
                        xmax=outer_xmax,
                        ymax=outer_ymin + paper_variant.H * scale,
                    )
                    predicted.append(self._expand_search_window(bbox))
        return predicted

    def _iter_scale_candidates(self, item: TextItem, calib: dict) -> list[dict]:
        text_h = item.text_height
        if text_h is None and item.bbox is not None:
            text_h = item.bbox.height / 1.2
        if text_h is None:
            return []
        base_h = calib.get("text_height_1to1_mm")
        overrides = calib.get("text_height_1to1_mm_by_project", {})
        candidates: list[dict] = []
        if base_h:
            candidates.append(
                {"scale": float(text_h) / float(base_h), "use_project_override": False}
            )
        if self.project_no and isinstance(overrides, dict):
            override = overrides.get(self.project_no)
            if override:
                candidates.append(
                    {
                        "scale": float(text_h) / float(override),
                        "use_project_override": True,
                    }
                )
        if not candidates:
            return []
        if not self.anchor_scale_candidates:
            return candidates

        def score(scale: float) -> float:
            return min(abs(scale - c) / max(c, 1e-9) for c in self.anchor_scale_candidates)

        scored = [(score(c["scale"]), c) for c in candidates]
        scored.sort(key=lambda item: item[0])
        filtered = [cand for err, cand in scored if err <= self.anchor_scale_tol]
        return filtered if filtered else []

    def _anchor_ref_point(self, item: TextItem) -> tuple[float, float]:
        if (
            self.anchor_calibration.get("reference_point") == "text_bbox_right_bottom"
            and item.bbox is not None
        ):
            return item.bbox.xmax, item.bbox.ymin
        return item.x, item.y

    def _resolve_anchor_rb_offset(self, calib: dict, use_project_override: bool) -> list[float]:
        base = calib.get("anchor_roi_rb_offset_1to1", [0.0, 0.0, 0.0, 0.0])
        overrides = calib.get("anchor_roi_rb_offset_1to1_by_project", {})
        if use_project_override and self.project_no and isinstance(overrides, dict):
            override = overrides.get(self.project_no)
            if override is not None:
                return [float(v) for v in override]
        return [float(v) for v in base]

    def _expand_search_window(self, bbox: BBox) -> BBox:
        dx = max(bbox.width * self.roi_margin_percent, 2 * self.coord_tol)
        dy = max(bbox.height * self.roi_margin_percent, 2 * self.coord_tol)
        return BBox(
            xmin=bbox.xmin - dx,
            ymin=bbox.ymin - dy,
            xmax=bbox.xmax + dx,
            ymax=bbox.ymax + dy,
        )

    def _build_a4_neighbor_window(self, bbox: BBox) -> BBox:
        min_size = min(bbox.width, bbox.height)
        gap = self.a4_gap_factor * min_size
        expand_x = bbox.width + gap + 2 * self.coord_tol
        expand_y = bbox.height + gap + 2 * self.coord_tol
        return BBox(
            xmin=bbox.xmin - expand_x,
            ymin=bbox.ymin - expand_y,
            xmax=bbox.xmax + expand_x,
            ymax=bbox.ymax + expand_y,
        )

    @staticmethod
    def _union_bbox(left: BBox, right: BBox) -> BBox:
        return BBox(
            xmin=min(left.xmin, right.xmin),
            ymin=min(left.ymin, right.ymin),
            xmax=max(left.xmax, right.xmax),
            ymax=max(left.ymax, right.ymax),
        )

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
