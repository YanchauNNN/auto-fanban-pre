"""
pytest 配置与公共 fixtures

使用方式：
    def test_something(spec, temp_job):
        assert spec.schema_version == "2.0"
"""

from __future__ import annotations

import tempfile
import os
import uuid
from collections.abc import Generator
from pathlib import Path

import ezdxf
import pytest

from src.config import BusinessSpec, RuntimeConfig, SpecLoader, reload_config
from src.models import (
    BBox,
    DerivedFields,
    DocContext,
    FrameMeta,
    FrameRuntime,
    GlobalDocParams,
    Job,
    JobType,
    TitleblockFields,
)

# ============================================================================
# 配置 Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def spec() -> BusinessSpec:
    """加载业务规范（会话级别缓存）"""
    # 尝试加载真实规范，失败则使用mock
    try:
        return SpecLoader.load("documents/参数规范.yaml")
    except FileNotFoundError:
        return _create_mock_spec()


@pytest.fixture
def runtime_config() -> RuntimeConfig:
    """运行期配置"""
    return RuntimeConfig()

@pytest.fixture(autouse=True)
def _isolate_fanban_env(monkeypatch):
    """Ensure FANBAN_* env/config state does not leak across tests."""
    original_cwd = Path.cwd()
    for key in [name for name in os.environ if name.startswith("FANBAN_")]:
        monkeypatch.delenv(key, raising=False)
    SpecLoader.clear_cache()
    reload_config()
    yield
    SpecLoader.clear_cache()
    reload_config()
    try:
        os.chdir(original_cwd)
    except FileNotFoundError:
        pass



def _create_mock_spec() -> BusinessSpec:
    """创建mock规范"""
    return BusinessSpec(
        schema_version="2.0",
        enums={
            "project_no": [{"id": "1818"}, {"id": "2016"}],
            "discipline_en_map": {"结构": "Structural Engineering"},
        },
        doc_generation={
            "options": {"enabled": True, "export_pdf": True},
            "params": {"project": {"project_no": {"type": "str", "required": True}}},
            "derivations": {},
            "rules": {"defaults": {}, "mappings": {}},
            "templates": {
                "cover_bindings": {"common": {}, "1818": {}},
                "catalog_bindings": {},
            },
        },
        titleblock_extract={
            "paper_variants": {
                "CNPE_A1": {"W": 841.0, "H": 594.0, "profile": "BASE10"},
            },
            "roi_profiles": {
                "BASE10": {
                    "description": "大图幅",
                    "tolerance": 0.5,
                    "outer_frame": [0, 1189, 0, 841],
                    "fields": {"内部编码": [10, 52, 42, 52]},
                },
            },
        },
        a4_multipage={},
    )


# ============================================================================
# 数据模型 Fixtures
# ============================================================================


@pytest.fixture
def sample_bbox() -> BBox:
    """示例边界框"""
    return BBox(xmin=0, ymin=0, xmax=841, ymax=594)


@pytest.fixture
def sample_titleblock() -> TitleblockFields:
    """示例图签字段"""
    return TitleblockFields(
        internal_code="1234567-JG001-001",
        external_code="JD1NHT11001B25C42SD",
        engineering_no="1234",
        subitem_no="JG001",
        paper_size_text="A1",
        discipline="结构",
        scale_text="1:100",
        scale_denominator=100.0,
        page_total=1,
        page_index=1,
        title_cn="测试图纸标题",
        title_en="Test Drawing Title",
        revision="A",
        status="CFC",
    )


@pytest.fixture
def sample_frame(sample_bbox: BBox, sample_titleblock: TitleblockFields) -> FrameMeta:
    """示例图框元数据"""
    runtime = FrameRuntime(
        frame_id=str(uuid.uuid4()),
        source_file=Path("test.dxf"),
        outer_bbox=sample_bbox,
        paper_variant_id="CNPE_A1",
        sx=1.0,
        sy=1.0,
        geom_scale_factor=1.0,
        roi_profile_id="BASE10",
    )
    return FrameMeta(runtime=runtime, titleblock=sample_titleblock)


