# 模块5 CAD路径工作总结

## 1. 文档目的与适用对象

- 目的：沉淀模块5（CAD切图与出图主链路）的最终实现方案、关键设计决策、问题修复闭环与验收证据。
- 适用对象：结构工程师、项目负责人、后续维护开发人员。
- 文档范围：仅覆盖“原生DWG -> 图框切图DWG/PDF产物”路径，不包含封面/目录/设计文件/IED文档生成。

---

## 2. 任务背景与目标

### 2.1 背景问题

历史路径存在以下痛点：

1. 以 DXF 作为切图主载体，复杂图纸出现图素丢失/字体异常风险。
2. 一度使用逐个产物DWG再打开打印，效率低且稳定性差。
3. A4多页组处理容易出现选集不全（仅最后一页进入写块）。
4. 无界面执行（AcCoreConsole）下，交互命令顺序稍有错位即产生空白PDF或缺失产物。

### 2.2 本次目标

1. 固化 CAD 静默链路（AcCoreConsole + LISP），避免依赖可视化窗口人工干预。
2. 从 DXF 中获取图框坐标/缩放信息后，回到原生 DWG 执行切图与窗口打印。
3. A4族按“逐页窗口打印 + 多页合并PDF + 组内并集写块DWG”落地。
4. 保证关键样例达标：
   - `001`（A4组）应为4页，且页边距/尺寸符合规则；
   - `002`（大图框）应为1页，且页边距/尺寸符合规则。

---

## 3. 设计原则（本次落地）

1. **几何真值优先**：页边距换算使用 `scale_fit` 输出的 `sx/sy`，不依赖图签ROI“比例文本”。
2. **单会话批处理**：同一源文件只启动一次 CAD 会话，降低启动开销与故障面。
3. **失败隔离**：单帧/单组失败不阻断全批次，错误写入 `flags` 可追溯。
4. **静默执行**：`FILEDIA/CMDDIA/TILEMODE` 等系统变量统一控制，避免弹窗阻塞。
5. **可验收可追溯**：`task.json/result.json/module5_trace.log/accoreconsole.log` 全链路留痕。

---

## 4. 最终技术架构与流程

## 4.1 总体链路

1. Python流水线阶段执行：
   - INGEST -> DWG->DXF -> 图框检测 -> 图签提取 -> A4成组 -> CAD切图出图 -> 结果回填
2. CAD执行器负责：
   - 构建 `task.json`
   - 生成运行脚本 `runtime_module5.scr`
   - 调用 `accoreconsole.exe` 执行 LISP
3. LISP负责：
   - 选集（Crossing + 重试 + 多边形兜底）
   - 写块 `-WBLOCK`
   - 窗口打印 `-PLOT`
   - 输出 `result.json`
4. Python后处理：
   - A4页级PDF合并
   - PDF尺寸规范化（必要时）
   - 结果映射回 `FrameMeta/SheetSet`

## 4.2 关键分层

- 编排层：`backend/src/pipeline/executor.py`
- CAD任务层：`backend/src/cad/cad_dxf_executor.py`
- CAD运行层：`backend/src/cad/accoreconsole_runner.py`
- CAD脚本层：`backend/src/cad/scripts/module5_cad_executor.lsp`

---

## 5. 核心设计细节

## 5.1 DWG主路径与坐标传递

### 5.1.1 数据模型增强

`FrameRuntime` 新增/使用以下关键字段：

- `cad_source_file`：CAD切图来源（优先DWG）
- `outer_vertices`：图框四顶点
- `sx/sy`：几何缩放比例（来自 scale_fit）

作用：确保“识别可在DXF，切图/打印在DWG”，并将比例链路贯通到 CAD 执行端。

### 5.1.2 检测阶段绑定 DWG 来源

- 在 DWG->DXF 转换时保存 `dxf_to_dwg` 映射；
- 在图框检测后，为每个 frame 回写 `cad_source_file`。

效果：后续分组执行按 DWG 聚合，避免误走“中间DXF切图主路径”。

## 5.2 CAD任务契约（task/result）

`task.json` 内核心字段：

- 全局：`plot`、`selection`
- 单帧：`bbox`、`vertices`、`paper_size_mm`、`sx/sy`
- A4组：`pages[]`（每页含 `page_index/bbox/vertices/paper_size_mm/sx/sy`）

`result.json` 内核心字段：

- `frames[]`：状态、DWG/PDF路径、选集计数、flags
- `sheet_sets[]`：组状态、页数、页级PDF路径列表（用于后续合并）

## 5.3 静默运行机制（AcCoreConsole）

运行脚本中统一设置：

- `FILEDIA=0`
- `CMDDIA=0`
- `SECURELOAD=0`
- `TRUSTEDPATHS` 追加脚本目录
- `TILEMODE=1`

目的：降低交互弹窗和空间模式差异带来的不确定性。

## 5.4 选集策略（单帧）

单帧采用：

1. `m5-select-with-retry`：
   - 先按 bbox + `bbox_margin_percent` 做 `_C` crossing；
   - 空集后按 `empty_selection_retry_margin_percent` 扩边再试；
   - 仍空则做更大容错扩边。
