import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import ezdxf  # type: ignore
import yaml  # type: ignore


@dataclass
class Rect:
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @property
    def w(self) -> float:
        return self.xmax - self.xmin

    @property
    def h(self) -> float:
        return self.ymax - self.ymin

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)

    def contains_point(self, x: float, y: float) -> bool:
        # half-open to avoid double-counting items that lie exactly on shared borders of adjacent ROIs
        return self.xmin <= x < self.xmax and self.ymin <= y < self.ymax

    def intersects(self, other: "Rect") -> bool:
        return not (
            self.xmax < other.xmin
            or self.xmin > other.xmax
            or self.ymax < other.ymin
            or self.ymin > other.ymax
        )

    def expanded(self, pct: float) -> "Rect":
        """Expand rect by pct of its own width/height on each side."""
        if pct <= 0:
            return self
        dx = self.w * pct
        dy = self.h * pct
        return Rect(self.xmin - dx, self.ymin - dy, self.xmax + dx, self.ymax + dy)


@dataclass
class TextItem:
    x: float
    y: float
    text: str
    src: str
    bbox: Optional[Rect] = None


def load_spec(spec_path: Path) -> dict[str, Any]:
    data = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    return data


def get_titleblock_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """适配v2.0 YAML结构，优先尝试顶层titleblock_extract，兜底旧版sections路径"""
    if "titleblock_extract" in spec:
        return spec["titleblock_extract"]
    # 兜底旧版路径
    if "sections" in spec and "titleblock_extraction_spec" in spec["sections"]:
        return spec["sections"]["titleblock_extraction_spec"]
    raise KeyError("无法找到 titleblock_extract 或 sections.titleblock_extraction_spec")


def iter_text_items_in_space(space: Any) -> Iterable[TextItem]:
    def add_text_entity(e: Any, src: str) -> Optional[TextItem]:
        t = ""
        if e.dxftype() == "TEXT":
            t = (e.dxf.text or "").strip()
            p = e.dxf.insert
            x = float(p.x)
            y = float(p.y)
            # Approximate bbox to catch cases where insertion point is outside ROI but glyph box intersects ROI.
            try:
                h = float(getattr(e.dxf, "height", 2.5) or 2.5)
            except Exception:
                h = 2.5
            s0 = t.replace(" ", "")
            w = max(1, len(s0)) * h * 0.6
            hh = h * 1.2
            halign = int(
                getattr(e.dxf, "halign", 0) or 0
            )  # 0=left,1=center,2=right (common)
            valign = int(
                getattr(e.dxf, "valign", 0) or 0
            )  # 0=baseline,1=bottom,2=middle,3=top
            if halign == 1:
                xmin, xmax = x - w / 2, x + w / 2
            elif halign == 2:
                xmin, xmax = x - w, x
            else:
                xmin, xmax = x, x + w
            # baseline ~= bottom for our purpose
            if valign == 3:
                ymin, ymax = y - hh, y
            elif valign == 2:
                ymin, ymax = y - hh / 2, y + hh / 2
            else:
                ymin, ymax = y, y + hh
            return TextItem(
                x, y, t, src, bbox=Rect(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax)
            )
        if e.dxftype() == "MTEXT":
            try:
                t = (e.plain_text() or "").strip()
            except Exception:
                t = (e.text or "").strip()
            p = e.dxf.insert
            # Approximate bbox (good enough to catch right/center aligned MTEXT whose insertion point is outside ROI)
            try:
                char_h = float(
                    getattr(e.dxf, "char_height", getattr(e.dxf, "height", 2.5))
                )
            except Exception:
                char_h = 2.5
            lines = [ln for ln in t.splitlines() if ln.strip()] or [t]
            n_lines = max(1, len(lines))
            try:
                width = float(getattr(e.dxf, "width", 0.0) or 0.0)
            except Exception:
                width = 0.0
            if width <= 0:
                width = max(len(ln) for ln in lines) * char_h * 0.6
            height = n_lines * char_h * 1.2
            ap = int(getattr(e.dxf, "attachment_point", 1) or 1)
            x = float(p.x)
            y = float(p.y)
            # derive bbox from attachment point
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
            bbox = Rect(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax)
            return TextItem(x, y, t, src, bbox=bbox)
        if e.dxftype() == "ATTRIB":
            t = (e.dxf.text or "").strip()
            p = e.dxf.insert
            x = float(p.x)
            y = float(p.y)
            # Similar bbox approximation as TEXT
            try:
                h = float(getattr(e.dxf, "height", 2.5) or 2.5)
            except Exception:
                h = 2.5
            s0 = t.replace(" ", "")
            w = max(1, len(s0)) * h * 0.6
            hh = h * 1.2
            halign = int(getattr(e.dxf, "halign", 0) or 0)
            valign = int(getattr(e.dxf, "valign", 0) or 0)
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
            return TextItem(
                x, y, t, src, bbox=Rect(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax)
            )
        return None

    def walk_entity(ent: Any, src_prefix: str, depth: int) -> Iterable[TextItem]:
        if depth > 8:
            return
        tp = ent.dxftype()
        if tp in {"TEXT", "MTEXT", "ATTRIB"}:
            item = add_text_entity(ent, f"{src_prefix}:{tp}")
            if item and item.text:
                yield item
            return
        if tp == "INSERT":
            # attributes on insert
            try:
                for a in ent.attribs:
                    item = add_text_entity(a, f"{src_prefix}:attrib")
                    if item and item.text:
                        yield item
            except Exception:
                pass
            # virtual entities (may include nested INSERT)
            try:
                for ve in ent.virtual_entities():
                    for x in walk_entity(ve, f"{src_prefix}:virtual", depth + 1):
                        yield x
            except Exception:
                pass

    for e in space:
        for item in walk_entity(e, "space", 0):
            yield item