@pytest.fixture
def sample_global_params() -> GlobalDocParams:
    """示例全局参数"""
    return GlobalDocParams(
        project_no="2016",
        cover_variant="通用",
        classification="非密",
        engineering_no="1234",
        subitem_no="JG001",
        subitem_name="测试子项",
        discipline="结构",
        revision="A",
        doc_status="CFC",
        album_title_cn="测试图册",
        cover_revision="A",
        wbs_code="WBS001",
    )


@pytest.fixture
def sample_doc_context(
    sample_frame: FrameMeta, sample_global_params: GlobalDocParams
) -> DocContext:
    """示例文档上下文"""
    return DocContext(
        params=sample_global_params,
        derived=DerivedFields(),
        frames=[sample_frame],
        sheet_sets=[],
    )


# ============================================================================
# Job Fixtures
# ============================================================================


@pytest.fixture
def temp_job() -> Generator[Job]:
    """临时任务（自动清理）"""
    job = Job(
        job_id=str(uuid.uuid4()),
        job_type=JobType.DELIVERABLE,
        project_no="2016",
    )

    # 创建临时工作目录
    with tempfile.TemporaryDirectory() as tmpdir:
        job.work_dir = Path(tmpdir)
        yield job


# ============================================================================
# 文件 Fixtures
# ============================================================================


@pytest.fixture
def temp_dir() -> Generator[Path]:
    """临时目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_dxf_path(temp_dir: Path) -> Path:
    """示例DXF文件路径（空文件）"""
    dxf_path = temp_dir / "test.dxf"
    # 创建一个最小的DXF文件内容
    dxf_content = """0
SECTION
2
HEADER
0
ENDSEC
0
SECTION
2
ENTITIES
0
ENDSEC
0
EOF
"""
    dxf_path.write_text(dxf_content)
    return dxf_path


# ============================================================================
# 锚点定位器测试用 Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def anchor_spec() -> BusinessSpec:
    """锚点定位器测试用 BusinessSpec（超集，兼容 calibrated/first）"""
    return BusinessSpec(
        schema_version="2.0",
        titleblock_extract={
            "paper_variants": {"A1": {"W": 100.0, "H": 50.0, "profile": "BASE10"}},
            "roi_profiles": {
                "BASE10": {
                    "description": "test",
                    "tolerance": 0.5,
                    "outer_frame": [0, 100, 0, 50],
                    "fields": {"锚点": [0, 100, 0, 50]},
                },
            },
            "anchor": {
                "search_text": ["ANCHOR"],
                "roi_field_name": "锚点",
                "match_policy": "single_hit_same_roi",
            },
            "tolerances": {"roi_margin_percent": 0.0},
        },
        a4_multipage={},
        doc_generation={},
        enums={},
    )


@pytest.fixture
def dxf_doc() -> tuple:
    """返回 (doc, msp) 元组，消除 ezdxf.new() 重复样板"""
    doc = ezdxf.new()
    return doc, doc.modelspace()


# ============================================================================
# DXF 几何辅助函数（纯函数，供测试文件直接 import 使用）
# ============================================================================


def add_rect_polyline(
    msp,
    layer: str,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> None:
    """向 modelspace 添加闭合矩形多段线"""
    msp.add_lwpolyline(
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
        close=True,
        dxfattribs={"layer": layer},
    )


def add_rect_lines(
    msp,
    layer: str,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> None:
    """向 modelspace 添加 4 条 LINE 围成的矩形"""
    msp.add_line((x0, y0), (x1, y0), dxfattribs={"layer": layer})
    msp.add_line((x1, y0), (x1, y1), dxfattribs={"layer": layer})
    msp.add_line((x1, y1), (x0, y1), dxfattribs={"layer": layer})
    msp.add_line((x0, y1), (x0, y0), dxfattribs={"layer": layer})
