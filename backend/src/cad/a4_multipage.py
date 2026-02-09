"""
A4多页成组器 - 处理001说明图

职责：
1. 识别同一DXF中的A4图框簇
2. 确定Master页（带完整图签）和Slave页（仅页码）
3. 提取Slave页的页码
4. 一致性校验（不中断，只打flags）

依赖：
- 参数规范.yaml: a4_multipage配置

测试要点：
- test_detect_a4_cluster: A4簇检测
- test_identify_master_slave: Master/Slave识别
- test_extract_slave_page_number: Slave页码提取
- test_consistency_check: 一致性校验
- test_flags_not_interrupt: flags不中断流程
"""

from __future__ import annotations

import uuid

from ..config import load_spec
from ..interfaces import IA4MultipageGrouper
from ..models import FrameMeta, PageInfo, SheetSet


class A4MultipageGrouper(IA4MultipageGrouper):
    """A4多页成组器实现"""

    def __init__(self, spec_path: str | None = None):
        self.spec = load_spec(spec_path) if spec_path else load_spec()
        self.a4_config = self.spec.a4_multipage

    def group_a4_pages(self, frames: list[FrameMeta]) -> tuple[list[FrameMeta], list[SheetSet]]:
        """对A4图框进行成组处理"""

        # 1. 分离A4和非A4图框
        a4_frames = []
        non_a4_frames = []

        for frame in frames:
            if self._is_a4_frame(frame):
                a4_frames.append(frame)
            else:
                non_a4_frames.append(frame)

        # 2. 如果A4图框少于2个，无需成组
        if len(a4_frames) < 2:
            return frames, []

        # 3. 构建A4簇
        clusters = self._build_clusters(a4_frames)

        # 4. 对每个簇进行处理
        sheet_sets: list[SheetSet] = []
        processed_frame_ids: set[str] = set()

        for cluster in clusters:
            if len(cluster) < 2:
                # 单帧簇不成组，保留为普通帧
                continue

            sheet_set = self._process_cluster(cluster)
            if sheet_set:
                sheet_sets.append(sheet_set)
                for frame in cluster:
                    processed_frame_ids.add(frame.frame_id)
            # 若 _process_cluster 返回 None（如 page_total < 2 回退），
            # 簇内帧不加入 processed_frame_ids，自然回到 remaining

        # 5. 返回未成组的图框（含回退帧） + 成组结果
        remaining_frames = [f for f in frames if f.frame_id not in processed_frame_ids]

        return remaining_frames, sheet_sets

    def _is_a4_frame(self, frame: FrameMeta) -> bool:
        """判断是否为A4图框"""
        paper_id = frame.runtime.paper_variant_id
        return paper_id is not None and "A4" in paper_id

    def _build_clusters(self, a4_frames: list[FrameMeta]) -> list[list[FrameMeta]]:
        """
        构建A4簇（按间距连边取连通分量）

        gap_threshold = gap_threshold_factor * min(W_obs, H_obs)
        gap_threshold_factor 从 YAML ``a4_multipage.cluster_building`` 读取（默认 1.0）
        """
        if not a4_frames:
            return []

        # 计算间距阈值系数（YAML 默认 1.0）
        cluster_cfg = self.a4_config.get("cluster_building", {})
        gap_factor = float(cluster_cfg.get("gap_threshold_factor", 1.0))

        # 构建邻接关系
        n = len(a4_frames)
        adj = [[] for _ in range(n)]

        for i in range(n):
            for j in range(i + 1, n):
                if self._frames_are_neighbors(a4_frames[i], a4_frames[j], gap_factor):
                    adj[i].append(j)
                    adj[j].append(i)

        # 找连通分量
        visited = [False] * n
        clusters = []

        for i in range(n):
            if not visited[i]:
                cluster = []
                self._dfs(i, adj, visited, a4_frames, cluster)
                clusters.append(cluster)

        return clusters

    def _frames_are_neighbors(self, f1: FrameMeta, f2: FrameMeta, gap_factor: float) -> bool:
        """判断两个图框是否相邻"""
        b1 = f1.runtime.outer_bbox
        b2 = f2.runtime.outer_bbox

        # 计算最小间距
        min_size = min(b1.width, b1.height, b2.width, b2.height)
        threshold = gap_factor * min_size
        dx = max(0, max(b1.xmin, b2.xmin) - min(b1.xmax, b2.xmax))
        dy = max(0, max(b1.ymin, b2.ymin) - min(b1.ymax, b2.ymax))

        return dx < threshold and dy < threshold

    def _dfs(
        self,
        node: int,
        adj: list[list[int]],
        visited: list[bool],
        frames: list[FrameMeta],
        cluster: list[FrameMeta],
    ) -> None:
        """深度优先搜索"""
        visited[node] = True
        cluster.append(frames[node])
        for neighbor in adj[node]:
            if not visited[neighbor]:
                self._dfs(neighbor, adj, visited, frames, cluster)

    def _process_cluster(self, cluster: list[FrameMeta]) -> SheetSet | None:
        """处理单个A4簇

        流程：
        1. 识别 Master 页
        2. Master 缺失关键字段检查 → 追加 flag（不中断）
        3. 确定 page_total（优先 Slave 共识 > 簇帧数 > Master titleblock）
        4. page_total < 2 回退 → 返回 None（簇内帧回退为普通帧）
        5. Slave page_total 交叉校验 → 追加 flag（不中断）
        6. 构建页面列表
        7. 一致性校验
        """
        flags: list[str] = []

        # 1. 识别Master页
        master = self._identify_master(cluster)
        if not master:
            return None

        # 2. Master 缺失关键字段检查
        self._check_master_fields(master, flags)

        # 3. 确定 page_total
        #    Master 的 titleblock.page_total 来自图签区"共N张"，
        #    可能只反映图纸文件级别（=1），而非 A4 多页组的真实张数。
        #    因此当簇有 ≥2 帧且 Master.page_total < 2 时，
        #    优先使用 Slave 共识 page_total 或簇帧数。
        page_total = self._resolve_page_total(master, cluster)

        # 4. page_total < 2 回退：不按多页处理
        if page_total < 2:
            return None

        # 5. Slave page_total 交叉校验（仅在 _process_cluster 中做，
        #    validate_consistency 中的同名检查会跳过已存在的 flag）
        self._check_slave_page_total(master, cluster, flags)

        # 6. 构建页面列表（Slave 也保存 frame_meta 引用）
        pages = []
        for frame in cluster:
            is_master = frame.frame_id == master.frame_id
            page_index = frame.titleblock.page_index or (1 if is_master else 0)

            pages.append(
                PageInfo(
                    page_index=page_index,
                    outer_bbox=frame.runtime.outer_bbox,
                    has_titleblock=is_master,
                    frame_meta=frame,  # Master 和 Slave 都保存引用
                )
            )

        # 7. 按页码排序
        pages.sort(key=lambda p: p.page_index)

        # 8. 找到 master_page 引用
        master_page_ref = next(
            (p for p in pages if p.has_titleblock), None
        )

        # 9. 构建SheetSet
        sheet_set = SheetSet(
            cluster_id=str(uuid.uuid4()),
            page_total=page_total,
            pages=pages,
            master_page=master_page_ref,
            flags=flags,  # 先把已收集的 flags 传入
        )

        # 10. 一致性校验（会追加更多 flags）
        sheet_set.validate_consistency()

        return sheet_set

    def _check_master_fields(
        self, master: FrameMeta, flags: list[str],
    ) -> None:
        """检查 Master 是否缺失关键字段

        缺失 internal_code / external_code / title_cn / page_total 中任一
        → 追加 flag ``A4多页_Master缺关键字段``
        """
        tb = master.titleblock
        required = [tb.internal_code, tb.external_code, tb.title_cn, tb.page_total]
        if any(v is None for v in required):
            flags.append("A4多页_Master缺关键字段")

    def _check_slave_page_total(
        self,
        master: FrameMeta,
        cluster: list[FrameMeta],
        flags: list[str],
    ) -> None:
        """Slave page_total 交叉校验

        若 Slave 的 page_total 非空且与 Master 的 page_total 不一致
        → 追加 flag ``A4多页_页总数冲突``（仅追加一次）
        """
        master_pt = master.titleblock.page_total
        if master_pt is None:
            return
        for frame in cluster:
            if frame.frame_id == master.frame_id:
                continue
            slave_pt = frame.titleblock.page_total
            if slave_pt is not None and slave_pt != master_pt:
                flags.append("A4多页_页总数冲突")
                return  # 只追加一次

    def _resolve_page_total(
        self, master: FrameMeta, cluster: list[FrameMeta],
    ) -> int:
        """确定簇的有效 page_total

        优先级：
        1. Master.titleblock.page_total（若 ≥ 2 则直接采用）
        2. Slave 共识 page_total（若所有非空 Slave 一致且 ≥ 2）
        3. 簇帧数（兜底）

        典型场景：Master 图签区"共1张 第1张"记录的是文件级页数，
        而 Slave 右上角页码标记"共7张 第X张"才是真实多页张数。
        """
        master_pt = master.titleblock.page_total

        # 快速路径：Master 的 page_total ≥ 2 → 直接信任
        if master_pt is not None and master_pt >= 2:
            return master_pt

        # 收集 Slave 的 page_total 值
        slave_totals: set[int] = set()
        for frame in cluster:
            if frame.frame_id == master.frame_id:
                continue
            spt = frame.titleblock.page_total
            if spt is not None:
                slave_totals.add(spt)

        # 若 Slave 达成共识（仅一个唯一值）且 ≥ 2 → 使用 Slave 值
        if len(slave_totals) == 1:
            consensus = next(iter(slave_totals))
            if consensus >= 2:
                return consensus

        # 兜底：簇帧数
        return len(cluster)

    def _identify_master(self, cluster: list[FrameMeta]) -> FrameMeta | None:
        """识别Master页（字段命中最多，或page_index=1）"""
        best_master = None
        best_score = -1

        for frame in cluster:
            score = self._calculate_master_score(frame)
            if score > best_score:
                best_score = score
                best_master = frame

        return best_master

    def _calculate_master_score(self, frame: FrameMeta) -> int:
        """计算Master候选评分"""
        score = 0
        tb = frame.titleblock

        # 关键字段命中
        if tb.engineering_no:
            score += 1
        if tb.internal_code:
            score += 1
        if tb.external_code:
            score += 1
        if tb.page_total:
            score += 1
        if tb.page_index == 1:
            score += 2  # page_index=1 额外加分

        return score
