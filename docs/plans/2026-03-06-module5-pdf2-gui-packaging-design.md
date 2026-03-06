# Module5 PDF2-Only GUI Packaging Design

**Date:** 2026-03-06

**Status:** Approved for implementation in the current session

## Goal

在不改变模块1~5核心业务链路的前提下，先修正当前程序，使模块5打印只能使用 `打印PDF2.pc3`，缺失时先自动部署依赖再继续执行；随后补一个简易 GUI，并将分发工程与打包产物统一放到 `test/dist/` 下。

## Constraints

- 必须先修改当前程序本体，再跑 `2016仿真图` 回归。
- 不允许再回退到 `DWG To PDF.pc3`。
- `.NET -> LISP` 引擎回退当前不删除，本次只处理打印设备回退。
- GUI 只覆盖单 DWG 输入、输出目录选择、任务记录查看三项能力。
- 目标分发形态是 `PyInstaller onedir`，即 `一个 exe + 若干依赖文件目录`。
- GUI 相关代码也放在 `test/dist/` 下。

## Current Facts

- 当前主入口是 `tools/run_dwg_split_only.py`，内部调用 `PipelineExecutor`，最终进入 `CADDXFExecutor`。
- 模块5任务记录已经落在 `storage/jobs/<job_id>/job.json`，GUI 可以直接复用。
- `documents/打印PDF2.pc3` 与 `documents/tszdef-02fc5f1cb3db4a5b8afc9cce5dca6cd1.pmp` 已在仓库中。
- 仓库没有内置 `monochrome.ctb`，当前开发机系统目录存在：
  - `C:\Users\Yan\AppData\Roaming\Autodesk\AutoCAD 2022\R24.1\chs\Plotters\Plot Styles\monochrome.ctb`
- `.NET` 桥接当前实际仍通过 `Pc3Name` 让 AutoCAD 选择设备，`Pc3ResolvedPath` 只是记录，不会直接加载文件。
- 因此，若要稳定命中 `打印PDF2.pc3`，必须先把 `PC3/PMP/CTB` 部署到 AutoCAD 可见的 `Plotters` 目录。

## Approaches Considered

### Approach A: 只改 GUI 启动器，不改当前程序

- 优点：改动少。
- 缺点：当前 CLI、测试脚本、GUI 三条入口会分叉，问题只会被隐藏，不满足“先修当前程序”的要求。

### Approach B: 先修当前程序，再让 GUI 复用当前程序

- 优点：当前 CLI、回归测试、最终 GUI 共用一条执行链，问题暴露一致，维护成本最低。
- 缺点：要同时改 Python、LISP、`.NET` 默认值与测试。

### Approach C: 直接重做为纯 GUI 程序

- 优点：用户入口统一。
- 缺点：风险最高，会把现有已验证的回归链路一起重写，不适合本次任务。

## Recommended Design

采用 **Approach B**。

先把当前程序改成 `PDF2-only + 自动部署 + 严格校验`，确认 `2016仿真图` 回归可跑；然后再在 `test/dist/` 下补 GUI 和打包脚手架，GUI 只作为现有执行链的桌面入口。

## Architecture

### 1. 当前程序打印资源管理

新增一个打印资源管理器，负责三件事：

- 发现 AutoCAD 当前用户的 `Plotters` / `Plot Styles` 目录；
- 将 `打印PDF2.pc3`、配套 `.pmp`、`monochrome.ctb` 自动部署到目标目录；
- 将实际命中的路径回写到任务上下文，供日志和诊断使用。

部署优先级：

1. 分发目录内置资产
2. 仓库 `documents/` 资产
3. 当前机器 AutoCAD 已存在的 `monochrome.ctb`

若 `打印PDF2.pc3` 或 `.pmp` 仍不可用，则直接报错，不再回退 `DWG To PDF.pc3`。

### 2. 打印设备选择规则

