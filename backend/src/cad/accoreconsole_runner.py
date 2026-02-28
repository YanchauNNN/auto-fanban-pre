"""
AcCoreConsole 运行器

职责：
- 生成运行期脚本
- 调用 accoreconsole.exe 执行 CAD 批处理
- 处理超时/重试/日志采集
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import RuntimeConfig, get_config


@dataclass(slots=True)
class AcCoreConsoleRunResult:
    """AcCoreConsole 单次执行结果。"""

    exit_code: int
    elapsed_sec: float
    command: list[str]
    stdout: str
    stderr: str
    task_json: Path
    result_json: Path


class AcCoreConsoleRunner:
    """AcCoreConsole 执行包装器。"""

    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self.config = config or get_config()
        runner_cfg = self.config.module5_export.cad_runner

        self.accoreconsole_exe = self._resolve_runner_path(
            runner_cfg.accoreconsole_exe,
        )
        self.script_dir = self._resolve_runner_path(runner_cfg.script_dir)
        self.task_timeout_sec = int(runner_cfg.task_timeout_sec)
        self.retry = int(runner_cfg.retry)
        self.locale = str(runner_cfg.locale)

    def run(
        self,
        *,
        source_dxf: Path,
        task_json: Path,
        result_json: Path,
        workspace_dir: Path,
    ) -> AcCoreConsoleRunResult:
        """执行一次 AcCoreConsole 任务。"""
        source_dxf = source_dxf.resolve()
        task_json = task_json.resolve()
        result_json = result_json.resolve()
        workspace_dir = workspace_dir.resolve()
        workspace_dir.mkdir(parents=True, exist_ok=True)

        if not source_dxf.exists():
            raise FileNotFoundError(f"source_dxf 不存在: {source_dxf}")
        if not task_json.exists():
            raise FileNotFoundError(f"task_json 不存在: {task_json}")
        if not self.accoreconsole_exe.exists():
            raise FileNotFoundError(
                f"accoreconsole.exe 不存在: {self.accoreconsole_exe}",
            )

        lsp_path = (self.script_dir / "module5_cad_executor.lsp").resolve()
        if not lsp_path.exists():
            raise FileNotFoundError(f"LISP脚本不存在: {lsp_path}")

        runtime_scr = workspace_dir / "runtime_module5.scr"
        runtime_log = workspace_dir / "accoreconsole.log"
        module5_trace_log = workspace_dir / "module5_trace.log"
        task_data = json.loads(task_json.read_text(encoding="utf-8"))
        self._write_runtime_script(
            runtime_scr=runtime_scr,
            lsp_path=lsp_path,
            task_data=task_data,
            result_json=result_json,
            module5_trace_log=module5_trace_log,
        )

        cmd = [
            str(self.accoreconsole_exe),
            "/i",
            str(source_dxf),
            "/s",
            str(runtime_scr),
            "/l",
            self.locale,
        ]

        last_exc: Exception | None = None
        for _ in range(self.retry + 1):
            t0 = time.monotonic()
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    timeout=self.task_timeout_sec,
                )
                elapsed = time.monotonic() - t0
                result = AcCoreConsoleRunResult(
                    exit_code=proc.returncode,
                    elapsed_sec=elapsed,
                    command=cmd,
                    stdout=proc.stdout or "",
                    stderr=proc.stderr or "",
                    task_json=task_json,
                    result_json=result_json,
                )
                if proc.returncode != 0 and not result_json.exists():
                    raise RuntimeError(
                        f"AcCoreConsole 返回码={proc.returncode}, stderr={result.stderr[:400]}",
                    )
                if not result_json.exists():
                    raise RuntimeError("AcCoreConsole 执行完成但 result.json 未生成")
                runtime_log.write_text(
                    "\n".join(
                        [
                            f"exit_code={proc.returncode}",
                            f"elapsed_sec={elapsed:.3f}",
                            "----- stdout -----",
                            result.stdout,
                            "----- stderr -----",
                            result.stderr,
                        ],
                    ),
                    encoding="utf-8",
                )
                return result
            except subprocess.TimeoutExpired as exc:
                elapsed = time.monotonic() - t0
                timeout_stdout = exc.stdout or ""
                timeout_stderr = exc.stderr or ""
                runtime_log.write_text(
                    "\n".join(
                        [
                            f"timeout=true elapsed_sec={elapsed:.3f}",
                            f"result_json_exists={result_json.exists()}",
                            "----- timeout_stdout -----",
                            timeout_stdout if isinstance(timeout_stdout, str) else "",
                            "----- timeout_stderr -----",
                            timeout_stderr if isinstance(timeout_stderr, str) else "",
                        ],
                    ),
                    encoding="utf-8",
                )
                # 实测存在“结果已落盘但进程未退出”的场景，此时优先接受 result.json。
                if result_json.exists():
                    return AcCoreConsoleRunResult(
                        exit_code=0,
                        elapsed_sec=elapsed,
                        command=cmd,
                        stdout=timeout_stdout if isinstance(timeout_stdout, str) else "",
                        stderr=timeout_stderr if isinstance(timeout_stderr, str) else "",
                        task_json=task_json,
                        result_json=result_json,
                    )
                last_exc = exc
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
        raise RuntimeError(f"AcCoreConsole 执行失败: {last_exc}") from last_exc

    @staticmethod
    def _resolve_runner_path(raw_path: str) -> Path:
        path = Path(raw_path)
        if path.is_absolute():
            return path.resolve()

        repo_root = Path(__file__).resolve().parents[3]
        candidates = [
            (Path.cwd() / path).resolve(),
            (repo_root / "documents" / path).resolve(),
            (repo_root / path).resolve(),
            (repo_root / "backend" / path).resolve(),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    @staticmethod
    def _quote_lisp_path(path: Path) -> str:
        """转义为 LISP 可读字符串。"""
        return path.as_posix().replace('"', '\\"')

    def _write_runtime_script(
        self,
        *,
        runtime_scr: Path,
        lsp_path: Path,
        task_data: dict[str, Any],
        result_json: Path,
        module5_trace_log: Path,
    ) -> None:
        """生成本次运行专用 SCR 文件。"""
        lsp_escaped = self._quote_lisp_path(lsp_path)
        lsp_dir_escaped = self._quote_lisp_path(lsp_path.parent)
        result_escaped = self._quote_lisp_path(result_json)
        trace_escaped = self._quote_lisp_path(module5_trace_log)
        source_dxf = self._quote_lisp_path(Path(task_data.get("source_dxf", "")))
        job_id = self._escape_lisp_string(str(task_data.get("job_id", "unknown")))
        output_dir = self._quote_lisp_path(Path(task_data.get("output_dir", "")))
        plot = task_data.get("plot", {})
        selection = task_data.get("selection", {})

        pc3_name = self._escape_lisp_string(str(plot.get("pc3_name", "DWG To PDF.pc3")))
        ctb_name = self._escape_lisp_string(str(plot.get("ctb_name", "monochrome.ctb")))
        use_monochrome = "T" if bool(plot.get("use_monochrome", True)) else "nil"
        margins = plot.get("margins_mm", {})
        margin_top = float(margins.get("top", 20.0))
        margin_bottom = float(margins.get("bottom", 10.0))
        margin_left = float(margins.get("left", 20.0))
        margin_right = float(margins.get("right", 10.0))

        bbox_margin = float(selection.get("bbox_margin_percent", 0.015))
        retry_margin = float(selection.get("empty_selection_retry_margin_percent", 0.03))

        content = [
            '(setvar "FILEDIA" 0)',
            '(setvar "CMDDIA" 0)',
            '(setvar "SECURELOAD" 0)',
            (f'(setvar "TRUSTEDPATHS" (strcat (getvar "TRUSTEDPATHS") ";{lsp_dir_escaped}"))'),
            f'(load "{lsp_escaped}")',
            (f'(module5-reset "{result_escaped}" "{job_id}" "{source_dxf}" "{trace_escaped}")'),
            (
                f'(module5-set-plot-config "{output_dir}" "{pc3_name}" "{ctb_name}" '
                f"{use_monochrome} {margin_top:.6f} {margin_bottom:.6f} "
                f"{margin_left:.6f} {margin_right:.6f} {bbox_margin:.6f} {retry_margin:.6f})"
            ),
        ]

        for frame in task_data.get("frames", []):
            frame_id = self._escape_lisp_string(str(frame.get("frame_id", "")))
            name = self._escape_lisp_string(str(frame.get("name", "")))
            bbox = frame.get("bbox", {})
            xmin = float(bbox.get("xmin", 0.0))
            ymin = float(bbox.get("ymin", 0.0))
            xmax = float(bbox.get("xmax", 0.0))
            ymax = float(bbox.get("ymax", 0.0))
            paper = frame.get("paper_size_mm") or [0.0, 0.0]
            paper_w = float(paper[0]) if len(paper) > 0 else 0.0
            paper_h = float(paper[1]) if len(paper) > 1 else 0.0
            content.append(
                (
                    f'(module5-run-frame "{frame_id}" "{name}" '
                    f"{xmin:.6f} {ymin:.6f} {xmax:.6f} {ymax:.6f} "
                    f"{paper_w:.6f} {paper_h:.6f})"
                ),
            )

        for sheet_set in task_data.get("sheet_sets", []):
            cluster_id = self._escape_lisp_string(str(sheet_set.get("cluster_id", "")))
            name = self._escape_lisp_string(str(sheet_set.get("name", "")))
            pages = sheet_set.get("pages", [])
            if not pages:
                content.append(
                    f'(module5-add-sheet-result "{cluster_id}" "failed" "" "" 0 '
                    '"A4_MULTI_NO_PAGES")',
                )
                continue

            union = self._union_pages_bbox(pages)
            page_count = len(pages)
            first_paper = pages[0].get("paper_size_mm") or [297.0, 210.0]
            paper_w = float(first_paper[0]) if len(first_paper) > 0 else 297.0
            paper_h = float(first_paper[1]) if len(first_paper) > 1 else 210.0
            content.append(
                (
                    f'(module5-run-sheet-set "{cluster_id}" "{name}" '
                    f"{union['xmin']:.6f} {union['ymin']:.6f} "
                    f"{union['xmax']:.6f} {union['ymax']:.6f} "
                    f"{paper_w:.6f} {paper_h:.6f} {page_count})"
                ),
            )

        content.extend(
            [
                "(module5-finalize)",
            ],
        )
        content.extend(
            [
                "_.QUIT",
                "_N",
            ],
        )
        runtime_scr.write_text("\n".join(content) + "\n", encoding="utf-8")

    @staticmethod
    def _escape_lisp_string(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    def _union_pages_bbox(pages: list[dict[str, Any]]) -> dict[str, float]:
        xmin = min(float(p["bbox"]["xmin"]) for p in pages)
        ymin = min(float(p["bbox"]["ymin"]) for p in pages)
        xmax = max(float(p["bbox"]["xmax"]) for p in pages)
        ymax = max(float(p["bbox"]["ymax"]) for p in pages)
        return {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax}
