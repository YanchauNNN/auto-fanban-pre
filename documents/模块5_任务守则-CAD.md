# 模块5_任务守则-CAD（DXF 原生执行版）

> 适用：新对话 AI 接手模块5改造  
> 目标：**模块5统一改为“CAD 打开 DXF 执行切割与打印”**，不再以 Python 几何删实体方式为主链路，注意现有路径不要删除，仅新增路径作为尝试，旧路径作为备用  
> 重要前提：**本守则明确“不考虑 DWG→DXF 损失问题”**，输入 DXF 视为可信源  
> 范围：仅模块5（`SPLIT_AND_RENAME` + `EXPORT_PDF_AND_DWG` 相关链路）

---

## 0) 决策与边界（先读，必须遵守）

- **强制决策**：模块5主链路 = `CAD 引擎执行 + DXF 输入`。
- **禁止主链路**：`ezdxf 复制后删除框外实体`（不要删除，仅保留为 emergency fallback，不参与默认路径）。
- **选择语义**：必须用 **Crossing（交叉窗）**，不是 Window（完全包含）。
- **处理对象**：单帧 + A4 成组都在 CAD 内执行导出（DWG + PDF）。
- **性能目标**：同一 DXF 文件内的所有图框，**一次 CAD 会话**完成，不得按帧重启 CAD。
- **失败隔离**：单帧失败仅打 flag，不中断该 DXF 其余帧；单 DXF 失败不影响其他 DXF。

---

## 1) 当前仓库基线与问题定位

### 1.1 当前代码事实（必须知道）

- `backend/src/cad/splitter.py` 现有主裁切逻辑是“复制 DXF + 删除框外实体”：
  - `_clip_by_copy_and_delete()`
  - `_should_delete_entity()`
- `backend/src/pipeline/executor.py` 目前先 `DWG->DXF`，后走 splitter 裁切/导出。
- `backend/src/cad/autocad_pdf_exporter.py` 已有 AutoCAD COM 打印能力，但未承担“CAD 内切割（WBLOCK）”。

### 1.2 本次改造的核心变化

- 从“Python 侧做几何裁切”改为“CAD 内核做交叉窗选集 + WBLOCK + PLOT”。
- Python 改为“任务编排器”，CAD 改为“执行器”。

---

## 2) 技术路线（明确主路径）

## 2.1 总体架构

```
模块2/3/4 (已有)
  -> 提供 FrameMeta / SheetSet / outer_bbox / page_index / 命名字段
  -> 模块5 Python编排层构建 CAD 任务(JSON)
  -> AcCoreConsole 启动 CAD 内核执行脚本（打开DXF）
  -> CAD 内执行：
       Crossing 选集 -> WBLOCK 输出 DWG
       Window/同bbox 打印 -> PDF
  -> 回写 result.json
  -> Python 回填 frame.runtime.pdf_path / dwg_path 与 flags
```

## 2.2 推荐执行引擎优先级

- **优先**：`AcCoreConsole.exe + .scr + AutoLISP`（无 UI、批处理稳定、可托管）。
- 次选：AutoCAD COM（已有实现，可留作 fallback，不做主链路）。

---

## 3) 必改文件清单（新 AI 按此执行）

## 3.1 新增文件

- `backend/src/cad/cad_dxf_executor.py`
  - 职责：组装任务、按 DXF 分组调用 CAD 执行、解析结果、回填路径与 flags。
- `backend/src/cad/accoreconsole_runner.py`
  - 职责：生成 `.scr`、调用 `accoreconsole.exe`、管理超时/重试/日志文件。
- `backend/src/cad/scripts/module5_cad_executor.lsp`
  - 职责：在 CAD 内读取任务 JSON，逐帧执行 crossing 选集、WBLOCK、PLOT。
- `backend/src/cad/scripts/module5_bootstrap.scr`
  - 职责：加载 LISP 并调用入口函数（参数：task.json/result.json）。
- `backend/tests/unit/test_cad_dxf_executor.py`
  - 职责：任务构建、命名、flag 映射、结果解析、失败隔离。

## 3.2 修改文件

- `backend/src/cad/splitter.py`
  - 保留对外接口，但默认分支改为调用 `CADDXFExecutor`。
  - 将 `_clip_by_copy_and_delete()` 标记为 fallback，不参与主链路。
- `backend/src/pipeline/executor.py`
  - Stage7/8 职责调整为“构建 CAD 批任务 + 执行 + 回填”。
  - 保留阶段名不变，避免破坏进度条/前端依赖。
- `backend/src/config/runtime_config.py`
  - 增加 CAD-DXF 执行参数模型（见第4节）。
- `documents/参数规范_运行期.yaml`
  - 增加 `module5_export.engine = cad_dxf` 等参数（见第4节）。

---

## 4) 运行配置（必须新增并接线）

在 `runtime_options` 下新增（或扩展）：

- `module5_export.engine`: `cad_dxf | autocad_com | python_fallback`
  - 默认：`cad_dxf`
