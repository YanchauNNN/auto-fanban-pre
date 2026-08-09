# 部署包业务探针与 Office COM 诊断设计

## 背景

当前 `codex-calculation-ai-unified` 已包含账号管理、工作量闭环、计算书 AI 配筋、
ZIP/RAR/7z 安全归档支持以及相关前后端修改，但现有完整部署包生成于 2026-08-06，
早于当前源码。现有部署健康检查主要覆盖端口、HTTP、IIS 和基础环境，不能证明账号、
工作量、计算书三类业务可用，也会在 `/api/system/health` 返回 HTTP 200 但
`ready=false` 或 Worker 不存活时误报健康。

Office COM 实测还暴露出两个必须修复的问题：Word 正式导出在 120 秒内不返回，Excel
打开工作簿返回 `RPC_E_CALL_REJECTED`，两次检测均残留 Office 进程。现有探针的部分
直接 COM 调用没有子进程超时保护，COM 注册诊断也只观察默认注册表视图，不能准确说明
32 位 Office 在 64 位系统上的注册状态。

## 目标

- 默认使用只读探针，不修改生产业务数据。
- 只有显式传入 `-AllowSyntheticMutation` 时，才创建带 `PROBE-` 前缀的临时账号、
  工作流或任务，并在结束时自动清理。
- Office、账号/工作量、计算书分别输出独立结论，由统一入口聚合。
- 任一必需项失败、超时或被跳过时，不得把相应业务模块判为健康。
- 所有探针即使遇到 Office 卡死、Worker 离线或 API 错误，也必须落盘可回传日志。
- 重新构建完整部署包，纳入当前源码、探针、私有归档运行时和全部 AI Skills。

## 方案选择

采用“模块化探针 + 统一编排”方案：

1. `probe_target_env.ps1` 继续负责操作系统、Python、CAD、Office 和私有归档运行时。
2. 新增 Python 业务探针，负责 API 认证、账号、工作量和计算书业务合同验证。
3. 部署包生成器产出 PowerShell 总入口，统一建立结果目录、调用子探针并汇总结论。
4. 快速环境检查与完整业务烟测分级，报告中明确 `probe_level`，不把快速检查冒充
   完整端到端证明。

不采用把全部逻辑继续堆入一个 PowerShell 文件的方案，因为 Office COM、HTTP API、
任务轮询和日志脱敏的失败模型不同；也不采用每次固定写入生产数据的方案，因为日常巡检
不应污染账号表和任务台账。

## Office COM 探针

### 隔离和超时

Word、Excel 的直接 COM 激活和真实模板导出全部通过独立 PowerShell 子进程执行。父进程
只负责启动、记录基线 PID、等待限定时间、读取结果 JSON，并在超时后终止探针子进程及
本次新增且可归属的 Office 进程。不得终止探针开始前已存在的 Word/Excel 进程。

Office 检查分为以下阶段，每个阶段记录开始、结束、耗时和错误：

1. 注册信息检查；
2. COM 激活；
3. 读取应用版本和 Ready 状态；
4. 打开部署包内真实模板；
5. 保存临时副本；
6. 使用正式 `PDFExporter` 导出 PDF；
7. 关闭文档和应用；
8. 检查新增残留进程。

父进程对直接 COM 和功能导出分别设置超时。子进程错误、退出码异常、结果 JSON 缺失、
超时、导出文件缺失、PDF 为空或残留进程均判为失败。

### 注册和错误分类

注册诊断同时读取：

- 默认 64 位 `HKCR` 视图；
- `HKLM\SOFTWARE\WOW6432Node\Classes` 的 32 位 Office 视图；
- App Paths；
- 注册命令中的可执行文件路径和文件存在性。

稳定错误码至少区分：注册缺失、可执行文件缺失、COM 激活失败、Office 忙、调用被拒绝、
交互式对话框或首次启动疑似阻塞、模板打开失败、导出失败、超时和进程泄漏。

当前实测只能确认 Word 阻塞和 Excel `RPC_E_CALL_REJECTED`，不能在没有进一步证据时把
原因直接写成“Office 未激活”或“安装损坏”。探针应在报告中给出修复建议，而不是自动
修改 Office 安装、全局配置或用户 Normal 模板。

## 通用健康判定

部署健康脚本不再以 HTTP 200 作为业务健康的充分条件。`/api/system/health` 必须满足：

- `ready == true`；
- `storage_writable == true`；
- `worker_alive == true`；
- `worker_count > 0`。

响应缺字段、字段类型错误或超时均失败。端口、IIS/ARR、同源代理和 API 业务健康继续分别
报告，防止用代理成功掩盖 Worker 或存储故障。

## 账号和工作量探针

### 默认只读

使用显式 Token，或账号密码换取 Token 后执行：

- `/api/auth/me`；
- 账号列表和无效行查询；
- 当前用户、部门、全所和管理员工作量查询（按当前账户权限选择必需项）；
- 任务组和流程监控只读接口；
- 响应结构、中文角色、金额/工作量数值、分页和终态字段检查；
- 敏感字段递归检查。

