from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
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
            return
        if tp == "MTEXT":
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
            return
        if tp == "ATTRIB":
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


def _find_outer_bbox_by_candidate_finder(msp) -> BBox | None:
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
    items: list[TextItem], search_texts: list[str], anchor_roi: BBox
) -> TextItem | None:
    matched = [it for it in items if _match_any_text(it.text, search_texts)]
    if not matched:
        return None
    inside = [it for it in matched if it.bbox and anchor_roi.intersects(it.bbox)]
    if inside:
        return max(inside, key=lambda it: len(it.text))
    return max(matched, key=lambda it: len(it.text))


def calibrate_profile(
    dxf_path: Path,
    *,
    search_texts: list[str],
    anchor_rb_offset: list[float],
    reference_point: str,
) -> dict[str, Any]:
    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()

    outer_bbox = _find_outer_bbox_by_candidate_finder(msp)
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


def find_outer_bbox_in_layer(msp, layer_name: str) -> BBox | None:
    best: BBox | None = None
    best_area = -1.0
    for e in msp:
        try:
            if e.dxf.layer != layer_name:
                continue
        except Exception:
            continue
        tp = e.dxftype()
        if tp not in {"LWPOLYLINE", "POLYLINE"}:
            continue
        is_closed = bool(getattr(e, "is_closed", False) or getattr(e, "closed", False))
        if not is_closed:
            continue
        vertices: list[tuple[float, float]] = []
        if tp == "LWPOLYLINE":
            for p in e.get_points():
                vertices.append((float(p[0]), float(p[1])))
        else:
            for v in e.vertices:
                loc = v.dxf.location
                vertices.append((float(loc.x), float(loc.y)))
        if len(vertices) < 4:
            continue
        xs = [p[0] for p in vertices]
        ys = [p[1] for p in vertices]
        bbox = BBox(xmin=min(xs), ymin=min(ys), xmax=max(xs), ymax=max(ys))
        area = bbox.width * bbox.height
        if area > best_area:
            best = bbox
            best_area = area
    return best


def compute_predicted_rb(
    item: TextItem,
    *,
    profile_id: str,
    calib: dict[str, Any],
    reference_point: str,
) -> dict[str, Any] | None:
    if reference_point == "text_bbox_right_bottom" and item.bbox is not None:
        ref_x, ref_y = item.bbox.xmax, item.bbox.ymin
    else:
        ref_x, ref_y = item.x, item.y

    text_h = item.text_height
    if text_h is None and item.bbox is not None:
        text_h = item.bbox.height / 1.2
    if text_h is None:
        return None
    base_h = calib.get("text_height_1to1_mm")
    if not base_h:
        return None
    scale = float(text_h) / float(base_h)

    ref_cfg = calib.get("text_ref_in_anchor_roi_1to1", {})
    dx_right = float(ref_cfg.get("dx_right", 0.0))
    dy_bottom = float(ref_cfg.get("dy_bottom", 0.0))
    roi_xmax = ref_x + dx_right * scale
    roi_ymin = ref_y - dy_bottom * scale

    anchor_rb = calib.get("anchor_roi_rb_offset_1to1", [0.0, 0.0, 0.0, 0.0])
    outer_xmax = roi_xmax + float(anchor_rb[0]) * scale
    outer_ymin = roi_ymin - float(anchor_rb[2]) * scale

    return {
        "profile_id": profile_id,
        "scale": scale,
        "ref_point": {"x": ref_x, "y": ref_y},
        "roi_rb": {"x": roi_xmax, "y": roi_ymin},
        "outer_rb": {"x": outer_xmax, "y": outer_ymin},
    }