- `module5_export.cad_runner`: 
  - `accoreconsole_exe`（绝对路径）
  - `script_dir`（脚本目录）
  - `task_timeout_sec`（单 DXF 超时）
  - `retry`（单 DXF 重试次数）
  - `locale`（如 `en-US`）
  - `max_parallel_dxf`（并发 DXF 数）
- `module5_export.selection`:
  - `mode: crossing`
  - `bbox_margin_percent`（例如 0.015）
  - `empty_selection_retry_margin_percent`（例如 0.03）
- `module5_export.plot`:
  - `pc3_name`
  - `ctb_name`
  - `paper_from_frame: true`
  - `use_monochrome: true`
- `module5_export.output`:
  - `a4_multipage_pdf: merge_pages`
  - `on_frame_fail: flag_and_continue`

---

## 5) 数据契约（必须落地）

## 5.1 task.json（Python -> CAD）

建议结构：

```json
{
  "schema_version": "cad-dxf-task@1.0",
  "job_id": "uuid",
  "source_dxf": "abs/path/source.dxf",
  "output_dir": "abs/path/output/drawings",
  "plot": {
    "pc3_name": "DWG To PDF.pc3",
    "ctb_name": "monochrome.ctb",
    "margins_mm": {"top":20, "bottom":10, "left":20, "right":10}
  },
  "selection": {
    "mode": "crossing",
    "bbox_margin_percent": 0.015,
    "empty_selection_retry_margin_percent": 0.03
  },
  "frames": [
    {
      "frame_id": "uuid",
      "name": "external(internal)",
      "bbox": {"xmin":0,"ymin":0,"xmax":100,"ymax":50},
      "paper_size_mm": [841,594],
      "kind": "single"
    }
  ],
  "sheet_sets": [
    {
      "cluster_id": "uuid",
      "name": "external(internal)",
      "pages": [
        {
          "page_index": 1,
          "bbox": {"xmin":0,"ymin":0,"xmax":100,"ymax":50},
          "paper_size_mm": [297,210]
        }
      ]
    }
  ]
}
```

## 5.2 result.json（CAD -> Python）

建议结构：

```json
{
  "schema_version": "cad-dxf-result@1.0",
  "job_id": "uuid",
  "source_dxf": "abs/path/source.dxf",
  "frames": [
    {
      "frame_id": "uuid",
      "status": "ok|failed",
      "pdf_path": "abs/path/xx.pdf",
      "dwg_path": "abs/path/xx.dwg",
      "selection_count": 1234,
      "flags": []
    }
  ],
  "sheet_sets": [
    {
      "cluster_id": "uuid",
      "status": "ok|failed",
      "pdf_path": "abs/path/xx.pdf",
      "dwg_path": "abs/path/xx.dwg",
      "page_count": 7,
      "flags": []
    }
  ],
  "errors": []
}
```

---

## 6) CAD 侧执行细则（核心算法）

## 6.1 单图框导出

对每个 frame：

1. 读取 bbox，按 `bbox_margin_percent` 扩边。
2. `ZOOM` 到 bbox（避免可见性导致 `ssget` 漏选）。
3. Crossing 选集：
   - `ss = (ssget "_C" p1 p2)`
4. 若 `ss` 为空：
   - 使用 `empty_selection_retry_margin_percent` 再扩边重试一次。
5. 仍为空：
   - 写 `status=failed` + flag `CAD选集为空`，继续下一个 frame。
6. 非空则执行：
   - `-WBLOCK` 导出 DWG（Retain 模式，避免污染源图）
   - `-PLOT` 按同 bbox 打印 PDF（窗口打印）
7. 校验产物文件是否存在且大小>0。

## 6.2 A4 成组导出

两种都可，推荐第一种：

- 推荐：按 `page_index` 逐页窗口打印临时 PDF，最后合并成一个多页 PDF。
- DWG：对 `pages[]` 做 union bbox 的 crossing 选集，`-WBLOCK` 一次导出成组 DWG。

兜底策略：

- 任一页失败：记录页级错误，整组 `status=failed`，但不中断其他组。

## 6.3 Crossing 语义约束

- 必须使用 Crossing（`_C`），不要使用 `_W`。
- 原因：`_C` = 选中“在窗内 + 与窗边界相交”的对象，符合业务“范围内涉及元素都选中”。

---

## 7) Python 侧编排细则

## 7.1 分组策略

- 以 `source_dxf` 分组（同一 DXF 一次 CAD 会话）。
- 每组构建一个 `task.json` 并单独执行，确保故障隔离。

## 7.2 命名规则

- 单图：`external_code(internal_code)` 优先；缺失时回退 `frame_id[:8]`。
- 成组：`sheet_set.master` 对应编码优先；缺失回退 `sheet_set_{cluster_id[:8]}`。

## 7.3 flag 映射（建议）

- `CAD选集为空`
- `WBLOCK失败`
- `PLOT失败`
- `PDF为空文件`
- `DWG缺失`
- `A4多页_部分页失败`
- `DXF执行超时`