def parse_rev_table_field(
    *,
    field: str,
    roi_items: list[TextItem],
    y_tol: float,
    expected_revision: Optional[str],
) -> dict[str, Any]:
    """
    Revision table cells sometimes contain combined row text like: "A 2025.12 CFC".
    We parse by row (y clustering), and then extract only the needed column (date/status)
    preferring the row whose rev matches expected_revision.
    """
    import re

    if field not in {"date", "status"}:
        return {
            "ok": True,
            "value": "",
            "raw": "",
            "note": "unsupported_rev_table_field",
        }

    lines = cluster_lines(roi_items, y_tol=y_tol)
    row_texts: list[tuple[float, str]] = []
    for line in lines:
        y = sum(it.y for it in line) / max(1, len(line))
        s = " ".join(it.text for it in line if it.text).strip()
        s = " ".join(s.split())
        if s:
            row_texts.append((y, s))

    # bottom first = latest
    row_texts.sort(key=lambda t: t[0])

    re_full = re.compile(
        r"^(?P<rev>[A-Z])\s+(?P<date>\d{4}\.\d{2})\s+(?P<status>[A-Z0-9]+)$"
    )
    re_date_status = re.compile(r"^(?P<date>\d{4}\.\d{2})\s+(?P<status>[A-Z0-9]+)$")
    re_date_only = re.compile(r"^(?P<date>\d{4}\.\d{2})$")
    re_status_only = re.compile(r"^(?P<status>[A-Z0-9]+)$")

    parsed_rows: list[dict[str, Any]] = []
    for y, s in row_texts:
        m = re_full.match(s)
        if m:
            parsed_rows.append(
                {
                    "y": y,
                    "raw": s,
                    "rev": m.group("rev"),
                    "date": m.group("date"),
                    "status": m.group("status"),
                }
            )
            continue
        m = re_date_status.match(s)
        if m:
            parsed_rows.append(
                {
                    "y": y,
                    "raw": s,
                    "rev": None,
                    "date": m.group("date"),
                    "status": m.group("status"),
                }
            )
            continue
        m = re_date_only.match(s)
        if m:
            parsed_rows.append(
                {"y": y, "raw": s, "rev": None, "date": m.group("date"), "status": None}
            )
            continue
        m = re_status_only.match(s)
        if m:
            parsed_rows.append(
                {
                    "y": y,
                    "raw": s,
                    "rev": None,
                    "date": None,
                    "status": m.group("status"),
                }
            )
            continue

    # choose best row by revision match first, else latest row that has the requested field
    chosen = None
    if expected_revision:
        for r in parsed_rows:
            if r.get("rev") == expected_revision and r.get(field):
                chosen = r
    if chosen is None:
        for r in reversed(parsed_rows):
            if r.get(field):
                chosen = r
                break

    if chosen is None:
        return {
            "ok": False,
            "value": None,
            "raw": join_text(roi_items, y_tol=y_tol, line_join="\n"),
            "error": "rev_table_no_match",
        }

    return {
        "ok": True,
        "value": chosen.get(field),
        "raw": chosen.get("raw", ""),
        "note": "rev_table_row_parse",
        "revision_ref": expected_revision,
    }


def clean_alnum(text: str) -> str:
    return "".join(ch for ch in text if ("A" <= ch <= "Z") or ("0" <= ch <= "9"))


def normalize_for_anchor(text: str) -> str:
    # remove all whitespace and common separators; keep CJK + ASCII letters/numbers
    t = "".join(ch for ch in (text or "") if not ch.isspace())
    return t.upper()


def cluster_lines(items: list[TextItem], y_tol: float) -> list[list[TextItem]]:
    # group by y proximity
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
    # sort each line by x
    for line in lines:
        line.sort(key=lambda it: it.x)
    return lines


def join_text(items: list[TextItem], y_tol: float, line_join: str) -> str:
    lines = cluster_lines(items, y_tol=y_tol)
    joined_lines: list[str] = []
    for line in lines:
        s = " ".join(t.text for t in line if t.text)
        s = " ".join(s.split())
        if s:
            joined_lines.append(s)
    return line_join.join(joined_lines).strip()


def extract_fixed19_from_single_chars(
    items: list[TextItem],
    *,
    fixed_len: int = 19,
    header_hint: str | None = None,
) -> tuple[Optional[str], list[dict[str, Any]]]:
    """
    For 'DOC.NO' style grids where each character is a separate TEXT,
    rebuild the fixed-length code by sorting single-char tokens by x.
    """
    header_xmax: Optional[float] = None
    header_clean = clean_alnum((header_hint or "").upper())
    if header_clean:
        for it in items:
            it_clean = clean_alnum((it.text or "").upper())
            if header_clean and header_clean in it_clean:
                xmax = it.bbox.xmax if it.bbox is not None else it.x
                header_xmax = xmax if header_xmax is None else max(header_xmax, xmax)

    toks: list[tuple[float, float, str, str]] = []  # x,y,char,src
    for it in items:
        s = clean_alnum(it.text.upper())
        if len(s) == 1:
            # Exclude header region chars if we found a header bbox (DOC.NO is to the LEFT of the 19 cells)
            if header_xmax is not None and it.x <= header_xmax + 1e-3:
                continue
            toks.append((it.x, it.y, s, it.src))

    toks.sort(key=lambda t: t[0])
    debug = [{"ch": t[2], "x": t[0], "y": t[1], "src": t[3]} for t in toks]

    if len(toks) < fixed_len:
        return None, debug

    # If we still have extra tokens (rare, e.g. header split into single chars), take right-most fixed_len.
    selected = toks if len(toks) == fixed_len else toks[-fixed_len:]
    code = "".join(t[2] for t in selected)
    return code, debug


def extract_page_info_two_tokens_by_x(
    roi_items: list[TextItem],
) -> tuple[Optional[str], Optional[str]]:
    """
    Many DXFs draw the labels "共/张/第/张" as graphics, leaving only two variable cells as text.
    Rule: left token = page_total, right token = page_index. Tokens are sorted by x.
    """
    toks: list[tuple[float, str]] = []
    for it in roi_items:
        s = clean_alnum((it.text or "").upper())
        if not s:
            continue
        # keep small tokens only (avoid swallowing other long strings if ROI is slightly off)
        if len(s) <= 4:
            toks.append((it.x, s))
    toks.sort(key=lambda t: t[0])
    if len(toks) < 2:
        return None, None
    return toks[0][1], toks[1][1]


