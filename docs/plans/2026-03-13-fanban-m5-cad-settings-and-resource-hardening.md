# Fanban M5 CAD 设置与资源加固 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复 fanban_m5 对系统 CTB 的破坏、加入启动完整性检查和 CAD 版本选择，并把可用版本下限放宽到 2010。

**Architecture:** 将打印资源改成程序自管文件，停止覆盖系统 `monochrome.ctb`；启动器负责 CAD 枚举、偏好持久化、完整性检查；GUI 只展示和修改设置。保留现有模块5执行链，不改 split-only 主流程。

**Tech Stack:** Python, Tkinter, PyInstaller onedir, existing AutoCAD path resolver / plot resource manager.

---

### Task 1: 锁定受管打印资源行为

**Files:**
- Modify: `backend/src/cad/plot_resource_manager.py`
- Modify: `backend/src/cad/cad_dxf_executor.py`
- Modify: `backend/src/cad/autocad_pdf_exporter.py`
- Test: `backend/tests/unit/test_plot_resource_manager.py`

**Step 1: Write failing tests**
- 覆盖“部署时不再覆盖系统 `monochrome.ctb`，而是部署受管 CTB 文件名”。
- 覆盖“返回的 `ctb_path` 指向受管 CTB，而不是用户系统 monochrome”。

**Step 2: Run tests to verify they fail**
- Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_plot_resource_manager.py -q`

**Step 3: Minimal implementation**
- 引入受管 CTB 常量与文件名。
- 优先使用 bundle 资产；不再写回系统 `monochrome.ctb`。
- 任务 JSON 与运行链统一读取受管 CTB 名称。

**Step 4: Re-run tests**
- Run same pytest command and confirm green.

### Task 2: 放宽 CAD 版本下限并提供枚举接口

**Files:**
- Modify: `backend/src/cad/autocad_path_resolver.py`
- Test: `backend/tests/unit/test_autocad_path_resolver.py`

**Step 1: Write failing tests**
- 覆盖 2010 版本应被接受。
- 覆盖按版本高到低枚举多个正式安装版本。

**Step 2: Run tests to verify red**
- Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_autocad_path_resolver.py -q`

**Step 3: Minimal implementation**
- 将最小版本降到 2010。
- 新增可列出所有可用 CAD 安装的函数和排序规则。

**Step 4: Re-run tests**
- Run same pytest command.

### Task 3: 启动完整性检查与设置持久化

**Files:**
- Modify: `test/dist/src/fanban_m5_launcher.py`
- Create: `backend/tests/unit/test_fanban_m5_launcher_integrity.py`
- Extend: `backend/tests/unit/test_fanban_m5_launcher.py`

**Step 1: Write failing tests**
- 覆盖缺失/损坏 `tcl_data/init.tcl` 时返回明确诊断。
- 覆盖设置文件保存/读取 CAD 选择结果。

**Step 2: Run tests to verify red**
- Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_fanban_m5_launcher.py backend/tests/unit/test_fanban_m5_launcher_integrity.py -q`

**Step 3: Minimal implementation**
- 新增 bundle 完整性检查。
- 新增 `fanban_m5_settings.json` 读写。
- 启动时枚举 CAD，默认最高版本，允许使用持久化选择。

**Step 4: Re-run tests**
- Run same pytest command.

### Task 4: GUI 增加 CAD 设置入口

**Files:**
- Modify: `test/dist/src/fanban_m5_gui.py`
- Test: `backend/tests/unit/test_fanban_m5_gui.py`

**Step 1: Write failing tests**
- 覆盖主界面显示当前 CAD 摘要。
- 覆盖 `CAD设置` 对话框展示版本、accoreconsole、PC3、CTB 和状态。

**Step 2: Run tests to verify red**
- Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_fanban_m5_gui.py -q`

**Step 3: Minimal implementation**
- 主界面新增 `CAD设置` 按钮。
- 设置弹窗可切换版本、重新探测，并显示受管打印配置摘要。
- 运行任务前使用当前所选 CAD。

**Step 4: Re-run tests**
- Run same pytest command.

### Task 5: 打包与回归

**Files:**
- Modify: `test/dist/src/build_fanban_m5.ps1`
- Modify: `test/dist/src/fanban_m5.spec` (if needed)
- Verification only: package directory under `test/dist/fanban_m5`

**Step 1: Ensure bundled CTB source is valid**
- 优先从正确位置复制真实 CTB，拒绝 11 字节占位文件。

**Step 2: Rebuild package**
- Run: `powershell -ExecutionPolicy Bypass -File test\dist\src\build_fanban_m5.ps1`

**Step 3: Verify package layout**
- 检查 `_internal\assets\plot_styles\<managed>.ctb`、`plotters\*.pc3/*.pmp`、`_internal\tcl_data\init.tcl`。

**Step 4: Run targeted regressions**
- `backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_plot_resource_manager.py backend/tests/unit/test_autocad_path_resolver.py backend/tests/unit/test_fanban_m5_launcher.py backend/tests/unit/test_fanban_m5_launcher_integrity.py backend/tests/unit/test_fanban_m5_gui.py -q`
- 必要时再跑一个本地 smoke job。
