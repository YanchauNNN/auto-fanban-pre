# Worker 进程与 SQLite 队列架构设计

日期：2026-07-05

## 背景

当前 `DeliverableApiRuntime` 在 uvicorn 进程内维护任务队列、线程池、CAD 槽位和文档后处理线程。CAD、Office COM、PDF/压缩包生成等重任务虽然运行在线程池中，但仍属于 API 进程。实机日志已经证明，在长任务或批量任务期间，`/api/system/ping` 可能连续超时；现有 supervisor 会把“端口仍监听但 ping 超时”当成 uvicorn 故障并重启，从而中断正在运行的任务。

同时，前端首页会长期轮询 `/api/jobs?offset=0&limit=100`，后端每次 `list_jobs()` 都从磁盘加载全部 `job.json` 和 `group.json` 后排序。任务历史增长后，这会同时增加浏览器渲染、后端 JSON 解析和磁盘 IO 压力。

目标是把 CAD/文档生成彻底移到独立 worker 进程，uvicorn 只做 API 和状态查询；重建任务队列、进程通信、失败恢复、前端轮询和部署 supervisor。

## 决策

采用 SQLite 作为本机控制面：

- 数据库路径：`storage/runtime/fanban_queue.sqlite3`
- 保留现有 `storage/jobs/*/job.json` 和 `storage/groups/*/group.json`
- SQLite 负责队列、worker 心跳、任务摘要索引和轻量活动状态
- JSON 文件继续作为任务详情、产物路径和兼容存储

不引入 Redis、Celery、Windows 服务或外部数据库，保持离线 Windows 单机部署模型。

## 进程模型

### API 进程

uvicorn 只负责：

- 上传文件并写入 job/group JSON
- 写入 SQLite 队列项
- 查询 SQLite 摘要索引和 JSON 详情
- 下载产物
- 返回 health/activity 状态

API 不再创建 CAD/文档线程池，也不再执行 `PipelineJobProcessor`、`SharedPrepService.prepare()` 或 Office 后处理。

### Worker 进程

新增 worker 入口，例如：

```powershell
python -X utf8 -m API.app.worker
```

worker 负责：

- 轮询并 claim SQLite 队列
- 执行任务组共享前处理
- 执行纠错、翻版、交付包、仅拆图、字体处理和文档后处理
- 维护 CAD 槽位和 Office 串行约束
- 持续更新 job/group JSON
- 同步更新 SQLite 摘要索引和心跳

worker 可以先实现为单进程内多线程池，后续再扩展为多个 worker 进程。关键要求是重任务不再运行在 uvicorn 进程内。

## SQLite 表

### queue_items

字段：

- `id`
- `item_type`：`job` 或 `group`
- `item_id`
- `status`：`queued`、`claimed`、`done`、`failed`、`cancelled`
- `priority`
- `run_after`
- `claimed_by`
- `claimed_at`
- `heartbeat_at`
- `attempt_count`
- `last_error`
- `created_at`
- `updated_at`

约束：

- 同一个未完成 `item_type + item_id` 不重复入队
- claim 使用 SQLite 事务，保证多进程下只有一个 worker 获得任务

### worker_heartbeats

字段：

- `worker_id`
- `pid`
- `started_at`
- `last_seen_at`
- `state`
- `current_item_type`
- `current_item_id`
- `message`

用途：

- health 展示 worker 是否在线
- supervisor 判断 worker 是否需要重启
- API 判断任务是否因 worker 中断需要恢复

### job_summaries

字段覆盖前端首页和历史列表需要的轻量摘要：

- `item_id`
- `is_group`
- `batch_id`
- `group_id`
- `source_filename`
- `task_kind`
- `task_role`
- `status`
- `stage`
- `percent`
- `message`
- `failure_reason`
- `stage_context`
- `created_at`
- `finished_at`
- `updated_at`
- `artifact_flags`
- `findings_count`
- `affected_drawings_count`

JSON 详情仍由 job/group 文件提供。摘要缺失时，API 可以从 JSON 重建索引。

### activity_state

保存轻量活动视图：

- `active_count`
- `queued_count`
- `running_count`
- `failed_count`
- `succeeded_count`
- `last_changed_at`
- `last_completed_at`
- `last_error_at`

前端首页优先轮询该信息。

## 队列与恢复

### 创建任务

API 创建任务时：

1. 写入上传文件。
2. 写入 job/group JSON，状态为 `queued`。
3. 写入 `queue_items`。
4. 写入或刷新 `job_summaries`。
5. 返回任务摘要。

### Worker claim

worker 循环：

1. 更新 worker 心跳。
2. 在事务中选择 `queued` 且 `run_after <= now` 的队列项。
3. 将队列项改为 `claimed`，写入 `claimed_by`、`claimed_at`、`heartbeat_at`。
4. 执行任务。
5. 根据结果将队列项改为 `done`、`failed` 或 `cancelled`。

### API 重启

API 重启不改变 running/claimed 任务状态，不再执行 `service_restarted_before_completion` 恢复判定。只要 worker 还活着，任务继续执行。

### Worker 重启

worker 启动时：