def pick_top_text_by_y(
    roi_items: list[TextItem], *, max_candidates: int = 20
) -> tuple[Optional[str], list[dict[str, Any]]]:
    """
    Pick the top-most (max y) text item in ROI, using insertion point only.
    Returns (selected_text, candidates_debug_sorted_by_y_desc).
    """
    cands = sorted(roi_items, key=lambda it: (-it.y, it.x))
    debug = [
        {"text": (it.text or "").strip(), "x": it.x, "y": it.y, "src": it.src}
        for it in cands[:max_candidates]
    ]
    for it in cands:
        s = (it.text or "").strip()
        if s:
            return s, debug
    return None, debug


def has_cjk(s: str) -> bool:
    for ch in s:
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF:
            return True
    return False


def extract_text_lines_for_title(
    roi_items: list[TextItem], *, y_tol: float
) -> list[str]:
    """
    Build "text lines" from ROI items:
    - Treat each TEXT/ATTRIB as one line fragment.
    - Treat MTEXT as one or multiple line fragments split by '\\n'.
    - Cluster fragments by y, then within each line sort by x and join with spaces.
    """
    frags: list[tuple[float, float, str]] = []
    for it in roi_items:
        t = (it.text or "").strip()
        if not t:
            continue
        parts = [p.strip() for p in t.splitlines() if p.strip()]
        if not parts:
            continue
        if len(parts) == 1:
            frags.append((it.y, it.x, parts[0]))
        else:
            # Preserve internal order top->bottom within one MTEXT by nudging y slightly
            for idx, p in enumerate(parts):
                frags.append((it.y - idx * (y_tol * 0.1), it.x, p))

    frags.sort(key=lambda t: (-t[0], t[1]))
    lines: list[list[tuple[float, float, str]]] = []
    for y, x, s in frags:
        placed = False
        for line in lines:
            if abs(line[0][0] - y) <= y_tol:
                line.append((y, x, s))
                placed = True
                break
        if not placed:
            lines.append([(y, x, s)])

    out: list[str] = []
    for line in lines:
        line.sort(key=lambda t: t[1])
        s = " ".join(t[2] for t in line if t[2])
        s = " ".join(s.split())
        if s:
            out.append(s)
    return out


def split_title_cn_en(lines: list[str]) -> tuple[str, str, list[str], list[str]]:
    cn_lines: list[str] = []
    en_lines: list[str] = []
    for ln in lines:
        if has_cjk(ln):
            cn_lines.append(ln)
        else:
            # treat pure ascii/digits/symbol lines as english candidate
            en_lines.append(ln)
    title_cn = "\n".join(cn_lines).strip()
    title_en = "\n".join(en_lines).strip()
    return title_cn, title_en, cn_lines, en_lines


def rect_from_rb_offset(
    *,
    outer: Rect,
    rb_offset: list[float],
    sx: float,
    sy: float,
) -> Rect:
    # rb_offset = [dx_right, dx_left, dy_bottom, dy_top]
    dx_right, dx_left, dy_bottom, dy_top = rb_offset
    outer_xmax = outer.xmax
    outer_ymin = outer.ymin
    xmin = outer_xmax - dx_left * sx
    xmax = outer_xmax - dx_right * sx
    ymin = outer_ymin + dy_bottom * sy
    ymax = outer_ymin + dy_top * sy
    return Rect(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax)


def expand_rect(r: Rect, *, base: Rect, margin_percent: float) -> Rect:
    """Expand ROI by a margin expressed as a percentage of the ROI size."""
    if margin_percent <= 0:
        return r
    dx = r.w * margin_percent
    dy = r.h * margin_percent
    return Rect(xmin=r.xmin - dx, ymin=r.ymin - dy, xmax=r.xmax + dx, ymax=r.ymax + dy)


def find_outer_frames_in_space(space: Any) -> list[Rect]:
    frames: list[Rect] = []
    segments: list[
        tuple[float, float, float, float, float]
    ] = []  # (x1,y1,x2,y2,length)
    for e in space:
        if e.dxftype() == "LWPOLYLINE":
            try:
                pts = [(float(p[0]), float(p[1])) for p in e.get_points("xy")]
            except Exception:
                continue
            if len(pts) < 2:
                continue
            if len(pts) == 2:
                (x1, y1), (x2, y2) = pts
                length = math.hypot(x2 - x1, y2 - y1)
                segments.append((x1, y1, x2, y2, length))
                continue
            if len(pts) < 4:
                # ignore small polylines with 3 vertices
                continue
            is_closed = False
            try:
                is_closed = bool(e.closed)
            except Exception:
                is_closed = False
            # some DXF have polylines that are geometrically closed but the flag isn't set
            if not is_closed:
                x0, y0 = pts[0]
                x1, y1 = pts[-1]
                if abs(x0 - x1) < 1e-3 and abs(y0 - y1) < 1e-3:
                    is_closed = True
            if not is_closed:
                # still accept as candidate (some frames are drawn as open polylines)
                pass
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            r = Rect(min(xs), min(ys), max(xs), max(ys))
            # basic sanity: must be reasonably large
            if r.area > 1.0:
                frames.append(r)
        # TODO: POLYLINE(closed) / LINE clusters if needed

    # Reconstruct a large outer frame bbox from long axis-aligned segments (many DXF store frame as 2-point polylines).
    if segments:
        # keep near-axis-aligned long segments
        axis_tol = 1e-3
        max_len = max(s[4] for s in segments)
        long_thresh = max_len * 0.6
        pts2: list[tuple[float, float]] = []
        for x1, y1, x2, y2, ln in segments:
            if ln < long_thresh:
                continue
            if abs(y2 - y1) < axis_tol or abs(x2 - x1) < axis_tol:
                pts2.append((x1, y1))
                pts2.append((x2, y2))
        if pts2:
            xs = [p[0] for p in pts2]
            ys = [p[1] for p in pts2]
            r = Rect(min(xs), min(ys), max(xs), max(ys))
            if r.area > 1.0:
                frames.append(r)

    frames.sort(key=lambda r: r.area, reverse=True)
    return frames


