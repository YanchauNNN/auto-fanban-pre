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
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
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

    def extract_fields(self, dxf_path: Path, frame: FrameMeta) -> FrameMeta:
        """提取单个图框的图签字段"""
        if not dxf_path.exists():
            raise ExtractionError(f"DXF文件不存在: {dxf_path}")

        try:
            doc = ezdxf.readfile(str(dxf_path))
        except Exception as e:
            raise ExtractionError(f"DXF解析失败: {e}") from e

        msp = doc.modelspace()
        text_items = list(self._iter_text_items(msp))

        profile_id = frame.runtime.roi_profile_id or "BASE10"
        profile = self.spec.get_roi_profile(profile_id)
        if not profile:
            frame.add_flag("ROI配置缺失")
            return frame

        if self._is_a4_frame(frame):
            self._extract_a4_page_marker(frame, text_items)
            return frame

        if self.anchor_texts and not self._frame_has_anchor_text(
            text_items, frame, profile, profile_id
        ):
            frame.add_flag("未命中锚点文本")
            return frame

        raw_extracts: dict[str, Any] = {}
        fields = TitleblockFields()

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
            point_only = field_key in self.point_only_fields
            roi_items = [t for t in text_items if self._item_in_roi(t, roi, use_bbox=not point_only)]

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
                page_total, page_index = self._parse_page_info(roi_items, parse_cfg)
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
                value = self._pick_top_by_y(roi_items)
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
        self._check_scale_mismatch(frame)
        return frame

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
            roi = self._expand_roi(frame.runtime.outer_bbox, self.roi_margin_percent)
        else:
            roi = self._restore_roi(
                frame.runtime.outer_bbox,
                rb_offset,
                frame.runtime.sx or 1.0,
                frame.runtime.sy or 1.0,
            )
            roi = self._expand_roi(roi, self.roi_margin_percent)
        for item in items:
            if not self._item_in_roi(item, roi, use_bbox=True):
                continue
            if self._match_any_text(item.text, self.anchor_texts):
                return True
        return False

    def _extract_a4_page_marker(self, frame: FrameMeta, items: list[TextItem]) -> None:
        """仅提取A4右上角页码，不做titleblock字段解析"""
        rb_offset = [0.0, 120.0, 255.0, 295.0]
        roi = self._restore_roi(
            frame.runtime.outer_bbox,
            rb_offset,
            frame.runtime.sx or 1.0,
            frame.runtime.sy or 1.0,
        )
        roi_items = [t for t in items if self._item_in_roi(t, roi, use_bbox=True)]
        frame.raw_extracts = {
            "A4_page_marker": [self._text_item_to_dict(t) for t in roi_items]
        }
        page_total, page_index = self._parse_page_marker_from_text(roi_items)
        if page_index is None:
            page_total, page_index = self._fallback_a4_page_marker(frame, items)
        if page_total is not None:
            frame.titleblock.page_total = page_total
        if page_index is not None:
            frame.titleblock.page_index = page_index

    def _parse_page_marker_from_text(
        self, items: list[TextItem]
    ) -> tuple[int | None, int | None]:
        joined = self._join_text(items)
        if joined:
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
        return None, None

    def _fallback_a4_page_marker(
        self, frame: FrameMeta, items: list[TextItem]
    ) -> tuple[int | None, int | None]:
        outer = frame.runtime.outer_bbox
        width = max(1e-6, outer.width)
        height = max(1e-6, outer.height)
        candidates: list[tuple[float, TextItem]] = []
        for item in items:
            if not item.text:
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
    def _item_in_roi(item: TextItem, roi: BBox, *, use_bbox: bool) -> bool:
        if roi.xmin <= item.x <= roi.xmax and roi.ymin <= item.y <= roi.ymax:
            return True
        if use_bbox and item.bbox:
            return roi.intersects(item.bbox)
        return False

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
        for cand in candidates:
            text = cand.upper().replace(" ", "")
            m = re_full.match(text)
            if not m:
                m = re_short.match(text)
            if not m:
                continue
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
        return None, None

    def _parse_external_code(
        self, items: list[TextItem], parse_cfg: dict[str, Any]
    ) -> str | None:
        fixed_len = int(parse_cfg.get("length", parse_cfg.get("fixed_len", 19)))
        header_hint = str(parse_cfg.get("header", "DOC.NO"))
        joined = self._join_text(items)
        cleaned = self._clean_alnum(joined.upper())
        header_clean = self._clean_alnum(header_hint.upper())
        if header_clean and cleaned.startswith(header_clean):
            cleaned = cleaned[len(header_clean) :]
        if len(cleaned) == fixed_len:
            return cleaned
        for i in range(0, max(0, len(cleaned) - fixed_len + 1)):
            sub = cleaned[i : i + fixed_len]
            if len(sub) == fixed_len:
                return sub
        rebuilt = self._rebuild_fixed19_from_single_chars(items, fixed_len, header_hint)
        return rebuilt

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
        self, items: list[TextItem], parse_cfg: dict[str, Any]
    ) -> tuple[int | None, int | None]:
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

        total_s, idx_s = self._page_info_two_tokens(items)
        if total_s is None or idx_s is None:
            return None, None
        total = int(total_s) if total_s.isdigit() else None
        idx = 1 if idx_s.upper() == "X" else int(idx_s) if idx_s.isdigit() else None
        return total, idx

    def _parse_title_bilingual(self, items: list[TextItem]) -> tuple[str | None, str | None]:
        if not items:
            return None, None
        lines = self._extract_title_lines(items)
        if not lines:
            return None, None
        cn_lines: list[str] = []
        en_lines: list[str] = []
        for line in lines:
            if self._has_cjk(line):
                cn_lines.append(self._normalize_spaces(line))
            else:
                en_lines.append(self._normalize_spaces(line))
        title_cn = self.line_join.join([ln for ln in cn_lines if ln]).strip()
        title_en = self.line_join.join([ln for ln in en_lines if ln]).strip()
        return (title_cn or None), (title_en or None)

    def _parse_text(self, items: list[TextItem]) -> str | None:
        joined = self._join_text(items)
        return joined or None

    def _pick_top_by_y(self, items: list[TextItem]) -> str | None:
        if not items:
            return None
        ordered = sorted(items, key=lambda t: (-t.y, t.x))
        for item in ordered:
            text = (item.text or "").strip()
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
        frags: list[tuple[float, float, str]] = []
        for it in items:
            text = (it.text or "").strip()
            if not text:
                continue
            parts = [p.strip() for p in text.splitlines() if p.strip()]
            if not parts:
                continue
            if len(parts) == 1:
                frags.append((it.y, it.x, parts[0]))
            else:
                for idx, part in enumerate(parts):
                    frags.append((it.y - idx * (self.y_cluster_abs * 0.1), it.x, part))

        frags.sort(key=lambda t: (-t[0], t[1]))
        lines: list[list[tuple[float, float, str]]] = []
        for y, x, text in frags:
            placed = False
            for line in lines:
                if abs(line[0][0] - y) <= self.y_cluster_abs:
                    line.append((y, x, text))
                    placed = True
                    break
            if not placed:
                lines.append([(y, x, text)])

        out: list[str] = []
        for line in lines:
            line.sort(key=lambda t: t[1])
            s = " ".join(seg[2] for seg in line if seg[2])
            s = self._normalize_spaces(s)
            if s:
                out.append(s)
        return out

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

    @staticmethod
    def _normalize_spaces(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").strip())

    @staticmethod
    def _normalize_anchor(text: str) -> str:
        return "".join(ch for ch in (text or "") if not ch.isspace())

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
    def _page_info_two_tokens(items: list[TextItem]) -> tuple[str | None, str | None]:
        tokens: list[tuple[float, str]] = []
        for it in items:
            s = TitleblockExtractor._clean_alnum((it.text or "").upper())
            if not s:
                continue
            if len(s) <= 4:
                tokens.append((it.x, s))
        tokens.sort(key=lambda t: t[0])
        if len(tokens) < 2:
            return None, None
        return tokens[0][1], tokens[1][1]

    def _rebuild_fixed19_from_single_chars(
        self, items: list[TextItem], fixed_len: int, header_hint: str
    ) -> str | None:
        header_clean = self._clean_alnum(header_hint.upper())
        header_xmax = None
        if header_clean:
            for it in items:
                it_clean = self._clean_alnum((it.text or "").upper())
                if header_clean and header_clean in it_clean:
                    xmax = it.bbox.xmax if it.bbox is not None else it.x
                    header_xmax = xmax if header_xmax is None else max(header_xmax, xmax)

        tokens: list[tuple[float, float, str]] = []
        for it in items:
            s = self._clean_alnum((it.text or "").upper())
            if len(s) == 1:
                if header_xmax is not None and it.x <= header_xmax + 1e-3:
                    continue
                tokens.append((it.x, it.y, s))
        tokens.sort(key=lambda t: t[0])
        if len(tokens) < fixed_len:
            return None
        selected = tokens if len(tokens) == fixed_len else tokens[-fixed_len:]
        return "".join(t[2] for t in selected)

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