任何响应不得包含 `password`、默认密码值、Authorization、Token、API Key 或无效行中的
敏感原始列。无权限接口返回明确 403 可记为权限符合预期，不能记作模块故障。

### 可选写链路

传入 `-AllowSyntheticMutation` 后才启用。所有对象使用 `PROBE-<session-id>` 前缀，并在
`finally` 中清理。创建、更新、查询和清理分别记录。若当前正式 API 不具备安全删除接口，
该写入项应保持 `SKIPPED` 并在报告中说明缺少可恢复清理能力，不得绕过 API 直接改 CSV、
JSON 或 SQLite。

## 计算书探针

### 快速层

快速层验证：

- 计算书业务 YAML 和运行期 YAML 可加载；
- 计算书模板、标准配筋模板和依赖资源存在且哈希可读；
- 四个 AI Skills 完整；
- 私有 7-Zip 运行时版本、哈希、格式 handler 和 ZIP/7z/RAR5 微型样本通过；
- API、Worker、存储和任务目录健康；
- 计算书预检接口可访问并返回期望合同。

快速层通过只表示 `probe_level=environment`，不等价于 Word 成品已经生成。

### 完整层

显式启用完整计算书烟测后，复用正式 API 和独立 Worker，以已批准真实 RAR 样本执行：

1. 预检；
2. 创建 AI 建议配筋计算书任务；
3. 轮询至终态；
4. 下载 Word 成品和任务诊断日志；
5. 校验墙体、方向、楼板和建议数量；
6. 校验 DOCX 为有效 ZIP 容器；
7. 校验诊断日志存在连续事件和 `task_completed` 终止事件。

任务失败或超时时保留任务 ID、最后状态、最后阶段、服务端错误、可下载日志路径及本地
HTTP 交互日志。完整层通过才可声明 `probe_level=full` 的计算书业务健康。

## 日志和脱敏

每次探针运行建立独立目录：

```text
probe-results/<UTC时间>-<session-id>/
├─ summary.json
├─ events.jsonl
├─ office/
│  ├─ word-result.json
│  ├─ excel-result.json
│  └─ process-evidence.json
├─ account-workload/
│  └─ result.json
├─ calculation-book/
│  ├─ result.json
│  ├─ task-diagnostic.jsonl
│  └─ downloaded-artifacts/
└─ child-process/
   ├─ *.stdout.log
   └─ *.stderr.log
```

每条 JSONL 事件包含 schema version、session ID、模块、阶段、时间、耗时、状态、稳定错误码
和安全上下文。写日志前递归脱敏密码、Token、Authorization、API Key、Secret、Cookie 和
Base64 大字段。报告只记录凭据来源，不记录凭据内容。

总结果使用 `PASS`、`FAIL`、`SKIPPED`。指定模式中的必需探针出现 `FAIL` 或 `SKIPPED`
时，进程退出码非零。日志自身无法创建时也必须通过 stderr 返回明确错误并非零退出。

## 部署包同步

部署包构建前必须：

- 编译最新前端；
- 准备并校验私有 7-Zip 26.02 运行时缓存；
- 复制最新 API、backend、frontend dist 和三份 YAML；
- 复制 Office、业务和计算书探针；
- 物化 `ansys-mapdl-18-2`、`building-structure-standards`、
  `reinforcement-table-normalizer`、`recommend-rebar-from-smx` 四个 Skills；
- 复制计算书模板和标准配筋模板；
- 在发布 ZIP 前从部署目录本身执行离线探针和清单哈希校验。

本次只生成完整部署包。现有 `baseline_exists=false` 的 delta 包不参与交付。最终完整 ZIP
继续使用 `build/AI测试终端部署包.zip`，并在 manifest 中记录 Git SHA、探针版本、Skill
清单、归档运行时版本和文件哈希。

## 测试与验收

- PowerShell 源码合同测试覆盖超时、PID 基线、32/64 位注册视图和结果落盘。
- 使用假的 Office 子进程验证超时后仍有 summary、只清理新增 PID、旧 PID 不受影响。
- Python API 探针使用真实临时 FastAPI 应用验证只读合同、权限和敏感字段检查。
- 计算书探针测试失败终态、超时、日志缺终止事件、产物损坏和完整成功路径。
- 部署包测试验证探针、四个 Skills、7-Zip、模板和 manifest 全部存在。
- 构建后从 `build/fanban-terminal-deploy` 运行离线探针，再生成最终 ZIP。
- 实机验收分别运行快速模式和显式完整模式；只有完整模式全绿时才声明对应业务端到端正常。

## 变更边界

当前 worktree 中已有的快速启动和 AI 侧栏四项未提交修改属于另一项工作。本设计和后续提交
必须使用精确路径暂存，不修改、不还原、不混入这些文件。
