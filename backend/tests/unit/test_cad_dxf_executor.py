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
        frames = []
        for frame in task.get("frames", []):
            name = frame["name"]
            frames.append(
                {
                    "frame_id": frame["frame_id"],
                    "status": "ok",
                    "pdf_path": str(Path(task["output_dir"]) / f"{name}.pdf"),
                    "dwg_path": str(Path(task["output_dir"]) / f"{name}.dwg"),
                    "selection_count": 10,
                    "flags": [],
                },
            )

        sheet_sets = []
        for sheet_set in task.get("sheet_sets", []):
            name = sheet_set["name"]
            sheet_sets.append(
                {
                    "cluster_id": sheet_set["cluster_id"],
                    "status": "ok",
                    "pdf_path": str(Path(task["output_dir"]) / f"{name}.pdf"),
                    "dwg_path": str(Path(task["output_dir"]) / f"{name}.dwg"),
                    "page_count": len(sheet_set.get("pages", [])),
                    "flags": [],
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
        task = json.loads(task_json.read_text(encoding="utf-8"))
        stage_output = Path(task["output_dir"])
        stage_output.mkdir(parents=True, exist_ok=True)

        frames = []
        for frame in task.get("frames", []):
            name = frame["name"]
            pdf_path = stage_output / f"{name}.pdf"
            dwg_path = stage_output / f"{name}.dwg"
            pdf_path.write_text("pdf", encoding="utf-8")
            dwg_path.write_text("dwg", encoding="utf-8")
            frames.append(
                {
                    "frame_id": frame["frame_id"],
                    "status": "ok",
                    "pdf_path": str(pdf_path),
                    "dwg_path": str(dwg_path),
                    "selection_count": 2,
                    "flags": [],
                },
            )

        result = {
            "schema_version": "cad-dxf-result@1.0",
            "job_id": task["job_id"],
            "source_dxf": task["source_dxf"],
            "frames": frames,
            "sheet_sets": [],
            "errors": [],
        }
        result_json.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return {"exit_code": 0}


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

    assert task["selection"]["mode"] == "crossing"
    assert task["plot"]["pc3_name"] == "DWG To PDF.pc3"
    assert len(task["frames"]) == 1
    assert len(task["sheet_sets"]) == 1
    assert task["frames"][0]["frame_id"] == "f-1"


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
    sheet_set = _make_sheet_set("cluster-1", frame)
    runner = _RunnerSuccessStub()
    executor = _make_executor(runner=runner)

    result = executor.execute_source_dxf(
        job_id="job-1",
        source_dxf=source,
        frames=[frame],
        sheet_sets=[sheet_set],
        output_dir=output_dir,
        task_root=tmp_path / "tasks",
    )

    frames_by_id = {frame.frame_id: frame}
    sheet_sets_by_id = {sheet_set.cluster_id: sheet_set}
    frame_count, sheet_count = executor.apply_result(
        result=result,
        frames_by_id=frames_by_id,
        sheet_sets_by_id=sheet_sets_by_id,
    )

    assert frame_count == 1
    assert sheet_count == 1
    assert frame.runtime.pdf_path is not None
    assert frame.runtime.dwg_path is not None


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
