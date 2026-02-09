"""
数据模型单元测试

每个模块完成后必须运行：pytest tests/unit/test_models.py -v
"""

import pytest

from src.models import (
    BBox,
    DocContext,
    FrameMeta,
    GlobalDocParams,
    Job,
    JobStatus,
    PageInfo,
    SheetSet,
    TitleblockFields,
)


class TestBBox:
    """边界框测试"""

    def test_width_height(self, sample_bbox: BBox):
        """测试宽高计算"""
        assert sample_bbox.width == 841
        assert sample_bbox.height == 594

    @pytest.mark.parametrize(
        ("other", "expected"),
        [
            (BBox(xmin=50, ymin=50, xmax=150, ymax=150), True),
            (BBox(xmin=200, ymin=200, xmax=300, ymax=300), False),
        ],
        ids=["overlapping", "separate"],
    )
    def test_intersects(self, other: BBox, expected: bool):
        """测试相交判定"""
        b1 = BBox(xmin=0, ymin=0, xmax=100, ymax=100)
        assert b1.intersects(other) == expected


class TestTitleblockFields:
    """图签字段测试"""

    def test_get_seq_no(self, sample_titleblock: TitleblockFields):
        """测试尾号提取"""
        assert sample_titleblock.get_seq_no() == 1

    def test_get_seq_no_none(self):
        """测试无尾号情况"""
        tb = TitleblockFields(internal_code="invalid")
        assert tb.get_seq_no() is None


class TestJob:
    """任务模型测试"""

    def test_mark_running(self, temp_job: Job):
        """测试标记运行中"""
        temp_job.mark_running("TEST_STAGE")
        assert temp_job.status == JobStatus.RUNNING
        assert temp_job.progress.stage == "TEST_STAGE"
        assert temp_job.started_at is not None

    def test_mark_succeeded(self, temp_job: Job):
        """测试标记成功"""
        temp_job.mark_running()
        temp_job.mark_succeeded()
        assert temp_job.status == JobStatus.SUCCEEDED
        assert temp_job.progress.percent == 100

    def test_mark_failed(self, temp_job: Job):
        """测试标记失败"""
        temp_job.mark_running()
        temp_job.mark_failed("Test error")
        assert temp_job.status == JobStatus.FAILED
        assert "Test error" in temp_job.errors

    def test_add_flag(self, temp_job: Job):
        """测试添加告警标记"""
        temp_job.add_flag("测试警告")
        temp_job.add_flag("测试警告")  # 重复添加
        assert temp_job.flags == ["测试警告"]


class TestSheetSet:
    """A4多页成组测试"""

    def test_validate_consistency_ok(self, sample_bbox: BBox):
        """测试一致性校验-正常"""
        pages = [
            PageInfo(page_index=1, outer_bbox=sample_bbox, has_titleblock=True),
            PageInfo(page_index=2, outer_bbox=sample_bbox),
            PageInfo(page_index=3, outer_bbox=sample_bbox),
        ]
        sheet_set = SheetSet(
            cluster_id="test",
            page_total=3,
            pages=pages,
            master_page=pages[0],
        )
        flags = sheet_set.validate_consistency()
        assert len(flags) == 0

    def test_validate_consistency_page_count_mismatch(self, sample_bbox: BBox):
        """测试一致性校验-页数不一致"""
        pages = [PageInfo(page_index=1, outer_bbox=sample_bbox)]
        sheet_set = SheetSet(
            cluster_id="test",
            page_total=3,  # 声明3页但只有1页
            pages=pages,
        )
        flags = sheet_set.validate_consistency()
        assert "A4多页_页数不一致" in flags


class TestDocContext:
    """文档上下文测试"""

    @pytest.mark.parametrize(
        ("project_no", "expected"),
        [("1818", True), ("2016", False)],
        ids=["is_1818", "not_1818"],
    )
    def test_is_1818(self, project_no: str, expected: bool):
        """测试1818项目判定"""
        ctx = DocContext(params=GlobalDocParams(project_no=project_no))
        assert ctx.is_1818 == expected

    def test_get_frame_001(self, sample_frame: FrameMeta):
        """测试获取001图纸"""
        params = GlobalDocParams(project_no="2016")
        ctx = DocContext(params=params, frames=[sample_frame])

        frame_001 = ctx.get_frame_001()
        assert frame_001 is not None
        assert frame_001.titleblock.internal_code.endswith("-001")

    def test_get_sorted_frames(self, sample_frame: FrameMeta):
        """测试图框排序"""
        # 创建多个图框
        from copy import deepcopy

        frame2 = deepcopy(sample_frame)
        frame2.titleblock.internal_code = "1234567-JG001-003"

        frame3 = deepcopy(sample_frame)
        frame3.titleblock.internal_code = "1234567-JG001-002"

        params = GlobalDocParams(project_no="2016")
        ctx = DocContext(params=params, frames=[frame2, frame3, sample_frame])

        sorted_frames = ctx.get_sorted_frames()
        codes = [f.titleblock.internal_code for f in sorted_frames]
        assert codes == [
            "1234567-JG001-001",
            "1234567-JG001-002",
            "1234567-JG001-003",
        ]
