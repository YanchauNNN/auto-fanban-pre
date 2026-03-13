# Fanban M5 GUI 进度视图设计

## 背景
- 当前 `fanban_m5` 主窗口在加入 `CAD / 打印设置` 后，任务记录和详情区域明显被压缩。
- 任务详情现在直接显示 `job.json` 原文，信息密度高，但对现场使用不友好，无法快速判断当前执行到了哪一阶段。

## 目标
- 放大主窗口，并重新分配 `任务记录` 与 `任务详情 / 日志` 的空间。
- 将任务详情改成“阶段进度视图 + 最近日志摘录”，不再直接展示原始 `job.json`。

## 方案
### 1. 主窗口布局
- 将默认窗口扩大到 `1360x940`。
- 将最小尺寸提升到 `1180x760`。
- 保留现有四段布局：
  - 任务输入
  - CAD / 打印设置
  - 任务记录
  - 任务详情 / 日志
- 调整 row weight，使 `任务详情 / 日志` 占更大比例。

### 2. 阶段进度视图
- 基于现有 `job.json.progress.stage / percent / message / details` 组织展示，不新增后端协议。
- 固定阶段顺序：
  - `INGEST`
  - `CONVERT_DWG_TO_DXF`
  - `DETECT_FRAMES`
  - `VERIFY_FRAMES_BY_ANCHOR`
  - `SCALE_FIT_AND_CHECK`
  - `EXTRACT_TITLEBLOCK_FIELDS`
  - `A4_MULTIPAGE_GROUPING`
  - `SPLIT_AND_RENAME`
  - `EXPORT_PDF_AND_DWG`
- 每个阶段显示：
  - 状态：未开始 / 进行中 / 已完成 / 失败
  - 当前可用的计数信息，例如：
    - `dwg_converted / dwg_total`
    - `dxf_processed / dxf_total`
    - `frames_field_done / frames_field_total`
    - `split_done / split_total`
    - `export_done / export_total`

### 3. 日志呈现
- 阶段视图上方显示任务状态、当前阶段、总体进度。
- 下方保留 `module5_trace.log` 尾部摘录，便于快速定位 CAD 运行问题。
- 原始 `job.json` 不再直接显示。

## 验证
- 新增 GUI 单测：
  - 锁定窗口尺寸常量。
  - 锁定阶段视图格式。
- 保留现有 `CAD 设置`、项目号自动填充相关单测。
