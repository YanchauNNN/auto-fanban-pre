# Fanban M5 GUI 进度视图 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 放大 `fanban_m5` 窗口，并将任务详情改成按阶段展示的进度视图。

**Architecture:** 在 `fanban_m5_gui.py` 中新增纯函数负责构造阶段进度文本，GUI 继续消费现有 `job.json` 和 `module5_trace.log` 数据，不修改后端协议。布局只调整主窗口尺寸与 row weight，不引入新的窗口层级。

**Tech Stack:** Python, Tkinter, pytest

---

### Task 1: 补 GUI 单测

**Files:**
- Modify: `backend/tests/unit/test_fanban_m5_gui.py`
- Test: `backend/tests/unit/test_fanban_m5_gui.py`

**Step 1: Write the failing test**
- 为窗口尺寸常量新增断言。
- 为阶段进度详情文本新增断言，覆盖：
  - 运行中阶段
  - 已完成阶段
  - 最近日志摘录

**Step 2: Run test to verify it fails**

Run:
```powershell
backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\test_fanban_m5_gui.py -q
```

**Step 3: Write minimal implementation**
- 在 `fanban_m5_gui.py` 中补窗口尺寸常量。
- 新增阶段进度格式化函数。

**Step 4: Run test to verify it passes**

Run:
```powershell
backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\test_fanban_m5_gui.py -q
```

### Task 2: 调整 GUI 布局与详情渲染

**Files:**
- Modify: `test/dist/src/fanban_m5_gui.py`

**Step 1: Implement layout changes**
- 扩大窗口。
- 调整 row weight。
- 让 `任务详情 / 日志` 获得更多空间。

**Step 2: Implement stage detail rendering**
- 在 `on_job_selected`、轮询更新、任务完成时统一使用新格式。
- 不再直接显示原始 `job.json`。

**Step 3: Run targeted tests**

Run:
```powershell
backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\test_fanban_m5_gui.py backend\tests\unit\test_fanban_m5_launcher.py -q
```

### Task 3: 整体验证与打包

**Files:**
- Modify: `test/dist/src/build_fanban_m5.ps1`（如无需修改则只验证）

**Step 1: Run compile checks**

Run:
```powershell
backend\.venv\Scripts\python.exe -m py_compile test\dist\src\fanban_m5_gui.py test\dist\src\fanban_m5_launcher.py
```

**Step 2: Rebuild packaged app**

Run:
```powershell
powershell -ExecutionPolicy Bypass -File test\dist\src\build_fanban_m5.ps1
```

**Step 3: Verify packaged files**
- 检查 `fanban_m5.exe`
- 检查 `_internal\_tcl_data\init.tcl`
- 检查 `assets\plotters` 与 `assets\plot_styles`
