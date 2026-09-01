# Build 目录清理设计

## 目标

整理 `build/`，保留可交付或可直接用于重新构包的部署内容，清除历次测试、烟测、视觉审查和诊断临时文件，并完善忽略规则，避免生成物进入 Git。

## 保留范围

- `build/AI测试终端部署包.zip`
- `build/AI测试终端部署包.zip.sha256`
- `build/fanban-terminal-deploy/`
- `build/fanban-terminal-deploy-delta/`
- `build/_downloads/`

其中 ZIP 必须重新按部署目录的“内容”压缩，压缩包根目录应直接包含 `backend-runtime/`、`frontend-dist/`、`documents/`、`documents_bin/`、`install/`、`scripts/` 等部署项，不得再额外包裹 `fanban-terminal-deploy/`。

## 删除范围

`build/` 下除上述白名单外的所有顶层文件和目录，包括：

- `ai-rebar-rar-smoke*`、`task9-real-smoke-*`
- `pytest-*`、`pytest-temp-*`
- `acceptance-*`、`abr`、`abt`
- `final*`、`rev2*`、`isolate401`
- `ui-review-final`
- `stale-proof.sqlite3`

这些内容均为可重建的测试、烟测或诊断产物，不属于正式部署包。

## Git 忽略策略

- 保持根目录 `/build/` 整体不进入 Git；部署 ZIP 通过本地制品交付，不提交 300MB 以上二进制文件。
- 补齐 mypy、coverage 和后端 CAD 临时错误日志的忽略规则。
- 合并重复的 `/outputs/` 忽略声明，但不清理既有历史追踪文件。
- 不删除 `.venv`、`node_modules`、`storage`、`output` 或用户业务文件。

## 验证

1. 对新 ZIP 执行 CRC 完整性检查。
2. 确认 ZIP 根目录不存在 `fanban-terminal-deploy/` 包裹层。
3. 确认 ZIP 内含 manifest、部署说明和关键运行目录。
4. 确认 `build/` 顶层仅剩白名单内容。
5. 检查 Git 差异、忽略命中结果和工作树状态后提交。
