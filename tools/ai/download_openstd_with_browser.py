from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.ai.standards_downloader import (  # noqa: E402
    inspect_existing_download,
    is_public_authorized_candidate,
    safe_filename,
)

DEFAULT_CATALOG = (
    REPO_ROOT
    / "tools"
    / "ai"
    / "building-structure-standards"
    / "assets"
    / "data"
    / "audit_catalog.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "build" / "建筑结构总图规范语料_509"


def browser_download(
    *,
    catalog_path: Path,
    output_dir: Path,
    session: str,
) -> int:
    records = json.loads(catalog_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, str]] = []
    seen_paths: set[Path] = set()
    for record in records:
        if not is_public_authorized_candidate(record):
            continue
        path = output_dir / safe_filename(
            str(record.get("standard_code") or ""),
            str(record.get("standard_name") or "未命名标准"),
        )
        if path in seen_paths or inspect_existing_download(record, output_dir):
            continue
        seen_paths.add(path)
        items.append(
            {
                "sourceId": str(record.get("source_id") or ""),
                "code": str(record.get("standard_code") or ""),
                "detailUrl": str(record.get("official_source_url") or ""),
                "savePath": path.resolve().as_posix(),
            }
        )

    if not items:
        print("所有可通过官网浏览器取得的文件均已存在。")
        return 0

    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if not npx:
        raise RuntimeError("未找到 npx，无法启动 Playwright CLI。")

    _run_cli(
        npx,
        session,
        ["open", items[0]["detailUrl"], "--headed"],
        check=False,
    )
    return_code = 0
    for index, item in enumerate(items, start=1):
        print(f"浏览器下载 {index}/{len(items)}：{item['code']}", flush=True)
        completed = _run_cli(
            npx,
            session,
            ["run-code", _build_playwright_code(item)],
            check=False,
            timeout=120,
        )
        if completed.returncode != 0:
            return_code = completed.returncode
    acquired = 0
    for record in records:
        if is_public_authorized_candidate(record) and inspect_existing_download(
            record, output_dir
        ):
            acquired += 1
    print(f"官网浏览器流程结束；当前识别到 {acquired} 条公开标准 PDF。")
    return return_code


def _build_playwright_code(item: dict[str, str]) -> str:
    detail_url = json.dumps(item["detailUrl"], ensure_ascii=True)
    save_path = json.dumps(item["savePath"], ensure_ascii=True)
    return (
        "async (page) => { "
        f"await page.goto({detail_url}, {{ waitUntil: 'domcontentloaded', timeout: 30000 }}); "
        "const popupPromise = page.waitForEvent('popup', { timeout: 30000 }); "
        "await page.getByRole('button', { name: '下载标准' }).click(); "
        "const popup = await popupPromise; "
        "const download = await popup.waitForEvent('download', { timeout: 30000 }); "
        f"await download.saveAs({save_path}); "
        "const filename = download.suggestedFilename(); "
        "await popup.close().catch(() => {}); "
        "return filename; }"
    )


def _run_cli(
    npx: str,
    session: str,
    arguments: list[str],
    *,
    check: bool,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    command = [
        npx,
        "--yes",
        "--package",
        "@playwright/cli",
        "playwright-cli",
        f"-s={session}",
        *arguments,
    ]
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=check,
        timeout=timeout,
        text=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="通过国家标准全文公开系统的真实下载按钮逐条取得公开 PDF。"
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--session", default="standards")
    args = parser.parse_args()
    return browser_download(
        catalog_path=args.catalog,
        output_dir=args.output,
        session=args.session,
    )


if __name__ == "__main__":
    raise SystemExit(main())
