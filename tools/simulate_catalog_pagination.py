"""
用 Excel COM(通过 comtypes) 导出目录PDF并统计页数，用于验证目录页数算法。
优先使用 Excel 分页信息计页，必要时回退为“导出PDF计页→回填→再导出”。

本脚本按“真实写入流程”模拟目录明细：
- 明细从第9行开始
- 第1条=封面文件
- 第2条=目录文件
- 后续为 001~XXX 图纸（按内部编码尾号XXX升序）

示例（用户给定20张图纸编码，分别跑2016与1818）：
  python tools/simulate_catalog_pagination.py --project_no 2016 --n_dwg 20
  python tools/simulate_catalog_pagination.py --project_no 1818 --n_dwg 20
"""

from __future__ import annotations

import argparse
import re
import shutil
import uuid
from pathlib import Path
from typing import Optional

import comtypes.client  # type: ignore

try:
    # when executed from repo root: `python tools/...`
    from tools.pdf_page_count import count_pdf_pages  # type: ignore
except Exception:
    # fallback when `tools` is not a package on sys.path
    from pdf_page_count import count_pdf_pages  # type: ignore


def _resolve_template(kind: str) -> Path:
    root = Path("documents_bin")
    if kind == "catalog_common":
        name = "\u76ee\u5f55\u6a21\u677f\u6587\u4ef6.xlsx"  # 目录模板文件.xlsx
    elif kind == "catalog_1818":
        name = "1818\u56fe\u518c\u76ee\u5f55\u6a21\u677f.xlsx"  # 1818图册目录模板.xlsx
    else:
        raise ValueError(f"unknown kind: {kind}")
    p = root / name
    if not p.exists():
        raise FileNotFoundError(p)
    return p


def _replace_pos_9_11(code: str, repl3: str) -> str:
    # 1-based positions 9..11 inclusive
    if len(code) < 11:
        return code
    return code[:8] + repl3 + code[11:]


def _derive_cover_catalog_codes(
    dwg_internal_001: str, dwg_external_001: str
) -> dict[str, str]:
    cover_internal = re.sub(r"-001$", "-FM", dwg_internal_001)
    catalog_internal = re.sub(r"-001$", "-TM", dwg_internal_001)
    cover_external = _replace_pos_9_11(dwg_external_001, "F01")
    catalog_external = _replace_pos_9_11(dwg_external_001, "T01")
    return {
        "cover_internal": cover_internal,
        "catalog_internal": catalog_internal,
        "cover_external": cover_external,
        "catalog_external": catalog_external,
    }


def _fill_catalog_entries(
    ws,
    start_row: int,
    *,
    project_no: str,
    n_dwg: int,
) -> int:
    """
    写入目录明细（封面、目录、001~n_dwg图纸），从 start_row 开始。
    返回 last_row。
    """
    bilingual_e = project_no == "1818"

    # user-provided code series
    def dwg_external(seq: int) -> str:
        return f"JD1NHT12{seq:03d}B25C42SD"

    def dwg_internal(seq: int) -> str:
        return f"20161NH-JGS01-{seq:03d}"

    base_external_001 = dwg_external(1)
    base_internal_001 = dwg_internal(1)
    derived = _derive_cover_catalog_codes(base_internal_001, base_external_001)

    album_title_cn = "图册名称测试"
    album_title_en = "Album Title Test"
    cover_title_cn = album_title_cn + "封面"
    catalog_title_cn = album_title_cn + "目录"
    cover_title_en = album_title_en + " Cover"
    catalog_title_en = album_title_en + " Contents"

    entries: list[dict[str, str]] = []
    # row1 cover
    entries.append(
        {
            "internal": derived["cover_internal"],
            "external": derived["cover_external"],
            "title_cn": cover_title_cn,
            "title_en": cover_title_en,
            "page_total": "1",
            "note": "",
        }
    )
    # row2 catalog (page_total placeholder; real value comes from PDF pages)
    entries.append(
        {
            "internal": derived["catalog_internal"],
            "external": derived["catalog_external"],
            "title_cn": catalog_title_cn,
            "title_en": catalog_title_en,
            "page_total": "",
            "note": "",
        }
    )
    # drawings 001..n
    for seq in range(1, n_dwg + 1):
        entries.append(
            {
                "internal": dwg_internal(seq),
                "external": dwg_external(seq),
                "title_cn": f"图纸标题-{seq:03d}",
                "title_en": f"Drawing Title {seq:03d}",
                "page_total": "1",
                "note": "",
            }
        )

    last_row = start_row - 1
    for i, e in enumerate(entries, start=1):
        r = start_row + (i - 1)
        last_row = r
        ws.Cells(r, 1).Value2 = i  # A 序号
        ws.Cells(r, 2).Value2 = e["internal"]  # B/C 内部编码（B即可）
        ws.Cells(r, 4).Value2 = e["external"]  # D 外部编码

        if bilingual_e:
            ws.Cells(r, 5).Value2 = f"{e['title_cn']}\n{e['title_en']}"
        else:
            ws.Cells(r, 5).Value2 = e["title_cn"]

        try:
            ws.Cells(r, 5).WrapText = True
        except Exception:
            pass

        ws.Cells(r, 6).Value2 = "A"  # F 版次（示意）
        ws.Cells(r, 7).Value2 = "CFC"  # G 状态（示意）
        ws.Cells(r, 8).Value2 = e["page_total"]  # H 页数（目录行留空）
        ws.Cells(r, 9).Value2 = e["note"]  # I 附注
        try:
            ws.Rows(r).AutoFit()
        except Exception:
            pass

    return last_row


