# 模块5_任务守则-CAD（当前机器实配留档版）

> 适用范围：`E:\project\auto-fanban-pre` 仓库，模块5（CAD-DXF 执行链路）
> 
> 目标：让后续 AI 维护者在不依赖上下文记忆的情况下，按本文即可定位路径、执行任务、排查问题。
> 
> 更新时间：`2026-03-04`

---

## 0) 决策与边界（必须遵守）

- 主链路固定：`.NET + AutoCAD Core Console`。
- 不允许“压错/吞错”：出现报错必须记录根因，不做静默忽略。
- 打印链路规则：
  - 先按名称匹配 PC3 纸张。
  - 打印窗口来自 DXF 识别图框顶点（WCS），打印使用 Window 模式。
  - `center_plot=false`，`plot_offset=(0,0)`，`margins_mm=0`。
  - 比例为 `manual_integer_from_geometry`，并执行整数化规则。
- 引擎策略：优先 .NET；只有 .NET 失败时才允许回退 LISP（由配置控制）。

---

## 1) 当前机器真实路径（绝对路径，逐项核对）

## 1.1 仓库与运行环境

- 仓库根目录：`E:\project\auto-fanban-pre`
- 后端目录：`E:\project\auto-fanban-pre\backend`
- Python 虚拟环境：`E:\project\auto-fanban-pre\backend\.venv`
- 常用解释器：`E:\project\auto-fanban-pre\backend\.venv\Scripts\python.exe`

## 1.2 关键配置文件

- 业务参数：`E:\project\auto-fanban-pre\documents\参数规范.yaml`
- 运行期参数：`E:\project\auto-fanban-pre\documents\参数规范_运行期.yaml`
- 运行配置代码：`E:\project\auto-fanban-pre\backend\src\config\runtime_config.py`

## 1.3 AutoCAD 与执行器

- AutoCAD 安装目录：`D:\Program Files\AUTOCAD\AutoCAD 2022`
- `acad.exe`：`D:\Program Files\AUTOCAD\AutoCAD 2022\acad.exe`
- `accoreconsole.exe`：`D:\Program Files\AUTOCAD\AutoCAD 2022\accoreconsole.exe`
- AutoCAD Fonts：`D:\Program Files\AUTOCAD\AutoCAD 2022\Fonts`

## 1.4 PC3 / CTB 路径

- Plotters 目录：`C:\Users\Yan\AppData\Roaming\Autodesk\AutoCAD 2022\R24.1\chs\Plotters`
- Plot Styles 目录：`C:\Users\Yan\AppData\Roaming\Autodesk\AutoCAD 2022\R24.1\chs\Plotters\Plot Styles`
- 当前业务 PC3（必须存在）：`C:\Users\Yan\AppData\Roaming\Autodesk\AutoCAD 2022\R24.1\chs\Plotters\打印PDF2.pc3`
- 当前 CTB：`C:\Users\Yan\AppData\Roaming\Autodesk\AutoCAD 2022\R24.1\chs\Plotters\Plot Styles\monochrome.ctb`
- AutoCAD 默认可发现 PC3（解析器参考）：`C:\Users\Yan\AppData\Roaming\Autodesk\AutoCAD 2022\R24.1\chs\Plotters\DWG To PDF.pc3`

## 1.5 模块5脚本与 .NET 桥接

- CAD 脚本目录：`E:\project\auto-fanban-pre\backend\src\cad\scripts`
- LISP 主脚本：`E:\project\auto-fanban-pre\backend\src\cad\scripts\module5_cad_executor.lsp`
- SCR 引导脚本：`E:\project\auto-fanban-pre\backend\src\cad\scripts\module5_bootstrap.scr`
- .NET 项目：`E:\project\auto-fanban-pre\backend\src\cad\dotnet\Module5CadBridge\Module5CadBridge.csproj`
- .NET DLL（运行时加载）：`E:\project\auto-fanban-pre\backend\src\cad\dotnet\Module5CadBridge\bin\Release\net48\Module5CadBridge.dll`

## 1.6 任务中间产物路径

- 任务根目录：`E:\project\auto-fanban-pre\storage\jobs`
- 模块5运行时临时根目录：`C:\Users\Yan\AppData\Local\Temp\fanban_module5_cad_tasks`
- 每次任务会生成：
  - `task.json`
  - `result.json`
  - `module5_trace.log`
  - `accoreconsole.log`
  - `cad_stage_output\*.pdf/*.dwg`

---

## 2) 当前主流程（按代码真实实现，不按历史文档想象）

## 2.1 总体两阶段

