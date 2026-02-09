"""
A4MultipageGrouper 单元测试

覆盖：
- 触发条件（无 A4 / 单个 A4 / 多个 A4）
- 簇构建（相邻 / 远距离）
- Master 识别与评分
- page_total < 2 回退
- 一致性校验（页数不一致 / 页码重复 / 页码不连续 / Slave page_total 冲突 / Master 缺字段）
- flags 不中断处理
- 页码排序
- 元数据继承
"""

from __future__ import annotations

import uuid
from pathlib import Path

from src.models import BBox, FrameMeta, FrameRuntime, TitleblockFields

# ---------------------------------------------------------------------------
# 为了绕开 A4MultipageGrouper 构造函数中的 load_spec()（需要真实 YAML），
# 我们用一个轻量子类注入 mock a4_config
# ---------------------------------------------------------------------------


class _TestableGrouper:
    """直接注入 a4_config 的测试辅助子类"""

    def __new__(cls, a4_config: dict | None = None):
        from src.cad.a4_multipage import A4MultipageGrouper

        # 避免调用 __init__（会触发 load_spec），手动构造
        obj = object.__new__(A4MultipageGrouper)
        obj.spec = None  # 不需要完整 spec
        obj.a4_config = a4_config or {
            "cluster_building": {"gap_threshold_factor": 1.0},
        }
        return obj


def _make_grouper(a4_config: dict | None = None):
    """创建可测试的 A4MultipageGrouper 实例"""
    return _TestableGrouper(a4_config)


# ---------------------------------------------------------------------------
# A4 FrameMeta 工厂
# ---------------------------------------------------------------------------

# A4 横向标准尺寸（约 297×210，实际按比例缩放后的观测值）
_A4_W = 297.0
_A4_H = 210.0


def make_a4_frame(
    *,
    x_offset: float = 0.0,
    y_offset: float = 0.0,
    page_total: int | None = 7,
    page_index: int | None = None,
    internal_code: str | None = None,
    external_code: str | None = None,
    engineering_no: str | None = None,
    title_cn: str | None = None,
    paper_variant_id: str = "CNPE_A4",
    frame_id: str | None = None,
) -> FrameMeta:
    """创建 A4 图框的 FrameMeta"""
    fid = frame_id or str(uuid.uuid4())
    bbox = BBox(
        xmin=x_offset,
        ymin=y_offset,
        xmax=x_offset + _A4_W,
        ymax=y_offset + _A4_H,
    )
    runtime = FrameRuntime(
        frame_id=fid,
        source_file=Path("test.dxf"),
        outer_bbox=bbox,
        paper_variant_id=paper_variant_id,
        sx=1.0,
        sy=1.0,
    )
    titleblock = TitleblockFields(
        page_total=page_total,
        page_index=page_index,
        internal_code=internal_code,
        external_code=external_code,
        engineering_no=engineering_no,
        title_cn=title_cn,
    )
    return FrameMeta(runtime=runtime, titleblock=titleblock)


def make_non_a4_frame(frame_id: str | None = None) -> FrameMeta:
    """创建非 A4 图框的 FrameMeta（如 A1）"""
    fid = frame_id or str(uuid.uuid4())
    bbox = BBox(xmin=0, ymin=0, xmax=841, ymax=594)
    runtime = FrameRuntime(
        frame_id=fid,
        source_file=Path("test.dxf"),
        outer_bbox=bbox,
        paper_variant_id="CNPE_A1",
        sx=1.0,
        sy=1.0,
    )
    return FrameMeta(runtime=runtime, titleblock=TitleblockFields())


# ---------------------------------------------------------------------------
# Master 模板：A4 主帧（完整图签字段）
# ---------------------------------------------------------------------------

def make_master_frame(
    *,
    x_offset: float = 0.0,
    y_offset: float = 0.0,
    page_total: int = 7,
) -> FrameMeta:
    """创建完整 Master A4 帧"""
    return make_a4_frame(
        x_offset=x_offset,
        y_offset=y_offset,
        page_total=page_total,
        page_index=1,
        internal_code="1234567-JG001-001",
        external_code="JD1NHT11001B25C42SD",
        engineering_no="1234",
        title_cn="测试图纸标题",
    )


def make_slave_frame(
    *,
    x_offset: float = 0.0,
    y_offset: float = 0.0,
    page_total: int | None = 7,
    page_index: int | None = 2,
) -> FrameMeta:
    """创建 Slave A4 帧（仅有页码，无图签关键字段）"""
    return make_a4_frame(
        x_offset=x_offset,
        y_offset=y_offset,
        page_total=page_total,
        page_index=page_index,
    )


