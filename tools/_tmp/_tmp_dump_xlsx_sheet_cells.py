from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
}

CELL_REF_RE = re.compile(r"^([A-Z]+)(\d+)$", re.I)


def _safe_read(z: zipfile.ZipFile, name: str) -> bytes | None:
    try:
        return z.read(name)
    except KeyError:
        return None


def _et(data: bytes | None) -> ET.Element | None:
    if not data:
        return None
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        return None


def _xlsx_load_shared_strings(z: zipfile.ZipFile) -> list[str]:
    root = _et(_safe_read(z, "xl/sharedStrings.xml"))
    if root is None:
        return []
    out: list[str] = []
    for si in root.findall("s:si", NS):
        texts = []
        for t in si.findall(".//s:t", NS):
            if t.text:
                texts.append(t.text)
        out.append("".join(texts))
    return out


def _xlsx_sheet_paths(z: zipfile.ZipFile) -> list[dict]:
    wb = _et(_safe_read(z, "xl/workbook.xml"))
    rels = _et(_safe_read(z, "xl/_rels/workbook.xml.rels"))
    if wb is None or rels is None:
        return []

    rid_to_target: dict[str, str] = {}
    for rel in rels.findall(
        "r:Relationship",
        {"r": "http://schemas.openxmlformats.org/package/2006/relationships"},
    ):
        rid = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if rid and target:
            rid_to_target[rid] = target

    out: list[dict] = []
    sheets = wb.find("s:sheets", NS)
    if sheets is None:
        return out
    for sh in sheets.findall("s:sheet", NS):
        name = sh.attrib.get("name") or ""
        rid = sh.attrib.get(f"{{{NS['r']}}}id") or sh.attrib.get("r:id") or ""
        target = rid_to_target.get(rid, "")
        path = (
            ("xl/" + target.lstrip("/"))
            if target and not target.startswith("xl/")
            else target
        )
        out.append({"name": name, "rid": rid, "path": path})
    return out


def _parse_cell_ref(ref: str) -> tuple[str, int] | None:
    m = CELL_REF_RE.match(ref.strip())
    if not m:
        return None
    return m.group(1).upper(), int(m.group(2))


def _cell_text(c: ET.Element, shared_strings: list[str]) -> str:
    t = c.attrib.get("t")
    if t == "inlineStr":
        texts = [t_el.text or "" for t_el in c.findall(".//s:t", NS)]
        return "".join(texts).strip()

    v = c.find("s:v", NS)
    if v is None or v.text is None:
        return ""
    raw = v.text
    if t == "s":
        try:
            idx = int(raw)
            return (
                shared_strings[idx] if 0 <= idx < len(shared_strings) else raw
            ).strip()
        except ValueError:
            return raw.strip()
    return raw.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True)
    ap.add_argument(
        "--sheet",
        default="",
        help="sheet name (exact). 若PowerShell下中文传参乱码，可用 --sheet-index",
    )
    ap.add_argument(
        "--sheet-index",
        type=int,
        default=-1,
        help="sheet index (0-based). e.g. 1 表示第二个sheet",
    )
    ap.add_argument("--out", required=True, help="output TSV path: cell\\tvalue")
    args = ap.parse_args()

    xlsx_path = Path(args.xlsx)
    # PowerShell 在某些编码下传入中文文件名可能乱码。给一个兜底：
    # - 若传入的是目录：优先匹配 IED*.xlsx
    # - 若传入路径不存在：在其父目录尝试匹配 IED*.xlsx
    if xlsx_path.is_dir():
        cands = sorted(xlsx_path.glob("IED*.xlsx"))
        if not cands:
            raise SystemExit(f"no IED*.xlsx found in dir: {xlsx_path}")
        xlsx_path = cands[0]
    elif not xlsx_path.exists():
        parent = xlsx_path.parent if xlsx_path.parent.exists() else Path(".")
        cands = sorted(parent.glob("IED*.xlsx"))
        if cands:
            xlsx_path = cands[0]
    out_path = Path(args.out)

    with zipfile.ZipFile(xlsx_path, "r") as z:
        shared = _xlsx_load_shared_strings(z)
        sheets = _xlsx_sheet_paths(z)
        target = None
        if args.sheet_index >= 0:
            if args.sheet_index >= len(sheets):
                raise SystemExit(
                    f"sheet-index out of range: {args.sheet_index}. total={len(sheets)}"
                )
            target = sheets[args.sheet_index]
        else:
            if not args.sheet:
                raise SystemExit("need --sheet or --sheet-index")
            target = next((s for s in sheets if s["name"] == args.sheet), None)
        if not target:
            raise SystemExit(
                f"sheet not found: {args.sheet}. available: {[s['name'] for s in sheets]}"
            )
        sh_root = _et(_safe_read(z, target["path"]))
        if sh_root is None:
            raise SystemExit(f"cannot parse sheet xml: {target['path']}")

        rows: list[tuple[int, str, str]] = []
        for c in sh_root.findall(".//s:c", NS):
            ref = c.attrib.get("r")
            if not ref:
                continue
            parsed = _parse_cell_ref(ref)
            if not parsed:
                continue
            col, row = parsed
            text = _cell_text(c, shared)
            if text == "":
                continue
            rows.append((row, col, text))

        rows.sort(key=lambda x: (x[0], x[1]))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            for row, col, text in rows:
                f.write(f"{col}{row}\t{text}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