1. `split_only`
- 入口：`CADDXFExecutor.execute_source_dxf()`
- 作用：按 frame/sheet_set 选集并 WBLOCK，产出 split DWG（不在此阶段判最终成败）。

2. `plot_window_only` 或 `plot_from_split_dwg`
- 默认主路径：`plot_window_only`（从原始 source DWG 窗口批量打印）。
- 失败回退：`plot_from_split_dwg`（从 split DWG 打印）。

## 2.2 引擎优先级

- 选择引擎：`module5_export.selection.engine=dotnet`
- 打印引擎：`module5_export.output.plot_engine=dotnet`
- .NET 回退 LISP：`module5_export.dotnet_bridge.fallback_to_lisp_on_error=true`

判定原则：
- 只要 .NET 成功，结果即为主结果。
- 只有 .NET 抛错且允许回退时，才切换到 LISP。

## 2.3 A4 成组打印关键点

- 多页打印由 `.NET PlotEngine` 统一输出多页 PDF（`PLOT_MULTIPAGE_USED`）。
- 每页窗口来自 `sheet_set.pages[].bbox/vertices`。
- 页面方向由图框宽高关系决定（`W>H=landscape，否则 portrait`），旋转由媒体方向与目标方向差异决定。

---

## 3) 当前生效配置（核心参数）

数据来源：`documents/参数规范_运行期.yaml` + `runtime_config.py`

- `module5_export.cad_runner.accoreconsole_exe = D:\Program Files\AUTOCAD\AutoCAD 2022\accoreconsole.exe`
- `module5_export.cad_runner.script_dir = E:\project\auto-fanban-pre\backend\src\cad\scripts`
- `module5_export.dotnet_bridge.dll_path = E:\project\auto-fanban-pre\backend\src\cad\dotnet\Module5CadBridge\bin\Release\net48\Module5CadBridge.dll`
- `module5_export.plot.pc3_name = 打印PDF2.pc3`
- `module5_export.plot.ctb_name = monochrome.ctb`
- `module5_export.plot.center_plot = false`
- `module5_export.plot.plot_offset_mm = {x:0.0, y:0.0}`
- `module5_export.plot.margins_mm = {top:0, bottom:0, left:0, right:0}`
- `module5_export.plot.scale_mode = manual_integer_from_geometry`
- `module5_export.plot.scale_integer_rounding = round`
- `module5_export.output.plot_preferred_area = window`
- `module5_export.output.plot_fallback_area = none`
- `module5_export.output.plot_session_mode = per_source_batch`
- `module5_export.output.plot_from_source_window_enabled = true`
- `module5_export.output.plot_fallback_to_split_on_failure = true`

---

## 4) AI 维护标准执行步骤（照抄即可跑）

## 4.1 预检查（路径/环境）

1. 校验关键文件存在：
- `accoreconsole.exe`
- `打印PDF2.pc3`
- `monochrome.ctb`
- `Module5CadBridge.dll`
- `module5_cad_executor.lsp`

2. 校验 Python 环境：
- 使用 `E:\project\auto-fanban-pre\backend\.venv\Scripts\python.exe`

3. 校验配置读取：
- 工作目录必须在仓库根 `E:\project\auto-fanban-pre`。

## 4.2 编译 .NET（改过 C# 必做）

```powershell
"E:\project\auto-fanban-pre\Dependency Library\.dotnet\sdk-local\dotnet.exe" build E:\project\auto-fanban-pre\backend\src\cad\dotnet\Module5CadBridge\Module5CadBridge.csproj -c Release
```

## 4.3 运行样本回归（最小集）

```powershell
E:\project\auto-fanban-pre\backend\.venv\Scripts\python.exe E:\project\auto-fanban-pre\tools\run_dwg_split_only.py "E:\project\auto-fanban-pre\test\dwg\2016仿真图.dwg" --project-no 2016
E:\project\auto-fanban-pre\backend\.venv\Scripts\python.exe E:\project\auto-fanban-pre\tools\run_dwg_split_only.py "E:\project\auto-fanban-pre\test\dwg\1818仿真图.dwg" --project-no 1818
```

## 4.4 必查输出

- `storage/jobs/<job_id>/output/drawings/*.pdf/*.dwg` 数量匹配。
- `storage/jobs/<job_id>/work/cad_tasks/*/module5_trace.log` 中：
  - `PLOT_FROM_SOURCE_WINDOW` 或 `PLOT_FROM_SPLIT_DWG`
  - `target_orientation/media_orientation/rotate`
  - `media=...`（是否命中预期纸张名）

---

## 5) 日志定位规范（AI 读日志必须按这个顺序）

