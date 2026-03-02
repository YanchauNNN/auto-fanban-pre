"""
CADDXFExecutor 单元测试
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.cad.cad_dxf_executor import CADDXFExecutor
from src.config import RuntimeConfig
from src.models import BBox, FrameMeta, FrameRuntime, PageInfo, SheetSet, TitleblockFields


class _SpecStub:
    """最小化 spec stub，仅提供图幅查询。"""

    def __init__(self, margins: dict[str, float] | None = None) -> None:
        self.doc_generation = {
            "options": {
                "pdf_margin_mm": margins
                or {"top": 20.0, "bottom": 10.0, "left": 20.0, "right": 10.0},
            },
        }

    class _Variant:
        def __init__(self, w: float, h: float):
            self.W = w
            self.H = h

    def get_paper_variants(self):
        return {"CNPE_A1": self._Variant(841.0, 594.0)}


def _write_dummy_pdf(path: Path) -> None:
    from pypdf import PdfWriter
    from pypdf.generic import NameObject, StreamObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=200.0, height=120.0)
    stream = StreamObject()
    stream._data = b"q\n" + (b"0 0 m 100 100 l S\n" * 120) + b"Q\n"
    page[NameObject("/Contents")] = writer._add_object(stream)
    with open(path, "wb") as f:
        writer.write(f)


class _RunnerSuccessStub:
    """模拟 AcCoreConsole 成功执行并写入 result.json。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, *, source_dxf: Path, task_json: Path, result_json: Path, workspace_dir: Path):
        self.calls.append(
            {
                "source_dxf": source_dxf,
                "task_json": task_json,
                "result_json": result_json,
                "workspace_dir": workspace_dir,
            },
        )

        task = json.loads(task_json.read_text(encoding="utf-8"))
        stage_output = Path(task["output_dir"])
        stage_output.mkdir(parents=True, exist_ok=True)
        workflow_stage = task.get("workflow_stage", "split_only")
        frames = []
        sheet_sets = []
        if workflow_stage == "split_only":
            for frame in task.get("frames", []):
                name = frame["name"]
                dwg_path = stage_output / f"{name}.dwg"
                dwg_path.write_text("dwg", encoding="utf-8")
                frames.append(
                    {
                        "frame_id": frame["frame_id"],
                        "status": "ok",
                        "pdf_path": "",
                        "dwg_path": str(dwg_path),
                        "selection_count": 10,
                        "flags": [],
                    },
                )

            for sheet_set in task.get("sheet_sets", []):
                name = sheet_set["name"]
                dwg_path = stage_output / f"{name}.dwg"
                dwg_path.write_text("dwg", encoding="utf-8")
                page_dwg_paths: list[str] = []
                for page in sheet_set.get("pages", []):
                    page_index = int(page.get("page_index", 0))
                    page_dwg = stage_output / f"{name}__p{page_index}.dwg"
                    page_dwg.write_text("dwg", encoding="utf-8")
                    page_dwg_paths.append(str(page_dwg))
                sheet_sets.append(
                    {
                        "cluster_id": sheet_set["cluster_id"],
                        "status": "ok",
                        "pdf_path": str(stage_output / f"{name}.pdf"),
                        "dwg_path": str(dwg_path),
                        "page_count": len(sheet_set.get("pages", [])),
                        "flags": [],
                        "page_dwg_paths": page_dwg_paths,
                        "page_pdf_paths": [],
                    },
                )
        elif workflow_stage == "plot_from_split_dwg":
            for frame in task.get("frames", []):
                name = frame["name"]
                pdf_path = stage_output / f"{name}.pdf"
                _write_dummy_pdf(pdf_path)
                frames.append(
                    {
                        "frame_id": frame["frame_id"],
                        "status": "ok",
                        "pdf_path": str(pdf_path),
                        "dwg_path": str(source_dxf),
                        "selection_count": 1,
                        "flags": ["PLOT_EXTENTS_USED"],
                    },
                )
        elif workflow_stage == "plot_window_only":
            for frame in task.get("frames", []):
                name = frame["name"]
                pdf_path = stage_output / f"{name}.pdf"
                _write_dummy_pdf(pdf_path)
                frames.append(
                    {
                        "frame_id": frame["frame_id"],
                        "status": "ok",
                        "pdf_path": str(pdf_path),
                        "dwg_path": str(source_dxf),
                        "selection_count": 1,
                        "flags": ["PLOT_WINDOW_USED"],
                    },
                )

        result = {
            "schema_version": "cad-dxf-result@1.0",
            "job_id": task["job_id"],
            "source_dxf": task["source_dxf"],
            "frames": frames,
            "sheet_sets": sheet_sets,
            "errors": [],
        }
        result_json.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return {"exit_code": 0}


