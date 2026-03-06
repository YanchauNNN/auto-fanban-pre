from __future__ import annotations

import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from fanban_m5_launcher import (
    list_recent_jobs,
    read_job_summary,
    read_job_trace_excerpt,
    run_split_only_job,
)


class FanbanM5App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Fanban Module5")
        self.geometry("1100x760")
        self.minsize(960, 640)

        self.dwg_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.project_var = tk.StringVar(value="2016")
        self.status_var = tk.StringVar(value="就绪")
        self._jobs_index: dict[str, dict] = {}

        self._build_ui()
        self.refresh_jobs()

    def _build_ui(self) -> None:
        container = ttk.Frame(self, padding=16)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)
        container.rowconfigure(3, weight=1)

        form = ttk.LabelFrame(container, text="任务输入", padding=12)
        form.grid(row=0, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="DWG").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.dwg_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(form, text="选择DWG", command=self.pick_dwg).grid(row=0, column=2, sticky="ew")

        ttk.Label(form, text="输出目录").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(form, textvariable=self.output_var).grid(
            row=1,
            column=1,
            sticky="ew",
            padx=8,
            pady=(8, 0),
        )
        ttk.Button(form, text="选择目录", command=self.pick_output_dir).grid(
            row=1,
            column=2,
            sticky="ew",
            pady=(8, 0),
        )

        ttk.Label(form, text="项目号").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(form, textvariable=self.project_var, width=12).grid(
            row=2,
            column=1,
            sticky="w",
            padx=8,
            pady=(8, 0),
        )
        ttk.Button(form, text="运行任务", command=self.run_job).grid(
            row=2,
            column=2,
            sticky="ew",
            pady=(8, 0),
        )

        status = ttk.Frame(container)
        status.grid(row=1, column=0, sticky="ew", pady=(12, 12))
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        ttk.Button(status, text="刷新任务记录", command=self.refresh_jobs).grid(row=0, column=1, sticky="e")

        jobs_frame = ttk.LabelFrame(container, text="任务记录", padding=12)
        jobs_frame.grid(row=2, column=0, sticky="nsew")
        jobs_frame.columnconfigure(0, weight=1)
        jobs_frame.rowconfigure(0, weight=1)

        columns = ("job_id", "status", "project_no", "created_at")
        self.jobs_tree = ttk.Treeview(jobs_frame, columns=columns, show="headings", height=10)
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
        detail.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(0, weight=1)
        self.detail_text = tk.Text(detail, wrap="word")
        self.detail_text.grid(row=0, column=0, sticky="nsew")
        detail_scroll = ttk.Scrollbar(detail, orient="vertical", command=self.detail_text.yview)
        detail_scroll.grid(row=0, column=1, sticky="ns")
        self.detail_text.configure(yscrollcommand=detail_scroll.set)

    def pick_dwg(self) -> None:
        file_path = filedialog.askopenfilename(
            title="选择DWG",
            filetypes=[("DWG files", "*.dwg"), ("All files", "*.*")],
        )
        if file_path:
            self.dwg_var.set(file_path)

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
                values=(
                    job["job_id"],
                    job["status"],
                    job["project_no"],
                    job["created_at"],
                ),
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
        detail = [
            json_dump(summary),
            "",
            "----- module5_trace.log -----",
            trace or "(empty)",
        ]
        self._set_detail_text("\n".join(detail))

    def run_job(self) -> None:
        dwg_path = self.dwg_var.get().strip()
        output_dir = self.output_var.get().strip()
        project_no = self.project_var.get().strip() or "2016"
        if not dwg_path:
            messagebox.showerror("缺少输入", "请先选择DWG文件。")
            return
        if not output_dir:
            messagebox.showerror("缺少输出目录", "请先选择输出目录。")
            return

        self.status_var.set("任务运行中...")

        def _worker():
            try:
                result = run_split_only_job(
                    dwg_path=Path(dwg_path),
                    selected_output_dir=Path(output_dir),
                    project_no=project_no,
                )
            except Exception as exc:  # noqa: BLE001
                detail = "".join(traceback.format_exception(exc))
                self.after(0, lambda: self._handle_run_error(detail))
                return

            self.after(0, lambda: self._handle_run_success(result))

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_run_success(self, result) -> None:
        self.status_var.set(
            f"任务完成: {result.job.job_id} status={result.job.status.value} copied={result.copied_files}"
        )
        self.refresh_jobs()
        self._set_detail_text(
            "\n".join(
                [
                    f"job_id: {result.job.job_id}",
                    f"status: {result.job.status.value}",
                    f"job_dir: {result.job_dir}",
                    f"selected_output_dir: {result.selected_output_dir}",
                    f"copied_files: {result.copied_files}",
                ],
            ),
        )

    def _handle_run_error(self, detail: str) -> None:
        self.status_var.set("任务失败")
        self._set_detail_text(detail)
        messagebox.showerror("任务失败", detail)

    def _set_detail_text(self, text: str) -> None:
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", text)


def json_dump(data: dict) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    FanbanM5App().mainloop()
