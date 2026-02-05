"""
离线/内网环境模板体检脚本（仅用标准库）：
- 解析 xlsx/docx（本质 zip + xml）
- 输出：sheet 列表、关键单元格取值、前几行表头、合并单元格区域、docx 是否含 OLE 嵌入对象等

用法（PowerShell）：
  python tools/inspect_office_templates.py --root documents_bin --out documents/template_scan_report.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

NS = {
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def _safe_read(z: zipfile.ZipFile, name: str) -> Optional[bytes]:
    try:
        return z.read(name)
    except KeyError:
        return None


def _et_from_bytes(data: Optional[bytes]) -> Optional[ET.Element]:
    if not data:
        return None
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        return None


def _col_to_index(col: str) -> int:
    col = col.upper()
    n = 0
    for ch in col:
        if not ("A" <= ch <= "Z"):
            break
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


def _index_to_col(idx: int) -> str:
    out = []
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        out.append(chr(ord("A") + rem))
    return "".join(reversed(out)) or "A"


CELL_REF_RE = re.compile(r"^([A-Z]+)(\d+)$", re.I)


def _parse_cell_ref(ref: str) -> Tuple[str, int]:
    m = CELL_REF_RE.match(ref.strip())
    if not m:
        raise ValueError(f"invalid cell ref: {ref}")
    return m.group(1).upper(), int(m.group(2))


def _cell_key(col: str, row: int) -> str:
    return f"{col.upper()}{row}"


def _xlsx_load_shared_strings(z: zipfile.ZipFile) -> List[str]:
    ss = _safe_read(z, "xl/sharedStrings.xml")
    root = _et_from_bytes(ss)
    if root is None:
        return []
    out: List[str] = []
    for si in root.findall("s:si", NS):
        # shared string 可能是多段 rich text <r><t>...</t></r>
        texts = []
        for t in si.findall(".//s:t", NS):
            if t.text:
                texts.append(t.text)
        out.append("".join(texts))
    return out


def _xlsx_sheet_map(z: zipfile.ZipFile) -> List[Dict[str, Any]]:
    """
    返回：[ {name, rid, path} ... ]，path 为 xl/worksheets/sheet*.xml
    """
    wb = _et_from_bytes(_safe_read(z, "xl/workbook.xml"))
    rels = _et_from_bytes(_safe_read(z, "xl/_rels/workbook.xml.rels"))
    if wb is None or rels is None:
        return []

    rid_to_target: Dict[str, str] = {}
    for rel in rels.findall(
        "r:Relationship",
        {"r": "http://schemas.openxmlformats.org/package/2006/relationships"},
    ):
        rid = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if rid and target:
            # Target 通常为 "worksheets/sheet1.xml"
            rid_to_target[rid] = target

    out: List[Dict[str, Any]] = []
    sheets = wb.find("s:sheets", NS)
    if sheets is None:
        return out

    for sh in sheets.findall("s:sheet", NS):
        name = sh.attrib.get("name") or ""
        rid = sh.attrib.get(f"{{{NS['r']}}}id") or sh.attrib.get("r:id") or ""
        target = rid_to_target.get(rid, "")
        if target and not target.startswith("xl/"):
            path = "xl/" + target.lstrip("/")
        else:
            path = target
        out.append({"name": name, "rid": rid, "path": path})
    return out


def _xlsx_extract_cells(
    sheet_root: ET.Element,
    shared_strings: List[str],
    wanted: List[str],
) -> Dict[str, Any]:
    wanted_set = {w.upper() for w in wanted}
    found: Dict[str, Any] = {}

    # cell: <c r="A1" t="s"><v>0</v></c> or inlineStr
    for c in sheet_root.findall(".//s:c", NS):
        r = c.attrib.get("r")
        if not r:
            continue
        r_u = r.upper()
        if r_u not in wanted_set:
            continue
        t = c.attrib.get("t")
        v = c.find("s:v", NS)
        if t == "s" and v is not None and v.text is not None:
            try:
                idx = int(v.text)
                found[r_u] = (
                    shared_strings[idx] if 0 <= idx < len(shared_strings) else v.text
                )
            except ValueError:
                found[r_u] = v.text
        elif t == "inlineStr":
            texts = [t_el.text or "" for t_el in c.findall(".//s:t", NS)]
            found[r_u] = "".join(texts).strip()
        else:
            # number / str / etc
            found[r_u] = v.text if v is not None else None
    return found


def _xlsx_extract_table_preview(
    sheet_root: ET.Element,
    shared_strings: List[str],
    max_rows: int = 6,
    max_cols: int = 12,
    start_row: int = 1,
) -> List[List[Optional[str]]]:
    """
    取 start_row..start_row+max_rows-1 行，A..(max_cols) 列的值预览
    """
    # 构建一个 {A1: value} map（只采集预览范围内，避免遍历太大）
    end_row = start_row + max_rows - 1
    preview_wanted: List[str] = []
    for r in range(start_row, end_row + 1):
        for ci in range(1, max_cols + 1):
            preview_wanted.append(_cell_key(_index_to_col(ci), r))
    cell_map = _xlsx_extract_cells(sheet_root, shared_strings, preview_wanted)

    out: List[List[Optional[str]]] = []
    for r in range(start_row, end_row + 1):
        row_vals: List[Optional[str]] = []
        for ci in range(1, max_cols + 1):
            key = _cell_key(_index_to_col(ci), r)
            val = cell_map.get(key)
            if val is None:
                row_vals.append(None)
            else:
                row_vals.append(str(val))
        out.append(row_vals)
    return out


def _xlsx_extract_merged_ranges(sheet_root: ET.Element) -> List[str]:
    merged = sheet_root.find("s:mergeCells", NS)
    if merged is None:
        return []
    out: List[str] = []
    for mc in merged.findall("s:mergeCell", NS):
        ref = mc.attrib.get("ref")
        if ref:
            out.append(ref)
    return out


def _xlsx_row_values(
    sheet_root: ET.Element,
    shared_strings: List[str],
    row_index: int,
    max_cols_cap: int = 120,
) -> Dict[str, Any]:
    """
    提取指定行的已填写单元格，并返回：
    - max_col: 该行出现过的最大列号（按单元格引用计算）
    - values: 从 A..max_col 的值列表（None 代表空/未出现），最多截断到 max_cols_cap
    """
    by_col: Dict[int, Optional[str]] = {}
    max_col = 0
    for c in sheet_root.findall(".//s:c", NS):
        r = c.attrib.get("r")
        if not r:
            continue
        try:
            col, row = _parse_cell_ref(r)
        except ValueError:
            continue
        if row != row_index:
            continue
        col_idx = _col_to_index(col)
        max_col = max(max_col, col_idx)

        t = c.attrib.get("t")
        v = c.find("s:v", NS)
        val: Optional[str]
        if t == "s" and v is not None and v.text is not None:
            try:
                idx = int(v.text)
                val = shared_strings[idx] if 0 <= idx < len(shared_strings) else v.text
            except ValueError:
                val = v.text
        elif t == "inlineStr":
            texts = [t_el.text or "" for t_el in c.findall(".//s:t", NS)]
            val = "".join(texts).strip()
        else:
            val = v.text if v is not None else None

        by_col[col_idx] = str(val) if val is not None else None

    max_col = min(max_col, max_cols_cap)
    values: List[Optional[str]] = []
    for i in range(1, max_col + 1):
        values.append(by_col.get(i))
    return {"max_col": max_col, "values": values}


def inspect_xlsx(path: str) -> Dict[str, Any]:
    with zipfile.ZipFile(path, "r") as z:
        shared = _xlsx_load_shared_strings(z)
        sheets = _xlsx_sheet_map(z)

        result: Dict[str, Any] = {
            "type": "xlsx",
            "path": path,
            "sheets": [],
        }

        for sh in sheets:
            sh_path = sh.get("path")
            sh_root = _et_from_bytes(_safe_read(z, sh_path))
            if sh_root is None:
                result["sheets"].append(
                    {
                        "name": sh.get("name"),
                        "path": sh_path,
                        "error": "cannot parse sheet xml",
                    }
                )
                continue

            merged = _xlsx_extract_merged_ranges(sh_root)
            # 预览范围加宽一些：便于直接看到“设计文件/IED”等长表头
            preview = _xlsx_extract_table_preview(
                sh_root, shared, max_rows=8, max_cols=40, start_row=1
            )

            # 一些常用关键单元格（目录模板常见）
            key_cells = ["C1", "H1", "H3", "C5", "H5"]
            key_values = _xlsx_extract_cells(sh_root, shared, key_cells)

            header_row1 = _xlsx_row_values(
                sh_root, shared, row_index=1, max_cols_cap=120
            )

            result["sheets"].append(
                {
                    "name": sh.get("name"),
                    "path": sh_path,
                    "merged_ranges": merged[:200],  # 限制一下体积
                    "key_cells": key_values,
                    "row1": header_row1,
                    "preview_A1_AN8": preview,
                }
            )
        return result


def _docx_extract_text(doc_root: ET.Element, max_chars: int = 2000) -> str:
    # 拼接所有 w:t
    texts: List[str] = []
    for t in doc_root.findall(".//w:t", NS):
        if t.text:
            texts.append(t.text)
        if sum(len(x) for x in texts) >= max_chars:
            break
    out = "".join(texts)
    return out[:max_chars]


def inspect_docx(path: str) -> Dict[str, Any]:
    with zipfile.ZipFile(path, "r") as z:
        names = z.namelist()
        doc = _et_from_bytes(_safe_read(z, "word/document.xml"))
        core = _et_from_bytes(_safe_read(z, "docProps/core.xml"))

        embeddings = [n for n in names if n.startswith("word/embeddings/")]

        core_props: Dict[str, Any] = {}
        if core is not None:
            title_el = core.find("dc:title", NS)
            subj_el = core.find("dc:subject", NS)
            creator_el = core.find("dc:creator", NS)
            core_props = {
                "title": (title_el.text if title_el is not None else None),
                "subject": (subj_el.text if subj_el is not None else None),
                "creator": (creator_el.text if creator_el is not None else None),
            }

        text_preview = _docx_extract_text(doc) if doc is not None else ""

        return {
            "type": "docx",
            "path": path,
            "core_props": core_props,
            "has_embeddings": bool(embeddings),
            "embeddings": embeddings,
            "text_preview": text_preview,
        }


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--root", default="documents_bin", help="包含模板的目录（相对或绝对）"
    )
    ap.add_argument("--out", default="", help="输出 JSON 报告路径（可选）")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"[ERR] root not found: {root}", file=sys.stderr)
        return 2

    results: Dict[str, Any] = {"root": root, "files": []}

    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name)
        if not os.path.isfile(p):
            continue
        lower = name.lower()
        try:
            if lower.endswith(".xlsx"):
                results["files"].append(inspect_xlsx(p))
            elif lower.endswith(".docx"):
                results["files"].append(inspect_docx(p))
        except Exception as e:
            results["files"].append({"path": p, "error": f"{type(e).__name__}: {e}"})

    if args.out:
        out_path = os.path.abspath(args.out)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"[OK] wrote report: {out_path}")

    # 控制台也输出一个简版摘要
    for f in results["files"]:
        print(f"- {os.path.basename(f.get('path', ''))}: {f.get('type', '?')}")
        if f.get("type") == "xlsx":
            sheets = f.get("sheets", [])
            print(f"  sheets: {[s.get('name') for s in sheets]}")
        if f.get("type") == "docx":
            print(f"  embeddings: {len(f.get('embeddings', []))}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
