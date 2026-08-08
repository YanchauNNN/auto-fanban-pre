# 开发环境快速启动与 AI 侧标调整设计

## 目标

整理现有 `codex-calculation-ai-unified` 开发测试启动命令，并把右侧 AI 侧标适度放大，使 `A`、`I` 两个字母正立纵向排列，同时保持现有抽屉交互和可访问性不变。

## 启动命令

- 保留 `documents/快速启动.txt` 中已有的 main 和 `codex-unified-workspace` 内容。
- 将第三组明确命名为“计算书 AI 测试空间 `codex-calculation-ai-unified`”。
- API、Worker、前端分别在三个 PowerShell 窗口启动；API 不承担任务执行，Worker 必须单独运行。
- API 与 Worker 均使用 `python -X utf8`。
- 前端使用 `npm.cmd`，规避当前 PowerShell 执行策略对 `npm.ps1` 的拦截。
- 前端显式设置 `VITE_API_PROXY_TARGET=http://127.0.0.1:8010`，但不设置 `VITE_API_BASE_URL`，继续走同源 `/api` 代理。
- 补充前端访问、API ping、系统 health 和 AI state 地址。

## AI 侧标

- 仅修改 `AiChatDrawer.module.css`，不改变组件 DOM、按钮语义、点击事件、焦点恢复或抽屉状态。
- 宽度从 `3rem` 调整为 `3.5rem`，最小高度从 `6.2rem` 调整为 `8rem`，字体从 `1.02rem` 调整为 `1.25rem`。
- 保留 `writing-mode: vertical-rl`，增加 `text-orientation: upright`，使 `A` 与 `I` 正立并上下排列。
- 保持移动端位置逻辑不变。

## 验证

- 先新增 CSS 契约测试并确认旧样式下失败。
- 修改样式后运行 AI 抽屉相关测试。
- 运行完整前端测试及生产构建。
- 对快速启动命令执行无持久副作用的入口导入、命令解析和代理配置检查。

## 边界

本次不自动改写或删除历史任务。任务 `f0eb000b-3709-4791-9a7b-a53a6a6c2f1f` 的卡住问题作为独立诊断结论交付。
