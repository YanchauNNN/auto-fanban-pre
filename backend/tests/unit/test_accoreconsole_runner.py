from __future__ import annotations

import json
import subprocess
from pathlib import Path

from src.cad.accoreconsole_runner import AcCoreConsoleRunner
from src.config import RuntimeConfig


def test_write_runtime_script_contains_frame_and_sheet_calls(tmp_path: Path):
    runner = AcCoreConsoleRunner(config=RuntimeConfig())

    runtime_scr = tmp_path / "runtime.scr"
    lsp_path = tmp_path / "module5_cad_executor.lsp"
    lsp_path.write_text("(princ)\n", encoding="utf-8")
    result_json = tmp_path / "result.json"
    module5_trace_log = tmp_path / "module5_trace.log"

    task_data = {
        "job_id": "job-1",
        "source_dxf": str(tmp_path / "src.dxf"),
        "output_dir": str(tmp_path / "out"),
        "plot": {
            "pc3_name": "DWG To PDF.pc3",
            "ctb_name": "monochrome.ctb",
            "use_monochrome": True,
            "margins_mm": {"top": 20, "bottom": 10, "left": 20, "right": 10},
        },
        "selection": {
            "bbox_margin_percent": 0.015,
            "empty_selection_retry_margin_percent": 0.03,
        },
        "frames": [
            {
                "frame_id": "f-1",
                "name": "N1",
                "bbox": {"xmin": 0, "ymin": 0, "xmax": 100, "ymax": 50},
                "paper_size_mm": [841.0, 594.0],
            },
        ],
        "sheet_sets": [
            {
                "cluster_id": "c-1",
                "name": "S1",
                "pages": [
                    {
                        "page_index": 1,
                        "bbox": {"xmin": 0, "ymin": 0, "xmax": 100, "ymax": 50},
                        "paper_size_mm": [297.0, 210.0],
                    },
                    {
                        "page_index": 2,
                        "bbox": {"xmin": 100, "ymin": 0, "xmax": 200, "ymax": 50},
                        "paper_size_mm": [297.0, 210.0],
                    },
                ],
            },
        ],
    }

    runner._write_runtime_script(
        runtime_scr=runtime_scr,
        lsp_path=lsp_path,
        task_data=task_data,
        result_json=result_json,
        module5_trace_log=module5_trace_log,
    )

    content = runtime_scr.read_text(encoding="utf-8")
    assert '(module5-reset "' in content
    assert '(module5-run-frame "f-1" "N1"' in content
    assert '(module5-run-sheet-set "c-1" "S1"' in content
    assert "(module5-finalize)" in content


def test_run_accepts_timeout_when_result_exists(tmp_path: Path, monkeypatch):
    cfg = RuntimeConfig()
    fake_exe = tmp_path / "accoreconsole.exe"
    fake_exe.write_text("", encoding="utf-8")
    script_dir = tmp_path / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "module5_cad_executor.lsp").write_text("(princ)\n", encoding="utf-8")
    cfg.module5_export.cad_runner.accoreconsole_exe = str(fake_exe)
    cfg.module5_export.cad_runner.script_dir = str(script_dir)
    cfg.module5_export.cad_runner.task_timeout_sec = 1
    cfg.module5_export.cad_runner.retry = 0

    source = tmp_path / "src.dxf"
    source.write_text("0\nEOF\n", encoding="utf-8")
    workspace = tmp_path / "work"
    workspace.mkdir(parents=True, exist_ok=True)
    task_json = workspace / "task.json"
    result_json = workspace / "result.json"
    task_json.write_text(
        json.dumps(
            {
                "job_id": "job-timeout",
                "source_dxf": str(source),
                "output_dir": str(workspace / "out"),
                "plot": {
                    "pc3_name": "DWG To PDF.pc3",
                    "ctb_name": "monochrome.ctb",
                    "use_monochrome": True,
                    "margins_mm": {"top": 20, "bottom": 10, "left": 20, "right": 10},
                },
                "selection": {
                    "bbox_margin_percent": 0.015,
                    "empty_selection_retry_margin_percent": 0.03,
                },
                "frames": [],
                "sheet_sets": [],
            },
        ),
        encoding="utf-8",
    )
    result_json.write_text("{}", encoding="utf-8")

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=kwargs.get("args", "accore"), timeout=1)

    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    runner = AcCoreConsoleRunner(config=cfg)
    result = runner.run(
        source_dxf=source,
        task_json=task_json,
        result_json=result_json,
        workspace_dir=workspace,
    )

    assert result.exit_code == 0
    assert result.result_json == result_json.resolve()


def test_run_accepts_nonzero_when_result_exists(tmp_path: Path, monkeypatch):
    cfg = RuntimeConfig()
    fake_exe = tmp_path / "accoreconsole.exe"
    fake_exe.write_text("", encoding="utf-8")
    script_dir = tmp_path / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "module5_cad_executor.lsp").write_text("(princ)\n", encoding="utf-8")
    cfg.module5_export.cad_runner.accoreconsole_exe = str(fake_exe)
    cfg.module5_export.cad_runner.script_dir = str(script_dir)
    cfg.module5_export.cad_runner.retry = 0

    source = tmp_path / "src.dxf"
    source.write_text("0\nEOF\n", encoding="utf-8")
    workspace = tmp_path / "work"
    workspace.mkdir(parents=True, exist_ok=True)
    task_json = workspace / "task.json"
    result_json = workspace / "result.json"
    task_json.write_text(
        json.dumps(
            {
                "job_id": "job-nonzero",
                "source_dxf": str(source),
                "output_dir": str(workspace / "out"),
                "plot": {
                    "pc3_name": "DWG To PDF.pc3",
                    "ctb_name": "monochrome.ctb",
                    "use_monochrome": True,
                    "margins_mm": {"top": 20, "bottom": 10, "left": 20, "right": 10},
                },
                "selection": {
                    "bbox_margin_percent": 0.015,
                    "empty_selection_retry_margin_percent": 0.03,
                },
                "frames": [],
                "sheet_sets": [],
            },
        ),
        encoding="utf-8",
    )
    result_json.write_text("{}", encoding="utf-8")

    def _return_nonzero(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=kwargs.get("args", []),
            returncode=1,
            stdout="non-zero",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", _return_nonzero)
    runner = AcCoreConsoleRunner(config=cfg)
    result = runner.run(
        source_dxf=source,
        task_json=task_json,
        result_json=result_json,
        workspace_dir=workspace,
    )

    assert result.result_json == result_json.resolve()


def test_resolve_runner_script_dir_with_default_relative_path():
    runner = AcCoreConsoleRunner(config=RuntimeConfig())
    assert runner.script_dir.exists()
    assert runner.script_dir.name == "scripts"