- 当前程序和分发程序都只允许 `打印PDF2.pc3`。
- 删除代码中的 `DWG To PDF.pc3` 默认值与自动回退。
- LISP 默认变量、`.NET Bridge` 默认值、Python 默认值统一改为 `打印PDF2.pc3`。
- `resolve_autocad_paths()` 不再把 `DWG To PDF.pc3` 视为有效主设备，只保留为环境诊断信息时的可选观测值。

### 3. GUI 结构

GUI 放在 `test/dist/` 下，采用 `Tkinter`。

界面只包含：

- 输入 DWG 文件选择
- 输出目录选择
- “运行任务”按钮
- 最近任务列表
- 当前任务状态与最近日志查看区

GUI 不直接实现业务逻辑，只负责：

- 收集输入参数
- 调用现有 `PipelineExecutor` / `run_dwg_split_only` 等价逻辑
- 轮询并展示 `storage/jobs/<job_id>/job.json`

### 4. 分发目录结构

建议结构：

```text
test/dist/
  assets/
    plotters/
      打印PDF2.pc3
      tszdef-02fc5f1cb3db4a5b8afc9cce5dca6cd1.pmp
    plot_styles/
      monochrome.ctb
  src/
    fanban_m5_gui.py
    build_fanban_m5.ps1
    fanban_m5.spec
  fanban_m5/
    fanban_m5.exe
    ...
```

其中：

- `assets/` 作为部署源；
- `src/` 作为 GUI 与打包脚手架源码；
- `fanban_m5/` 作为最终 onedir 输出目录。

### 5. 打包策略

- 使用 `PyInstaller onedir`。
- 不使用 `onefile`，避免临时解包目录破坏 `.NET DLL`、`PC3/PMP/CTB` 与 AutoCAD 绝对路径引用。
- 运行时先做环境预检：
  - `accoreconsole.exe` 是否存在
  - `打印PDF2.pc3` 是否已部署成功
  - `monochrome.ctb` 是否可用
  - `Module5CadBridge.dll` 是否存在

任一关键条件不满足，GUI 直接显示错误并停止，不尝试隐式降级。

## Data Flow

1. GUI 选择单个 DWG 与输出目录。
2. GUI 调用当前模块1~5执行链。
3. 执行前，打印资源管理器自动部署 `PC3/PMP/CTB`。
4. `CADDXFExecutor` 构造 `task.json`，其中 `pc3_name` 固定为 `打印PDF2.pc3`。
5. AutoCAD 通过 `.NET` 或 LISP 路径执行打印。
6. 任务结果继续落盘到 `storage/jobs/<job_id>/job.json`。
7. GUI 读取任务记录并显示状态、标记、错误与产物目录。

## Error Handling

- 找不到 AutoCAD：直接失败，提示 `accoreconsole.exe` 未发现。
- 自动部署失败：直接失败，提示缺失的具体资源名与目标目录。
- 命中了非主路径：继续执行，但必须在任务记录或日志中写明具体路径来源。
- `.NET -> LISP` 引擎回退：本次保留，但任务记录必须保留现有 `DOTNET_TO_LISP_FALLBACK` 标记。

## Testing Strategy

### Unit

- `autocad_path_resolver`：优先返回用户 `Plotters` 目录，并识别 `打印PDF2.pc3`。
- 打印资源管理器：能从仓库/系统路径复制 `PC3/PMP/CTB` 到目标目录。
- `CADDXFExecutor`：任务构建与执行前只接受 `打印PDF2.pc3`，不再回退默认 PDF 设备。
- `AcCoreConsoleRunner` / `.NET Bridge` 默认值：改为 `打印PDF2.pc3`。

### Integration

- 跑 `backend` 目标单测。
- 跑 `tools/run_dwg_split_only.py "test/dwg/2016仿真图.dwg" --project-no 2016`。

### Packaging Smoke

- 在 `test/dist/` 生成 onedir 目录。
- 验证 GUI 可启动。
- 验证首次启动会自动部署 `PC3/PMP/CTB`。

## Out of Scope

- 模块6。
- 多 DWG 批量 GUI。
- 下载或安装 AutoCAD 本体。
- 重写 `.NET -> LISP` 引擎回退机制。
