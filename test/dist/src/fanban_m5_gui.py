from __future__ import annotations

import ctypes
import sys
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from fanban_m5_launcher import (
    get_cad_settings_snapshot,
    list_recent_jobs,
    new_job_id,
    read_job_live_snapshot,
    read_job_summary,
    read_job_trace_excerpt,
    resolve_job_dir,
    run_split_only_job,
    save_launcher_settings,
    validate_runtime_bundle,
)
from src.pipeline.project_no_inference import infer_project_no_from_path

APP_TITLE = "拆图打印工具"
APP_EXECUTABLE_NAME = "拆图打印工具"
WATERMARK_TEXT = "by——建筑结构所 王任超"
WINDOW_GEOMETRY = "1360x940"
WINDOW_MINSIZE = (1180, 760)

STAGE_DEFINITIONS = [
    ("INGEST", "文件接收", None),
    ("CONVERT_DWG_TO_DXF", "DWG转DXF", ("dxf_processed", "dxf_total")),
    ("DETECT_FRAMES", "图框检测", None),
    ("VERIFY_FRAMES_BY_ANCHOR", "锚点校核", None),
    ("SCALE_FIT_AND_CHECK", "比例校核", None),
    ("EXTRACT_TITLEBLOCK_FIELDS", "图签提取", ("frames_field_done", "frames_field_total")),
    ("A4_MULTIPAGE_GROUPING", "A4多页组页", None),
    ("SPLIT_AND_RENAME", "拆图与重命名", ("split_done", "split_total")),
    ("EXPORT_PDF_AND_DWG", "PDF/DWG导出", ("export_done", "export_total")),
]


def resolve_project_field_update(
    *,
    current_value: str,
    auto_managed: bool,
    dwg_path: str | Path,
) -> tuple[str, bool]:
    inferred = infer_project_no_from_path(dwg_path)
    if not inferred:
        return current_value, auto_managed
    if auto_managed or not current_value.strip():
        return inferred, True
    return current_value, False


def format_cad_snapshot_summary(snapshot: dict) -> str:
    selected = snapshot.get("selected")
    if selected:
        cad_line = selected.get("label", selected.get("install_dir", ""))
        accore_line = selected.get("accoreconsole_exe", "")
    else:
        cad_line = "未检测到可用 CAD"
        accore_line = ""
    lines = [
        f"当前 CAD: {cad_line}",
        f"PC3: {snapshot.get('pc3_name', '')}",
        f"打印样式: {snapshot.get('ctb_name', '')}",
    ]
    if accore_line:
        lines.append(f"accoreconsole: {accore_line}")
    errors = snapshot.get("bundle_errors", [])
    if errors:
        lines.append("资源状态: 异常")
        lines.extend(errors)
    else:
        lines.append("资源状态: 正常")
    return "\n".join(lines)


def _stage_state(*, stage_name: str, current_stage: str, status: str) -> str:
    ordered = [item[0] for item in STAGE_DEFINITIONS]
    if stage_name not in ordered:
        return "未开始"
    if current_stage not in ordered:
        return "未开始"

    current_index = ordered.index(current_stage)
    stage_index = ordered.index(stage_name)
    normalized_status = (status or "").lower()

    if normalized_status == "failed" and stage_index == current_index:
        return "失败"
    if stage_index < current_index:
        return "已完成"
    if stage_index == current_index:
        if normalized_status == "succeeded":
            return "已完成"
        if normalized_status == "failed":
            return "失败"
        return "进行中"
    return "未开始"


def _stage_progress_suffix(details: dict, progress_keys: tuple[str, str] | None) -> str:
    if not progress_keys:
        return ""
    done_key, total_key = progress_keys
    done = details.get(done_key)
    total = details.get(total_key)
    if done is None or total in (None, 0):
        return ""
    return f" {done}/{total}"


