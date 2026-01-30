from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ezdxf  # type: ignore
import yaml


@dataclass(frozen=True)
class BBox:
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

    def contains_point(self, x: float, y: float) -> bool:
        return self.xmin <= x <= self.xmax and self.ymin <= y <= self.ymax

    def intersects(self, other: "BBox") -> bool:
        return not (
            self.xmax < other.xmin
            or self.xmin > other.xmax
            or self.ymax < other.ymin
            or self.ymin > other.ymax
        )


@dataclass(frozen=True)
class TextItem:
    x: float
    y: float
    text: str
    bbox: BBox | None
    text_height: float | None
    source: str


def _normalize(text: str) -> str:
    return "".join(ch for ch in (text or "") if not ch.isspace())


def _match_any_text(text: str, patterns: list[str]) -> bool:
    normalized = _normalize(text)
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


def _bbox_from_mtext(e, text: str, x: float, y: float) -> tuple[BBox, float]:
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
    return BBox(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax), char_h


def _iter_text_items(msp) -> list[TextItem]:
    items: list[TextItem] = []

    def add_text_entity(e, source: str) -> None:
        tp = e.dxftype()
        if tp == "TEXT":
            text = (e.dxf.text or "").strip()
            p = e.dxf.insert
            x, y = float(p.x), float(p.y)
            height = float(getattr(e.dxf, "height", 2.5) or 2.5)
            bbox = _bbox_from_text(
                text=text,
                x=x,
                y=y,
                height=height,
                halign=int(getattr(e.dxf, "halign", 0) or 0),
                valign=int(getattr(e.dxf, "valign", 0) or 0),
            )
            items.append(
                TextItem(
                    x=x, y=y, text=text, bbox=bbox, text_height=height, source=source
                )
            )
        elif tp == "MTEXT":
            try:
                text = (e.plain_text() or "").strip()
            except Exception:
                text = (e.text or "").strip()
            p = e.dxf.insert
            x, y = float(p.x), float(p.y)
            bbox, char_h = _bbox_from_mtext(e, text, x, y)
            items.append(
                TextItem(
                    x=x, y=y, text=text, bbox=bbox, text_height=char_h, source=source
                )
            )
        elif tp == "ATTRIB":
            text = (e.dxf.text or "").strip()
            p = e.dxf.insert
            x, y = float(p.x), float(p.y)
            height = float(getattr(e.dxf, "height", 2.5) or 2.5)
            bbox = _bbox_from_text(
                text=text,
                x=x,
                y=y,
                height=height,
                halign=int(getattr(e.dxf, "halign", 0) or 0),
                valign=int(getattr(e.dxf, "valign", 0) or 0),
            )
            items.append(
                TextItem(
                    x=x, y=y, text=text, bbox=bbox, text_height=height, source=source
                )
            )

    def walk_entity(ent, src_prefix: str, depth: int) -> None:
        if depth > 8:
            return
        tp = ent.dxftype()
        if tp in {"TEXT", "MTEXT", "ATTRIB"}:
            add_text_entity(ent, f"{src_prefix}:{tp}")
            return
        if tp == "INSERT":
            try:
                for a in ent.attribs:
                    add_text_entity(a, f"{src_prefix}:attrib")
            except Exception:
                pass
            try:
                for ve in ent.virtual_entities():
                    walk_entity(ve, f"{src_prefix}:virtual", depth + 1)
            except Exception:
                pass

    for e in msp:
        walk_entity(e, "msp", 0)

    return items


def _restore_roi(
    outer_bbox: BBox, rb_offset: list[float], sx: float = 1.0, sy: float = 1.0
) -> BBox:
    dx_right, dx_left, dy_bottom, dy_top = rb_offset
    return BBox(
        xmin=outer_bbox.xmax - dx_left * sx,
        xmax=outer_bbox.xmax - dx_right * sx,
        ymin=outer_bbox.ymin + dy_bottom * sy,
        ymax=outer_bbox.ymin + dy_top * sy,
    )


def _find_outer_bbox(msp) -> BBox | None:
    repo_root = Path(__file__).resolve().parents[1]
    backend_root = repo_root / "backend"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    from src.cad.detection.candidate_finder import CandidateFinder  # type: ignore

    finder = CandidateFinder()
    candidates = finder.find_rectangles(msp)
    if not candidates:
        return None
    best = max(candidates, key=lambda b: b.width * b.height)
    return BBox(xmin=best.xmin, ymin=best.ymin, xmax=best.xmax, ymax=best.ymax)


