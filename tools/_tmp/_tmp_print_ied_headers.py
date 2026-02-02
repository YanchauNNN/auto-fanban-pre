from __future__ import annotations

import json
from pathlib import Path


def idx_to_col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(ord("A") + r) + s
    return s


def main() -> None:
    report_path = Path("documents/_tmp_template_scan_report.json")
    obj = json.loads(report_path.read_text(encoding="utf-8"))

    ied = None
    for f in obj.get("files", []):
        if f.get("type") == "xlsx" and str(f.get("path", "")).endswith(
            "IED计划模板文件.xlsx"
        ):
            ied = f
            break
    if not ied:
        raise SystemExit("IED计划模板文件.xlsx not found in report")

    sheet = None
    for sh in ied.get("sheets", []):
        if "IED导入模板" in (sh.get("name") or ""):
            sheet = sh
            break
    if not sheet:
        raise SystemExit("sheet 'IED导入模板 (修改)' not found in report")

    row1 = sheet.get("row1", {})
    values = row1.get("values", [])

    # A..BW => 1..75
    for i in range(1, 76):
        v = values[i - 1] if i - 1 < len(values) else None
        print(f"{idx_to_col(i)}\t{(v or '').strip()}")


if __name__ == "__main__":
    main()