1. 先看任务汇总 JSON（命令输出中的 `job_id`）。
2. 看 `storage/jobs/<job_id>/work/cad_tasks/*/result.json`。
3. 看 `storage/jobs/<job_id>/work/cad_tasks/*/module5_trace.log`。
4. 若是窗口批量路径，再看：
- `C:\Users\Yan\AppData\Local\Temp\fanban_module5_cad_tasks\<task_id>\plot_tasks\<subtask>\module5_trace.log`

关键关键词：
- `[DOTNET][PLOT][CFG]`
- `[DOTNET][PLOT][BUILD]`
- `[DOTNET][PLOT][MULTI]`
- `PLOT_FROM_SOURCE_WINDOW`
- `PLOT_FROM_SPLIT_DWG`
- `MEDIA_NOT_MATCHED`

---

## 6) 常见问题 -> 根因 -> 处理动作

## 6.1 “PDF 看起来像窗口选错了”

常见根因：
- 不是窗口框错，而是命中媒体可打印区域过小（例如命中 `ISO_A4` 而非业务 PC3 纸张名）。

处理：
1. 查 `BUILD` 行的 `media=...`。
2. 对照 `参数规范.yaml` 纸张名称映射。
3. 若命中错误媒体，先修名称匹配优先级，再复跑。

## 6.2 “A4 方向不对（应竖向却被横向）”

根因：
- 目标方向与媒体方向判定/旋转逻辑冲突。

处理：
1. 看 `target_orientation` 与 `media_orientation`。
2. 看 `rotate=0/90` 是否符合 `W>H` 规则。
3. 若不符合，改 `PlotEngine.cs` 中方向判定与旋转逻辑，不改业务框架识别逻辑。

## 6.3 “大量 PLOT 失败”

根因方向：
- PC3 路径不可达。
- 纸张名在 PC3 中不存在。
- AutoCAD 环境未加载正确 Plotters。

处理：
1. 先看 `[DOTNET][PLOT][CFG] pc3_resolved_path=`。
2. 再看 `[DOTNET][PLOT][MEDIA]` 的 available sample。
3. 再确认 `打印PDF2.pc3` 里纸张名称与映射是否一致。

## 6.4 “.NET 与 LISP 混用导致结果不稳定”

处理：
- 明确一轮任务只看最终 flags：
  - 有 `DOTNET_TO_LISP_FALLBACK` 说明确实发生回退。
  - 无该标记即为纯 .NET 路径。

---

## 7) 禁止事项（维护红线）

- 禁止直接删除或静默绕过报错逻辑。
- 禁止未经验证就改 `plot_preferred_area/window` 语义。
- 禁止把“名称匹配纸张”退回“纯尺寸近似匹配”。
- 禁止在未查 trace 的情况下判断“窗口错/比例错”。

---

## 8) 验收标准（改动完成后必须全部满足）

- `2016仿真图`、`1818仿真图` 均可跑通，`pdf_count == dwg_count`（按样本预期）。
- A4 多页 PDF 页数正确，方向与图框宽高关系一致。
- trace 中可看到完整 BUILD 证据：`media + orientation + rotate + bbox_wcs/bbox_dcs`。
- 未出现“压错通过”：所有失败都有具体 flag 或 error 文本。

---

## 9) 维护记录模板（每次改动后必须补）

按以下模板附在提交说明或任务记录：

```text
[模块5维护记录]
日期:
操作者:
改动文件:
改动目标:
关键路径是否变化(是/否):
2016回归结果:
1818回归结果:
是否发生DOTNET_TO_LISP_FALLBACK:
遗留问题:
```

---

## 10) 快速命令清单（可直接复制）

```powershell
# 1) 编译 .NET 桥接
cd /d E:\project\auto-fanban-pre
"Dependency Library\.dotnet\sdk-local\dotnet.exe" build backend\src\cad\dotnet\Module5CadBridge\Module5CadBridge.csproj -c Release

# 2) 跑 2016
backend\.venv\Scripts\python.exe tools\run_dwg_split_only.py "test\dwg\2016仿真图.dwg" --project-no 2016

# 3) 跑 1818
backend\.venv\Scripts\python.exe tools\run_dwg_split_only.py "test\dwg\1818仿真图.dwg" --project-no 1818

# 4) 查看最新临时任务目录
powershell -NoProfile -Command "Get-ChildItem $env:TEMP\fanban_module5_cad_tasks -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 3 FullName,LastWriteTime"
```

---

> 本文件是模块5当前机器的“执行实况标准文档”。
> 
> 后续任何 AI 维护都应先对照第 1 章路径，再执行第 4 章流程，再按第 8 章验收。
