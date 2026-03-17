# 模块5 CAD 路径中等重构完成报告（.NET 主路径）

## 1. 文档定位

本文仅记录本次“模块5 CAD 路径中等重构”的完成情况与技术方案，重点回答三个问题：

1. .NET 主路径是否已经接管关键执行链路；
2. 当前架构如何保证稳定、可追溯、可扩展；
3. 本轮重构的边界、已知限制与后续优化方向。

---

## 2. 重构目标与范围

### 2.1 重构目标

- 将模块5从“LISP主路径”升级为“.NET主路径”；
- 维持静默后台执行（AcCoreConsole），不依赖人工交互；
- 提升切图与打印稳定性，降低空白PDF、图元丢失、弹窗中断等风险；
- 保持业务语义不变：输入一套图框数据，输出稳定的 DWG/PDF 产物。

### 2.2 本次范围

- 范围内：
  - .NET Bridge（AutoCAD 插件）落地；
  - Python 编排层接入 .NET 引擎与回退控制；
  - 关键脚本调用链改造（NETLOAD + 命令执行）；
  - 单元测试、端到端验证、文档更新。
- 范围外：
  - 非模块5链路功能；
  - 业务字段体系本身的定义变更（参数规范只做运行期开关补充，不改业务含义）。

---

## 3. 完成情况总览

本次中等重构已完成，状态如下：

- 已完成：.NET 工程 `Module5CadBridge` 建立并可构建产出 DLL；
- 已完成：Python 运行时配置支持 .NET 引擎、命令名、DLL 路径、回退开关；
- 已完成：`accoreconsole` 运行脚本按引擎分支生成（.NET / LISP）；
- 已完成：`.NET -> result.json -> Python` 的结果回传与解析闭环；
- 已完成：UTF-8 BOM 兼容、命令调用稳定性修复；
- 已完成：单元测试补齐与通过，`ruff` 检查通过；
- 已完成：强制 `.NET only` 的整链路验证，产物稳定生成。

---

## 4. 重构后总体架构

## 4.1 分层结构

1. **编排层（Pipeline）**
   - 负责任务生命周期、阶段调度、结果汇总；
   - 路径：`backend/src/pipeline/executor.py`。

2. **CAD 任务层（Executor）**
   - 负责构建 `task.json`、触发 CAD 执行、读取 `result.json`、质量校验；
   - 路径：`backend/src/cad/cad_dxf_executor.py`。

3. **CAD 运行层（Runner）**
   - 负责生成运行时 SCR 并调用 `accoreconsole.exe`；
   - 路径：`backend/src/cad/accoreconsole_runner.py`。

4. **.NET Bridge 层（AutoCAD 插件）**
   - 负责在 AutoCAD API 内完成核心操作（选中/写块/绘图）；
   - 路径：`backend/src/cad/dotnet/Module5CadBridge/`。

5. **脚本层（保留）**
   - 旧 LISP 路径保留为可控兜底，不再作为默认主路径；
   - 路径：`backend/src/cad/scripts/module5_cad_executor.lsp`。

## 4.2 执行链路（重构后）

1. Python 生成任务描述（包含分帧/分组/引擎配置）并写入 `task.json`；
2. Runner 生成 SCR，静默启动 `accoreconsole`；
3. SCR 通过 `NETLOAD` 加载 `Module5CadBridge.dll`；
4. 执行 `M5BRIDGE_RUN <task.json> <result.json> <trace.log>`；
5. .NET Bridge 在 AutoCAD API 内执行：
   - 按帧选择图元并导出 DWG；
   - 按策略执行 PDF 打印；
   - 输出结构化结果 `result.json` 与 trace；
6. Python 读取并校验结果，产出最终文件列表与状态。

---

## 5. 核心技术特点

## 5.1 “主路径控制权”从 LISP 切换到 .NET

- 关键命令由 .NET 插件 `M5BRIDGE_RUN` 承接；
- 在强制 `.NET only` 验证中，`dotnet_to_lisp_fallback_hits = 0`；
- 表明本次执行不依赖 LISP 回退即可完成交付。

## 5.2 写块能力升级：数据库级 API 优先

- 使用 AutoCAD .NET API 处理对象选择与导出，避免命令态选集不稳定；
- 目标是让 WBLOCK 路径从“脚本驱动”升级为“API驱动”；
- 对 A4 组保留“按业务规则聚合后导出”的能力。