- `queued` 任务继续等待。
- `claimed` 且心跳未过期的任务保持不动。
- `claimed` 且心跳过期的任务标记为 `worker_interrupted_before_completion`。
- 对可安全重试的阶段，后续可以按配置重新入队；初版默认失败，不伪装成功。

### 任务组

任务组编排也由 worker 执行。replace-then-deliverable 的顺序关系保持：

1. 共享前处理。
2. 翻版子任务。
3. 翻版成功并产出 replaced DWG 后，再执行交付子任务。
4. 聚合子任务状态和产物到 group。

## API 变化

新增：

- `GET /api/jobs/activity`
- `POST /api/system/worker/reindex`，可选维护入口，重建摘要索引

调整：

- `GET /api/jobs` 优先读 SQLite 摘要索引并分页
- `GET /api/system/health` 增加 worker 状态、队列深度、stale claim 数量
- `POST /api/jobs/batch` 和纠错/翻版创建接口只入队，不执行重任务

保持：

- 任务详情接口
- 下载接口
- 前端已有任务卡片字段

## 前端轮询

首页不再双路长期轮询 `/api/jobs?offset=0&limit=100`。

改为：

- `connectionQuery` 可保留，但只表示 API HTTP 可达。
- `healthQuery` 低频轮询。
- 新增 `jobsActivityQuery` 轮询 `/api/jobs/activity`。
- 首页最近任务只在 activity 的 `last_changed_at` 变化时刷新少量摘要。
- 历史任务弹窗继续分页加载。

目标是把空闲状态下的轮询成本降到固定小 JSON，避免任务历史越多越卡。

## Supervisor

`FanBanBackend` 计划任务仍作为唯一运维入口。

`scripts/start_backend.ps1` 启动两个子进程：

- API：`python -X utf8 -m uvicorn API.app.main:create_app --factory ...`
- Worker：`python -X utf8 -m API.app.worker`

停止语义：

- `Stop-ScheduledTask -TaskName FanBanBackend` 必须关闭 supervisor、API、worker 以及其子进程。
- 继续使用 Job Object 绑定子进程生命周期。

重启语义：

- API ping 超时只重启 API，不杀 worker。
- worker 心跳过期只重启 worker，不杀 API。
- 端口无监听才作为 API 进程异常处理。
- 不再因为 `ping_failed_listener_alive` 直接重启整个后端执行面。

日志：

- `api-stdout-*` / `api-stderr-*`
- `worker-stdout-*` / `worker-stderr-*`
- `backend-stderr-*` 汇总 supervisor 判定

## 部署与兼容

部署包新增或更新：

- worker 入口源码
- SQLite 控制面模块
- `start_backend.ps1`
- `check_health.ps1`
- `README_部署说明.md`
- `documents/终端实装安装计划.md`

安装命令原则上不增加新系统依赖。SQLite 使用 Python 标准库 `sqlite3`。

覆盖更新后：

- 后端相关文件变更时仍需重启 `FanBanBackend`。
- 计划任务动作本身若仍指向 `start_backend.ps1`，通常不需要重新注册。
- 如果 register 脚本参数或任务配置变更，再重新注册。

## 测试计划

单元测试：

- SQLite schema 初始化和迁移
- 队列入队、claim、完成、失败、心跳过期
- job/group 摘要索引重建
- API 创建任务只入队
- worker 执行 queued job
- API 重启不标记 running 任务失败
- worker stale claim 恢复为 interrupted
- `/api/jobs/activity` 轻量返回
- `list_jobs` 不全量扫磁盘的路径
- 部署脚本生成 API + worker supervisor

前端测试：

- 首页使用 activity 轮询
- activity 变化时刷新最近任务
- 历史任务弹窗分页行为保持
- 连接提示区分 API 断开和 worker 异常

部署测试：

- `uv run --project backend pytest backend/tests/unit/test_terminal_deploy_builder.py`
- 打包生成部署包
- 检查部署包包含 worker 入口和 SQLite 模块
- 检查脚本中无开发绝对路径残留

全任务烟测：

- 交付出图
- 仅拆图
- 纠错检查
- 翻版
- 翻版后出图
- 字体预检/替换
- 任务详情和下载产物
- worker 执行中 API health/ping 仍可响应
- 停止计划任务能停止 API 和 worker

## 风险

- 任务组编排从 API runtime 移出后，需要小心复用现有逻辑，避免复制两套业务流程。
- JSON 和 SQLite 双写存在一致性风险；必须提供摘要重建能力。
- worker 被强杀时无法保证 Office/CAD 子进程完全干净退出；supervisor 必须继续使用 Job Object。
- 全任务烟测依赖真实 CAD/Office 环境，开发机和部署机结果仍需分开记录。

## 验收标准

1. uvicorn 进程中不再执行 CAD/Office/文档生成重任务。
2. 独立 worker 可以完成现有任务类型。
3. API 重启不打断 worker 当前任务。
4. worker 故障能被 health 和 supervisor 识别。
5. 前端首页不再长期双路拉取 100 条任务摘要。
6. 后端任务列表查询不再每次全量扫描磁盘。
7. 部署包脚本能同时启动、停止、诊断 API 和 worker。
8. 全任务烟测输出正确。
