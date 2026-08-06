# Build Artifact Cleanup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 `build/` 收敛到方案 2 的部署白名单，修正正式 ZIP 目录结构，补齐生成物忽略规则并提交清理版本。

**Architecture:** 以顶层白名单控制删除边界；先从现有完整部署 staging 生成临时 ZIP 并完成 CRC/结构验证，再原子替换正式 ZIP。Git 仅记录清理策略和忽略规则，部署二进制继续作为本地制品。

**Tech Stack:** PowerShell、Python 3 标准库 `zipfile`、Git。

---

### Task 1: 完善忽略规则

**Files:**
- Modify: `.gitignore`
- Modify: `backend/.gitignore`

**Step 1: 检查现有命中规则**

运行 `git check-ignore -v build/AI测试终端部署包.zip .mypy_cache/index.json backend/acad.err`，记录缺少的规则。

**Step 2: 最小修改忽略规则**

- 保留 `/build/`。
- 增加根目录 mypy 和 coverage 产物规则。
- 合并重复 `/outputs/` 条目。
- 在 `backend/.gitignore` 增加精确的 `/acad.err`。

**Step 3: 验证命中结果**

再次运行 `git check-ignore -v`，期望每个生成物均由仓库规则命中。

### Task 2: 重制并校验正式部署 ZIP

**Files:**
- Replace locally: `build/AI测试终端部署包.zip`
- Create locally: `build/AI测试终端部署包.zip.sha256`

**Step 1: 校验 staging**

确认 `build/fanban-terminal-deploy/package-manifest.json`、`README_部署说明.md` 和关键目录存在。

**Step 2: 生成临时 ZIP**

使用 Python `zipfile` 压缩 staging 目录内部内容，不包含外层 `fanban-terminal-deploy/`。

**Step 3: 验证临时 ZIP**

- `ZipFile.testzip()` 返回 `None`。
- 顶层包含 `backend-runtime`、`frontend-dist`、`documents`、`documents_bin`、`install`、`scripts`。
- 不存在 `fanban-terminal-deploy/` 顶层包裹。
- 包含 `package-manifest.json` 和 `README_部署说明.md`。

**Step 4: 替换与校验**

验证成功后替换正式 ZIP，并写入 SHA-256 校验文件。

### Task 3: 按白名单清理 build

**Files:**
- Preserve: `build/AI测试终端部署包.zip`
- Preserve: `build/AI测试终端部署包.zip.sha256`
- Preserve: `build/fanban-terminal-deploy/`
- Preserve: `build/fanban-terminal-deploy-delta/`
- Preserve: `build/_downloads/`
- Delete: `build/` 下其他顶层项

**Step 1: 解析并验证路径边界**

确认所有删除目标的绝对路径均直接位于目标 worktree 的 `build/` 下，且不命中白名单。

**Step 2: 删除测试与诊断产物**

使用同一 PowerShell 进程逐项执行 `Remove-Item -LiteralPath -Recurse -Force`。

**Step 3: 复核目录**

列出 `build/` 顶层项和总大小，期望仅剩五项白名单内容。

### Task 4: 最终验证与提交

**Files:**
- Modify: `.gitignore`
- Modify: `backend/.gitignore`
- Add: `docs/plans/2026-08-06-build-artifact-cleanup.md`

**Step 1: 检查 Git 差异**

运行 `git diff --check`、`git status --short --branch` 和定向 `git diff`。

**Step 2: 重新检查部署 ZIP**

运行 CRC、顶层目录、manifest 和 SHA-256 校验。

**Step 3: 提交**

提交消息：`chore: clean generated build artifacts`。