def text_in_rect(items: list[TextItem], r: Rect) -> list[TextItem]:
    return [
        t
        for t in items
        if r.contains_point(t.x, t.y) or (t.bbox is not None and r.intersects(t.bbox))
    ]


def has_anchor_combo(items: list[TextItem]) -> tuple[bool, int, int]:
    """Return (has_both, company_count, cnpe_count) within given items."""
    company = 0
    cnpe = 0
    for t in items:
        nt = normalize_for_anchor(t.text)
        if "中国核电工程有限公司" in nt:
            company += 1
        if "CNPE" in nt:
            cnpe += 1
    return (company > 0 and cnpe > 0), company, cnpe


def fit_scale(
    *,
    outer: Rect,
    canonical_variants: dict[str, Any],
    fit_method: dict[str, Any],
) -> dict[str, Any]:
    allow_rotation = bool(fit_method.get("allow_rotation", True))
    uniform_required = bool(fit_method.get("uniform_scale_required", True))
    uniform_tol = float(fit_method.get("uniform_scale_tol_rel", 0.02))

    best: Optional[dict[str, Any]] = None

    def score_fit(
        Wc: float, Hc: float, rotated: bool
    ) -> tuple[float, float, float, float]:
        sx = outer.w / Wc
        sy = outer.h / Hc
        geom_scale = (sx + sy) / 2.0
        max_rel_err = max(
            abs(outer.w - Wc * sx) / max(1e-9, outer.w),
            abs(outer.h - Hc * sy) / max(1e-9, outer.h),
        )
        # uniformity
        if geom_scale == 0:
            uni = 1e9
        else:
            uni = abs(sx - sy) / geom_scale
        if uniform_required and uni > uniform_tol:
            return (1e9, sx, sy, geom_scale)
        # score by max_rel_err + small penalty for non-uniformity
        return (max_rel_err + uni * 0.1, sx, sy, geom_scale)

    for vid, v in canonical_variants.items():
        Wc = float(v["W"])
        Hc = float(v["H"])
        # normal
        s, sx, sy, geom = score_fit(Wc, Hc, False)
        cand = {
            "paper_variant_id": vid,
            "sx": sx,
            "sy": sy,
            "geom_scale_factor": geom,
            "score": s,
            "rotated": False,
        }
        if best is None or cand["score"] < best["score"]:
            best = cand
        if allow_rotation:
            s2, sx2, sy2, geom2 = score_fit(Hc, Wc, True)
            cand2 = {
                "paper_variant_id": vid,
                "sx": sx2,
                "sy": sy2,
                "geom_scale_factor": geom2,
                "score": s2,
                "rotated": True,
            }
            if best is None or cand2["score"] < best["score"]:
                best = cand2

    assert best is not None
    best["roi_profile_id_default"] = canonical_variants[best["paper_variant_id"]][
        "roi_profile_id_default"
    ]
    return best