def _select_anchor_item(
    items: list[TextItem],
    search_texts: list[str],
    anchor_roi: BBox,
) -> TextItem | None:
    matched = [it for it in items if _match_any_text(it.text, search_texts)]
    if not matched:
        return None
    # Prefer item inside anchor ROI
    inside = [it for it in matched if it.bbox and anchor_roi.intersects(it.bbox)]
    if inside:
        return max(inside, key=lambda it: len(it.text))
    return max(matched, key=lambda it: len(it.text))


def _calibrate_profile(
    dxf_path: Path,
    search_texts: list[str],
    anchor_rb_offset: list[float],
    reference_point: str,
) -> dict[str, Any]:
    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()

    outer_bbox = _find_outer_bbox(msp)
    if not outer_bbox:
        raise RuntimeError(f"No outer bbox found in {dxf_path}")

    anchor_roi = _restore_roi(outer_bbox, anchor_rb_offset, sx=1.0, sy=1.0)
    items = _iter_text_items(msp)
    anchor_item = _select_anchor_item(items, search_texts, anchor_roi)
    if not anchor_item or not anchor_item.bbox:
        raise RuntimeError(f"Anchor text not found in {dxf_path}")

    if reference_point == "text_bbox_right_bottom":
        ref_x = anchor_item.bbox.xmax
        ref_y = anchor_item.bbox.ymin
    elif reference_point == "text_insert":
        ref_x = anchor_item.x
        ref_y = anchor_item.y
    else:
        raise ValueError(f"Unsupported reference_point: {reference_point}")

    dx_right = anchor_roi.xmax - ref_x
    dy_bottom = ref_y - anchor_roi.ymin
    dx_left = ref_x - anchor_roi.xmin
    dy_top = anchor_roi.ymax - ref_y

    return {
        "text_height_1to1_mm": anchor_item.text_height,
        "text_ref_in_anchor_roi_1to1": {
            "dx_right": round(dx_right, 4),
            "dy_bottom": round(dy_bottom, 4),
            "dx_left": round(dx_left, 4),
            "dy_top": round(dy_top, 4),
        },
    }


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Calibrate anchor text from 1:1 DXF samples."
    )
    ap.add_argument("--spec", default="documents/参数规范.yaml")
    ap.add_argument("--base10-dxf", default="test/dxf-biaozhun/2016-A0.dxf")
    ap.add_argument("--small5-dxf", default="test/dxf-biaozhun/2016-A4.dxf")
    ap.add_argument(
        "--reference-point",
        default="text_bbox_right_bottom",
        choices=["text_bbox_right_bottom", "text_insert"],
    )
    ap.add_argument("--out", default="documents/anchor_calibration.json")
    args = ap.parse_args()

    spec = _load_yaml(Path(args.spec))
    titleblock = spec.get("titleblock_extract", {})
    anchor_cfg = titleblock.get("anchor", {})
    search_texts = anchor_cfg.get("search_text", [])

    # Prefer calibration anchor ROI if present; fallback to roi_profiles fields
    roi_profiles = titleblock.get("roi_profiles", {})
    calib_cfg = anchor_cfg.get("calibration", {})

    def anchor_rb_offset(profile_id: str) -> list[float]:
        if calib_cfg.get(profile_id, {}).get("anchor_roi_rb_offset_1to1"):
            return calib_cfg[profile_id]["anchor_roi_rb_offset_1to1"]
        profile = roi_profiles.get(profile_id, {})
        fields = profile.get("fields", {})
        rb = fields.get("锚点")
        if not rb:
            raise RuntimeError(f"Missing anchor ROI rb_offset for profile {profile_id}")
        return rb

    reference_point = args.reference_point

    base10 = _calibrate_profile(
        Path(args.base10_dxf),
        search_texts,
        anchor_rb_offset("BASE10"),
        reference_point,
    )
    small5 = _calibrate_profile(
        Path(args.small5_dxf),
        search_texts,
        anchor_rb_offset("SMALL5"),
        reference_point,
    )

    result = {
        "reference_point": reference_point,
        "BASE10": base10,
        "SMALL5": small5,
    }

    out_path = Path(args.out)
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