# ===========================================================================
# 测试用例
# ===========================================================================


class TestNoA4Frames:
    """无 A4 图框时应返回原始列表和空 sheet_sets"""

    def test_no_a4_frames(self):
        grouper = _make_grouper()
        f1 = make_non_a4_frame()
        f2 = make_non_a4_frame()
        remaining, sheet_sets = grouper.group_a4_pages([f1, f2])

        assert len(remaining) == 2
        assert sheet_sets == []


class TestSingleA4Frame:
    """仅 1 个 A4 图框时不成组"""

    def test_single_a4_frame(self):
        grouper = _make_grouper()
        a4 = make_master_frame()
        non_a4 = make_non_a4_frame()
        remaining, sheet_sets = grouper.group_a4_pages([a4, non_a4])

        assert sheet_sets == []
        # 原始帧全部保留
        assert len(remaining) == 2


class TestBasicCluster:
    """2+ 个相邻 A4 图框形成簇"""

    def test_basic_cluster(self):
        grouper = _make_grouper()
        # Master 在 (0, 0)，3 个 Slave 紧邻排列（y 方向堆叠）
        master = make_master_frame(x_offset=0, y_offset=0, page_total=4)
        s2 = make_slave_frame(x_offset=0, y_offset=_A4_H + 5, page_index=2, page_total=4)
        s3 = make_slave_frame(x_offset=0, y_offset=2 * (_A4_H + 5), page_index=3, page_total=4)
        s4 = make_slave_frame(x_offset=0, y_offset=3 * (_A4_H + 5), page_index=4, page_total=4)

        remaining, sheet_sets = grouper.group_a4_pages([master, s2, s3, s4])

        assert len(sheet_sets) == 1
        ss = sheet_sets[0]
        assert ss.page_total == 4
        assert len(ss.pages) == 4
        assert ss.master_page is not None
        assert ss.master_page.has_titleblock is True
        # 成组后的帧不在 remaining 中
        assert len(remaining) == 0


class TestSeparateClusters:
    """远距离 A4 图框分属不同簇"""

    def test_separate_clusters(self):
        grouper = _make_grouper()
        # 簇1：两个相邻帧
        m1 = make_master_frame(x_offset=0, y_offset=0, page_total=2)
        s1 = make_slave_frame(x_offset=0, y_offset=_A4_H + 5, page_index=2, page_total=2)

        # 簇2：两个相邻帧（远离簇1，x 偏移 10000）
        m2 = make_master_frame(x_offset=10000, y_offset=0, page_total=2)
        s2 = make_slave_frame(x_offset=10000, y_offset=_A4_H + 5, page_index=2, page_total=2)

        remaining, sheet_sets = grouper.group_a4_pages([m1, s1, m2, s2])

        assert len(sheet_sets) == 2
        assert len(remaining) == 0


class TestMasterIdentification:
    """Master 评分正确——字段命中最多的被选中"""

    def test_master_identification(self):
        grouper = _make_grouper()
        # Master 有完整字段（得分 = 1+1+1+1+2 = 6）
        master = make_master_frame(x_offset=0, y_offset=0, page_total=3)
        # Slave 仅有 page_total（得分 = 1）
        slave1 = make_slave_frame(x_offset=0, y_offset=_A4_H + 5, page_index=2, page_total=3)
        slave2 = make_slave_frame(x_offset=0, y_offset=2 * (_A4_H + 5), page_index=3, page_total=3)

        remaining, sheet_sets = grouper.group_a4_pages([slave1, master, slave2])

        assert len(sheet_sets) == 1
        ss = sheet_sets[0]
        # master_page 应指向有 titleblock 的那一页
        assert ss.master_page is not None
        assert ss.master_page.frame_meta is not None
        assert ss.master_page.frame_meta.titleblock.internal_code == "1234567-JG001-001"


