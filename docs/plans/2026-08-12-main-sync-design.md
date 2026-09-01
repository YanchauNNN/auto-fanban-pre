# 最新 main 同步设计

## 目标

把本地 `main@78e087b` 的变更页码提取、字体打印兼容、运行时配置和部署更新完整同步到 `codex/calculation-ai-unified`，同时保留该 worktree 已完成的计算书 AI、任务组、审批归档、工作量、账号管理、AI 侧栏和实机连接方式。

## 当前边界

- `main` 已干净提交，本地比 `origin/main` 超前 1 个提交。
- 目标 worktree 为 `codex/calculation-ai-unified@eb7efe8`。
- 共同基点为 `2164364`；双方有 27 个重叠文件，不能用整树覆盖。
- 目标 worktree 的 `documents/快速启动.txt` 与 `backend/tests/unit/test_quick_start_commands.py` 是合并前需要保护的本地成果。
- 两份计算书 Excel 模板当前 SHA256 一致；根目录文件作为业务源，运行目录文件作为部署副本，后续必须验证一致性。

## 合并策略

采用“检查点提交 + 正式 merge + 语义冲突解决”。不逐文件复制 `main`，不强制覆盖 worktree，也不只 cherry-pick 单笔提交。

### 后端

- 引入 `archive_tools`、`change_page_extract`、字体预检和 AcCoreConsole 兼容改动。
- 保留现有计算书 AI、TaskGroup 状态发布、归档结算、账号会话原子持久化及独立 API/Worker 模式。
- `API/app/runtime.py`、任务模型、流水线执行器和部署运行时按公开接口及状态机语义合并，禁止选取单侧整文件。

### 前端

- 保留现有平台标题、模块页签、账号与工作量紧凑布局、计算书三阶段页面、AI 侧栏及当前实机 API 连接契约。
- 增加变更页码提取入口、工作区、任务状态和 API 类型。
- 对 `App.tsx`、`App.module.css`、`httpAdapter.ts`、`types.ts` 逐段合并。
- 在 1600×900、1366×768 和窄屏下检查入口密度、内部滚动、主地标和焦点可见性。

### 配置、模板和部署

- `参数规范-3.yaml` 与 `参数规范_运行期.yaml` 按键合并，保留计算书 AI、任务组闭环、探针和新增页码提取/字体配置。
- 根目录计算书模板作为业务源文件；部署过程复制到 `documents_bin/calculation_book`，并用哈希测试防止两份内容漂移。
- 合并探针、Office COM、CAD/AcCore、账号、工作量、计算书和变更页码检测；健康检查必须区分 API 可达、业务 ready、Worker 存活、IIS/ARR 与 supervisor 状态。
- 最终只生成最新完整部署包，不使用旧 delta 包。

## 错误处理

- 合并前本地成果必须提交成独立检查点。
- 所有冲突标记必须清零；二进制 DLL 以合并后源代码重新构建/核验为准。
- 测试或探针失败视为真实失败，不能以“扫描为空”或“开发环境可启动”代替业务健康。
- 实机任务烟测必须记录上传文件、任务 ID、输出目录、生成物、日志与未覆盖环节。

## 验收标准

1. 目标分支包含 `main@78e087b` 的完整可达历史。
2. 现有计算书 AI、账号、工作量和任务组业务回归通过。
3. 变更页码提取和字体打印兼容的后端/前端测试通过。
4. 前端全量 Vitest 与生产构建通过，既有连接配置未被回退。
5. 探针和真实计算书 RAR 任务通过；部署包清单、哈希和 `D:\FanBanServer` 布局核验通过。