def _count_pages_by_pagebreaks(ws) -> Optional[int]:
    """
    Try to compute page count from Excel page breaks.
    Returns None if page breaks are not available/stable.
    """
    try:
        # Trigger Excel to calculate page breaks.
        ws.DisplayPageBreaks = True
    except Exception:
        pass
    try:
        h = int(ws.HPageBreaks.Count)
        v = int(ws.VPageBreaks.Count)
    except Exception:
        return None
    # total pages = (horizontal breaks + 1) * (vertical breaks + 1)
    return max(1, (h + 1) * (v + 1))


def export_catalog_pdf_and_count_pages(
    kind: str, *, project_no: str, n_dwg: int, out_dir: Path
) -> tuple[Path, int]:
    template = _resolve_template(kind)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = out_dir / "_tmp_excel"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    work_xlsx = tmp_dir / f"_tmp_{kind}_{project_no}_{n_dwg}_{token}.xlsx"
    pdf_path = out_dir / f"catalog_{kind}_{project_no}_{n_dwg}dwg.pdf"

    shutil.copyfile(template, work_xlsx)

    excel = comtypes.client.CreateObject("Excel.Application", dynamic=True)
    excel.Visible = False
    excel.DisplayAlerts = False
    excel.AskToUpdateLinks = False

    wb = None
    try:
        wb = excel.Workbooks.Open(str(work_xlsx.resolve()))
        ws = wb.Worksheets(1)  # Sheet1

        # 按模板约定：明细从第9行开始；标题行1~8固定为Print_Titles
        start_row = 9
        last_row = _fill_catalog_entries(
            ws, start_row=start_row, project_no=project_no, n_dwg=n_dwg
        )

        ws.PageSetup.PrintTitleRows = "$1:$8"
        ws.PageSetup.PrintArea = f"$A$1:$I${last_row}"

        # 目录页数计算与回填（目录行=第2条，对应start_row+1的H列）
        # 优先：用分页信息计页 -> 回填H列 -> 仅导出一次最终PDF
        # 兜底：若分页信息不稳定/不可用，回退为“导出PDF计页→回填→再导出”
        pages = _count_pages_by_pagebreaks(ws)
        if pages is not None:
            try:
                # H列=8；catalog row is the 2nd entry -> start_row+1
                ws.Cells(start_row + 1, 8).Value2 = pages
            except Exception:
                pass
            # xlTypePDF = 0
            ws.ExportAsFixedFormat(0, str(pdf_path.resolve()))
            # If the actual PDF page count differs, align H and re-export once.
            pdf_pages = count_pdf_pages(pdf_path)
            if pdf_pages != pages:
                try:
                    ws.Cells(start_row + 1, 8).Value2 = pdf_pages
                except Exception:
                    pass
                ws.ExportAsFixedFormat(0, str(pdf_path.resolve()))
                pages = pdf_pages
        else:
            # fallback: double export
            ws.ExportAsFixedFormat(0, str(pdf_path.resolve()))
            pages = count_pdf_pages(pdf_path)
            try:
                ws.Cells(start_row + 1, 8).Value2 = pages
            except Exception:
                pass
            ws.ExportAsFixedFormat(0, str(pdf_path.resolve()))

    finally:
        try:
            if wb is not None:
                # dynamic dispatch: use positional args
                wb.Close(False)
        finally:
            excel.Quit()

        # best-effort cleanup of temp workbook
        try:
            if work_xlsx.exists():
                work_xlsx.unlink()
        except PermissionError:
            # Excel may still be releasing file handles; leave it for manual cleanup.
            pass

    pages = count_pdf_pages(pdf_path)
    return pdf_path, pages


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project_no", required=True, choices=["2016", "1818"])
    ap.add_argument("--n_dwg", type=int, default=20)
    ap.add_argument("--out_dir", default="documents")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    kind = "catalog_1818" if args.project_no == "1818" else "catalog_common"
    pdf, pages = export_catalog_pdf_and_count_pages(
        kind, project_no=args.project_no, n_dwg=args.n_dwg, out_dir=out_dir
    )
    print(
        f"{args.project_no} kind={kind} dwg={args.n_dwg} -> catalog_pages={pages} pdf={pdf}"
    )


if __name__ == "__main__":
    main()