def parse_field(var_name: str, raw: str, parse_cfg: dict[str, Any]) -> dict[str, Any]:
    t = (raw or "").strip()
    ptype = parse_cfg.get("type")
    if ptype == "internal_code_cnpe":
        import re

        patterns = parse_cfg.get("patterns") or {}
        full_pat = (
            patterns.get("full")
            or r"^(?P<prefix>[A-Z0-9]{7})-(?P<mid>[A-Z0-9]{5})-(?P<seq>[0-9]{3})$"
        )
        short_pat = (
            patterns.get("short") or r"^(?P<prefix>[A-Z0-9]{7})-(?P<mid>[A-Z0-9]{5})$"
        )
        mid_album_pat = (
            patterns.get("mid_album") or r"^(?P<mid3>[A-Z0-9]{3})(?P<album>[0-9]{2})$"
        )

        m = re.match(full_pat, t)
        kind = "full" if m else None
        if not m:
            m = re.match(short_pat, t)
            kind = "short" if m else None
        if not m:
            return {
                "ok": False,
                "value": None,
                "raw": t,
                "error": "internal_code_no_match",
            }

        prefix = m.group("prefix") if "prefix" in m.groupdict() else None
        mid = m.group("mid") if "mid" in m.groupdict() else None
        out: dict[str, Any] = {
            "ok": True,
            "value": m.group(0),
            "raw": t,
            "variant": kind,
        }
        if prefix and mid:
            out["internal_code_base"] = f"{prefix}-{mid}"
            mm = re.match(mid_album_pat, mid)
            if mm:
                out["album_code"] = mm.group("album")
        if kind == "full":
            try:
                out["internal_code_seq"] = int(m.group("seq"))
            except Exception:
                out["internal_code_seq"] = m.groupdict().get("seq")
        return out

    if ptype == "derived_from_internal_code_album_code":
        # This parse type is handled in a post-pass (needs internal_code parse result).
        return {
            "ok": False,
            "value": None,
            "raw": t,
            "error": "derived_field_requires_postpass",
        }

    if ptype == "page_info_auto":
        import re

        # 1) try phrase regex (if the static labels are extractable as text)
        pattern = parse_cfg.get("pattern")
        if pattern:
            m = re.search(str(pattern), t)
            if m:
                out: dict[str, Any] = {"ok": True, "value": m.group(0), "raw": t}
                if "output" in parse_cfg and isinstance(parse_cfg["output"], dict):
                    out_map = parse_cfg["output"]
                    for k, group_idx in out_map.items():
                        try:
                            out[k] = (
                                float(m.group(int(group_idx)))
                                if "." in m.group(int(group_idx))
                                else int(m.group(int(group_idx)))
                            )
                        except Exception:
                            out[k] = m.group(int(group_idx))
                return out

        # 2) fallback: many DXFs only have two variable cells inside ROI, e.g. "1" and "X"
        parts: list[str] = []
        for ln in t.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            # keep A-Z/0-9 and X, drop other chars
            s = "".join(
                ch for ch in ln.upper() if ("A" <= ch <= "Z") or ("0" <= ch <= "9")
            )
            if s:
                parts.append(s)
        if len(parts) >= 2:
            total_s, idx_s = parts[0], parts[1]
            try:
                total = int(total_s)
            except Exception:
                total = total_s
            try:
                idx = int(idx_s)
            except Exception:
                idx = idx_s
            return {
                "ok": True,
                "value": None,
                "raw": t,
                "page_total": total,
                "page_index": idx,
                "note": "page_info_two_tokens_fallback",
            }
        return {"ok": False, "value": None, "raw": t, "error": "page_info_no_match"}

    if ptype == "regex":
        import re

        pattern = parse_cfg["pattern"]
        m = re.search(pattern, t)
        if not m:
            return {"ok": False, "value": None, "raw": t, "error": "regex_no_match"}
        out: dict[str, Any] = {"ok": True, "value": m.group(0), "raw": t}
        # special output mapping
        if "output" in parse_cfg and isinstance(parse_cfg["output"], dict):
            out_map = parse_cfg["output"]
            for k, group_idx in out_map.items():
                try:
                    out[k] = (
                        float(m.group(int(group_idx)))
                        if "." in m.group(int(group_idx))
                        else int(m.group(int(group_idx)))
                    )
                except Exception:
                    out[k] = m.group(int(group_idx))
        return out

    if ptype == "docno_plus_fixed19":
        fixed_len = int(parse_cfg.get("fixed_len", 19))
        s = clean_alnum(t.upper())
        if len(s) == fixed_len:
            return {"ok": True, "value": s, "raw": t}
        # try find substring
        for i in range(0, max(0, len(s) - fixed_len + 1)):
            sub = s[i : i + fixed_len]
            if len(sub) == fixed_len:
                return {"ok": True, "value": sub, "raw": t}
        return {
            "ok": False,
            "value": None,
            "raw": t,
            "error": f"fixed_len_{fixed_len}_not_found",
            "clean": s,
        }

    if ptype in {"text", "text_exact_or_lexicon"}:
        return {"ok": True, "value": t, "raw": t}

    if ptype == "text_multiline":
        return {"ok": True, "value": t, "raw": t}

    if ptype in {"latest_nonempty_in_column", "latest_nonempty_in_column_or_text"}:
        parts = [ln.strip() for ln in t.splitlines() if ln.strip()]
        return {"ok": True, "value": (parts[-1] if parts else ""), "raw": t}

    return {"ok": True, "value": t, "raw": t, "note": f"unhandled_parse_type:{ptype}"}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Test DXF ROI extraction against documents/参数规范.yaml."
    )
    ap.add_argument(
        "--dxf",
        default="dxf/A0.dxf",
        help="DXF file path OR a directory containing sample DXFs",
    )
    ap.add_argument(
        "--dxf-kind",
        default="a0",
        help="When --dxf is a directory, pick which sample to use: a0/titleblock/frameset/mix (default: a0)",
    )
    ap.add_argument("--spec", default="documents/参数规范.yaml", help="Spec YAML path")
    ap.add_argument(
        "--out",
        default="documents/dxf_roi_test_report_A0.json",
        help="Output report JSON path",
    )
    ap.add_argument(
        "--topn",
        type=int,
        default=5,
        help="Top-N outer frame candidates by area to test",
    )
    ap.add_argument(
        "--mode",
        default="debug",
        choices=["debug", "summary"],
        help="debug: full report with ROI details; summary: only key results",
    )
    args = ap.parse_args()

    dxf_path = Path(args.dxf)
    spec_path = Path(args.spec)
    out_path = Path(args.out)

    if spec_path.is_dir():
        # Avoid passing non-ASCII filenames via CLI on some Windows terminals.
        candidate = spec_path / "参数规范.yaml"
        if candidate.exists():
            spec_path = candidate
        else:
            raise SystemExit(
                f"Could not find 参数规范.yaml under directory: {spec_path}"
            )

    spec = load_spec(spec_path)
    tb = get_titleblock_spec(spec)

    if dxf_path.is_dir():
        kind = str(args.dxf_kind).strip().lower()
        mapping = {
            "a0": "A0.dxf",
            "titleblock": "图签.dxf",
            "frameset": "图框合集.dxf",
            "mix": "图框组合1-100.dxf",
        }
        fname = mapping.get(kind, "A0.dxf")
        cand = dxf_path / fname
        if not cand.exists():
            # fallback: first .dxf file
            dxfs = sorted(dxf_path.glob("*.dxf"))
            if not dxfs:
                raise SystemExit(f"No .dxf files found under directory: {dxf_path}")
            cand = dxfs[0]
        dxf_path = cand

    doc = ezdxf.readfile(str(dxf_path))

    canonical_variants = tb["scale_fit"]["canonical_variants"]
    fit_method = tb["scale_fit"]["fit_method"]
    roi_profiles = tb["roi_profiles"]
    anchor_cfg = tb["anchor"]
    field_defs = tb["field_definitions"]
    tol = tb["tolerance"]
    y_tol = float(tol["text_grouping"]["y_cluster_abs"])
    line_join = tol["text_grouping"]["line_join"]
    roi_margin_percent = float(tol.get("roi_margin_percent", 0.0))
    scale_tol_abs = float(tol["scale_mismatch"]["abs_tol"])
    scale_tol_rel = float(tol["scale_mismatch"]["rel_tol"])
    flag_name = tol["scale_mismatch"]["flag_name"]

    # Collect candidates from all layouts (Model + paper layouts)
    spaces: list[tuple[str, Any]] = [("Model", doc.modelspace())]
    try:
        for name in doc.layouts.names():
            if name == "Model":
                continue
            try:
                layout = doc.layouts.get(
                    name
                )  # safer than doc.layout(name) across ezdxf versions
            except Exception:
                layout = None
            if layout is None:
                continue
            spaces.append((name, layout))
    except Exception:
        pass

    all_candidates: list[tuple[str, Rect]] = []
    text_by_space: dict[str, list[TextItem]] = {}
    diagnostics_by_space: dict[str, Any] = {}
    for space_name, space in spaces:
        if space is None:
            continue
        items = list(iter_text_items_in_space(space))
        text_by_space[space_name] = items

        # Diagnostics: where are key texts globally (helps decide ROI mismatch vs. missing data)
        import re

        # internal_code may have multiple compatible patterns
        if field_defs["internal_code"]["parse"].get("type") == "internal_code_cnpe":
            pats = field_defs["internal_code"]["parse"].get("patterns") or {}
            re_internal_full = re.compile(
                pats.get("full", r"^[A-Z0-9]{7}-[A-Z0-9]{5}-[0-9]{3}$")
            )
            re_internal_short = re.compile(
                pats.get("short", r"^[A-Z0-9]{7}-[A-Z0-9]{5}$")
            )
        else:
            re_internal_full = re.compile(
                field_defs["internal_code"]["parse"]["pattern"]
            )
            re_internal_short = re_internal_full
        re_engineering = re.compile(field_defs["engineering_no"]["parse"]["pattern"])
        re_scale = re.compile(field_defs["scale_text"]["parse"]["pattern"])
        re_page = re.compile(field_defs["page_info"]["parse"]["pattern"])

        anchor_text_items = [
            t
            for t in items
            if any(s in t.text for s in anchor_cfg["search_text_any_of"])
        ]
        external19 = []
        internal = []
        engineering = []
        scale = []
        page = []
        for t in items:
            al = clean_alnum(t.text.upper())
            if len(al) == 19:
                external19.append({"value": al, "x": t.x, "y": t.y, "src": t.src})
            if re_internal_full.search(t.text.strip()) or re_internal_short.search(
                t.text.strip()
            ):
                internal.append(
                    {"value": t.text.strip(), "x": t.x, "y": t.y, "src": t.src}
                )
            if re_engineering.search(t.text.strip()):
                engineering.append(
                    {"value": t.text.strip(), "x": t.x, "y": t.y, "src": t.src}
                )
            if re_scale.search(t.text.strip()):
                scale.append(
                    {"value": t.text.strip(), "x": t.x, "y": t.y, "src": t.src}
                )
            if re_page.search(t.text.strip()):
                page.append({"value": t.text.strip(), "x": t.x, "y": t.y, "src": t.src})

        diagnostics_by_space[space_name] = {
            "anchor_text_items": [
                {"x": t.x, "y": t.y, "text": t.text, "src": t.src}
                for t in anchor_text_items
            ],
            "external19_candidates_top20": external19[:20],
            "internal_code_candidates_top20": internal[:20],
            "engineering_no_candidates_top20": engineering[:20],
            "scale_text_candidates_top20": scale[:20],
            "page_info_candidates_top20": page[:20],
        }

        frames = find_outer_frames_in_space(space)
        # take top-n per space (avoid modelspace giant frame dominating everything)
        for r in frames[: args.topn]:
            all_candidates.append((space_name, r))

    report: dict[str, Any] = {
        "dxf": str(dxf_path),
        "spec": str(spec_path),
        "text_items_count_by_space": {k: len(v) for k, v in text_by_space.items()},
        "diagnostics_by_space": diagnostics_by_space,
        "anchor_global_combo_count_by_space": {},
        "outer_frame_candidates": [],
    }

    # Step 1 (per user): count global anchor combos (CNPE + 中国核电工程有限公司) per space
    for space_name, items in text_by_space.items():
        ok, cc, nc = has_anchor_combo(items)
        report["anchor_global_combo_count_by_space"][space_name] = {
            "has_combo": ok,
            "company_count": cc,
            "cnpe_count": nc,
        }

    # Evaluate all candidates; later you can focus on anchor_ok ones.
    for idx, (space_name, outer) in enumerate(all_candidates):
        fit = fit_scale(
            outer=outer, canonical_variants=canonical_variants, fit_method=fit_method
        )
        sx = float(fit["sx"])
        sy = float(fit["sy"])
        profile_id = fit["roi_profile_id_default"]
        profile = roi_profiles[profile_id]

        texts = text_by_space.get(space_name, [])
        # Step 2 (per user): if anchor match fails, expand search range progressively until found.
        # We start from the candidate outer frame bbox (not ROI) to decide whether this candidate corresponds to an anchor combo.
        anchor_search_steps: list[dict[str, Any]] = []
        anchor_combo_ok = False
        company_cnt = 0
        cnpe_cnt = 0
        search_rect = outer
        for step_i in range(0, 8):
            step_rect = search_rect if step_i == 0 else outer.expanded(0.05 * step_i)
            step_items = text_in_rect(texts, step_rect)
            ok2, cc2, nc2 = has_anchor_combo(step_items)
            anchor_search_steps.append(
                {
                    "step": step_i,
                    "rect": step_rect.__dict__,
                    "items_count": len(step_items),
                    "has_combo": ok2,
                    "company_count": cc2,
                    "cnpe_count": nc2,
                }
            )
            if ok2:
                anchor_combo_ok = True
                company_cnt, cnpe_cnt = cc2, nc2
                break

        # anchor ROI name can vary; try all ROI boxes that contain "图框定位"
        anchor_hits: list[dict[str, Any]] = []
        for roi_name, rb in profile["fields_rb_offset_1to1"].items():
            if "图框定位" not in roi_name:
                continue
            roi = rect_from_rb_offset(
                outer=outer, rb_offset=[float(x) for x in rb], sx=sx, sy=sy
            )
            roi = expand_rect(roi, base=outer, margin_percent=roi_margin_percent)
            roi_items = [
                t
                for t in texts
                if roi.contains_point(t.x, t.y)
                or (t.bbox is not None and roi.intersects(t.bbox))
            ]
            joined = join_text(roi_items, y_tol=y_tol, line_join=line_join)
            # allow spaces inside Chinese anchor text
            nj = normalize_for_anchor(joined)
            hit = any(
                normalize_for_anchor(s) in nj for s in anchor_cfg["search_text_any_of"]
            )
            anchor_hits.append(
                {
                    "roi_name": roi_name,
                    "roi": roi.__dict__,
                    "text": joined,
                    "hit": hit,
                    "count": len(roi_items),
                }
            )

        anchor_ok = any(x["hit"] for x in anchor_hits) if anchor_hits else False

        # field extraction
        extracted: dict[str, Any] = {}
        debug_rois: dict[str, Any] = {}
        for var, fd in field_defs.items():
            # Derived fields (no ROI): postpone to post-pass
            if (
                fd.get("parse", {}).get("type")
                == "derived_from_internal_code_album_code"
            ):
                continue
            # system_no removed -> may appear as comment only; skip non-dict
            if not isinstance(fd, dict):
                continue
            roi_field_name = fd.get("extract_roi_field_name")
            if not roi_field_name:
                continue
            rb = profile["fields_rb_offset_1to1"].get(roi_field_name)
            if rb is None:
                extracted[var] = {
                    "ok": False,
                    "value": None,
                    "error": f"roi_not_found:{roi_field_name}",
                }
                continue
            roi = rect_from_rb_offset(
                outer=outer, rb_offset=[float(x) for x in rb], sx=sx, sy=sy
            )
            # Adjacent revision-table columns (版次/状态/日期) share borders; expanding ROI can cause cross-contamination.
            effective_margin = (
                0.0 if var in {"revision", "status", "date"} else roi_margin_percent
            )
            roi = expand_rect(roi, base=outer, margin_percent=effective_margin)
            # Important: for revision-table columns and page_info cells, users expect STRICT "in-ROI" behavior.
            # Using approximate bbox intersection can falsely pull neighbor-column texts due to alignment/width heuristics.
            point_only_vars = {"revision", "status", "date", "page_info"}
            if var in point_only_vars:
                roi_items = [t for t in texts if roi.contains_point(t.x, t.y)]
            else:
                roi_items = [
                    t
                    for t in texts
                    if roi.contains_point(t.x, t.y)
                    or (t.bbox is not None and roi.intersects(t.bbox))
                ]
            raw_text = join_text(roi_items, y_tol=y_tol, line_join=line_join)

            # Title bilingual split: compute title_cn + title_en from the same ROI, no extra ROI.
            if fd.get("parse", {}).get("type") == "title_bilingual_split":
                if "title_cn" not in extracted or "title_en" not in extracted:
                    lines = extract_text_lines_for_title(roi_items, y_tol=y_tol)
                    cn, en, cn_lines, en_lines = split_title_cn_en(lines)
                    extracted["title_cn"] = {
                        "ok": bool(cn),
                        "value": cn if cn else None,
                        "raw": "\n".join(lines),
                        "note": "title_bilingual_split",
                        "cn_lines": cn_lines,
                    }
                    extracted["title_en"] = {
                        "ok": bool(en),
                        "value": en if en else None,
                        "raw": "\n".join(lines),
                        "note": "title_bilingual_split",
                        "en_lines": en_lines,
                    }
                    # record ROI debug once
                    debug_rois["title_cn"] = {
                        "roi_field_name": roi_field_name,
                        "roi": roi.__dict__,
                        "raw": "\n".join(lines),
                        "count": len(roi_items),
                    }
                    debug_rois["title_en"] = {
                        "roi_field_name": roi_field_name,
                        "roi": roi.__dict__,
                        "raw": "\n".join(lines),
                        "count": len(roi_items),
                    }
                continue

            # Rule: for revision/date/status columns, user requires picking the top-most (highest y) text in the column.
            if var in {"revision", "date", "status"}:
                top, cand_debug = pick_top_text_by_y(roi_items)
                parsed = {
                    "ok": bool(top),
                    "value": top,
                    "raw": raw_text,
                    "note": "pick_top_by_y",
                    "candidates": cand_debug,
                }
                extracted[var] = parsed
                debug_rois[var] = {
                    "roi_field_name": roi_field_name,
                    "roi": roi.__dict__,
                    "raw": raw_text,
                    "count": len(roi_items),
                }
                continue

            # Special: external_code is often stored as 19 separate single-char texts in cells.
            if (
                var == "external_code"
                and fd.get("parse", {}).get("type") == "docno_plus_fixed19"
            ):
                fixed_len = int(fd.get("parse", {}).get("fixed_len", 19))
                rebuilt, rebuilt_debug = extract_fixed19_from_single_chars(
                    roi_items,
                    fixed_len=fixed_len,
                    header_hint=str(fd.get("parse", {}).get("header", "DOC.NO")),
                )
                if rebuilt and len(rebuilt) == fixed_len:
                    parsed = {
                        "ok": True,
                        "value": rebuilt,
                        "raw": raw_text,
                        "note": "rebuilt_from_single_chars",
                        "rebuilt_tokens_debug": rebuilt_debug,
                    }
                else:
                    parsed = parse_field(var, raw_text, fd.get("parse", {}))
            # Special: page_info often only has two variable cells as text; sort by x: left=total, right=index
            elif (
                var == "page_info"
                and fd.get("parse", {}).get("type") == "page_info_auto"
            ):
                total_s, idx_s = extract_page_info_two_tokens_by_x(roi_items)
                if total_s is not None and idx_s is not None:
                    try:
                        total_v: Any = int(total_s)
                    except Exception:
                        total_v = total_s
                    try:
                        idx_v: Any = int(idx_s)
                    except Exception:
                        idx_v = idx_s
                    parsed = {
                        "ok": True,
                        "value": f"共{total_s}张 第{idx_s}张",
                        "raw": raw_text,
                        "page_total": total_v,
                        "page_index": idx_v,
                        "note": "page_info_two_tokens_by_x",
                    }
                else:
                    parsed = parse_field(var, raw_text, fd.get("parse", {}))
            else:
                parsed = parse_field(var, raw_text, fd.get("parse", {}))
            extracted[var] = parsed
            debug_rois[var] = {
                "roi_field_name": roi_field_name,
                "roi": roi.__dict__,
                "raw": raw_text,
                "count": len(roi_items),
            }
        # Post-pass: derive album_code from internal_code (no new ROI)
        if "album_code" in field_defs:
            fd = field_defs["album_code"]
            if (
                fd.get("parse", {}).get("type")
                == "derived_from_internal_code_album_code"
            ):
                ic = extracted.get("internal_code")
                if isinstance(ic, dict) and ic.get("ok"):
                    ac = ic.get("album_code")
                    ok = bool(ac)
                    extracted["album_code"] = {
                        "ok": ok,
                        "value": ac if ok else None,
                        "raw": ic.get("raw", ""),
                        "note": "derived_from_internal_code",
                    }
                else:
                    extracted["album_code"] = {
                        "ok": False,
                        "value": None,
                        "raw": (ic.get("raw") if isinstance(ic, dict) else ""),
                        "error": "missing_internal_code",
                    }

        # scale consistency check (geom vs titleblock)
        geom = float(fit["geom_scale_factor"])
        scale_den: Optional[float] = None
        if (
            "scale_text" in extracted
            and extracted["scale_text"].get("ok")
            and "scale_denominator" in extracted["scale_text"]
        ):
            try:
                scale_den = float(extracted["scale_text"]["scale_denominator"])
            except Exception:
                scale_den = None
        mismatch = None
        flags: list[str] = []
        if scale_den is not None and geom > 0:
            diff = abs(geom - scale_den)
            thresh = max(scale_tol_abs, scale_tol_rel * scale_den)
            mismatch = diff > thresh
            if mismatch:
                flags.append(flag_name)

        cand = {
            "candidate_index": idx,
            "space": space_name,
            "outer": outer.__dict__,
            "fit": fit,
            "anchor_ok": anchor_ok,
            "anchor_combo_ok": anchor_combo_ok,
            "anchor_combo_counts": {
                "company_count": company_cnt,
                "cnpe_count": cnpe_cnt,
            },
            "anchor_search_steps": anchor_search_steps,
            "anchor_hits": anchor_hits,
            "titleblock": extracted,
            "debug_rois": debug_rois,
            "scale_consistency": {
                "geom_scale_factor": geom,
                "scale_denominator": scale_den,
                "mismatch": mismatch,
                "flags_added": flags,
            },
        }
        report["outer_frame_candidates"].append(cand)

    if args.mode == "summary":
        # pick best candidate: anchor_ok first then lowest score
        candidates = report["outer_frame_candidates"]
        best = None
        if candidates:
            best = sorted(
                candidates, key=lambda c: (not c["anchor_ok"], c["fit"]["score"])
            )[0]
        summary = {
            "dxf": report["dxf"],
            "spec": report["spec"],
            "text_items_count_by_space": report["text_items_count_by_space"],
            "anchor_global_combo_count_by_space": report[
                "anchor_global_combo_count_by_space"
            ],
            "best_candidate": None,
            "extracted_titleblock_values": None,
            "scale_fit": None,
            "scale_consistency": None,
        }
        if best:
            summary["best_candidate"] = {
                "space": best["space"],
                "outer": best["outer"],
                "paper_variant_id": best["fit"]["paper_variant_id"],
                "sx": best["fit"]["sx"],
                "sy": best["fit"]["sy"],
                "geom_scale_factor": best["fit"]["geom_scale_factor"],
                "roi_profile_id_default": best["fit"]["roi_profile_id_default"],
                "anchor_ok": best["anchor_ok"],
                "anchor_combo_ok": best["anchor_combo_ok"],
                "anchor_combo_counts": best["anchor_combo_counts"],
            }
            summary["scale_fit"] = best["fit"]
            summary["scale_consistency"] = best["scale_consistency"]
            summary["extracted_titleblock"] = {
                k: v for k, v in best["titleblock"].items()
            }
            summary["extracted_titleblock_values"] = {
                k: (v.get("value") if isinstance(v, dict) else None)
                for k, v in best["titleblock"].items()
            }
        report = summary

    # Defensive: ensure no generators leak into JSON (some ezdxf APIs return generators).
    import types

    def sanitize_for_json(obj: Any) -> Any:
        if isinstance(obj, types.GeneratorType):
            return [sanitize_for_json(x) for x in obj]
        if isinstance(obj, dict):
            return {str(k): sanitize_for_json(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [sanitize_for_json(x) for x in obj]
        if isinstance(obj, (Rect, TextItem)):
            return sanitize_for_json(obj.__dict__)
        return obj

    report = sanitize_for_json(report)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote report: {out_path}")

    # basic summary
    if args.mode == "debug":
        # show anchor_ok first
        ordered = sorted(
            report["outer_frame_candidates"],
            key=lambda c: (not c["anchor_ok"], c["fit"]["score"]),
        )
        for c in ordered[: min(10, len(ordered))]:
            fit = c["fit"]
            print(
                f"[cand#{c['candidate_index']}] space={c['space']} "
                f"size={c['outer']['xmax'] - c['outer']['xmin']:.3f}x{c['outer']['ymax'] - c['outer']['ymin']:.3f} "
                f"variant={fit['paper_variant_id']} sx={fit['sx']:.6f} sy={fit['sy']:.6f} anchor_ok={c['anchor_ok']}"
            )
    else:
        bc = report.get("best_candidate") if isinstance(report, dict) else None
        if bc:
            print(
                f"[best] space={bc['space']} variant={bc['paper_variant_id']} sx={bc['sx']:.6f} sy={bc['sy']:.6f} "
                f"anchor_ok={bc['anchor_ok']} anchor_combo_ok={bc['anchor_combo_ok']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