---

## 8) 阶段职责建议（尽量少改架构）

## 8.1 Stage7（SPLIT_AND_RENAME）

- 改为：构建 CAD 任务 + 执行 CAD 导出（生成最终 PDF+DWG）。
- 不再产出“中间 split DXF”作为主路径。

## 8.2 Stage8（EXPORT_PDF_AND_DWG）

- 改为：一致性校验与统计补录（文件存在、页数、flags 聚合）。
- 保留阶段是为了兼容现有进度条与上层接口。

---

## 9) 测试要求（必须新增）

## 9.1 单测（无需真实 CAD）

- `test_build_task_json_from_frames_and_sheet_sets`
- `test_group_by_source_dxf`
- `test_result_json_backfill_paths`
- `test_frame_failure_isolation`
- `test_sheet_set_partial_failure_flags`
- `test_name_collision_policy`

通过 mock runner 验证：

- `AcCoreConsoleRunner.run(task_path)` 的输入输出契约
- 超时/重试逻辑

## 9.2 集成测试（有 CAD 环境）

- 样例 DXF（含普通帧 + A4 成组）一键跑通。
- 验证：
  - 同一 DXF 内多帧只启动一次 CAD 会话
  - PDF、DWG 都存在且可打开
  - A4 多页顺序正确
  - 任一帧失败不影响其他帧

---

## 10) 验收标准（必须全部满足）

- 主链路不再依赖 `_clip_by_copy_and_delete()`。
- 产物来自 CAD 内核选集与打印，不是 Python 渲染兜底结果。
- “范围内涉及元素都选中”在实测样例可复现（边界相交对象被选中）。
- 同一 DXF 多帧处理没有“每帧重启 CAD”。
- 模块5测试通过，且不破坏现有单测回归。

---

## 11) 实施顺序（建议给新 AI 的执行步骤）

1. 新建 `CADDXFExecutor` 与 `AcCoreConsoleRunner`（先打通空任务）。
2. 落地 `task.json/result.json` 契约，先做单帧导出通路。
3. 接入 A4 成组（多页 PDF 合并 + 成组 DWG）。
4. 改 `executor.py` 的 Stage7/8 逻辑。
5. 新增单测与 mock runner 测试。
6. 最后用真实 CAD 样例做 smoke 回归。

---

## 12) 参考资料与检索指引（给新 AI）

> 说明：部分 Autodesk Help 页面有 JS 防护或区域限制；若打不开，按“关键词”搜索同名页面。

### 12.1 WBLOCK 与对象导出

- Autodesk Support（可访问）：  
  `https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Export-Objects-to-Drawing-File-with-WBLOCK-Command.html`
- Autodesk Help（可能受限，关键词检索）：  
  `AutoCAD -WBLOCK (Command) Retain Delete Convert to block`

### 12.2 Crossing 选集（关键语义）

- Lee Mac `ssget` 参考（可访问）：  
  `https://lee-mac.com/ssget.html`
- CorelCAD `ssget` 参考（可访问）：  
  `https://product.corel.com/help/CorelCAD-2015/EN/Documentation/html/lisp_function_ssget.htm`
- 关键词：  
  `ssget "_C" crossing window`  
  `ssget "_W" window fully inside`

### 12.3 AcCoreConsole 批处理

- 入门案例（可访问）：  
  `https://autocadtips1.com/2013/01/30/up-and-running-with-the-2013-core-console/`
- 社区样例仓库（可访问）：  
  `https://github.com/albisserAdrian/acadCC`
- 关键词：  
  `accoreconsole /i /s /l en-US`  
  `AutoCAD Core Console batch script`

### 12.4 命令行 -PLOT

- BricsCAD 命令行文档（结构与 AutoCAD 类似，适合理解脚本参数流）：  
  `https://help.bricsys.com/en-us/document/command-reference/p/-plot-command`
- 关键词：  
  `AutoCAD -PLOT command line Window PDF script`

### 12.5 托管稳定性背景（为何优先 CoreConsole）

- StackOverflow（可访问）：  
  `https://stackoverflow.com/questions/21768170/how-to-start-autocad-from-net-using-windows-service`
- Microsoft Session 0（可访问）：  
  `https://learn.microsoft.com/en-us/previous-versions/windows/hardware/design/dn653293(v=vs.85)`

---

## 13) 交付清单（完成时必须具备）

- 新增：`cad_dxf_executor.py`、`accoreconsole_runner.py`、CAD 脚本文件（`.lsp` + `.scr`）。
- 修改：`splitter.py`、`executor.py`、`runtime_config.py`、`参数规范_运行期.yaml`。
- 新增测试：`test_cad_dxf_executor.py`。
- 文档回填：在模块5工作总结中记录“CAD-DXF 主链路上线”与已知限制。

---

> 本守则是“模块5 CAD-DXF 主链路”的单一执行标准。  
> 若出现实现分歧，以本文件“0) 决策与边界”优先。