## 5.3 打印能力升级：窗口打印 + 同引擎内部回退

- 首选策略：源图窗口打印（window-only）；
- 当前在部分任务出现 `eInvalidInput` 时，触发同引擎内部回退到 `plot_from_split_dwg`；
- 回退仍在 .NET 路径内完成，不切回 LISP。

## 5.4 静默执行稳定性加固

- SCR 调用从 `command-s` 调整为 `command`（用于 `NETLOAD` 与桥接命令）；
- 去除 .NET 路径下对 `TRUSTEDPATHS` 的动态改写，避免 `0xC00000FD` 风险；
- 统一 `FILEDIA/CMDDIA/SECURELOAD` 等关键变量，降低交互式干扰。

## 5.5 契约化与可追溯

- `task.json`：输入契约，明确引擎、任务对象、输出策略；
- `result.json`：输出契约，记录帧级状态、产物路径、错误标记；
- `module5_trace.log` + `accoreconsole.log`：便于快速定位问题；
- Python 侧支持 `utf-8-sig` 读取，兼容 .NET 默认 BOM 输出。

---

## 6. 关键代码落点

- 运行期配置：
  - `backend/src/config/runtime_config.py`
  - 新增/完善 .NET Bridge 配置与引擎开关。

- 任务编排与回退控制：
  - `backend/src/cad/cad_dxf_executor.py`
  - 包含引擎注入、执行包装、结果解析、PDF 校验与可选回退。

- AcCoreConsole 运行脚本生成：
  - `backend/src/cad/accoreconsole_runner.py`
  - 生成 .NET 路径 SCR、命令调用方式修复。

- .NET 插件实现：
  - `backend/src/cad/dotnet/Module5CadBridge/Commands.cs`
  - `backend/src/cad/dotnet/Module5CadBridge/PlotEngine.cs`
  - `backend/src/cad/dotnet/Module5CadBridge/Module5CadBridge.csproj`
  - `backend/src/cad/dotnet/build_module5_bridge.ps1`

- 测试与质量门禁：
  - `backend/tests/unit/test_accoreconsole_runner.py`
  - `backend/tests/unit/test_cad_dxf_executor.py`
  - `backend/tests/unit/test_config.py`

---

## 7. 验证结果（本轮重构）

## 7.1 构建与基础质量

- .NET Bridge 可构建（已解决本机 SDK / 引用程序集环境问题）；
- Python 代码通过 `ruff check`；
- 相关单元测试通过（含新增场景）。

## 7.2 强制 .NET 主路径端到端验证

验证条件：

- 输入：`2016仿真图.dwg`；
- 配置：`fallback_to_lisp_on_error = False`（禁止回退到 LISP）。

验证结果（关键指标）：

- 任务状态：`succeeded`；
- `dotnet_to_lisp_fallback_hits: 0`；
- 产物数量：`DWG=15`，`PDF=15`；
- 样例检查：`001/002` 等关键文件存在且页数、尺寸符合预期。

结论：.NET 主路径已在“切图+出图”主流程上实现可交付级接管并稳定产出。

---

## 8. 当前状态判定

### 8.1 已达成

- 主流程控制权：已由 .NET Bridge 接管；
- 交付稳定性：在禁用 LISP 回退的条件下，可稳定产出完整结果；
- 工程可维护性：配置化、契约化、测试化均已落地。

### 8.2 已知限制

- `plot_window_only` 在部分场景仍可能出现 `PLOT_ERROR:eInvalidInput`；
- 当前通过 .NET 内部回退 `plot_from_split_dwg` 保证最终 PDF 可用；
- 即：最终交付稳定，但窗口打印策略仍有进一步收敛空间。

---

## 9. 后续优化建议（下一阶段）

1. 聚焦清理 `plot_window_only` 的 `eInvalidInput` 根因（坐标系/窗口合法性/布局上下文）；
2. 增加“窗口打印成功率”指标到回归脚本，形成持续可观测性；
3. 对更多项目样本做跨图幅回归，验证在不同模板、不同图框密度下的一致性；
4. 在保持 `.NET 主路径` 的前提下，逐步收缩 LISP 兜底触发面。

---

## 10. 本次重构结论

本次中等重构目标已完成：模块5已从“LISP主执行”升级为“.NET主执行”，并在强制 `.NET only` 条件下验证了稳定交付能力。当前剩余工作聚焦于窗口打印策略的精细化优化，不影响现阶段稳定产出与交付可用性。