class TestPageTotalLt2Fallback:
    """page_total < 2 回退逻辑测试

    新逻辑：_resolve_page_total() 优先级为
    Master(≥2) > Slave共识(≥2) > 簇帧数。
    因此只要簇帧数 ≥ 2，就不会真正回退。
    """

    def test_single_a4_not_grouped(self):
        """仅 1 个 A4 帧时（簇无法形成），不成组"""
        grouper = _make_grouper()
        master = make_master_frame(x_offset=0, y_offset=0, page_total=1)
        non_a4 = make_non_a4_frame()
        remaining, sheet_sets = grouper.group_a4_pages([master, non_a4])
        assert sheet_sets == []
        assert len(remaining) == 2

    def test_master_pt1_slave_pt1_uses_cluster_size(self):
        """Master 和 Slave 都声称 page_total=1，但簇有 2 帧
        → 使用簇帧数(2)成组，并标记页数不一致"""
        grouper = _make_grouper()
        master = make_master_frame(x_offset=0, y_offset=0, page_total=1)
        slave = make_slave_frame(x_offset=0, y_offset=_A4_H + 5, page_index=2, page_total=1)

        remaining, sheet_sets = grouper.group_a4_pages([master, slave])

        # 簇帧数=2 ≥ 2 → 依然成组
        assert len(sheet_sets) == 1
        ss = sheet_sets[0]
        assert ss.page_total == 2
        assert len(remaining) == 0

    def test_master_pt1_slave_pt7_uses_slave_consensus(self):
        """Master page_total=1（图签区值），Slave 共识 page_total=7
        → 使用 Slave 共识值成组（真实场景：1818仿真图.dxf）"""
        grouper = _make_grouper()
        master = make_master_frame(x_offset=0, y_offset=0, page_total=1)
        slaves = [
            make_slave_frame(
                x_offset=0, y_offset=(i + 1) * (_A4_H + 5),
                page_index=i + 2, page_total=7,
            )
            for i in range(6)
        ]
        remaining, sheet_sets = grouper.group_a4_pages([master, *slaves])

        assert len(sheet_sets) == 1
        ss = sheet_sets[0]
        # Slave 共识值 7 被采用
        assert ss.page_total == 7
        assert len(ss.pages) == 7
        assert len(remaining) == 0


class TestConsistencyPageCountMismatch:
    """帧数 != page_total 时产生 flag"""

    def test_consistency_page_count_mismatch(self):
        grouper = _make_grouper()
        # Master 声明 page_total=5，但簇内实际只有 2 个帧
        master = make_master_frame(x_offset=0, y_offset=0, page_total=5)
        slave = make_slave_frame(x_offset=0, y_offset=_A4_H + 5, page_index=2, page_total=5)

        _, sheet_sets = grouper.group_a4_pages([master, slave])

        assert len(sheet_sets) == 1
        assert "A4多页_页数不一致" in sheet_sets[0].flags


class TestConsistencyDuplicatePageIndex:
    """页码重复时产生 flag"""

    def test_consistency_duplicate_page_index(self):
        grouper = _make_grouper()
        # 两个帧都声称是 page_index=1
        master = make_master_frame(x_offset=0, y_offset=0, page_total=2)
        slave = make_slave_frame(
            x_offset=0, y_offset=_A4_H + 5,
            page_index=1,  # 重复！
            page_total=2,
        )

        _, sheet_sets = grouper.group_a4_pages([master, slave])

        assert len(sheet_sets) == 1
        assert "A4多页_页码重复" in sheet_sets[0].flags


class TestConsistencyGapInPageIndex:
    """页码不连续时产生 flag（如 1, 3 缺 2）"""

    def test_consistency_gap_in_page_index(self):
        grouper = _make_grouper()
        # 页码 1, 3（缺 2）但 page_total=2 所以帧数匹配
        # 用 3 个帧来构造更清晰的场景
        master = make_master_frame(x_offset=0, y_offset=0, page_total=3)
        slave2 = make_slave_frame(x_offset=0, y_offset=_A4_H + 5, page_index=2, page_total=3)
        slave4 = make_slave_frame(
            x_offset=0, y_offset=2 * (_A4_H + 5),
            page_index=4,  # 跳过了 3
            page_total=3,
        )

        _, sheet_sets = grouper.group_a4_pages([master, slave2, slave4])

        assert len(sheet_sets) == 1
        assert "A4多页_页码不连续" in sheet_sets[0].flags


class TestSlavePageTotalConflict:
    """Slave 的 page_total 与 Master 不一致时产生 flag"""

    def test_slave_page_total_conflict(self):
        grouper = _make_grouper()
        master = make_master_frame(x_offset=0, y_offset=0, page_total=3)
        slave_ok = make_slave_frame(
            x_offset=0, y_offset=_A4_H + 5,
            page_index=2, page_total=3,
        )
        slave_bad = make_slave_frame(
            x_offset=0, y_offset=2 * (_A4_H + 5),
            page_index=3,
            page_total=5,  # 与 Master 的 3 不一致
        )

        _, sheet_sets = grouper.group_a4_pages([master, slave_ok, slave_bad])

        assert len(sheet_sets) == 1
        assert "A4多页_页总数冲突" in sheet_sets[0].flags


