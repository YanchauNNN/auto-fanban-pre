"""
AcCoreConsole 运行器

职责：
- 生成运行期脚本
- 调用 accoreconsole.exe 执行 CAD 批处理
- 处理超时/重试/日志采集
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import RuntimeConfig, get_config
from .autocad_path_resolver import resolve_autocad_paths

logger = logging.getLogger(__name__)


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
        if not self.accoreconsole_exe.exists():
            detected = resolve_autocad_paths(
                configured_install_dir=self.config.autocad.install_dir,
            ).accoreconsole_exe
            if detected is not None and detected.exists():
                self.accoreconsole_exe = detected.resolve()
                logger.warning(
                    "cad_runner.accoreconsole_exe 不存在，已回退到自动探测路径: %s",
                    self.accoreconsole_exe,
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
            task_json=task_json,
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
        task_json: Path,
        lsp_path: Path,
        task_data: dict[str, Any],
        result_json: Path,
        module5_trace_log: Path,
    ) -> None:
        """生成本次运行专用 SCR 文件。"""
        workflow_stage = str(task_data.get("workflow_stage", "split_only")).strip().lower()
        engines = task_data.get("engines", {})
        dotnet_bridge = (
            engines.get("dotnet_bridge", {})
            if isinstance(engines, dict) and isinstance(engines.get("dotnet_bridge", {}), dict)
            else {}
        )
        selection_engine = (
            str(engines.get("selection_engine", "lisp")).strip().lower()
            if isinstance(engines, dict)
            else "lisp"
        )
        plot_engine = (
            str(engines.get("plot_engine", "lisp")).strip().lower()
            if isinstance(engines, dict)
            else "lisp"
        )
        use_dotnet = bool(dotnet_bridge.get("enabled", False)) and (
            (workflow_stage == "split_only" and selection_engine == "dotnet")
            or (
                workflow_stage in {"plot_window_only", "plot_from_split_dwg"}
                and plot_engine == "dotnet"
            )
        )

        if use_dotnet:
            content = self._build_dotnet_runtime_content(
                task_json=task_json,
                result_json=result_json,
                module5_trace_log=module5_trace_log,
                dotnet_bridge=dotnet_bridge,
            )
        else:
            content = self._build_lisp_runtime_content(
                lsp_path=lsp_path,
                task_data=task_data,
                result_json=result_json,
                module5_trace_log=module5_trace_log,
            )
        content.extend(["_.QUIT", "_N"])
        runtime_scr.write_text("\n".join(content) + "\n", encoding="utf-8")

    def _build_dotnet_runtime_content(
        self,
        *,
        task_json: Path,
        result_json: Path,
        module5_trace_log: Path,
        dotnet_bridge: dict[str, Any],
    ) -> list[str]:
        dll_file = Path(str(dotnet_bridge.get("dll_path", "")))
        dll_path = self._quote_lisp_path(dll_file)
        command_name = self._escape_lisp_string(
            str(dotnet_bridge.get("command_name", "M5BRIDGE_RUN"))
        )
        task_json_escaped = self._quote_lisp_path(task_json)
        result_escaped = self._quote_lisp_path(result_json)
        trace_escaped = self._quote_lisp_path(module5_trace_log)
        netload_each_run = bool(dotnet_bridge.get("netload_each_run", True))
        content = [
            '(setvar "FILEDIA" 0)',
            '(setvar "CMDDIA" 0)',
            '(setvar "SECURELOAD" 0)',
        ]
        if netload_each_run:
            content.append(f'(command "_.NETLOAD" "{dll_path}")')
        content.append(
            f'(command "{command_name}" "{task_json_escaped}" "{result_escaped}" "{trace_escaped}")',
        )
        return content

    def _build_lisp_runtime_content(
        self,
        *,
        lsp_path: Path,
        task_data: dict[str, Any],
        result_json: Path,
        module5_trace_log: Path,
    ) -> list[str]:
        lsp_escaped = self._quote_lisp_path(lsp_path)
        lsp_dir_escaped = self._quote_lisp_path(lsp_path.parent)
        result_escaped = self._quote_lisp_path(result_json)
        trace_escaped = self._quote_lisp_path(module5_trace_log)
        source_dxf = self._quote_lisp_path(Path(task_data.get("source_dxf", "")))
        job_id = self._escape_lisp_string(str(task_data.get("job_id", "unknown")))
        output_dir = self._quote_lisp_path(Path(task_data.get("output_dir", "")))
        plot = task_data.get("plot", {})
        selection = task_data.get("selection", {})
        output = task_data.get("output", {})
        workflow_stage = str(task_data.get("workflow_stage", "split_only")).strip().lower()

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
        hard_retry_margin = float(selection.get("hard_retry_margin_percent", 0.25))
        selection_mode = self._escape_lisp_string(str(selection.get("mode", "database")))
        db_unknown_bbox_policy = self._escape_lisp_string(
            str(selection.get("db_unknown_bbox_policy", "keep_if_uncertain")),
        )
        db_fallback_to_crossing = (
            "T" if bool(selection.get("db_fallback_to_crossing", True)) else "nil"
        )
        pdf_from_split_mode = self._escape_lisp_string(
            str(output.get("pdf_from_split_dwg_mode", "always")),
        )
        plot_preferred_area = self._escape_lisp_string(
            str(output.get("plot_preferred_area", "extents")),
        )
        plot_fallback_area = self._escape_lisp_string(
            str(output.get("plot_fallback_area", "window")),
        )
        split_stage_plot_enabled = (
            "T" if bool(output.get("split_stage_plot_enabled", False)) else "nil"
        )

        content: list[str] = [
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
            (
                f'(module5-set-selection-config "{selection_mode}" {hard_retry_margin:.6f} '
                f'"{db_unknown_bbox_policy}" {db_fallback_to_crossing})'
            ),
            (
                f'(module5-set-output-config "{pdf_from_split_mode}" '
                f'"{plot_preferred_area}" "{plot_fallback_area}" {split_stage_plot_enabled})'
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
            vertices = self._frame_vertices(frame, bbox)
            paper = frame.get("paper_size_mm") or [0.0, 0.0]
            paper_w = float(paper[0]) if len(paper) > 0 else 0.0
            paper_h = float(paper[1]) if len(paper) > 1 else 0.0
            sx = float(frame.get("sx")) if frame.get("sx") is not None else 0.0
            sy = float(frame.get("sy")) if frame.get("sy") is not None else 0.0
            frame_runner = "module5-run-frame"
            if workflow_stage == "split_only":
                frame_runner = "module5-run-frame-split"
            elif workflow_stage == "plot_from_split_dwg":
                frame_runner = "module5-run-frame-plot-from-split"
            elif workflow_stage == "plot_window_only":
                frame_runner = "module5-run-frame-plot-window"
            content.append(
                (
                    f'({frame_runner} "{frame_id}" "{name}" '
                    f"{xmin:.6f} {ymin:.6f} {xmax:.6f} {ymax:.6f} "
                    f"{vertices[0][0]:.6f} {vertices[0][1]:.6f} "
                    f"{vertices[1][0]:.6f} {vertices[1][1]:.6f} "
                    f"{vertices[2][0]:.6f} {vertices[2][1]:.6f} "
                    f"{vertices[3][0]:.6f} {vertices[3][1]:.6f} "
                    f"{sx:.6f} {sy:.6f} "
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
                    '"A4_MULTI_NO_PAGES" nil nil)',
                )
                continue

            page_count = len(pages)
            first_paper = pages[0].get("paper_size_mm") or [297.0, 210.0]
            paper_w = float(first_paper[0]) if len(first_paper) > 0 else 297.0
            paper_h = float(first_paper[1]) if len(first_paper) > 1 else 210.0
            pages_expr = self._pages_to_lisp_list(pages)
            sheet_runner = "module5-run-sheet-set"
            if workflow_stage == "split_only":
                sheet_runner = "module5-run-sheet-set-split"
            content.append(
                (
                    f'({sheet_runner} "{cluster_id}" "{name}" '
                    f"{pages_expr} "
                    f"{paper_w:.6f} {paper_h:.6f} {page_count})"
                ),
            )

        content.append("(module5-finalize)")
        return content

    @staticmethod
    def _escape_lisp_string(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    def _frame_vertices(frame: dict[str, Any], bbox: dict[str, Any]) -> list[tuple[float, float]]:
        raw_vertices = frame.get("vertices")
        if isinstance(raw_vertices, list) and len(raw_vertices) >= 4:
            parsed: list[tuple[float, float]] = []
            for item in raw_vertices[:4]:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    parsed.append((float(item[0]), float(item[1])))
            if len(parsed) == 4:
                return parsed

        xmin = float(bbox.get("xmin", 0.0))
        ymin = float(bbox.get("ymin", 0.0))
        xmax = float(bbox.get("xmax", 0.0))
        ymax = float(bbox.get("ymax", 0.0))
        return [
            (xmin, ymin),
            (xmax, ymin),
            (xmax, ymax),
            (xmin, ymax),
        ]

    @staticmethod
    def _pages_to_lisp_list(pages: list[dict[str, Any]]) -> str:
        literals: list[str] = []
        for page in pages:
            page_index = int(page.get("page_index", 0))
            bbox = page.get("bbox", {})
            xmin = float(bbox.get("xmin", 0.0))
            ymin = float(bbox.get("ymin", 0.0))
            xmax = float(bbox.get("xmax", 0.0))
            ymax = float(bbox.get("ymax", 0.0))
            vertices = page.get("vertices")
            if isinstance(vertices, list) and len(vertices) >= 4:
                parsed: list[tuple[float, float]] = []
                for item in vertices[:4]:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        parsed.append((float(item[0]), float(item[1])))
                if len(parsed) == 4:
                    vx1, vy1 = parsed[0]
                    vx2, vy2 = parsed[1]
                    vx3, vy3 = parsed[2]
                    vx4, vy4 = parsed[3]
                else:
                    vx1, vy1, vx2, vy2, vx3, vy3, vx4, vy4 = (
                        xmin,
                        ymin,
                        xmax,
                        ymin,
                        xmax,
                        ymax,
                        xmin,
                        ymax,
                    )
            else:
                vx1, vy1, vx2, vy2, vx3, vy3, vx4, vy4 = (
                    xmin,
                    ymin,
                    xmax,
                    ymin,
                    xmax,
                    ymax,
                    xmin,
                    ymax,
                )
            sx = float(page.get("sx")) if page.get("sx") is not None else 0.0
            sy = float(page.get("sy")) if page.get("sy") is not None else 0.0
            literals.append(
                "(list "
                f"{page_index:d} "
                f"{xmin:.6f} {ymin:.6f} {xmax:.6f} {ymax:.6f} "
                f"{vx1:.6f} {vy1:.6f} {vx2:.6f} {vy2:.6f} "
                f"{vx3:.6f} {vy3:.6f} {vx4:.6f} {vy4:.6f} "
                f"{sx:.6f} {sy:.6f})",
            )
        return f"(list {' '.join(literals)})"