class _RunnerMaterializeStub:
    """模拟 CAD 在 staging 目录生成真实文件。"""

    def run(self, *, source_dxf: Path, task_json: Path, result_json: Path, workspace_dir: Path):
        helper = _RunnerSuccessStub()
        return helper.run(
            source_dxf=source_dxf,
            task_json=task_json,
            result_json=result_json,
            workspace_dir=workspace_dir,
        )


class _RunnerWindowFailFallbackStub(_RunnerSuccessStub):
    """窗口批量打印指定页失败，验证 split-dwg 定向回退。"""

    def __init__(self, *, fail_frame_ids: set[str] | None = None) -> None:
        super().__init__()
        self.fail_frame_ids = fail_frame_ids or set()

    def run(self, *, source_dxf: Path, task_json: Path, result_json: Path, workspace_dir: Path):
        self.calls.append(
            {
                "source_dxf": source_dxf,
                "task_json": task_json,
                "result_json": result_json,
                "workspace_dir": workspace_dir,
            },
        )
        task = json.loads(task_json.read_text(encoding="utf-8"))
        stage_output = Path(task["output_dir"])
        stage_output.mkdir(parents=True, exist_ok=True)
        workflow_stage = task.get("workflow_stage", "split_only")
        frames = []
        sheet_sets = []
        if workflow_stage == "split_only":
            helper = _RunnerSuccessStub()
            return helper.run(
                source_dxf=source_dxf,
                task_json=task_json,
                result_json=result_json,
                workspace_dir=workspace_dir,
            )
        if workflow_stage == "plot_window_only":
            for frame in task.get("frames", []):
                frame_id = frame["frame_id"]
                name = frame["name"]
                pdf_path = stage_output / f"{name}.pdf"
                if frame_id in self.fail_frame_ids:
                    frames.append(
                        {
                            "frame_id": frame_id,
                            "status": "failed",
                            "pdf_path": str(pdf_path),
                            "dwg_path": str(source_dxf),
                            "selection_count": 1,
                            "flags": ["PLOT_WINDOW_FAILED"],
                        },
                    )
                else:
                    _write_dummy_pdf(pdf_path)
                    frames.append(
                        {
                            "frame_id": frame_id,
                            "status": "ok",
                            "pdf_path": str(pdf_path),
                            "dwg_path": str(source_dxf),
                            "selection_count": 1,
                            "flags": ["PLOT_WINDOW_USED"],
                        },
                    )
        elif workflow_stage == "plot_from_split_dwg":
            for frame in task.get("frames", []):
                name = frame["name"]
                pdf_path = stage_output / f"{name}.pdf"
                _write_dummy_pdf(pdf_path)
                frames.append(
                    {
                        "frame_id": frame["frame_id"],
                        "status": "ok",
                        "pdf_path": str(pdf_path),
                        "dwg_path": str(source_dxf),
                        "selection_count": 1,
                        "flags": ["PLOT_EXTENTS_USED"],
                    },
                )
        result = {
            "schema_version": "cad-dxf-result@1.0",
            "job_id": task["job_id"],
            "source_dxf": task["source_dxf"],
            "frames": frames,
            "sheet_sets": sheet_sets,
            "errors": [],
        }
        result_json.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return {"exit_code": 0}