class TestMasterMissingFieldsFlag:
    """Master 缺关键字段时产生 flag"""

    def test_master_missing_fields_flag(self):
        grouper = _make_grouper()
        # Master 缺 internal_code 和 title_cn
        master = make_a4_frame(
            x_offset=0, y_offset=0,
            page_total=2, page_index=1,
            engineering_no="1234",
            external_code="JD1NHT11001B25C42SD",
            # internal_code=None, title_cn=None → 缺失
        )
        slave = make_slave_frame(x_offset=0, y_offset=_A4_H + 5, page_index=2, page_total=2)

        _, sheet_sets = grouper.group_a4_pages([master, slave])

        assert len(sheet_sets) == 1
        assert "A4多页_Master缺关键字段" in sheet_sets[0].flags


class TestFlagsNotInterrupt:
    """任何 flag 都不中断处理，SheetSet 正常返回"""

    def test_flags_not_interrupt(self):
        grouper = _make_grouper()
        # 构造一个会触发多种 flag 的场景：
        # - Master 缺 title_cn → A4多页_Master缺关键字段
        # - 帧数(2) != page_total(5) → A4多页_页数不一致
        # - Slave page_total(3) != Master page_total(5) → A4多页_页总数冲突
        master = make_a4_frame(
            x_offset=0, y_offset=0,
            page_total=5, page_index=1,
            engineering_no="1234",
            internal_code="1234567-JG001-001",
            external_code="JD1NHT11001B25C42SD",
            # title_cn=None → 触发 Master缺关键字段
        )
        slave = make_slave_frame(
            x_offset=0, y_offset=_A4_H + 5,
            page_index=2,
            page_total=3,  # 与 Master 的 5 不一致
        )

        _, sheet_sets = grouper.group_a4_pages([master, slave])

        # 尽管有多种异常，SheetSet 依然正常返回
        assert len(sheet_sets) == 1
        ss = sheet_sets[0]
        assert ss.page_total == 5
        assert len(ss.pages) == 2
        assert ss.master_page is not None
        # 应包含多个 flags
        assert "A4多页_Master缺关键字段" in ss.flags
        assert "A4多页_页数不一致" in ss.flags
        assert "A4多页_页总数冲突" in ss.flags


class TestPagesSortedByIndex:
    """pages 按 page_index 升序排列"""

    def test_pages_sorted_by_index(self):
        grouper = _make_grouper()
        # 故意倒序输入
        master = make_master_frame(x_offset=0, y_offset=2 * (_A4_H + 5), page_total=3)
        s3 = make_slave_frame(x_offset=0, y_offset=0, page_index=3, page_total=3)
        s2 = make_slave_frame(x_offset=0, y_offset=_A4_H + 5, page_index=2, page_total=3)

        _, sheet_sets = grouper.group_a4_pages([s3, s2, master])

        assert len(sheet_sets) == 1
        pages = sheet_sets[0].pages
        indices = [p.page_index for p in pages]
        assert indices == sorted(indices)
        assert indices == [1, 2, 3]


class TestInheritedTitleblock:
    """get_inherited_titleblock() 返回 Master 字段"""

    def test_inherited_titleblock(self):
        grouper = _make_grouper()
        master = make_master_frame(x_offset=0, y_offset=0, page_total=2)
        slave = make_slave_frame(x_offset=0, y_offset=_A4_H + 5, page_index=2, page_total=2)

        _, sheet_sets = grouper.group_a4_pages([master, slave])

        assert len(sheet_sets) == 1
        inherited = sheet_sets[0].get_inherited_titleblock()
        assert inherited["internal_code"] == "1234567-JG001-001"
        assert inherited["external_code"] == "JD1NHT11001B25C42SD"
        assert inherited["engineering_no"] == "1234"
        assert inherited["title_cn"] == "测试图纸标题"
        assert inherited["page_total"] == 2
        assert inherited["page_index"] == 1


class TestSlaveFrameMetaSaved:
    """Slave 的 frame_meta 也保存引用（模块5 裁切需要 outer_bbox）"""

    def test_slave_frame_meta_saved(self):
        grouper = _make_grouper()
        master = make_master_frame(x_offset=0, y_offset=0, page_total=2)
        slave = make_slave_frame(x_offset=0, y_offset=_A4_H + 5, page_index=2, page_total=2)

        _, sheet_sets = grouper.group_a4_pages([master, slave])

        assert len(sheet_sets) == 1
        for page in sheet_sets[0].pages:
            # 所有页面（包括 Slave）都应有 frame_meta
            assert page.frame_meta is not None
