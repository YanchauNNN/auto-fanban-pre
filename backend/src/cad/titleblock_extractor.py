"""
图签提取器 - 从图框中提取字段

职责：
1. 根据ROI profile还原各字段的ROI区域
2. 提取ROI内的文本
3. 解析字段值（internal_code/external_code/title等）

依赖：
- ezdxf: DXF解析
- 参数规范.yaml: roi_profiles/field_definitions

测试要点：
- test_roi_restore: ROI坐标还原
- test_extract_internal_code: 内部编码提取
- test_extract_external_code: 外部编码提取（19位）
- test_extract_title_bilingual: 中英文标题分流
- test_extract_page_info: 张数解析（共N张第M张）
- test_extract_revision_status_date: 版次/状态/日期（取列内最高y）
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

import ezdxf

from ..config import load_spec
from ..interfaces import ExtractionError, ITitleblockExtractor
from ..models import BBox, FrameMeta, TitleblockFields


@dataclass(frozen=True)
class TextItem:
    x: float
    y: float
    text: str
    bbox: BBox | None
    text_height: float | None
    source: str
    halign: int | None = None
    valign: int | None = None
    attachment_point: int | None = None


class TitleblockExtractor(ITitleblockExtractor):
    """图签提取器实现"""

    STATUS_MISSING_FLAG = "状态为空"

    def __init__(self, spec_path: str | None = None):
        self.spec = load_spec(spec_path) if spec_path else load_spec()
        self.field_defs = self.spec.get_field_definitions()
        anchor_cfg = self.spec.titleblock_extract.get("anchor", {})
        anchor_texts = anchor_cfg.get("search_text", [])
        if isinstance(anchor_texts, str):
            anchor_texts = [anchor_texts]
        primary_text = anchor_cfg.get("primary_text")
        if primary_text:
            anchor_texts = [primary_text, *anchor_texts]
        any_of = anchor_cfg.get("search_text_any_of")
        if isinstance(any_of, list):
            anchor_texts.extend(any_of)
        self.anchor_texts = [t for t in anchor_texts if t]
        self.anchor_roi_field_name = anchor_cfg.get("roi_field_name", "锚点")
        self.anchor_calibration = anchor_cfg.get("calibration", {})
        tolerances = self.spec.titleblock_extract.get("tolerances", {})
        text_grouping = tolerances.get("text_grouping", {})
        self.roi_margin_percent = float(tolerances.get("roi_margin_percent", 0.0))
        self.y_cluster_abs = float(text_grouping.get("y_cluster_abs", 1.0))
        self.line_join = str(text_grouping.get("line_join", "\n"))
        scale_mismatch = tolerances.get("scale_mismatch", {})
        self.scale_tol_abs = float(scale_mismatch.get("abs_tol", 0.5))
        self.scale_tol_rel = float(scale_mismatch.get("rel_tol", 0.02))
        self.scale_mismatch_flag = str(scale_mismatch.get("flag_name", "比例不一致"))
        self.point_only_fields = {"revision", "status", "date", "page_info"}
        self._text_item_cache: dict[tuple[str, int, int], list[TextItem]] = {}
        self.project_no: str | None = None

    def set_project_no(self, project_no: str | None) -> None:
        normalized = str(project_no).strip() if project_no is not None else ""
        self.project_no = normalized or None

    def extract_fields(self, dxf_path: Path, frame: FrameMeta) -> FrameMeta:
        """提取单个图框的图签字段"""
        if not dxf_path.exists():
            raise ExtractionError(f"DXF文件不存在: {dxf_path}")

        text_items = self._load_text_items(dxf_path)

        profile_id = frame.runtime.roi_profile_id or "BASE10"
        profile = self.spec.get_roi_profile(profile_id)
        if not profile:
            frame.add_flag("ROI配置缺失")
            return frame

        if self._is_a4_frame(frame):
            if self.anchor_texts and self._frame_has_anchor_text(
                text_items, frame, profile, profile_id
            ):
                pass
            else:
                self._extract_a4_page_marker(frame, text_items)
                return frame
        elif self.anchor_texts and not self._frame_has_anchor_text(
            text_items, frame, profile, profile_id
        ):
            self._extract_a4_page_marker(frame, text_items)
            if frame.titleblock.internal_code and frame.titleblock.page_index:
                return frame
            frame.add_flag("未命中锚点文本")
            return frame

        raw_extracts: dict[str, Any] = {}
        fields = TitleblockFields()
        claimed_item_ids: set[int] = set()

        for field_key, field_def in self.field_defs.items():
            roi_name = field_def.roi
            if not roi_name:
                continue
            rb_offset = profile.fields.get(roi_name)
            if rb_offset is None:
                continue

            roi = self._restore_roi(
                frame.runtime.outer_bbox,
                rb_offset,
                frame.runtime.sx or 1.0,
                frame.runtime.sy or 1.0,
            )
            margin = 0.0 if field_key in self.point_only_fields else self.roi_margin_percent
            roi = self._expand_roi(roi, margin)
            roi_items = self._claim_items_in_roi(text_items, roi, claimed_item_ids)

            if roi_name not in raw_extracts:
                raw_extracts[roi_name] = [self._text_item_to_dict(t) for t in roi_items]

            parse_cfg = field_def.parse or {}
            parse_type = str(parse_cfg.get("type") or "text")

            if parse_type == "bilingual_split" or field_key == "title":
                title_cn, title_en = self._parse_title_bilingual(roi_items)
                if title_cn:
                    fields.title_cn = title_cn
                if title_en:
                    fields.title_en = title_en
                continue

            if parse_type == "page_info_auto" or field_key == "page_info":
                page_total, page_index = self._parse_page_info(
                    roi_items,
                    parse_cfg,
                    total_then_index_tokens=self._uses_001_homepage_page_info_order(
                        frame,
                        fields,
                    ),
                )
                if page_total is not None:
                    fields.page_total = page_total
                if page_index is not None:
                    fields.page_index = page_index
                continue

            if parse_type == "regex_multi" and field_key == "internal_code":
                internal_code, album_code = self._parse_internal_code(roi_items, parse_cfg)
                if internal_code:
                    fields.internal_code = internal_code
                if album_code:
                    fields.album_code = album_code
                continue

            if parse_type in {"docno_fixed19", "docno_plus_fixed19"} and field_key == "external_code":
                external_code = self._parse_external_code(roi_items, parse_cfg)
                if external_code:
                    fields.external_code = external_code
                continue

            if field_key == "subitem_no":
                value = self._parse_subitem_no(roi_items, internal_code=fields.internal_code)
                if value:
                    fields.subitem_no = value
                continue

            if parse_type == "regex":
                value, extras = self._parse_regex(roi_items, parse_cfg)
                if value and hasattr(fields, field_key):
                    setattr(fields, field_key, value)
                if field_key == "scale_text":
                    if value:
                        fields.scale_text = value
                    if extras.get("scale_denominator") is not None:
                        fields.scale_denominator = extras["scale_denominator"]
                continue

            if parse_type == "pick_top_by_y":
                value = self._pick_top_by_y(
                    roi_items,
                    candidate_pattern=parse_cfg.get("candidate_pattern"),
                )
                if value and hasattr(fields, field_key):
                    setattr(fields, field_key, value)
                continue

            if parse_type in {"text", "text_or_lexicon", "text_multiline"}:
                value = self._parse_text(roi_items)
                if value and hasattr(fields, field_key):
                    setattr(fields, field_key, value)
                continue

            # fallback: treat as text
            value = self._parse_text(roi_items)
            if value and hasattr(fields, field_key):
                setattr(fields, field_key, value)

        frame.titleblock = fields
        frame.raw_extracts = raw_extracts
        self._validate_required_status(frame)
        self._check_scale_mismatch(frame)
        return frame

    def _validate_required_status(self, frame: FrameMeta) -> None:
        if str(frame.titleblock.status or "").strip():
            return
        frame.add_flag(self.STATUS_MISSING_FLAG)

    def _load_text_items(self, dxf_path: Path) -> list[TextItem]:
        resolved = dxf_path.resolve()
        stat = resolved.stat()
        cache_key = (str(resolved), stat.st_mtime_ns, stat.st_size)
        cached = self._text_item_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            doc = ezdxf.readfile(str(resolved))
        except Exception as e:
            raise ExtractionError(f"DXF解析失败: {e}") from e

        text_items = list(self._iter_text_items(doc.modelspace()))
        self._text_item_cache = {cache_key: text_items}
        return text_items

    @staticmethod
    def _is_a4_frame(frame: FrameMeta) -> bool:
        paper_id = (frame.runtime.paper_variant_id or "").upper()
        return "A4" in paper_id

    def _get_anchor_rb_offset(self, profile_id: str, profile) -> list[float] | None:
        rb_offset = None
        if self.anchor_roi_field_name:
            rb_offset = profile.fields.get(self.anchor_roi_field_name)
        if rb_offset:
            return rb_offset
        calib = self.anchor_calibration.get(profile_id, {})
        if isinstance(calib, dict):
            rb_offset = calib.get("anchor_roi_rb_offset_1to1")
        if rb_offset:
            return [float(v) for v in rb_offset]
        return None

    def _frame_has_anchor_text(
        self,
        items: list[TextItem],
        frame: FrameMeta,
        profile,
        profile_id: str,
    ) -> bool:
        rb_offset = self._get_anchor_rb_offset(profile_id, profile)
        if rb_offset is None:
            return False
        roi = self._restore_roi(
            frame.runtime.outer_bbox,
            rb_offset,
            frame.runtime.sx or 1.0,
            frame.runtime.sy or 1.0,
        )
        roi = self._expand_roi(roi, self.roi_margin_percent)
        sx = frame.runtime.sx or 1.0
        sy = frame.runtime.sy or 1.0
        scale = (sx + sy) / 2.0
        tol_base = float(getattr(profile, "tolerance", 0.5))
        margin_tol = min(roi.width, roi.height) * self.roi_margin_percent
        tol = max(tol_base * scale, margin_tol, 1.0)
        roi_items = [item for item in items if self._item_in_roi(item, roi)]
        best_dist = None
        for item in items:
            if not self._match_any_text(item.text, self.anchor_texts):
                continue
            dist = self._point_to_bbox_distance(item.x, item.y, roi)
            best_dist = dist if best_dist is None else min(best_dist, dist)
        if best_dist is not None and best_dist <= tol:
            return True
        return self._match_joined_anchor_text(roi_items)

    @staticmethod
    def _point_to_bbox_distance(x: float, y: float, bbox: BBox) -> float:
        dx = 0.0
        if x < bbox.xmin:
            dx = bbox.xmin - x
        elif x > bbox.xmax:
            dx = x - bbox.xmax
        dy = 0.0
        if y < bbox.ymin:
            dy = bbox.ymin - y
        elif y > bbox.ymax:
            dy = y - bbox.ymax
        return (dx * dx + dy * dy) ** 0.5

    def _extract_a4_page_marker(self, frame: FrameMeta, items: list[TextItem]) -> None:
        """提取无完整图签页面右上角页码/001标记，不做完整titleblock字段解析。"""
        rb_offset = [0.0, 120.0, 255.0, 295.0]
        roi = self._restore_roi(
            frame.runtime.outer_bbox,
            rb_offset,
            frame.runtime.sx or 1.0,
            frame.runtime.sy or 1.0,
        )
        roi_items = [t for t in items if self._item_in_roi(t, roi)]
        marker_items = self._dedupe_text_items(
            [*roi_items, *self._fallback_page_marker_items(frame, items)]
        )
        frame.raw_extracts = {
            "A4_page_marker": [self._text_item_to_dict(t) for t in marker_items]
        }
        page_total, page_index = self._parse_page_marker_from_text(marker_items)
        marker_internal_code, marker_revision = self._parse_a4_marker_identity(marker_items)
        if page_index is None:
            page_total, page_index = self._fallback_a4_page_marker(frame, items)
        if page_total is not None:
            frame.titleblock.page_total = page_total
        if page_index is not None:
            frame.titleblock.page_index = page_index
        if marker_internal_code:
            frame.titleblock.internal_code = marker_internal_code
        if marker_revision:
            frame.titleblock.revision = marker_revision
        if marker_internal_code or marker_revision:
            frame.raw_extracts["A4_page_marker_meta"] = {
                "internal_code": marker_internal_code,
                "revision": marker_revision,
            }

    @staticmethod
    def _dedupe_text_items(items: list[TextItem]) -> list[TextItem]:
        deduped: list[TextItem] = []
        seen: set[tuple[str, float, float]] = set()
        for item in items:
            key = (
                str(item.text or ""),
                round(float(item.x), 3),
                round(float(item.y), 3),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _match_joined_anchor_text(self, items: list[TextItem]) -> bool:
        if len(items) < 2 or not self.anchor_texts:
            return False
        candidates: list[str] = []
        joined = self._join_text(items)
        if joined:
            candidates.append(joined)
        lines = self._extract_title_lines(items)
        if lines:
            candidates.append(self.line_join.join(lines))
            candidates.append(" ".join(lines))
            candidates.append("".join(lines))
        seen: set[str] = set()
        for candidate in candidates:
            normalized = self._normalize_spaces(candidate)
            if not normalized:
                continue
            dedupe_key = self._normalize_anchor(normalized)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            if self._match_any_text(normalized, self.anchor_texts):
                return True
        return False

    def _parse_page_marker_from_text(
        self, items: list[TextItem]
    ) -> tuple[int | None, int | None]:
        labeled_total, labeled_index = self._parse_labeled_page_info_from_lines(items)
        if labeled_total is not None or labeled_index is not None:
            return labeled_total, labeled_index

        joined = self._join_text(items)
        if joined:
            m = re.search(r"rolls\s*(\d+)\s*of\s*(\d+)", joined, flags=re.IGNORECASE)
            if m:
                idx_raw, total_raw = m.group(1), m.group(2)
                idx = int(idx_raw) if idx_raw.isdigit() else None
                total = int(total_raw) if total_raw.isdigit() else None
                return total, idx
            m = re.search(r"(\d+)\s*of\s*(\d+)", joined, flags=re.IGNORECASE)
            if m:
                idx_raw, total_raw = m.group(1), m.group(2)
                idx = int(idx_raw) if idx_raw.isdigit() else None
                total = int(total_raw) if total_raw.isdigit() else None
                return total, idx
            m = re.search(r"共\s*(\d+)\s*张\s*第\s*([0-9Xx]+)\s*张", joined)
            if m:
                total_raw, idx_raw = m.group(1), m.group(2)
                total = int(total_raw) if total_raw.isdigit() else None
                idx = 1 if idx_raw.upper() == "X" else int(idx_raw) if idx_raw.isdigit() else None
                return total, idx
            m = re.search(r"第\s*([0-9Xx]+)\s*张", joined)
            if m:
                idx_raw = m.group(1)
                idx = 1 if idx_raw.upper() == "X" else int(idx_raw) if idx_raw.isdigit() else None
                return None, idx
        fragmented_total, fragmented_index = self._parse_fragmented_page_marker(items)
        if fragmented_index is not None:
            return fragmented_total, fragmented_index
        return None, None

    def _parse_fragmented_page_marker(
        self, items: list[TextItem]
    ) -> tuple[int | None, int | None]:
        pairs: list[tuple[int, int]] = []
        for label in items:
            if not self._is_page_marker_label(label.text):
                continue
            tokens = self._collect_page_marker_tokens(label, items)
            if len(tokens) < 2:
                continue
            idx_raw, total_raw = tokens[0], tokens[1]
            total = int(total_raw) if total_raw.isdigit() else None
            idx = 1 if idx_raw.upper() == "X" else int(idx_raw) if idx_raw.isdigit() else None
            if total is None or idx is None:
                continue
            pairs.append((total, idx))
        if not pairs:
            return None, None
        (page_total, page_index), _ = Counter(pairs).most_common(1)[0]
        return page_total, page_index

    @classmethod
    def _is_page_marker_label(cls, text: str) -> bool:
        compact = cls._strip_all_whitespace(text).upper()
        if not compact:
            return False
        if re.fullmatch(r"\u7b2c[0-9Xx]*\u5f20\u5171[0-9Xx]*\u5f20", compact):
            return True
        return re.fullmatch(r"PAGE[0-9Xx]*OF[0-9Xx]*", compact) is not None

    def _collect_page_marker_tokens(
        self, label: TextItem, items: list[TextItem]
    ) -> list[str]:
        _, lymin, _, lymax = self._item_span(label)
        label_height = max(1.0, lymax - lymin)
        label_anchor_x = label.x
        candidates: list[tuple[float, float, str]] = []
        for item in items:
            if item is label:
                continue
            token = self._normalize_page_marker_token(item.text)
            if token is None:
                continue
            ixmin, iymin, ixmax, iymax = self._item_span(item)
            if ixmin <= label_anchor_x:
                continue
            margin = max(6.0, 0.2 * label_height)
            if iymax < lymin - margin or iymin > lymax + margin:
                continue
            x_center = (ixmin + ixmax) / 2.0
            width = max(1.0, ixmax - ixmin)
            candidates.append((x_center, width, token))
        if len(candidates) < 2:
            return []
        candidates.sort(key=lambda entry: entry[0])
        widths = sorted(width for _, width, _ in candidates)
        width_mid = widths[len(widths) // 2]
        cluster_tol = max(10.0, min(40.0, width_mid * 1.5))
        clusters: list[list[tuple[float, str]]] = []
        for x_center, _, token in candidates:
            if not clusters or abs(clusters[-1][-1][0] - x_center) > cluster_tol:
                clusters.append([(x_center, token)])
            else:
                clusters[-1].append((x_center, token))
        collapsed: list[str] = []
        for cluster in clusters:
            token_counts = Counter(token for _, token in cluster)
            collapsed.append(token_counts.most_common(1)[0][0])
        return collapsed[:2]

    @staticmethod
    def _normalize_page_marker_token(text: str) -> str | None:
        compact = TitleblockExtractor._clean_alnum((text or "").upper())
        if not compact:
            return None
        if compact == "X" or compact.isdigit():
            return compact
        return None

    @staticmethod
    def _item_span(item: TextItem) -> tuple[float, float, float, float]:
        if item.bbox is not None:
            return item.bbox.xmin, item.bbox.ymin, item.bbox.xmax, item.bbox.ymax
        height = max(1.0, float(item.text_height or 0.0) or 1.0)
        return item.x, item.y, item.x, item.y + height

    def _parse_a4_marker_identity(
        self, items: list[TextItem]
    ) -> tuple[str | None, str | None]:
        pattern = re.compile(
            r"(?P<code>[A-Z0-9]{7}-[A-Z0-9]{5}-[0-9]{3})"
            r"\s*(?:\(\s*(?P<rev_paren>[A-Z0-9]+)\s*\)|[:：]\s*(?P<rev_colon>[A-Z0-9]+))?",
            flags=re.IGNORECASE,
        )
        for cand in self._candidate_strings(items):
            match = pattern.search(cand.upper())
            if not match:
                continue
            revision = match.group("rev_paren") or match.group("rev_colon")
            return match.group("code"), revision.upper() if revision else None
        return None, None

    def _fallback_a4_page_marker(
        self, frame: FrameMeta, items: list[TextItem]
    ) -> tuple[int | None, int | None]:
        outer = frame.runtime.outer_bbox
        width = max(1e-6, outer.width)
        height = max(1e-6, outer.height)
        # 允许 5% 的边界容差，但必须在图框附近（防止匹配到其他图框的文本）
        margin_x = width * 0.05
        margin_y = height * 0.05
        candidates: list[tuple[float, TextItem]] = []
        for item in items:
            if not item.text:
                continue
            # 首先确保文本在当前图框范围内（含容差）
            if not (outer.xmin - margin_x <= item.x <= outer.xmax + margin_x
                    and outer.ymin - margin_y <= item.y <= outer.ymax + margin_y):
                continue
            xnorm = (item.x - outer.xmin) / width
            ynorm = (item.y - outer.ymin) / height
            if xnorm < 0.60 or ynorm < 0.85:
                continue
            bonus = 1.0 if re.search(r"第\s*[0-9Xx]+\s*张", item.text) else 0.0
            score = 2 * xnorm + 2 * ynorm + bonus
            candidates.append((score, item))
        if not candidates:
            return None, None
        _, best = max(candidates, key=lambda t: t[0])
        text = (best.text or "").strip()
        m = re.search(r"第\s*([0-9Xx]+)\s*张", text)
        if m:
            idx_raw = m.group(1)
            idx = 1 if idx_raw.upper() == "X" else int(idx_raw) if idx_raw.isdigit() else None
            return None, idx
        cleaned = self._clean_alnum(text.upper())
        if cleaned.isdigit():
            return None, int(cleaned)
        return None, None

    def _fallback_page_marker_items(
        self,
        frame: FrameMeta,
        items: list[TextItem],
    ) -> list[TextItem]:
        outer = frame.runtime.outer_bbox
        width = max(1e-6, outer.width)
        height = max(1e-6, outer.height)
        marker_items: list[TextItem] = []
        for item in items:
            text = self._normalize_spaces(item.text or "")
            if not text:
                continue
            if not (outer.xmin <= item.x <= outer.xmax and outer.ymin <= item.y <= outer.ymax):
                continue
            xnorm = (item.x - outer.xmin) / width
            ynorm = (item.y - outer.ymin) / height
            if xnorm < 0.55 or ynorm < 0.85:
                continue
            compact = self._strip_all_whitespace(text).upper()
            if (
                re.search(r"[A-Z0-9]{7}-[A-Z0-9]{5}-001", compact, flags=re.IGNORECASE)
                or "PAGE" in compact
                or "OF" in compact
                or "第" in compact
                or "共" in compact
                or "张" in compact
            ):
                marker_items.append(item)
        marker_items.sort(key=lambda item: (-item.y, item.x))
        return marker_items

    def _check_scale_mismatch(self, frame: FrameMeta) -> None:
        geom = frame.runtime.geom_scale_factor
        scale_den = frame.titleblock.scale_denominator
        if geom is None or scale_den is None:
            return
        if geom <= 0:
            return
        diff = abs(geom - scale_den)
        threshold = max(self.scale_tol_abs, self.scale_tol_rel * scale_den)
        mismatch = diff > threshold
        frame.runtime.scale_mismatch = mismatch
        if mismatch:
            frame.add_flag(self.scale_mismatch_flag)

    def _restore_roi(
        self,
        outer_bbox: BBox,
        rb_offset: list[float],
        sx: float,
        sy: float,
    ) -> BBox:
        """
        还原ROI坐标

        rb_offset格式: [dx_right, dx_left, dy_bottom, dy_top]
        公式:
            xmin = outer_xmax - dx_left * sx
            xmax = outer_xmax - dx_right * sx
            ymin = outer_ymin + dy_bottom * sy
            ymax = outer_ymin + dy_top * sy
        """
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
    def _item_reference_point(item: TextItem) -> tuple[float, float]:
        if item.bbox is not None:
            return (
                (item.bbox.xmin + item.bbox.xmax) / 2.0,
                (item.bbox.ymin + item.bbox.ymax) / 2.0,
            )
        return item.x, item.y

    @classmethod
    def _item_in_roi(cls, item: TextItem, roi: BBox) -> bool:
        px, py = cls._item_reference_point(item)
        return roi.xmin <= px <= roi.xmax and roi.ymin <= py <= roi.ymax

    @classmethod
    def _claim_items_in_roi(
        cls,
        items: list[TextItem],
        roi: BBox,
        claimed_item_ids: set[int],
    ) -> list[TextItem]:
        selected: list[TextItem] = []
        for item in items:
            item_id = id(item)
            if item_id in claimed_item_ids:
                continue
            if cls._item_in_roi(item, roi):
                selected.append(item)
        claimed_item_ids.update(id(item) for item in selected)
        return selected

    def _parse_internal_code(
        self, items: list[TextItem], parse_cfg: dict[str, Any]
    ) -> tuple[str | None, str | None]:
        patterns = parse_cfg.get("patterns") or {}
        full_pat = patterns.get(
            "full", r"^(?P<prefix>[A-Z0-9]{7})-(?P<mid>[A-Z0-9]{5})-(?P<seq>[0-9]{3})$"
        )
        short_pat = patterns.get(
            "short", r"^(?P<prefix>[A-Z0-9]{7})-(?P<mid>[A-Z0-9]{5})$"
        )
        mid_album_pat = patterns.get("mid_album", r"^(?P<mid3>[A-Z0-9]{3})(?P<album>[0-9]{2})$")
        re_full = re.compile(full_pat)
        re_short = re.compile(short_pat)
        re_mid_album = re.compile(mid_album_pat)

        candidates = self._candidate_strings(items)
        ordered_items = sorted(items, key=lambda t: (-t.y, t.x))
        joined_fragments = "".join(
            self._strip_all_whitespace((item.text or "").upper()) for item in ordered_items
        )
        if joined_fragments:
            candidates.append(joined_fragments)
        short_match: re.Match[str] | None = None
        for cand in candidates:
            text = self._strip_all_whitespace(cand.upper())
            m = re_full.match(text)
            if m:
                internal_code = m.group(0)
                album_code = None
                mid = m.groupdict().get("mid")
                if mid:
                    mm = re_mid_album.match(mid)
                    if mm:
                        album_code = mm.group("album")
                    elif len(mid) >= 2:
                        album_code = mid[-2:]
                return internal_code, album_code

            m = re_short.match(text)
            if m and short_match is None:
                short_match = m

        rebuilt = self._rebuild_internal_code_from_segments(items, re_full, re_short)
        if rebuilt:
            m = re_full.match(rebuilt)
            if m:
                album_code = None
                mid = m.groupdict().get("mid")
                if mid:
                    mm = re_mid_album.match(mid)
                    if mm:
                        album_code = mm.group("album")
                    elif len(mid) >= 2:
                        album_code = mid[-2:]
                return rebuilt, album_code

        if short_match:
            internal_code = short_match.group(0)
            album_code = None
            mid = short_match.groupdict().get("mid")
            if mid:
                mm = re_mid_album.match(mid)
                if mm:
                    album_code = mm.group("album")
                elif len(mid) >= 2:
                    album_code = mid[-2:]
            return internal_code, album_code

        return None, None

    # 外部编码中至少包含的数字个数（过滤模板占位文字）
    _EXT_CODE_MIN_DIGITS = 3

    def _parse_external_code(
        self, items: list[TextItem], parse_cfg: dict[str, Any]
    ) -> str | None:
        fixed_len = int(parse_cfg.get("length", parse_cfg.get("fixed_len", 19)))
        header_hint = str(parse_cfg.get("header", "DOC.NO"))

        best_match = None
        best_score = None
        for candidate in self._external_code_candidates(items, header_hint):
            if len(candidate) != fixed_len or not self._is_valid_external_code(candidate):
                continue
            score = (0 if candidate[:1].isalpha() else 1,)
            if best_score is None or score < best_score:
                best_score = score
                best_match = candidate
        if best_match:
            return best_match

        rebuilt = self._rebuild_fixed19_from_single_chars(items, fixed_len, header_hint)
        if rebuilt and self._is_valid_external_code(rebuilt):
            return rebuilt

        return None

    def _external_code_candidates(self, items: list[TextItem], header_hint: str) -> list[str]:
        candidates: list[str] = []
        items = self._dedupe_external_code_items(items, header_hint)

        ordered_items = sorted(items, key=lambda t: (t.x, t.y))
        joined_all = "".join((t.text or "") for t in ordered_items)
        normalized_all = self._normalize_external_candidate(joined_all, header_hint)
        if normalized_all:
            candidates.append(normalized_all)

        for line in self._cluster_by_y(items, self.y_cluster_abs):
            ordered = sorted(line, key=lambda t: t.x)
            joined = "".join((t.text or "") for t in ordered)
            normalized = self._normalize_external_candidate(joined, header_hint)
            if normalized:
                candidates.append(normalized)

        for candidate in self._candidate_strings(items):
            normalized = self._normalize_external_candidate(candidate, header_hint)
            if normalized:
                candidates.append(normalized)

        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            deduped.append(candidate)
        return deduped

    def _dedupe_external_code_items(
        self,
        items: list[TextItem],
        header_hint: str,
    ) -> list[TextItem]:
        selected: list[TextItem] = []
        for item in items:
            if not self._normalize_external_candidate(item.text or "", header_hint):
                selected.append(item)
                continue
            duplicate_index = next(
                (
                    idx
                    for idx, existing in enumerate(selected)
                    if self._external_code_items_overlap_duplicate(
                        existing,
                        item,
                        header_hint,
                    )
                ),
                None,
            )
            if duplicate_index is None:
                selected.append(item)
                continue
            if self._prefer_external_code_item(item, selected[duplicate_index]):
                selected[duplicate_index] = item
        return selected

    def _external_code_items_overlap_duplicate(
        self,
        left: TextItem,
        right: TextItem,
        header_hint: str,
    ) -> bool:
        left_text = self._normalize_external_candidate(left.text or "", header_hint)
        right_text = self._normalize_external_candidate(right.text or "", header_hint)
        if not left_text or left_text != right_text:
            return False
        left_x, left_y = self._item_center(left)
        right_x, right_y = self._item_center(right)
        tol = max(
            0.5,
            (left.text_height or 0.0) * 0.05,
            (right.text_height or 0.0) * 0.05,
        )
        if abs(left_x - right_x) > tol or abs(left_y - right_y) > tol:
            return False
        if left.bbox is None or right.bbox is None:
            return True
        return self._bbox_overlap_ratio(left.bbox, right.bbox) >= 0.80

    @staticmethod
    def _prefer_external_code_item(candidate: TextItem, existing: TextItem) -> bool:
        candidate_virtual = ":virtual" in candidate.source
        existing_virtual = ":virtual" in existing.source
        if candidate_virtual != existing_virtual:
            return not candidate_virtual
        return (candidate.text_height or 0.0) > (existing.text_height or 0.0)

    @staticmethod
    def _item_center(item: TextItem) -> tuple[float, float]:
        if item.bbox is None:
            return item.x, item.y
        return (
            (item.bbox.xmin + item.bbox.xmax) / 2.0,
            (item.bbox.ymin + item.bbox.ymax) / 2.0,
        )

    @staticmethod
    def _bbox_overlap_ratio(left: BBox, right: BBox) -> float:
        x_overlap = max(0.0, min(left.xmax, right.xmax) - max(left.xmin, right.xmin))
        y_overlap = max(0.0, min(left.ymax, right.ymax) - max(left.ymin, right.ymin))
        overlap_area = x_overlap * y_overlap
        if overlap_area <= 0.0:
            return 0.0
        left_area = max((left.xmax - left.xmin) * (left.ymax - left.ymin), 1e-6)
        right_area = max((right.xmax - right.xmin) * (right.ymax - right.ymin), 1e-6)
        return overlap_area / min(left_area, right_area)

    def _normalize_external_candidate(self, text: str, header_hint: str) -> str:
        cleaned = self._clean_alnum(self._normalize_spaces(text).upper())
        header_clean = self._clean_alnum(header_hint.upper())
        if header_clean:
            cleaned = cleaned.replace(header_clean, "", 1)
        return cleaned

    @classmethod
    def _is_valid_external_code(cls, code: str) -> bool:
        """校验外部编码有效性：长度正确且包含足够数字（排除模板占位文字）"""
        digit_count = sum(1 for ch in code if ch.isdigit())
        return digit_count >= cls._EXT_CODE_MIN_DIGITS

    def _parse_regex(
        self, items: list[TextItem], parse_cfg: dict[str, Any]
    ) -> tuple[str | None, dict[str, Any]]:
        pattern = parse_cfg.get("pattern")
        if not pattern:
            return None, {}
        regex = re.compile(str(pattern))
        extras: dict[str, Any] = {}
        for cand in self._candidate_strings(items):
            match = regex.search(cand)
            if not match:
                continue
            out = match.group(0)
            output_map = parse_cfg.get("output") or {}
            for key, group_idx in output_map.items():
                try:
                    raw = match.group(int(group_idx))
                    if raw.upper() == "X":
                        extras[key] = 1
                    else:
                        extras[key] = float(raw) if "." in raw else int(raw)
                except Exception:
                    extras[key] = None
            return out, extras
        return None, extras

    def _parse_page_info(
        self,
        items: list[TextItem],
        parse_cfg: dict[str, Any],
        *,
        total_then_index_tokens: bool = False,
    ) -> tuple[int | None, int | None]:
        labeled_total, labeled_index = self._parse_labeled_page_info_from_lines(items)
        if labeled_total is not None or labeled_index is not None:
            return labeled_total, labeled_index

        pattern = parse_cfg.get("pattern")
        if pattern:
            regex = re.compile(str(pattern))
            for cand in self._candidate_strings(items):
                match = regex.search(cand)
                if match:
                    total_raw = match.group(1)
                    idx_raw = match.group(2)
                    total = int(total_raw) if total_raw.isdigit() else None
                    idx = 1 if idx_raw.upper() == "X" else int(idx_raw) if idx_raw.isdigit() else None
                    return total, idx

        total_s, idx_s = self._page_info_two_tokens(
            items,
            total_then_index_tokens=total_then_index_tokens,
        )
        if total_s is None or idx_s is None:
            return None, None
        total = int(total_s) if total_s.isdigit() else None
        idx = 1 if idx_s.upper() == "X" else int(idx_s) if idx_s.isdigit() else None
        return total, idx

    def _parse_title_bilingual(self, items: list[TextItem]) -> tuple[str | None, str | None]:
        if not items:
            return None, None
        lines = [
            line
            for line in self._extract_title_lines(items)
            if not self._looks_like_page_info_line(line)
        ]
        if not lines:
            return None, None
        if self.project_no and self.project_no != "1818":
            title_cn = self.line_join.join(
                [self._normalize_spaces(line) for line in lines if line]
            ).strip()
            return (title_cn or None), None
        normalized_lines = [self._normalize_spaces(line) for line in lines if line]
        cn_lines: list[str] = []
        en_lines: list[str] = []
        for idx, normalized in enumerate(normalized_lines):
            scope_token, cn_remainder = self._split_leading_scope_token_from_cn_line(normalized)
            if scope_token:
                en_lines.append(scope_token)
                if cn_remainder:
                    cn_lines.append(cn_remainder)
                continue

            language = self._classify_title_line(normalized)
            if self._looks_like_title_scope_line(normalized):
                for following in normalized_lines[idx + 1 :]:
                    if self._looks_like_title_scope_line(following):
                        continue
                    language = self._classify_title_line(following)
                    break
            if language == "cn":
                cn_lines.append(normalized)
            else:
                en_lines.append(normalized)
        title_cn = self.line_join.join([ln for ln in cn_lines if ln]).strip()
        title_en = self.line_join.join([ln for ln in en_lines if ln]).strip()
        return (title_cn or None), (title_en or None)

    def _parse_text(self, items: list[TextItem]) -> str | None:
        joined = self._join_text(items)
        return joined or None

    def _parse_subitem_no(
        self,
        items: list[TextItem],
        *,
        internal_code: str | None = None,
    ) -> str | None:
        expected = self._subitem_no_from_internal_code(internal_code)
        candidates: list[str] = []

        for item in items:
            text = str(item.text or "")
            candidates.extend(part.strip() for part in text.splitlines() if part.strip())

        joined = self._join_text(items)
        if joined:
            candidates.append(joined)
            candidates.extend(part.strip() for part in joined.splitlines() if part.strip())

        normalized_candidates = [self._normalize_subitem_candidate(value) for value in candidates]
        normalized_candidates = [value for value in normalized_candidates if value]

        if expected and expected in normalized_candidates:
            return expected

        for value in normalized_candidates:
            if self._is_clean_subitem_no(value):
                return value

        return expected

    @staticmethod
    def _subitem_no_from_internal_code(internal_code: str | None) -> str | None:
        text = str(internal_code or "").strip().upper()
        match = re.match(r"^\d{4}\d(?P<subitem>[A-Z]{2,4})-", text)
        if not match:
            return None
        return match.group("subitem")

    @staticmethod
    def _normalize_subitem_candidate(value: str) -> str:
        text = re.sub(r"\s+", "", str(value or "").strip().upper())
        if not text:
            return ""
        noise_tokens = ("图号", "圖號", "DOC.NO", "DOCNO", "DOCUMENTNO", "NO.", "NO")
        for token in noise_tokens:
            text = text.replace(token, "")
        text = re.sub(r"[^A-Z0-9]", "", text)
        return text

    @staticmethod
    def _is_clean_subitem_no(value: str) -> bool:
        return bool(re.fullmatch(r"(?:[A-Z]{1,4}|00)", value or ""))

    def _pick_top_by_y(
        self,
        items: list[TextItem],
        *,
        candidate_pattern: str | None = None,
    ) -> str | None:
        if not items:
            return None
        ordered = sorted(items, key=lambda t: (-t.y, t.x))
        regex = re.compile(str(candidate_pattern)) if candidate_pattern else None
        for item in ordered:
            text = (item.text or "").strip()
            if regex and not regex.fullmatch(text):
                continue
            if text:
                return text
        return None

    def _candidate_strings(self, items: list[TextItem]) -> list[str]:
        out: list[str] = []
        for item in items:
            text = (item.text or "").strip()
            if text:
                out.append(text)
        joined = self._join_text(items)
        if joined:
            out.append(joined)
            out.extend([ln for ln in joined.splitlines() if ln.strip()])
        return out

    def _join_text(self, items: list[TextItem]) -> str:
        if not items:
            return ""
        lines = self._cluster_by_y(items, self.y_cluster_abs)
        joined: list[str] = []
        for line in lines:
            line.sort(key=lambda t: t.x)
            s = " ".join((t.text or "").strip() for t in line if t.text)
            s = self._normalize_spaces(s)
            if s:
                joined.append(s)
        return self.line_join.join(joined).strip()

    def _extract_title_lines(self, items: list[TextItem]) -> list[str]:
        frags: list[tuple[float, float, str, float, float]] = []
        for it in items:
            text = (it.text or "").strip()
            if not text:
                continue
            parts = [p.strip() for p in text.splitlines() if p.strip()]
            if not parts:
                continue
            _, ymin, _, ymax = self._item_span(it)
            if len(parts) == 1:
                frags.append((it.y, it.x, parts[0], ymin, ymax))
            else:
                for idx, part in enumerate(parts):
                    part_y = it.y - idx * (self.y_cluster_abs * 0.1)
                    frags.append((part_y, it.x, part, ymin, ymax))

        frags.sort(key=lambda t: (-t[0], t[1]))
        lines: list[list[tuple[float, float, str, float, float]]] = []
        for y, x, text, ymin, ymax in frags:
            placed = False
            for line in lines:
                if self._title_fragments_same_visual_line(line, y, ymin, ymax):
                    line.append((y, x, text, ymin, ymax))
                    placed = True
                    break
            if not placed:
                lines.append([(y, x, text, ymin, ymax)])

        out: list[str] = []
        for line in lines:
            line.sort(key=lambda t: t[1])
            s = " ".join(seg[2] for seg in line if seg[2])
            s = self._normalize_spaces(s)
            if s:
                out.append(s)
        return out

    def _title_fragments_same_visual_line(
        self,
        line: list[tuple[float, float, str, float, float]],
        y: float,
        ymin: float,
        ymax: float,
    ) -> bool:
        if abs(line[0][0] - y) <= self.y_cluster_abs:
            return True

        line_ymin = min(seg[3] for seg in line)
        line_ymax = max(seg[4] for seg in line)
        overlap = min(line_ymax, ymax) - max(line_ymin, ymin)
        if overlap <= 0:
            return False
        line_height = max(line_ymax - line_ymin, 1e-6)
        frag_height = max(ymax - ymin, 1e-6)
        return overlap / min(line_height, frag_height) >= 0.35

    @staticmethod
    def _cluster_by_y(items: list[TextItem], y_tol: float) -> list[list[TextItem]]:
        items_sorted = sorted(items, key=lambda it: (-it.y, it.x))
        lines: list[list[TextItem]] = []
        for it in items_sorted:
            placed = False
            for line in lines:
                if abs(line[0].y - it.y) <= y_tol:
                    line.append(it)
                    placed = True
                    break
            if not placed:
                lines.append([it])
        return lines

    @staticmethod
    def _has_cjk(text: str) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in text)

    @classmethod
    def _looks_like_english_title_line(cls, text: str) -> bool:
        if not text:
            return False
        if not any(char.isascii() and char.isalpha() for char in text):
            return False
        if not cls._has_cjk(text):
            return True
        stripped = re.sub(
            r"[\(\uff08]\s*[\u4e00-\u9fff0-9IVXivx]+\s*[\)\uff09]",
            "",
            text,
        )
        return not cls._has_cjk(stripped)

    @classmethod
    def _classify_title_line(cls, text: str) -> str:
        if cls._looks_like_compact_cn_title_token(text):
            return "cn"
        if cls._looks_like_english_title_line(text):
            return "en"
        if cls._has_cjk(text):
            return "cn"
        return "en"

    @staticmethod
    def _looks_like_title_scope_line(text: str) -> bool:
        normalized = text.strip().upper().replace("\uff5e", "~")
        return (
            re.fullmatch(
                r"[0-9]{1,2}[A-Z]{1,4}\s+[-+]?[0-9]+(?:\.[0-9]+)?"
                r"(?:\s*~\s*[-+]?[0-9]+(?:\.[0-9]+)?)?(?:\s*M)?",
                normalized,
            )
            is not None
        )

    @classmethod
    def _split_leading_scope_token_from_cn_line(cls, text: str) -> tuple[str | None, str | None]:
        normalized = cls._normalize_spaces(text)
        if not cls._has_cjk(normalized):
            return None, None
        match = re.match(r"^(?P<scope>[A-Z]{1,4})\s+(?P<rest>.+)$", normalized)
        if not match:
            return None, None
        scope = match.group("scope").strip()
        rest = match.group("rest").strip()
        if not rest or not cls._has_cjk(rest):
            return None, None
        if cls._looks_like_english_title_line(rest):
            return None, None
        return scope, rest

    @staticmethod
    def _looks_like_compact_cn_title_token(text: str) -> bool:
        normalized = text.strip().upper()
        return re.fullmatch(r"[0-9]{1,2}[A-Z]{1,4}", normalized) is not None

    @staticmethod
    def _normalize_spaces(text: str) -> str:
        normalized = TitleblockExtractor._decode_cad_control_codes(text or "")
        return re.sub(r"\s+", " ", normalized.strip())

    @staticmethod
    def _strip_all_whitespace(text: str) -> str:
        return re.sub(r"\s+", "", text or "")

    @staticmethod
    def _normalize_anchor(text: str) -> str:
        return "".join(ch for ch in (text or "") if not ch.isspace())

    def _rebuild_internal_code_from_segments(
        self,
        items: list[TextItem],
        re_full: re.Pattern[str],
        re_short: re.Pattern[str],
    ) -> str | None:
        prefix_candidates: list[tuple[TextItem, str]] = []
        for item in sorted(items, key=lambda t: (-t.y, t.x)):
            text = self._strip_all_whitespace((item.text or "").upper())
            if not text:
                continue
            if re_full.match(text):
                return text
            base = text[:-1] if text.endswith("-") else text
            if re_short.match(base):
                prefix_candidates.append((item, base))

        for prefix_item, prefix in prefix_candidates:
            prefix_right = self._text_item_right_edge(prefix_item)
            y_tol = max(self.y_cluster_abs * 3.0, (prefix_item.text_height or 0.0) * 0.25, 3.0)
            suffix_chunks: list[tuple[float, str]] = []
            suffix_tokens: list[tuple[float, str]] = []
            for item in items:
                text = self._strip_all_whitespace((item.text or "").upper())
                if item.x <= prefix_right:
                    continue
                if abs(item.y - prefix_item.y) > y_tol:
                    continue
                if re.fullmatch(r"-?[0-9]{3}", text):
                    suffix_chunks.append((item.x, text.lstrip("-")))
                    continue
                if len(text) != 1 or not text.isdigit():
                    continue
                suffix_tokens.append((item.x, text))
            suffix_chunks.sort(key=lambda t: t[0])
            for _, suffix in suffix_chunks:
                candidate = f"{prefix}-{suffix}"
                if re_full.match(candidate):
                    return candidate
            suffix_tokens.sort(key=lambda t: t[0])
            suffix = "".join(token for _, token in suffix_tokens[:3])
            candidate = f"{prefix}-{suffix}"
            if len(suffix) == 3 and re_full.match(candidate):
                return candidate
        visual_line_rebuilt = self._rebuild_internal_code_from_visual_lines(items, re_full)
        if visual_line_rebuilt:
            return visual_line_rebuilt
        return None

    def _rebuild_internal_code_from_visual_lines(
        self,
        items: list[TextItem],
        re_full: re.Pattern[str],
    ) -> str | None:
        lines: list[list[TextItem]] = []
        for item in sorted(items, key=lambda t: (-self._item_center_y(t), t.x)):
            text = self._clean_internal_code_fragment(item.text or "")
            if not text:
                continue
            for line in lines:
                if self._items_on_same_visual_line(line[0], item):
                    line.append(item)
                    break
            else:
                lines.append([item])

        for line in lines:
            line.sort(key=lambda t: t.x)
            candidate = "".join(
                self._clean_internal_code_fragment(item.text or "") for item in line
            )
            if re_full.match(candidate):
                return candidate
        return None

    @staticmethod
    def _clean_internal_code_fragment(text: str) -> str:
        text = TitleblockExtractor._strip_all_whitespace((text or "").upper())
        return "".join(ch for ch in text if ("A" <= ch <= "Z") or ("0" <= ch <= "9") or ch == "-")

    @classmethod
    def _items_on_same_visual_line(cls, left: TextItem, right: TextItem) -> bool:
        left_span = cls._item_span(left)
        right_span = cls._item_span(right)
        overlap = min(left_span[3], right_span[3]) - max(left_span[1], right_span[1])
        if overlap > 0:
            left_height = max(left_span[3] - left_span[1], 1e-6)
            right_height = max(right_span[3] - right_span[1], 1e-6)
            if overlap / min(left_height, right_height) >= 0.35:
                return True
        y_tol = max(
            3.0,
            (left.text_height or 0.0) * 0.25,
            (right.text_height or 0.0) * 0.25,
        )
        return abs(cls._item_center_y(left) - cls._item_center_y(right)) <= y_tol

    @staticmethod
    def _item_center_y(item: TextItem) -> float:
        if item.bbox is not None:
            return (item.bbox.ymin + item.bbox.ymax) / 2.0
        return item.y

    @staticmethod
    def _text_item_right_edge(item: TextItem) -> float:
        if item.bbox is not None:
            return item.bbox.xmax
        text = (item.text or "").strip()
        if not text:
            return item.x
        height = item.text_height or 0.0
        approx_width = max(len(text) * max(height, 1.0) * 0.6, 1.0)
        return item.x + approx_width

    @classmethod
    def _looks_like_page_info_line(cls, text: str) -> bool:
        compact = cls._strip_all_whitespace(text)
        if not compact:
            return False
        if re.fullmatch(r"第[0-9Xx]*张共[0-9Xx]*张", compact):
            return True
        if re.fullmatch(r"共[0-9Xx]*张第[0-9Xx]*张", compact):
            return True

        normalized = cls._normalize_spaces(text).upper()
        return re.fullmatch(r"PAGE\s*[0-9Xx]*\s*OF\s*[0-9Xx]*", normalized) is not None

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

    @staticmethod
    def _clean_alnum(text: str) -> str:
        return "".join(ch for ch in text if ("A" <= ch <= "Z") or ("0" <= ch <= "9"))

    @staticmethod
    def _decode_cad_control_codes(text: str) -> str:
        if not text:
            return ""
        decoded = text
        replacements = {
            "%%D": "°",
            "%%d": "°",
            "%%P": "±",
            "%%p": "±",
            "%%C": "⌀",
            "%%c": "⌀",
        }
        for raw, replacement in replacements.items():
            decoded = decoded.replace(raw, replacement)
        return decoded

    @staticmethod
    def _uses_001_homepage_page_info_order(
        frame: FrameMeta,
        fields: TitleblockFields,
    ) -> bool:
        code = (fields.internal_code or frame.titleblock.internal_code or "").strip().upper()
        if not code.endswith("-001"):
            return False
        return True

    def _parse_labeled_page_info_from_lines(
        self,
        items: list[TextItem],
    ) -> tuple[int | None, int | None]:
        best: tuple[int, float, int | None, int | None] | None = None

        def remember(
            *,
            line_text: str,
            y: float,
            total: int | None,
            index: int | None,
        ) -> None:
            nonlocal best
            if total is None and index is None:
                return
            score = (self._page_info_line_priority(line_text), y, total, index)
            if best is None or score[:2] > best[:2]:
                best = score

        for line in self._cluster_by_y(items, self.y_cluster_abs):
            ordered = sorted(line, key=lambda it: it.x)
            line_text = self._normalize_spaces(
                " ".join((it.text or "").strip() for it in ordered if it.text)
            )
            if not line_text:
                continue

            parsed = self._parse_page_info_text(line_text)
            if parsed != (None, None):
                total, index = parsed
            else:
                token_order = self._page_info_token_order(line_text)
                if token_order is None:
                    continue
                numeric_tokens = [
                    (it.x, token)
                    for it in ordered
                    if (token := self._page_info_numeric_token(it.text or "")) is not None
                ]
                if len(numeric_tokens) < 2:
                    continue
                numeric_tokens.sort(key=lambda t: t[0])
                first = numeric_tokens[0][1]
                second = numeric_tokens[-1][1]
                if token_order == "index_total":
                    index = self._page_info_token_to_int(first, is_index=True)
                    total = self._page_info_token_to_int(second, is_index=False)
                else:
                    total = self._page_info_token_to_int(first, is_index=False)
                    index = self._page_info_token_to_int(second, is_index=True)

            remember(
                line_text=line_text,
                y=max((it.y for it in ordered), default=0.0),
                total=total,
                index=index,
            )

        for label in items:
            label_text = self._normalize_spaces(label.text or "")
            token_order = self._page_info_token_order(label_text)
            if token_order is None:
                continue
            label_height = max(1.0, label.text_height or 0.0)
            y_tol = max(self.y_cluster_abs * 3.0, label_height * 0.35, 8.0)
            numeric_tokens: list[tuple[float, str]] = []
            for item in items:
                if item is label:
                    continue
                token = self._page_info_numeric_token(item.text or "")
                if token is None:
                    continue
                if item.x < label.x - 1.0:
                    continue
                if abs(item.y - label.y) > y_tol:
                    continue
                numeric_tokens.append((item.x, token))
            if len(numeric_tokens) < 2:
                continue
            numeric_tokens.sort(key=lambda t: t[0])
            first = numeric_tokens[0][1]
            second = numeric_tokens[-1][1]
            if token_order == "index_total":
                index = self._page_info_token_to_int(first, is_index=True)
                total = self._page_info_token_to_int(second, is_index=False)
            else:
                total = self._page_info_token_to_int(first, is_index=False)
                index = self._page_info_token_to_int(second, is_index=True)
            remember(line_text=label_text, y=label.y, total=total, index=index)

        if best is None:
            return None, None
        return best[2], best[3]

    @classmethod
    def _parse_page_info_text(cls, text: str) -> tuple[int | None, int | None]:
        normalized = cls._normalize_spaces(text)
        if not normalized:
            return None, None

        patterns = [
            (
                re.compile(r"第\s*([0-9Xx]+)\s*[张页]\s*共\s*([0-9Xx]+)\s*[张页]"),
                "index_total",
            ),
            (
                re.compile(r"共\s*([0-9Xx]+)\s*[张页]\s*第\s*([0-9Xx]+)\s*[张页]"),
                "total_index",
            ),
            (
                re.compile(r"(?:page|rolls)?\s*([0-9Xx]+)\s*of\s*([0-9Xx]+)", re.IGNORECASE),
                "index_total",
            ),
        ]
        for pattern, token_order in patterns:
            match = pattern.search(normalized)
            if not match:
                continue
            first = match.group(1)
            second = match.group(2)
            if token_order == "index_total":
                total = cls._page_info_token_to_int(second, is_index=False)
                index = cls._page_info_token_to_int(first, is_index=True)
            else:
                total = cls._page_info_token_to_int(first, is_index=False)
                index = cls._page_info_token_to_int(second, is_index=True)
            return total, index
        return None, None

    @classmethod
    def _page_info_token_order(cls, text: str) -> str | None:
        compact = cls._strip_all_whitespace(text).upper()
        if not compact:
            return None
        first_index = compact.find("第")
        first_total = compact.find("共")
        if first_index >= 0 and first_total >= 0:
            return "index_total" if first_index < first_total else "total_index"
        if "PAGE" in compact or "OF" in compact:
            return "index_total"
        return None

    def _page_info_two_tokens(
        self,
        items: list[TextItem],
        *,
        total_then_index_tokens: bool = False,
    ) -> tuple[str | None, str | None]:
        best_line_tokens: list[tuple[float, str]] = []
        best_line_score: tuple[int, float] | None = None

        for line in self._cluster_by_y(items, self.y_cluster_abs):
            ordered = sorted(line, key=lambda it: it.x)
            tokens: list[tuple[float, str]] = []
            line_parts: list[str] = []
            for it in ordered:
                text = self._normalize_spaces(it.text or "")
                if text:
                    line_parts.append(text)
                token = self._page_info_numeric_token(it.text or "")
                if token is not None:
                    tokens.append((it.x, token))
            if len(tokens) < 2:
                continue

            line_text = self._normalize_spaces(" ".join(line_parts))
            score = (self._page_info_line_priority(line_text), max((it.y for it in ordered), default=0.0))
            if best_line_score is None or score > best_line_score:
                best_line_score = score
                best_line_tokens = tokens

        if len(best_line_tokens) >= 2:
            best_line_tokens.sort(key=lambda t: t[0])
            if total_then_index_tokens:
                return best_line_tokens[0][1], best_line_tokens[-1][1]
            return best_line_tokens[-1][1], best_line_tokens[0][1]

        tokens: list[tuple[float, str]] = []
        for it in items:
            token = self._page_info_numeric_token(it.text or "")
            if token is not None:
                tokens.append((it.x, token))
        tokens.sort(key=lambda t: t[0])
        if len(tokens) < 2:
            return None, None
        if total_then_index_tokens:
            return tokens[0][1], tokens[-1][1]
        return tokens[-1][1], tokens[0][1]

    @classmethod
    def _page_info_line_priority(cls, text: str) -> int:
        compact = cls._strip_all_whitespace(text).upper()
        if "第" in text or "共" in text:
            return 3
        if "PAGE" in compact or "OF" in compact:
            return 2
        if cls._has_cjk(text):
            return 1
        return 0

    @staticmethod
    def _page_info_numeric_token(text: str) -> str | None:
        cleaned = TitleblockExtractor._clean_alnum((text or "").upper())
        if not cleaned:
            return None
        if cleaned == "X" or cleaned.isdigit():
            return cleaned
        return None

    @staticmethod
    def _page_info_token_to_int(token: str, *, is_index: bool) -> int | None:
        normalized = str(token or "").strip().upper()
        if normalized == "X":
            return 1 if is_index else None
        if normalized.isdigit():
            return int(normalized)
        return None

    def _rebuild_fixed19_from_single_chars(
        self, items: list[TextItem], fixed_len: int, header_hint: str
    ) -> str | None:
        items = self._dedupe_external_code_items(items, header_hint)
        tokens: list[tuple[float, float, str]] = []
        for it in items:
            s = self._normalize_external_candidate(it.text or "", header_hint)
            if len(s) == 1:
                tokens.append((it.x, it.y, s))
        tokens.sort(key=lambda t: t[0])
        if len(tokens) < fixed_len:
            return None
        selected = self._pick_best_single_char_window(tokens, fixed_len)
        return "".join(t[2] for t in selected)

    @staticmethod
    def _pick_best_single_char_window(
        tokens: list[tuple[float, float, str]],
        fixed_len: int,
    ) -> list[tuple[float, float, str]]:
        if len(tokens) <= fixed_len:
            return tokens

        best_window = tokens[-fixed_len:]
        best_score = float("inf")
        for start in range(0, len(tokens) - fixed_len + 1):
            window = tokens[start : start + fixed_len]
            xs = [token[0] for token in window]
            gaps = [right - left for left, right in zip(xs, xs[1:], strict=False)]
            positive_gaps = [gap for gap in gaps if gap > 1e-6]
            if not positive_gaps:
                continue
            typical_gap = median(positive_gaps)
            if typical_gap <= 1e-6:
                continue
            max_gap_ratio = max(positive_gaps) / typical_gap
            jitter = sum(abs(gap - typical_gap) for gap in positive_gaps) / typical_gap
            span_ratio = (xs[-1] - xs[0]) / max(typical_gap * (fixed_len - 1), 1e-6)
            score = max_gap_ratio * 10.0 + jitter + abs(span_ratio - 1.0)
            if score < best_score:
                best_score = score
                best_window = window
        return best_window

    @staticmethod
    def _text_item_to_dict(item: TextItem) -> dict[str, Any]:
        data: dict[str, Any] = {
            "text": item.text,
            "x": item.x,
            "y": item.y,
            "source": item.source,
        }
        if item.text_height is not None:
            data["height"] = item.text_height
        if item.halign is not None:
            data["halign"] = item.halign
        if item.valign is not None:
            data["valign"] = item.valign
        if item.attachment_point is not None:
            data["attachment_point"] = item.attachment_point
        if item.bbox is not None:
            data["bbox"] = {
                "xmin": item.bbox.xmin,
                "ymin": item.bbox.ymin,
                "xmax": item.bbox.xmax,
                "ymax": item.bbox.ymax,
            }
        return data

    @staticmethod
    def _iter_text_items(msp) -> Iterable[TextItem]:
        def add_text_entity(e, src: str) -> TextItem | None:
            tp = e.dxftype()
            if tp == "TEXT":
                text = (e.dxf.text or "").strip()
                p = e.dxf.insert
                x, y = float(p.x), float(p.y)
                height = float(getattr(e.dxf, "height", 2.5) or 2.5)
                halign = int(getattr(e.dxf, "halign", 0) or 0)
                valign = int(getattr(e.dxf, "valign", 0) or 0)
                bbox = TitleblockExtractor._bbox_from_text(
                    text=text,
                    x=x,
                    y=y,
                    height=height,
                    halign=halign,
                    valign=valign,
                )
                return TextItem(
                    x=x,
                    y=y,
                    text=text,
                    bbox=bbox,
                    text_height=height,
                    source=src,
                    halign=halign,
                    valign=valign,
                )
            if tp == "MTEXT":
                try:
                    text = (e.plain_text() or "").strip()
                except Exception:
                    text = (e.text or "").strip()
                p = e.dxf.insert
                x, y = float(p.x), float(p.y)
                bbox = TitleblockExtractor._bbox_from_mtext(e, text, x, y)
                try:
                    height = float(getattr(e.dxf, "char_height", getattr(e.dxf, "height", 2.5)))
                except Exception:
                    height = 2.5
                ap = int(getattr(e.dxf, "attachment_point", 1) or 1)
                return TextItem(
                    x=x,
                    y=y,
                    text=text,
                    bbox=bbox,
                    text_height=height,
                    source=src,
                    attachment_point=ap,
                )
            if tp == "ATTRIB":
                text = (e.dxf.text or "").strip()
                p = e.dxf.insert
                x, y = float(p.x), float(p.y)
                height = float(getattr(e.dxf, "height", 2.5) or 2.5)
                halign = int(getattr(e.dxf, "halign", 0) or 0)
                valign = int(getattr(e.dxf, "valign", 0) or 0)
                bbox = TitleblockExtractor._bbox_from_text(
                    text=text,
                    x=x,
                    y=y,
                    height=height,
                    halign=halign,
                    valign=valign,
                )
                return TextItem(
                    x=x,
                    y=y,
                    text=text,
                    bbox=bbox,
                    text_height=height,
                    source=src,
                    halign=halign,
                    valign=valign,
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