def cmd_calibrate(args: argparse.Namespace) -> int:
    spec = yaml.safe_load(Path(args.spec).read_text(encoding="utf-8")) or {}
    titleblock = spec.get("titleblock_extract", {}) or {}
    anchor_cfg = titleblock.get("anchor", {}) or {}
    search_texts = anchor_cfg.get("search_text", [])
    if isinstance(search_texts, str):
        search_texts = [search_texts]
    search_texts = [t for t in search_texts if t]

    roi_profiles = titleblock.get("roi_profiles", {}) or {}
    calib_cfg = anchor_cfg.get("calibration", {}) or {}

    def anchor_rb_offset(profile_id: str) -> list[float]:
        calib = calib_cfg.get(profile_id, {}) if isinstance(calib_cfg, dict) else {}
        if isinstance(calib, dict) and calib.get("anchor_roi_rb_offset_1to1"):
            return calib["anchor_roi_rb_offset_1to1"]
        profile = roi_profiles.get(profile_id, {}) or {}
        fields = profile.get("fields", {}) or {}
        rb = fields.get("锚点")
        if not rb:
            raise RuntimeError(f"Missing anchor ROI rb_offset for profile {profile_id}")
        return rb

    reference_point = args.reference_point
    base10 = calibrate_profile(
        Path(args.base10_dxf),
        search_texts=search_texts,
        anchor_rb_offset=anchor_rb_offset("BASE10"),
        reference_point=reference_point,
    )
    small5 = calibrate_profile(
        Path(args.small5_dxf),
        search_texts=search_texts,
        anchor_rb_offset=anchor_rb_offset("SMALL5"),
        reference_point=reference_point,
    )
    result = {"reference_point": reference_point, "BASE10": base10, "SMALL5": small5}
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote: {out_path}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    dxf_dir = Path(args.dxf_dir)
    spec_path = Path(args.spec)
    out_path = Path(args.json_out)

    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    anchor_cfg = (spec.get("titleblock_extract") or {}).get("anchor") or {}
    search_texts = anchor_cfg.get("search_text") or []
    if isinstance(search_texts, str):
        search_texts = [search_texts]
    search_texts = [t for t in search_texts if t]

    calibration = anchor_cfg.get("calibration") or {}
    reference_point = str(calibration.get("reference_point", "text_bbox_right_bottom"))
    profile_calibs = {
        k: v
        for k, v in calibration.items()
        if k != "reference_point" and isinstance(v, dict)
    }

    dxfs = sorted(dxf_dir.glob("*.dxf"))
    if not dxfs:
        print("未找到DXF文件")
        return 1

    report: dict[str, Any] = {
        "spec": str(spec_path),
        "dxf_dir": str(dxf_dir),
        "outer_layer": args.outer_layer,
        "tol": float(args.tol),
        "search_texts": search_texts,
        "profiles": list(profile_calibs.keys()),
        "items": [],
    }

    for dxf_path in dxfs:
        item: dict[str, Any] = {"file": dxf_path.name, "errors": []}
        try:
            doc = ezdxf.readfile(str(dxf_path))
        except Exception as exc:  # noqa: BLE001
            item["errors"].append(f"DXF解析失败: {exc}")
            report["items"].append(item)
            print(f"{dxf_path.name}: ERROR DXF解析失败: {exc}")
            continue
        msp = doc.modelspace()

        outer_bbox = find_outer_bbox_in_layer(msp, args.outer_layer)
        if outer_bbox is None:
            item["errors"].append(f"未找到外层矩形图层外框: layer={args.outer_layer}")
            report["items"].append(item)
            print(f"{dxf_path.name}: ERROR 未找到外层矩形图层外框")
            continue
        outer_rb = {"x": outer_bbox.xmax, "y": outer_bbox.ymin}
        item["outer_bbox"] = asdict(outer_bbox)
        item["outer_rb"] = outer_rb

        texts = _iter_text_items(msp)
        anchors = [t for t in texts if t.text and _match_any_text(t.text, search_texts)]
        item["anchor_count"] = len(anchors)
        if not anchors:
            item["errors"].append("未找到锚点文本实体")
            report["items"].append(item)
            print(f"{dxf_path.name}: ERROR 未找到锚点文本")
            continue

        preds: list[dict[str, Any]] = []
        for a in anchors:
            for profile_id, calib in profile_calibs.items():
                pred = compute_predicted_rb(
                    a,
                    profile_id=profile_id,
                    calib=calib,
                    reference_point=reference_point,
                )
                if pred is None:
                    continue
                dx = float(pred["outer_rb"]["x"]) - float(outer_rb["x"])
                dy = float(pred["outer_rb"]["y"]) - float(outer_rb["y"])
                pred["delta"] = {"dx": dx, "dy": dy, "abs_max": max(abs(dx), abs(dy))}
                preds.append(pred)

        item["predictions"] = preds
        if not preds:
            item["errors"].append("无法从锚点计算RB（缺少字高或校准参数）")
            report["items"].append(item)
            print(f"{dxf_path.name}: ERROR 无法从锚点计算RB")
            continue

        best = min(preds, key=lambda p: float(p["delta"]["abs_max"]))
        item["best"] = best
        ok = float(best["delta"]["abs_max"]) <= float(args.tol)
        item["ok"] = ok
        status = "OK" if ok else "FAIL"
        print(
            f"{dxf_path.name}: {status} profile={best['profile_id']} scale={best['scale']:.6f} "
            f"dx={best['delta']['dx']:.3f} dy={best['delta']['dy']:.3f}"
        )
        report["items"].append(item)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"JSON报告已输出: {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Anchor calibration tools (calibrate/verify)."
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_cal = sub.add_parser(
        "calibrate", help="Generate calibration JSON from 1:1 DXF templates."
    )
    p_cal.add_argument("--spec", default="documents/参数规范.yaml")
    p_cal.add_argument("--base10-dxf", default="test/dxf-biaozhun/2016-A0.dxf")
    p_cal.add_argument("--small5-dxf", default="test/dxf-biaozhun/2016-A4.dxf")
    p_cal.add_argument(
        "--reference-point",
        default="text_bbox_right_bottom",
        choices=["text_bbox_right_bottom", "text_insert"],
    )
    p_cal.add_argument("--out", default="documents/anchor_calibration.json")
    p_cal.set_defaults(func=cmd_calibrate)

    p_ver = sub.add_parser(
        "verify", help="Verify calibration RB against outer-frame layer."
    )
    p_ver.add_argument("--dxf-dir", default="test/dxf-biaozhun")
    p_ver.add_argument("--spec", default="documents/参数规范.yaml")
    p_ver.add_argument("--outer-layer", default="外层矩形")
    p_ver.add_argument("--tol", type=float, default=1.0)
    p_ver.add_argument(
        "--json-out", default="test/dxf-biaozhun/anchor_rb_verify_report.json"
    )
    p_ver.set_defaults(func=cmd_verify)

    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