class _RunnerWindowOkMissingDwgStub(_RunnerSuccessStub):
    """split 缺少 dwg，但窗口打印成功。"""

    def run(self, *, source_dxf: Path, task_json: Path, result_json: Path, workspace_dir: Path):
        self.calls.append(
            {
                "source_dxf": source_dxf,
                "task_json": task_json,
                "result_json": result_json,
                "workspace_dir": workspace_dir,
            },
        )
        task = json.loads(task_json.read_text(encoding="utf-8"))
        stage_output = Path(task["output_dir"])
        stage_output.mkdir(parents=True, exist_ok=True)
        workflow_stage = task.get("workflow_stage", "split_only")
        frames: list[dict] = []
        if workflow_stage == "split_only":
            for frame in task.get("frames", []):
                frames.append(
                    {
                        "frame_id": frame["frame_id"],
                        "status": "failed",
                        "pdf_path": "",
                        "dwg_path": str(stage_output / f"{frame['name']}.dwg"),
                        "selection_count": 0,
                        "flags": ["WBLOCK_FAILED"],
                    },
                )
        elif workflow_stage == "plot_window_only":
            for frame in task.get("frames", []):
                pdf_path = stage_output / f"{frame['name']}.pdf"
                _write_dummy_pdf(pdf_path)
                frames.append(
                    {
                        "frame_id": frame["frame_id"],
                        "status": "ok",
                        "pdf_path": str(pdf_path),
                        "dwg_path": str(source_dxf),
                        "selection_count": 1,
                        "flags": ["PLOT_WINDOW_USED"],
                    },
                )
        result_json.write_text(
            json.dumps(
                {
                    "schema_version": "cad-dxf-result@1.0",
                    "job_id": task["job_id"],
                    "source_dxf": task["source_dxf"],
                    "frames": frames,
                    "sheet_sets": [],
                    "errors": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return {"exit_code": 0}


class _RunnerWindowInvalidPdfFallbackStub(_RunnerSuccessStub):
    """窗口打印返回无效PDF，验证回退到 split-dwg 打印。"""

    def run(self, *, source_dxf: Path, task_json: Path, result_json: Path, workspace_dir: Path):
        self.calls.append(
            {
                "source_dxf": source_dxf,
                "task_json": task_json,
                "result_json": result_json,
                "workspace_dir": workspace_dir,
            },
        )
        task = json.loads(task_json.read_text(encoding="utf-8"))
        stage_output = Path(task["output_dir"])
        stage_output.mkdir(parents=True, exist_ok=True)
        workflow_stage = task.get("workflow_stage", "split_only")
        frames: list[dict] = []
        if workflow_stage == "split_only":
            helper = _RunnerSuccessStub()
            return helper.run(
                source_dxf=source_dxf,
                task_json=task_json,
                result_json=result_json,
                workspace_dir=workspace_dir,
            )
        if workflow_stage == "plot_window_only":
            for frame in task.get("frames", []):
                pdf_path = stage_output / f"{frame['name']}.pdf"
                pdf_path.write_text("invalid-pdf", encoding="utf-8")
                frames.append(
                    {
                        "frame_id": frame["frame_id"],
                        "status": "ok",
                        "pdf_path": str(pdf_path),
                        "dwg_path": str(source_dxf),
                        "selection_count": 1,
                        "flags": ["PLOT_WINDOW_USED"],
                    },
                )
        elif workflow_stage == "plot_from_split_dwg":
            for frame in task.get("frames", []):
                pdf_path = stage_output / f"{frame['name']}.pdf"
                _write_dummy_pdf(pdf_path)
                frames.append(
                    {
                        "frame_id": frame["frame_id"],
                        "status": "ok",
                        "pdf_path": str(pdf_path),
                        "dwg_path": str(source_dxf),
                        "selection_count": 1,
                        "flags": ["PLOT_EXTENTS_USED"],
                    },
                )
        result_json.write_text(
            json.dumps(
                {
                    "schema_version": "cad-dxf-result@1.0",
                    "job_id": task["job_id"],
                    "source_dxf": task["source_dxf"],
                    "frames": frames,
                    "sheet_sets": [],
                    "errors": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return {"exit_code": 0}


class _RunnerWindowResultMissingStub(_RunnerSuccessStub):
    """窗口批量执行成功但未返回对应 frame 结果。"""

    def run(self, *, source_dxf: Path, task_json: Path, result_json: Path, workspace_dir: Path):
        self.calls.append(
            {
                "source_dxf": source_dxf,
                "task_json": task_json,
                "result_json": result_json,
                "workspace_dir": workspace_dir,
            },
        )
        task = json.loads(task_json.read_text(encoding="utf-8"))
        stage_output = Path(task["output_dir"])
        stage_output.mkdir(parents=True, exist_ok=True)
        workflow_stage = task.get("workflow_stage", "split_only")
        if workflow_stage == "split_only":
            helper = _RunnerSuccessStub()
            return helper.run(
                source_dxf=source_dxf,
                task_json=task_json,
                result_json=result_json,
                workspace_dir=workspace_dir,
            )
        if workflow_stage == "plot_window_only":
            result_json.write_text(
                json.dumps(
                    {
                        "schema_version": "cad-dxf-result@1.0",
                        "job_id": task["job_id"],
                        "source_dxf": task["source_dxf"],
                        "frames": [],
                        "sheet_sets": [],
                        "errors": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            return {"exit_code": 0}
        return _RunnerSuccessStub().run(
            source_dxf=source_dxf,
            task_json=task_json,
            result_json=result_json,
            workspace_dir=workspace_dir,
        )


class _RunnerDotnetFailThenLispSuccessStub(_RunnerSuccessStub):
    """dotnet 路由抛错，验证 Python 自动回退 lisp。"""

    def run(self, *, source_dxf: Path, task_json: Path, result_json: Path, workspace_dir: Path):
        self.calls.append(
            {
                "source_dxf": source_dxf,
                "task_json": task_json,
                "result_json": result_json,
                "workspace_dir": workspace_dir,
            },
        )
        task = json.loads(task_json.read_text(encoding="utf-8"))
        engines = task.get("engines", {})
        dotnet_bridge = engines.get("dotnet_bridge", {}) if isinstance(engines, dict) else {}
        if isinstance(dotnet_bridge, dict) and dotnet_bridge.get("enabled", False):
            raise RuntimeError("dotnet bridge unavailable")
        return _RunnerSuccessStub().run(
            source_dxf=source_dxf,
            task_json=task_json,
            result_json=result_json,
            workspace_dir=workspace_dir,
        )


def _make_runtime(frame_id: str, source_file: Path, bbox: BBox) -> FrameRuntime:
    return FrameRuntime(
        frame_id=frame_id,
        source_file=source_file,
        outer_bbox=bbox,
        paper_variant_id="CNPE_A1",
        sx=1.0,
        sy=1.0,
        geom_scale_factor=1.0,
        roi_profile_id="BASE10",
    )


def _make_frame(
    *,
    frame_id: str,
    source_file: Path,
    internal_code: str,
    external_code: str,
) -> FrameMeta:
    bbox = BBox(xmin=0, ymin=0, xmax=1000, ymax=600)
    runtime = _make_runtime(frame_id, source_file, bbox)
    tb = TitleblockFields(
        internal_code=internal_code,
        external_code=external_code,
        title_cn="测试图纸",
        page_total=1,
        page_index=1,
    )
    return FrameMeta(runtime=runtime, titleblock=tb)


def _make_sheet_set(cluster_id: str, frame: FrameMeta) -> SheetSet:
    page = PageInfo(
        page_index=1,
        outer_bbox=frame.runtime.outer_bbox,
        has_titleblock=True,
        frame_meta=frame,
    )
    return SheetSet(
        cluster_id=cluster_id,
        page_total=1,
        pages=[page],
        master_page=page,
    )


def _make_sheet_set_two_pages(cluster_id: str, frame: FrameMeta) -> SheetSet:
    page1 = PageInfo(
        page_index=1,
        outer_bbox=frame.runtime.outer_bbox,
        has_titleblock=True,
        frame_meta=frame,
    )
    page2 = PageInfo(
        page_index=2,
        outer_bbox=BBox(xmin=0, ymin=0, xmax=900, ymax=600),
        has_titleblock=True,
        frame_meta=frame,
    )
    return SheetSet(
        cluster_id=cluster_id,
        page_total=2,
        pages=[page1, page2],
        master_page=page1,
    )


def _make_executor(
    config: RuntimeConfig | None = None,
    runner=None,
    spec: _SpecStub | None = None,
) -> CADDXFExecutor:
    return CADDXFExecutor(
        config=config or RuntimeConfig(),
        runner=runner or _RunnerSuccessStub(),
        spec=spec or _SpecStub(),
    )


def test_build_task_json_from_frames_and_sheet_sets(tmp_path: Path):
    source = tmp_path / "src.dxf"
    source.write_text("0\nEOF\n", encoding="utf-8")
    frame = _make_frame(
        frame_id="f-1",
        source_file=source,
        internal_code="20161NH-JGS03-001",
        external_code="JD1NHH11001B25C42SD",
    )
    sheet_set = _make_sheet_set("cluster-1", frame)
    executor = _make_executor()

    task = executor.build_task_json(
        job_id="job-1",
        source_dxf=source,
        frames=[frame],
        sheet_sets=[sheet_set],
        output_dir=tmp_path / "out",
    )

    assert task["selection"]["mode"] == "database"
    assert task["plot"]["pc3_name"] == "DWG To PDF.pc3"
    assert task["engines"]["selection_engine"] == "dotnet"
    assert task["engines"]["plot_engine"] == "dotnet"
    assert task["engines"]["dotnet_bridge"]["enabled"] is True
    assert len(task["frames"]) == 1
    assert len(task["sheet_sets"]) == 1
    assert task["frames"][0]["frame_id"] == "f-1"


def test_build_task_json_contains_split_dwg_output_strategy(tmp_path: Path):
    source = tmp_path / "src.dxf"
    source.write_text("0\nEOF\n", encoding="utf-8")
    frame = _make_frame(
        frame_id="f-1",
        source_file=source,
        internal_code="20161NH-JGS03-001",
        external_code="JD1NHH11001B25C42SD",
    )
    executor = _make_executor()

    task = executor.build_task_json(
        job_id="job-1",
        source_dxf=source,
        frames=[frame],
        sheet_sets=[],
        output_dir=tmp_path / "out",
        workflow_stage="plot_from_split_dwg",
    )

    assert task["workflow_stage"] == "plot_from_split_dwg"
    assert task["output"]["pdf_from_split_dwg_mode"] == "always"
    assert task["output"]["plot_preferred_area"] == "extents"
    assert task["output"]["plot_fallback_area"] == "window"
    assert task["output"]["split_stage_plot_enabled"] is False


def test_plot_margins_mapping_from_doc_generation_spec(tmp_path: Path):
    source = tmp_path / "src.dxf"
    source.write_text("0\nEOF\n", encoding="utf-8")
    frame = _make_frame(
        frame_id="f-1",
        source_file=source,
        internal_code="20161NH-JGS03-001",
        external_code="JD1NHH11001B25C42SD",
    )
    spec = _SpecStub(margins={"top": 1.0, "bottom": 2.0, "left": 3.0, "right": 4.0})
    executor = _make_executor(spec=spec)

    task = executor.build_task_json(
        job_id="job-1",
        source_dxf=source,
        frames=[frame],
        sheet_sets=[],
        output_dir=tmp_path / "out",
    )

    assert task["plot"]["margins_mm"] == {
        "top": 1.0,
        "bottom": 2.0,
        "left": 3.0,
        "right": 4.0,
    }


def test_group_by_source_dxf(tmp_path: Path):
    source_a = tmp_path / "a.dxf"
    source_b = tmp_path / "b.dxf"
    source_a.write_text("0\nEOF\n", encoding="utf-8")
    source_b.write_text("0\nEOF\n", encoding="utf-8")

    frame_a = _make_frame(
        frame_id="fa",
        source_file=source_a,
        internal_code="A-001",
        external_code="EA001",
    )
    frame_b = _make_frame(
        frame_id="fb",
        source_file=source_b,
        internal_code="B-001",
        external_code="EB001",
    )
    sheet_set = _make_sheet_set("cluster-a", frame_a)

    executor = _make_executor()
    grouped = executor.group_by_source_dxf([frame_a, frame_b], [sheet_set])

    assert len(grouped) == 2
    assert len(grouped[source_a.resolve()]["frames"]) == 1
    assert len(grouped[source_a.resolve()]["sheet_sets"]) == 1
    assert len(grouped[source_b.resolve()]["frames"]) == 1


def test_result_json_backfill_paths(tmp_path: Path):
    source = tmp_path / "src.dxf"
    source.write_text("0\nEOF\n", encoding="utf-8")
    output_dir = tmp_path / "drawings"
    output_dir.mkdir(parents=True, exist_ok=True)

    frame = _make_frame(
        frame_id="f-1",
        source_file=source,
        internal_code="I-001",
        external_code="E001",
    )
    runner = _RunnerSuccessStub()
    executor = _make_executor(runner=runner)

    result = executor.execute_source_dxf(
        job_id="job-1",
        source_dxf=source,
        frames=[frame],
        sheet_sets=[],
        output_dir=output_dir,
        task_root=tmp_path / "tasks",
    )

    frames_by_id = {frame.frame_id: frame}
    frame_count, sheet_count = executor.apply_result(
        result=result,
        frames_by_id=frames_by_id,
        sheet_sets_by_id={},
    )

    assert frame_count == 1
    assert sheet_count == 0
    assert frame.runtime.pdf_path is not None
    assert frame.runtime.dwg_path is not None


def test_page_index_sort_key_orders_numeric_suffix():
    paths = [
        Path("set__p10.dwg"),
        Path("set__p2.dwg"),
        Path("set__p1.dwg"),
        Path("set_invalid.dwg"),
    ]
    ordered = sorted(paths, key=CADDXFExecutor._page_index_sort_key)
    assert [p.name for p in ordered] == [
        "set__p1.dwg",
        "set__p2.dwg",
        "set__p10.dwg",
        "set_invalid.dwg",
    ]


def test_frame_failure_isolation(tmp_path: Path):
    source = tmp_path / "src.dxf"
    source.write_text("0\nEOF\n", encoding="utf-8")

    frame_ok = _make_frame(
        frame_id="f-ok",
        source_file=source,
        internal_code="I-001",
        external_code="E001",
    )
    frame_fail = _make_frame(
        frame_id="f-fail",
        source_file=source,
        internal_code="I-002",
        external_code="E002",
    )
    executor = _make_executor()
    result = {
        "frames": [
            {
                "frame_id": "f-ok",
                "status": "ok",
                "pdf_path": str(tmp_path / "ok.pdf"),
                "dwg_path": str(tmp_path / "ok.dwg"),
                "flags": [],
            },
            {
                "frame_id": "f-fail",
                "status": "failed",
                "pdf_path": "",
                "dwg_path": "",
                "flags": ["CAD选集为空"],
            },
        ],
        "sheet_sets": [],
        "errors": [],
    }
    executor.apply_result(
        result=result,
        frames_by_id={"f-ok": frame_ok, "f-fail": frame_fail},
        sheet_sets_by_id={},
    )

    assert frame_ok.runtime.pdf_path is not None
    assert frame_ok.runtime.dwg_path is not None
    assert "导出失败" in frame_fail.runtime.flags
    assert "CAD选集为空" in frame_fail.runtime.flags


def test_sheet_set_partial_failure_flags(tmp_path: Path):
    source = tmp_path / "src.dxf"
    source.write_text("0\nEOF\n", encoding="utf-8")
    frame = _make_frame(
        frame_id="f-1",
        source_file=source,
        internal_code="I-001",
        external_code="E001",
    )
    sheet_set = _make_sheet_set("cluster-1", frame)
    executor = _make_executor()

    result = {
        "frames": [],
        "sheet_sets": [
            {
                "cluster_id": "cluster-1",
                "status": "failed",
                "flags": ["A4多页_部分页失败"],
            },
        ],
        "errors": [],
    }
    executor.apply_result(
        result=result,
        frames_by_id={},
        sheet_sets_by_id={sheet_set.cluster_id: sheet_set},
    )

    assert "A4多页_部分页失败" in sheet_set.flags
    assert "导出失败" in sheet_set.flags


def test_name_collision_policy(tmp_path: Path):
    source = tmp_path / "src.dxf"
    source.write_text("0\nEOF\n", encoding="utf-8")
    frame_a = _make_frame(
        frame_id="f-1",
        source_file=source,
        internal_code="DUP-001",
        external_code="E001",
    )
    frame_b = _make_frame(
        frame_id="f-2",
        source_file=source,
        internal_code="DUP-001",
        external_code="E002",
    )
    executor = _make_executor(config=RuntimeConfig())

    with pytest.raises(ValueError):
        executor.build_task_json(
            job_id="job-1",
            source_dxf=source,
            frames=[frame_a, frame_b],
            sheet_sets=[],
            output_dir=tmp_path / "out",
        )


def test_execute_source_dxf_materializes_staging_outputs(tmp_path: Path):
    source = tmp_path / "源图.dxf"
    source.write_text("0\nEOF\n", encoding="utf-8")
    output_dir = tmp_path / "输出目录"
    output_dir.mkdir(parents=True, exist_ok=True)
    frame = _make_frame(
        frame_id="f-1",
        source_file=source,
        internal_code="I-001",
        external_code="E001",
    )
    executor = _make_executor(runner=_RunnerMaterializeStub())

    result = executor.execute_source_dxf(
        job_id="job-1",
        source_dxf=source,
        frames=[frame],
        sheet_sets=[],
        output_dir=output_dir,
        task_root=tmp_path / "任务目录",
    )

    item = result["frames"][0]
    pdf_path = Path(item["pdf_path"])
    dwg_path = Path(item["dwg_path"])
    assert pdf_path.exists()
    assert dwg_path.exists()
    assert pdf_path.parent == output_dir
    assert dwg_path.parent == output_dir


def test_safe_task_dir_name_strips_non_ascii():
    name = CADDXFExecutor._safe_task_dir_name(Path("2016仿真图.dxf"))
    assert name.startswith("2016_")
    assert all(ch.isascii() for ch in name)


def test_execute_source_dxf_runs_split_then_plot_without_python_fallback(tmp_path: Path):
    source = tmp_path / "src.dxf"
    source.write_text("0\nEOF\n", encoding="utf-8")
    frame = _make_frame(
        frame_id="f-1", source_file=source, internal_code="I-001", external_code="E001"
    )
    runner = _RunnerSuccessStub()
    executor = _make_executor(runner=runner)
    output_dir = tmp_path / "drawings"
    output_dir.mkdir(parents=True, exist_ok=True)

    result = executor.execute_source_dxf(
        job_id="job-1",
        source_dxf=source,
        frames=[frame],
        sheet_sets=[],
        output_dir=output_dir,
        task_root=tmp_path / "tasks",
    )

    stages = [
        json.loads(call["task_json"].read_text(encoding="utf-8"))["workflow_stage"]
        for call in runner.calls
    ]
    assert stages[0] == "split_only"
    assert "plot_window_only" in stages
    assert "plot_from_split_dwg" not in stages
    assert "PDF_PYTHON_FALLBACK" not in result["frames"][0]["flags"]


def test_normalize_canvas_swaps_target_size_after_rotation(tmp_path: Path):
    pypdf = pytest.importorskip("pypdf")

    executor = _make_executor()

    pdf_path = tmp_path / "portrait.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(
        width=CADDXFExecutor._mm_to_pt(210.0),
        height=CADDXFExecutor._mm_to_pt(297.0),
    )
    with open(pdf_path, "wb") as f:
        writer.write(f)

    changed = executor._normalize_cad_pdf_canvas_for_paper(
        pdf_path=pdf_path,
        paper_size_mm=(297.0, 210.0),
    )
    assert changed is True

    reader = pypdf.PdfReader(str(pdf_path))
    page = reader.pages[0]
    width_mm = float(page.mediabox.width) * 25.4 / 72.0
    height_mm = float(page.mediabox.height) * 25.4 / 72.0
    assert width_mm == pytest.approx(240.0, abs=2.0)
    assert height_mm == pytest.approx(327.0, abs=2.0)
    assert height_mm > 296.0


def test_window_batch_failure_falls_back_to_split_for_single_frame(tmp_path: Path):
    source = tmp_path / "src.dxf"
    source.write_text("0\nEOF\n", encoding="utf-8")
    frame = _make_frame(
        frame_id="f-1",
        source_file=source,
        internal_code="I-001",
        external_code="E001",
    )
    runner = _RunnerWindowFailFallbackStub(fail_frame_ids={"f-1"})
    executor = _make_executor(runner=runner)
    output_dir = tmp_path / "drawings"
    output_dir.mkdir(parents=True, exist_ok=True)

    result = executor.execute_source_dxf(
        job_id="job-1",
        source_dxf=source,
        frames=[frame],
        sheet_sets=[],
        output_dir=output_dir,
        task_root=tmp_path / "tasks",
    )

    stages = [
        json.loads(call["task_json"].read_text(encoding="utf-8"))["workflow_stage"]
        for call in runner.calls
    ]
    assert stages[0] == "split_only"
    assert "plot_window_only" in stages
    assert "plot_from_split_dwg" in stages
    assert result["frames"][0]["status"] == "ok"
    assert "PLOT_FROM_SPLIT_FALLBACK" in result["frames"][0]["flags"]


def test_dotnet_engine_error_auto_falls_back_to_lisp(tmp_path: Path):
    source = tmp_path / "src.dxf"
    source.write_text("0\nEOF\n", encoding="utf-8")
    frame = _make_frame(
        frame_id="f-1",
        source_file=source,
        internal_code="I-001",
        external_code="E001",
    )
    runner = _RunnerDotnetFailThenLispSuccessStub()
    executor = _make_executor(runner=runner)
    result = executor.execute_source_dxf(
        job_id="job-1",
        source_dxf=source,
        frames=[frame],
        sheet_sets=[],
        output_dir=tmp_path / "drawings",
        task_root=tmp_path / "tasks",
    )
    assert result["frames"][0]["status"] == "ok"
    assert any(
        isinstance(err, str) and err.startswith("DOTNET_TO_LISP_FALLBACK:")
        for err in result["errors"]
    )


def test_sheet_page_window_failure_falls_back_only_failed_pages(tmp_path: Path):
    source = tmp_path / "src.dxf"
    source.write_text("0\nEOF\n", encoding="utf-8")
    frame = _make_frame(
        frame_id="f-1",
        source_file=source,
        internal_code="I-001",
        external_code="E001",
    )
    sheet_set = _make_sheet_set_two_pages("cluster-1", frame)
    # 仅让第2页窗口打印失败，验证定向回退。
    runner = _RunnerWindowFailFallbackStub(fail_frame_ids={"cluster-1__p2"})
    executor = _make_executor(runner=runner)
    output_dir = tmp_path / "drawings"
    output_dir.mkdir(parents=True, exist_ok=True)

    result = executor.execute_source_dxf(
        job_id="job-1",
        source_dxf=source,
        frames=[frame],
        sheet_sets=[sheet_set],
        output_dir=output_dir,
        task_root=tmp_path / "tasks",
    )

    stages = [
        json.loads(call["task_json"].read_text(encoding="utf-8"))["workflow_stage"]
        for call in runner.calls
    ]
    assert "plot_window_only" in stages
    assert "plot_from_split_dwg" in stages
    assert result["sheet_sets"][0]["status"] == "ok"
    assert "PLOT_FALLBACK_PAGE_OK:2" in result["sheet_sets"][0]["flags"]


def test_window_success_with_missing_split_dwg_still_marks_ok(tmp_path: Path):
    source = tmp_path / "src.dxf"
    source.write_text("0\nEOF\n", encoding="utf-8")
    frame = _make_frame(
        frame_id="f-1",
        source_file=source,
        internal_code="I-001",
        external_code="E001",
    )
    executor = _make_executor(runner=_RunnerWindowOkMissingDwgStub())
    result = executor.execute_source_dxf(
        job_id="job-1",
        source_dxf=source,
        frames=[frame],
        sheet_sets=[],
        output_dir=tmp_path / "drawings",
        task_root=tmp_path / "tasks",
    )
    item = result["frames"][0]
    assert item["status"] == "ok"
    assert "DWG_MISSING_FOR_PLOT" in item["flags"]
    assert Path(item["pdf_path"]).exists()


def test_window_invalid_pdf_falls_back_to_split_plot(tmp_path: Path):
    source = tmp_path / "src.dxf"
    source.write_text("0\nEOF\n", encoding="utf-8")
    frame = _make_frame(
        frame_id="f-1",
        source_file=source,
        internal_code="I-001",
        external_code="E001",
    )
    runner = _RunnerWindowInvalidPdfFallbackStub()
    executor = _make_executor(runner=runner)
    result = executor.execute_source_dxf(
        job_id="job-1",
        source_dxf=source,
        frames=[frame],
        sheet_sets=[],
        output_dir=tmp_path / "drawings",
        task_root=tmp_path / "tasks",
    )
    stages = [
        json.loads(call["task_json"].read_text(encoding="utf-8"))["workflow_stage"]
        for call in runner.calls
    ]
    assert "plot_from_split_dwg" in stages
    assert result["frames"][0]["status"] == "ok"
    assert any(
        str(flag).startswith("PLOT_WINDOW_INVALID_PDF:") for flag in result["frames"][0]["flags"]
    )


def test_window_invalid_pdf_without_fallback_marks_failed(tmp_path: Path):
    source = tmp_path / "src.dxf"
    source.write_text("0\nEOF\n", encoding="utf-8")
    frame = _make_frame(
        frame_id="f-1",
        source_file=source,
        internal_code="I-001",
        external_code="E001",
    )
    cfg = RuntimeConfig()
    cfg.module5_export.output.plot_fallback_to_split_on_failure = False
    runner = _RunnerWindowInvalidPdfFallbackStub()
    executor = _make_executor(config=cfg, runner=runner)
    result = executor.execute_source_dxf(
        job_id="job-1",
        source_dxf=source,
        frames=[frame],
        sheet_sets=[],
        output_dir=tmp_path / "drawings",
        task_root=tmp_path / "tasks",
    )
    stages = [
        json.loads(call["task_json"].read_text(encoding="utf-8"))["workflow_stage"]
        for call in runner.calls
    ]
    assert "plot_from_split_dwg" not in stages
    assert result["frames"][0]["status"] == "failed"


def test_missing_window_result_falls_back_to_split_plot(tmp_path: Path):
    source = tmp_path / "src.dxf"
    source.write_text("0\nEOF\n", encoding="utf-8")
    frame = _make_frame(
        frame_id="f-1",
        source_file=source,
        internal_code="I-001",
        external_code="E001",
    )
    runner = _RunnerWindowResultMissingStub()
    executor = _make_executor(runner=runner)
    result = executor.execute_source_dxf(
        job_id="job-1",
        source_dxf=source,
        frames=[frame],
        sheet_sets=[],
        output_dir=tmp_path / "drawings",
        task_root=tmp_path / "tasks",
    )
    assert result["frames"][0]["status"] == "ok"
    assert "PLOT_WINDOW_RESULT_MISSING" in result["frames"][0]["flags"]
    assert "PLOT_FROM_SPLIT_FALLBACK" in result["frames"][0]["flags"]


def test_load_result_json_accepts_utf8_bom(tmp_path: Path):
    result_json = tmp_path / "result.json"
    payload = {"schema_version": "cad-dxf-result@1.0", "frames": [], "sheet_sets": []}
    result_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig")

    loaded = CADDXFExecutor.load_result_json(result_json)

    assert loaded["schema_version"] == "cad-dxf-result@1.0"
    assert loaded["frames"] == []