2. 若仍为空，回退 `_CP` 多边形选集。

该策略兼顾大图框与小图框容错。

## 5.5 A4组策略（重点）

### 5.5.1 PDF策略

- 对组内每页单独窗口打印，输出 `__p1..__pN.pdf`
- Python侧合并为最终 `001.pdf`

### 5.5.2 DWG策略

- 组内先逐页选集并做并集；
- 写块前增加“并集外包框二次重选”：
  - 若成功，强制替换为并集重选集；
  - 若失败，回退使用此前页并集。

该修复用于解决“仅最后一页进入写块”的风险。

## 5.6 比例与页边距处理

页边距最终采用：

- `图上偏移量 = 页边距(mm) * sx/sy`

其中 `sx/sy` 来源于 `scale_fit` 几何拟合输出（不是ROI文本比例）。

## 5.7 打印媒体自适配与稳定性

`m5-do-plot` 针对 A0/A1 纸张做了媒体名与方向的多轮尝试（含 `ISO_expand_A0_*`），提高不同驱动环境下出图成功率。

## 5.8 后处理策略（Python）

1. 若 CAD 已产出页级PDF，优先合并，不降级到 Python 渲染。
2. 对部分“大图幅无页边距画布”的PDF，执行页面画布规范化（保留CAD渲染内容，只修页面尺寸与边距坐标系）。
3. 仅在 CAD 没有 PDF 时，才使用 Python fallback 导出。

---

## 6. 问题闭环与关键修复记录

## 6.1 字体错乱问题

- 原因：Python渲染路径对复杂字体/排版还原不足；
- 修复：切换为 CAD 原生窗口出图为主路径。

## 6.2 空白PDF/丢PDF问题

- 原因：`-PLOT` 应答序列错位导致输出文件未落盘；
- 修复：重排命令行应答顺序，并增加媒体/方向重试。

## 6.3 A4组仅最后一页写块问题

- 现象：`001` DWG疑似只包含组内最后一页内容；
- 修复：写块前加入“并集外包框二次重选 + 兜底日志”，确保 `_P` 指向整组并集。
- 证据：`module5_trace.log` 出现 `union reselection ok, count=665`，并且组内 `sel_count` 明显大于单页。

## 6.4 卡住/超时问题

- 原因：某些 `WBLOCK` 参数形式在 AcCoreConsole 下不稳定；
- 修复：使用稳定的 `_P` 路线，并通过重选策略保证 `_P` 对应正确选集。

---

## 7. 验收证据（最新稳定任务）

任务：`splitonly-20260228-213205-baa2487b`

- 输入：`test/dwg/2016仿真图.dwg`
- 状态：`succeeded`
- 统计：
  - `export_total=15`, `export_done=15`
  - `pdf_count=15`, `dwg_count=15`

关键样例：

1. `JD1NHH11001B25C42SD(20161NH-JGS03-001).pdf`
   - 页数：4
   - 尺寸（首页）：240.0 x 327.0 mm
2. `JD1NHH11002B25C42SD(20161NH-JGS03-002).pdf`
   - 页数：1
   - 尺寸：1219.0 x 871.0 mm

A4组执行证据（trace）：

- `union reselection ok, count=665`
- `wblock=ok plot=ok ... sel_count=665 page_pdfs=4`

---

## 8. 结构工程师评估清单（建议）

请按以下条目做“通过/不通过”评估：

1. **主路径正确性**
   - 是否为原生DWG切图与出图（非中间DXF主切图）
2. **A4组完整性**
   - `001` DWG中是否包含组内4页图框相关内容（建议在CAD中逐区域抽查）
3. **关键尺寸**
   - `001` PDF：4页，A4+边距目标
   - `002` PDF：1页，大图幅+边距目标
4. **稳定性**
   - 同一输入重复跑3次，产物数量、页数、尺寸是否一致
5. **可追溯性**
   - `task.json/result.json/module5_trace.log` 是否可用于定位问题
6. **异常可见性**
   - 失败项是否有明确 `flags`，且不拖垮整批任务

---

## 9. 当前已知限制

1. A4组最终结果仍保留流程标记 `PLOT_MERGE_REQUIRED`（语义为“页级已成功，等待Python合并”），可后续做flag降噪。
2. `pypdf` 读取部分CAD输出时会提示 `/PageMode` 重复定义警告（不影响当前业务结果）。
3. A4组并集重选使用“外包框策略”，在极端复杂叠图场景可能存在过选风险，建议保留抽检。

---

## 10. 复现实操（用于回归）

```bash
python tools/run_dwg_split_only.py "test/dwg/2016仿真图.dwg" --project-no 2016
```

建议回归项：

1. 检查 stdout summary 的 `pdf_count/dwg_count`；
2. 核对 `001/002` 页数与尺寸；
3. 抽查 `work/cad_tasks/*/module5_trace.log` 中 `wblock/plot` 状态。

---

## 11. 本次结论

模块5 CAD路径已完成从“中间路径不稳定”到“原生DWG静默主链路可交付”的升级，关键样例与批量统计达到目标，且已形成可追溯、可复现、可评估的交付闭环。  
建议结构工程师按第8节清单完成最终业务验收签字。

