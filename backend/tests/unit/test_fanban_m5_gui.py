from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
GUI_PATH = PROJECT_ROOT / "test" / "dist" / "src" / "fanban_m5_gui.py"


def _load_gui():
    spec = importlib.util.spec_from_file_location("fanban_m5_gui", GUI_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_pick_dwg_project_no_overwrites_auto_managed_default() -> None:
    gui = _load_gui()

    value, auto_managed = gui.resolve_project_field_update(
        current_value="2016",
        auto_managed=True,
        dwg_path=Path("20261RS-JGS65.dwg"),
    )

    assert value == "2026"
    assert auto_managed is True


def test_pick_dwg_project_no_preserves_manual_value() -> None:
    gui = _load_gui()

    value, auto_managed = gui.resolve_project_field_update(
        current_value="1818",
        auto_managed=False,
        dwg_path=Path("20261RS-JGS65.dwg"),
    )

    assert value == "1818"
    assert auto_managed is False


def test_pick_dwg_project_no_keeps_current_value_when_not_inferable() -> None:
    gui = _load_gui()

    value, auto_managed = gui.resolve_project_field_update(
        current_value="2016",
        auto_managed=True,
        dwg_path=Path("sample.dwg"),
    )

    assert value == "2016"
    assert auto_managed is True


def test_format_cad_snapshot_summary_shows_selected_version_and_plot_style() -> None:
    gui = _load_gui()

    summary = gui.format_cad_snapshot_summary(
        {
            "selected": {
                "label": "AutoCAD 2022 | C:\\Program Files\\Autodesk\\AutoCAD 2022",
                "accoreconsole_exe": "C:\\Program Files\\Autodesk\\AutoCAD 2022\\accoreconsole.exe",
            },
            "pc3_name": "打印PDF2.pc3",
            "ctb_name": "fanban_monochrome.ctb",
            "bundle_errors": [],
        }
    )

    assert "AutoCAD 2022" in summary
    assert "打印PDF2.pc3" in summary
    assert "fanban_monochrome.ctb" in summary


def test_format_cad_snapshot_summary_reports_bundle_errors() -> None:
    gui = _load_gui()

    summary = gui.format_cad_snapshot_summary(
        {
            "selected": None,
            "pc3_name": "打印PDF2.pc3",
            "ctb_name": "fanban_monochrome.ctb",
            "bundle_errors": ["缺少关键运行资源"],
        }
    )

    assert "未检测到可用 CAD" in summary
    assert "缺少关键运行资源" in summary


def test_window_size_constants_are_large_enough() -> None:
    gui = _load_gui()

    assert gui.WINDOW_GEOMETRY == "1360x940"
    assert gui.WINDOW_MINSIZE == (1180, 760)


def test_app_title_and_watermark_constants() -> None:
    gui = _load_gui()

    assert gui.APP_TITLE == "拆图打印工具"
    assert gui.APP_EXECUTABLE_NAME == "拆图打印工具"
    assert gui.WATERMARK_TEXT == "by——建筑结构所 王任超"


def test_format_job_progress_detail_shows_stage_progress_and_trace() -> None:
    gui = _load_gui()

    detail = gui.format_job_progress_detail(
        {
            "job_id": "fanban-m5-1",
            "status": "running",
            "project_no": "2026",
            "progress": {
                "stage": "EXTRACT_TITLEBLOCK_FIELDS",
                "percent": 62,
                "current_file": "20261RS-JGS65.dwg",
                "message": "提取图签字段",
                "details": {
                    "dwg_total": 1,
                    "dwg_converted": 1,
                    "dxf_total": 1,
                    "dxf_processed": 1,
                    "frames_total": 14,
                    "frames_field_total": 14,
                    "frames_field_done": 8,
                },
            },
            "flags": ["PLOT_WINDOW_USED"],
            "errors": [],
        },
        "line-a\nline-b",
    )

    assert "任务状态: running" in detail
    assert "当前阶段: EXTRACT_TITLEBLOCK_FIELDS" in detail
    assert "总体进度: 62%" in detail
    assert "[进行中] 图签提取 8/14" in detail
    assert "[已完成] DWG转DXF 1/1" in detail
    assert "最近日志" in detail
    assert "line-a" in detail


def test_format_job_progress_detail_marks_failure_stage() -> None:
    gui = _load_gui()

    detail = gui.format_job_progress_detail(
        {
            "job_id": "fanban-m5-2",
            "status": "failed",
            "project_no": "2026",
            "progress": {
                "stage": "EXPORT_PDF_AND_DWG",
                "percent": 100,
                "message": "阶段失败",
                "details": {"export_total": 11, "export_done": 4},
            },
            "flags": [],
            "errors": ["CAD导出失败"],
        },
        "",
    )

    assert "[失败] PDF/DWG导出 4/11" in detail
    assert "错误: CAD导出失败" in detail