def format_job_progress_detail(summary: dict, trace: str) -> str:
    if not summary:
        return "(job.json not ready)\n\n----- 最近日志 -----\n" + (trace or "(empty)")

    progress = summary.get("progress", {}) or {}
    details = progress.get("details", {}) or {}
    current_stage = str(progress.get("stage", "") or "")
    status = str(summary.get("status", "unknown"))

    lines = [
        f"任务: {summary.get('job_id', '')}",
        f"任务状态: {status}",
        f"项目号: {summary.get('project_no', '')}",
    ]
    current_file = progress.get("current_file")
    if current_file:
        lines.append(f"当前文件: {current_file}")
    lines.extend(
        [
            f"当前阶段: {current_stage or '(unknown)'}",
            f"总体进度: {progress.get('percent', 0)}%",
        ]
    )
    message = progress.get("message")
    if message:
        lines.append(f"消息: {message}")

    lines.append("")
    lines.append("阶段进度:")
    for stage_name, stage_label, progress_keys in STAGE_DEFINITIONS:
        state = _stage_state(stage_name=stage_name, current_stage=current_stage, status=status)
        suffix = _stage_progress_suffix(details, progress_keys)
        lines.append(f"[{state}] {stage_label}{suffix}")

    flags = summary.get("flags", []) or []
    if flags:
        lines.append("")
        lines.append(f"告警: {len(flags)} 项")
        for flag in flags[:8]:
            lines.append(f"- {flag}")
        if len(flags) > 8:
            lines.append(f"- ... 其余 {len(flags) - 8} 项")

    errors = summary.get("errors", []) or []
    if errors:
        lines.append("")
        for error in errors:
            lines.append(f"错误: {error}")

    lines.extend(["", "----- 最近日志 -----", trace or "(empty)"])
    return "\n".join(lines)


def _show_startup_error(message: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, message, f"{APP_TITLE} 启动失败", 0x10)
    except Exception:
        print(message, file=sys.stderr)


class CADSettingsDialog(tk.Toplevel):
    def __init__(self, master: tk.Tk, snapshot: dict, on_save) -> None:
        super().__init__(master)
        self.title("CAD设置")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self._options = snapshot.get("options", [])
        self._on_save = on_save
        self._selected_var = tk.StringVar(value=snapshot.get("selected_install_dir", ""))

        container = ttk.Frame(self, padding=16)
        container.pack(fill="both", expand=True)
        container.columnconfigure(1, weight=1)

        ttk.Label(container, text="CAD 版本").grid(row=0, column=0, sticky="w")
        option_values = [item["install_dir"] for item in self._options]
        self.combo = ttk.Combobox(
            container,
            values=option_values,
            textvariable=self._selected_var,
            state="readonly" if option_values else "normal",
            width=72,
        )
        self.combo.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        labels = {item["install_dir"]: item["label"] for item in self._options}
        selected_label = labels.get(self._selected_var.get(), "未检测到可用 CAD")
        ttk.Label(container, text=f"当前选择: {selected_label}").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

        detail = tk.Text(container, height=10, width=90, wrap="word")
        detail.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(12, 0))
        detail.insert("1.0", format_cad_snapshot_summary(snapshot))
        detail.configure(state="disabled")

        actions = ttk.Frame(container)
        actions.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(actions, text="保存", command=self._save).pack(side="right")
        ttk.Button(actions, text="关闭", command=self.destroy).pack(side="right", padx=(0, 8))

    def _save(self) -> None:
        self._on_save(self._selected_var.get().strip())
        self.destroy()


class FanbanM5App(tk.Tk):
    def __init__(self) -> None:
        bundle_errors = validate_runtime_bundle()
        if bundle_errors:
            raise RuntimeError("\n".join(bundle_errors))

        super().__init__()
        self.title(APP_TITLE)
        self.geometry(WINDOW_GEOMETRY)
        self.minsize(*WINDOW_MINSIZE)

        self.dwg_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.project_var = tk.StringVar(value="2016")
        self.status_var = tk.StringVar(value="就绪")
        self.cad_summary_var = tk.StringVar(value="正在检测 CAD...")
        self._jobs_index: dict[str, dict] = {}
        self._active_job_id: str | None = None
        self._poll_after_id: str | None = None
        self._poll_interval_ms = 1000
        self._project_auto_managed = True
        self._project_trace_guard = False
        self._cad_snapshot = get_cad_settings_snapshot()
        self._selected_cad_install_dir = str(self._cad_snapshot.get("selected_install_dir", ""))

        self._build_ui()
        self._refresh_cad_summary()
        self.project_var.trace_add("write", self._on_project_var_changed)
        self.refresh_jobs()

    def _build_ui(self) -> None:
        container = ttk.Frame(self, padding=16)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=2)
        container.rowconfigure(3, weight=4)
        container.rowconfigure(4, weight=0)

        form = ttk.LabelFrame(container, text="任务输入", padding=12)
        form.grid(row=0, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="DWG").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.dwg_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(form, text="选择DWG", command=self.pick_dwg).grid(row=0, column=2, sticky="ew")

        ttk.Label(form, text="输出目录").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(form, textvariable=self.output_var).grid(
            row=1, column=1, sticky="ew", padx=8, pady=(8, 0)
        )
        ttk.Button(form, text="选择目录", command=self.pick_output_dir).grid(
            row=1, column=2, sticky="ew", pady=(8, 0)
        )

        ttk.Label(form, text="项目号").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(form, textvariable=self.project_var, width=12).grid(
            row=2, column=1, sticky="w", padx=8, pady=(8, 0)
        )
        buttons = ttk.Frame(form)
        buttons.grid(row=2, column=2, sticky="ew", pady=(8, 0))
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        ttk.Button(buttons, text="CAD设置", command=self.open_cad_settings).grid(row=0, column=0, sticky="ew")
        ttk.Button(buttons, text="运行任务", command=self.run_job).grid(row=0, column=1, sticky="ew", padx=(8, 0))

        cad_frame = ttk.LabelFrame(container, text="CAD / 打印设置", padding=12)
        cad_frame.grid(row=1, column=0, sticky="ew", pady=(12, 12))
        cad_frame.columnconfigure(0, weight=1)
        ttk.Label(
            cad_frame,
            textvariable=self.cad_summary_var,
            justify="left",
            wraplength=1180,
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(cad_frame, text="刷新检测", command=self.refresh_cad_snapshot).grid(row=0, column=1, sticky="e")

        jobs_frame = ttk.LabelFrame(container, text="任务记录", padding=12)
        jobs_frame.grid(row=2, column=0, sticky="nsew")
        jobs_frame.columnconfigure(0, weight=1)
        jobs_frame.rowconfigure(0, weight=1)

        columns = ("job_id", "status", "project_no", "created_at")
        self.jobs_tree = ttk.Treeview(jobs_frame, columns=columns, show="headings", height=9)
        for col, title, width in (
            ("job_id", "Job ID", 280),
            ("status", "状态", 120),
            ("project_no", "项目号", 100),
            ("created_at", "创建时间", 220),
        ):
            self.jobs_tree.heading(col, text=title)
            self.jobs_tree.column(col, width=width, anchor="w")
        self.jobs_tree.grid(row=0, column=0, sticky="nsew")
        self.jobs_tree.bind("<<TreeviewSelect>>", self.on_job_selected)
        job_scroll = ttk.Scrollbar(jobs_frame, orient="vertical", command=self.jobs_tree.yview)
        job_scroll.grid(row=0, column=1, sticky="ns")
        self.jobs_tree.configure(yscrollcommand=job_scroll.set)

        detail = ttk.LabelFrame(container, text="任务详情 / 日志", padding=12)
        detail.grid(row=3, column=0, sticky="nsew")
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(0, weight=1)
        self.detail_text = tk.Text(detail, wrap="word")
        self.detail_text.grid(row=0, column=0, sticky="nsew")
        detail_scroll = ttk.Scrollbar(detail, orient="vertical", command=self.detail_text.yview)
        detail_scroll.grid(row=0, column=1, sticky="ns")
        self.detail_text.configure(yscrollcommand=detail_scroll.set)

        footer = ttk.Frame(container)
        footer.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(
            footer,
            text=WATERMARK_TEXT,
            foreground="#7a7a7a",
            anchor="e",
            justify="right",
        ).grid(row=0, column=0, sticky="e")

    def refresh_cad_snapshot(self) -> None:
        self._cad_snapshot = get_cad_settings_snapshot()
        self._selected_cad_install_dir = str(self._cad_snapshot.get("selected_install_dir", ""))
        self._refresh_cad_summary()

    def _refresh_cad_summary(self) -> None:
        self.cad_summary_var.set(format_cad_snapshot_summary(self._cad_snapshot))

    def open_cad_settings(self) -> None:
        dialog = CADSettingsDialog(self, self._cad_snapshot, self._save_cad_selection)
        self.wait_window(dialog)

    def _save_cad_selection(self, selected_install_dir: str) -> None:
        save_launcher_settings({"selected_cad_install_dir": selected_install_dir})
        self.refresh_cad_snapshot()

    def pick_dwg(self) -> None:
        file_path = filedialog.askopenfilename(
            title="选择DWG",
            filetypes=[("DWG files", "*.dwg"), ("All files", "*.*")],
        )
        if file_path:
            self.dwg_var.set(file_path)
            self._auto_fill_project_no(file_path)

    def pick_output_dir(self) -> None:
        dir_path = filedialog.askdirectory(title="选择输出目录")
        if dir_path:
            self.output_var.set(dir_path)

    def refresh_jobs(self) -> None:
        jobs = list_recent_jobs(limit=30)
        self._jobs_index = {job["job_id"]: job for job in jobs}
        for item in self.jobs_tree.get_children():
            self.jobs_tree.delete(item)
        for job in jobs:
            self.jobs_tree.insert(
                "",
                "end",
                iid=job["job_id"],
                values=(job["job_id"], job["status"], job["project_no"], job["created_at"]),
            )

    def on_job_selected(self, _event=None) -> None:
        selection = self.jobs_tree.selection()
        if not selection:
            return
        job_id = selection[0]
        job_info = self._jobs_index.get(job_id)
        if not job_info:
            return
        job_dir = Path(job_info["job_dir"])
        summary = read_job_summary(job_dir=job_dir)
        trace = read_job_trace_excerpt(job_dir=job_dir)
        self._set_detail_text(format_job_progress_detail(summary, trace))

    def run_job(self) -> None:
        dwg_path = self.dwg_var.get().strip()
        output_dir = self.output_var.get().strip()
        project_no = self.project_var.get().strip()
        if not dwg_path:
            messagebox.showerror("缺少输入", "请先选择 DWG 文件。")
            return
        if not output_dir:
            messagebox.showerror("缺少输出目录", "请先选择输出目录。")
            return

        job_id = new_job_id()
        self._active_job_id = job_id
        self.status_var.set(f"任务运行中: {job_id}")
        self._set_detail_text(f"job_id: {job_id}\nstatus: running\n")
        self._start_live_poll()

        def _worker() -> None:
            try:
                result = run_split_only_job(
                    dwg_path=Path(dwg_path),
                    selected_output_dir=Path(output_dir),
                    project_no=project_no,
                    job_id=job_id,
                    selected_install_dir=self._selected_cad_install_dir,
                )
            except Exception as exc:  # noqa: BLE001
                detail = "".join(traceback.format_exception(exc))
                self.after(0, lambda: self._handle_run_error(detail))
                return
            self.after(0, lambda: self._handle_run_success(result))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_project_var_changed(self, *_args) -> None:
        if self._project_trace_guard:
            return
        self._project_auto_managed = False

    def _set_project_var_auto(self, value: str) -> None:
        self._project_trace_guard = True
        try:
            self.project_var.set(value)
        finally:
            self._project_trace_guard = False
        self._project_auto_managed = True

    def _auto_fill_project_no(self, dwg_path: str | Path) -> None:
        value, auto_managed = resolve_project_field_update(
            current_value=self.project_var.get(),
            auto_managed=self._project_auto_managed,
            dwg_path=dwg_path,
        )
        if auto_managed:
            self._set_project_var_auto(value)
        else:
            self._project_auto_managed = False

    def _handle_run_success(self, result) -> None:
        self._stop_live_poll()
        snapshot = read_job_live_snapshot(job_dir=result.job_dir)
        flags = snapshot["summary"].get("flags", []) if snapshot["summary"] else []
        self.status_var.set(
            f"任务完成: {result.job.job_id} status={result.job.status.value} copied={result.copied_files} flags={len(flags)}"
        )
        self.refresh_jobs()
        self._set_detail_text(self._format_live_detail(snapshot))
        self._active_job_id = None

    def _handle_run_error(self, detail: str) -> None:
        self._stop_live_poll()
        self._active_job_id = None
        self.status_var.set("任务失败")
        self._set_detail_text(detail)
        messagebox.showerror("任务失败", detail)

    def _set_detail_text(self, text: str) -> None:
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", text)

    def _start_live_poll(self) -> None:
        self._stop_live_poll()
        self._poll_live_job()

    def _stop_live_poll(self) -> None:
        if self._poll_after_id is not None:
            self.after_cancel(self._poll_after_id)
            self._poll_after_id = None

    def _poll_live_job(self) -> None:
        if not self._active_job_id:
            return
        job_dir = resolve_job_dir(self._active_job_id)
        snapshot = read_job_live_snapshot(job_dir=job_dir)
        if snapshot["summary"]:
            self.refresh_jobs()
            self._set_detail_text(self._format_live_detail(snapshot))
            status = str(snapshot["summary"].get("status", "")).lower()
            if status in {"succeeded", "failed", "cancelled"}:
                self._poll_after_id = None
                return
        self._poll_after_id = self.after(self._poll_interval_ms, self._poll_live_job)

    def _format_live_detail(self, snapshot: dict) -> str:
        return format_job_progress_detail(snapshot.get("summary", {}), snapshot.get("trace", ""))


def json_dump(data: dict) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    try:
        FanbanM5App().mainloop()
    except Exception as exc:  # noqa: BLE001
        detail = "".join(traceback.format_exception(exc))
        _show_startup_error(detail)
        raise SystemExit(1)
