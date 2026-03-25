# 前端新业务模块接入计划

## Summary

以“独立路由 + 全局会话层 + 现有出图链复用”为主方案，完成登录鉴权、账号模块、最近任务提交流程、工作量监视/审批/统计三条线接入，并顺手拆解当前过大的 `App.tsx`，把首页从“单页巨型工作台”重构为受保护的应用壳。

默认路由形态如下：

- `/login`：登录页
- `/`：登录后重定向到 `/business`
- `/business`：现有业务模块首页，保留出图/纠错/翻版入口
- `/task-groups/:groupId`：任务包管理详情
- `/jobs/:jobId`：保留现有产物/下载详情页
- `/workload`：流程监视、审批、历史与统计
- `/account`：个人信息、修改密码、个人工作量
- `/account/admin`：管理员账号管理与归档路径配置

## Key Changes

### 1. 会话层与应用壳

- 新增 `shared/session/`，用 React Context 管理 `token / currentAccount / pendingTodoCount / sessionStatus`，token 持久化到 `localStorage`。
- `HttpAdapter` 升级为鉴权感知适配器：
  - 所有管理接口统一自动附带 `Authorization: Bearer <token>`
  - 401 时统一清空会话并跳回 `/login`
- `App.tsx` 只保留路由、QueryClient、受保护壳层与全局提示，不再承载业务模块大逻辑。
- 顶部导航按角色展示入口与待办数：
  - 设计人员：业务、账号、个人工作量
  - 室主任：增加科室视角
  - 所领导：增加全所视角
  - 管理员：增加管理员账号/配置入口
- 现有 hero 背景图、教程预览、业务首页、任务详情改成按路由懒加载，避免登录页和账号/工作量页继续吃业务首页的大资源。

### 2. API 与前端类型扩展

- 在 `platform/api/types.ts` 增加并类型化：
  - `CurrentAccount`
  - `LoginRequest/LoginResponse`
  - `PersonnelNormalizationResult`
  - `PersonnelCandidate`
  - `TaskGroupSummary/TaskGroupDetail`
  - `WorkflowMonitorItem`
  - `WorkflowApprovePayload`
  - `WorkflowRepairPayload`
  - `WorkloadScopeResponse`
  - `AccountRecord/InvalidAccountRow/AdminConfig`
- 在 `HttpAdapter` 新增接口：
  - `login`
  - `logout`
  - `getMe`
  - `changePassword`
  - `normalizePersonnel`
  - `listTaskGroups`
  - `getTaskGroupDetail`
  - `submitTaskGroup`
  - `restartSubmitTaskGroup`
  - `getWorkflowMonitor`
  - `approveWorkflow`
  - `repairCurrentNode`
  - `listAccounts`
  - `listInvalidAccountRows`
  - `createAccount`
  - `updateAccount`
  - `getAdminConfig`
  - `patchAdminConfig`
  - `getWorkloadMe/Office/Institute/Admin`
- 保留现有 `createBatch / createAuditCheck / createAuditReplace / getJobDetail`，业务创建链不换接口。
- `task-groups` 详情页额外并行拉取 `child_job_ids -> getJobDetail`，继续复用现有下载与产物展示，因为 `task-groups` 接口本身不返回 artifact URL。

### 3. 业务模块改造

- 把首页“任务记录”从 `/api/jobs` 切到 `/api/task-groups`，卡片直接消费后端字段：
  - `creator_name / creator_account / creator_office`
  - `workflow_status / current_node_key / archive_status`
  - `workload / effective_workload`
  - `can_view_detail / can_submit / can_approve / is_related_to_current_user`
- 任务包卡片只显示后端允许的操作，不再前端自行推断权限。
- 提交流程改成标准二段式：
  - 先直调 `submit`
  - 命中 `422 archive_target_exists` 时弹覆盖确认并重试
  - 命中 `422 duplicate_in_progress_exists` 时弹取消旧流程确认并重试
  - 命中 `422 submitter_must_match_creator` 时明确提示“仅创建者本人可提交”
  - `restart-submit` 复用同一弹窗和请求体
- 创建任务表单接入人员字段即时补全：
  - 仅对 `ied_prepared_by / ied_checked_by / ied_reviewed_by / ied_approved_by` 做 300ms 防抖补全，请求 `/api/accounts/normalize-personnel`
  - `matched`：直接写回 `姓名@账号`
  - `ambiguous`：在输入框下方打开轻量候选选择器
  - `invalid`：字段级错误并阻断提交
  - `ied_chief_designer` 不做自动补全
  - `ied_discipline_leader` 保持独立字段，不再与 `ied_checked_by` 双写同步
  - 提交前额外阻断这四个角色字段的重复账号冲突
- 现有出图/纠错/翻版创建成功后，不再以 jobs 列表为首页刷新源，而是失效并刷新 `task-groups` 列表；若需要下载产物，走任务包详情到子任务详情。

### 4. 工作量模块

- 新增 `/workload` 页面，分为两个区：
  - `当前流程监视`
  - `历史与统计`
- `当前流程监视` 只用 `/api/workflow/monitor`，绝不复用最近任务筛选逻辑。
- 监视卡直接消费后端可见结果：
  - 当前用户可审批：绿色强调
  - 与我有关但未轮到：灰色静默
  - 归档失败：红色强调
- 审批弹窗：
  - 默认 `factor = 1.00`
  - 输入范围 `0.80 ~ 1.10`
  - 两位小数
  - 若当前卡持有 `current_node_key`，一并提交 `node_key`
  - 成功后统一刷新 `workflow monitor + task-groups + auth/me`
- 管理员修复弹窗：
  - 模式一：选择现有账号，提交 `replace_with_account_id`
  - 模式二：新增账号后修复，提交 `create_account_payload`
  - 修复创建账号时默认密码固定为 `password`
  - 修复成功后刷新当前卡和任务包详情
- 历史统计区按角色显示 scope tabs：
  - 全员：个人
  - 室主任：个人 + 科室
  - 所领导：个人 + 科室 + 全所
  - 管理员：个人 + 科室 + 全所 + 管理员
- 筛选参数统一映射后端 query：
  - `start_date`
  - `end_date`
  - `status`
  - `valid_only`

### 5. 账号模块

- `/account` 页面：
  - 展示 `GET /api/auth/me` 的账号、角色、科室、待办数
  - 修改密码走 `POST /api/auth/change-password`
  - 内嵌个人工作量摘要或跳转到 `/workload?scope=me`
- `/account/admin` 页面仅管理员可见，包含：
  - 账号列表
  - 无效行高亮区
  - 新增账号
  - 编辑账号
  - 归档根路径配置
- 管理员创建账号：
  - 表单初始密码为 `password`
  - 允许编辑 `office_code / office_name / account_id / display_name / role / password`
  - 若后端返回 `account_id already exists`，提示并切到对应账号编辑态
- 账号更新成功后，前端刷新：
  - `accounts`
  - `invalid rows`
  - `auth/me`（若当前用户改的是自己）
  - `task-groups / workflow monitor`，以反映进行中流程的新快照
- 管理员配置页只接 `archive_root_path`，不预铺其他字段。

## Test Plan

- 会话与路由
  - 登录成功后持久化 token，刷新能恢复 `me`
  - token 失效返回 401 时自动回到 `/login`
  - 不同角色只看到允许的导航和 scope tabs
- 创建任务
  - 四个人员字段的 matched / ambiguous / invalid 三种补全结果
  - 重名候选选择后写回 `姓名@账号`
  - `ied_checked_by` 与 `ied_discipline_leader` 保持独立
  - 四个审批角色重复账号时阻断提交
- 最近任务与提交
  - `task-groups` 卡片正确展示 `creator_* / workflow / archive / effective_workload`
  - `can_submit/can_view_detail/can_approve` 直接驱动按钮
  - `archive_target_exists / duplicate_in_progress_exists / submitter_must_match_creator` 三条提交流程分支
  - 任务包详情能展示管理信息，并从子任务详情继续拿到下载入口
- 工作量
  - monitor 卡片按后端结果渲染，不做本地二次筛选
  - 审批 factor 边界值与 `node_key_mismatch`
  - 管理员修复的“换人 / 新增账号”两条路径
  - `me / office / institute / admin` 四类统计页按角色显隐
- 账号与配置
  - 修改密码成功后可用新密码重登
  - 账号列表与无效行加载
  - 新增/编辑账号成功后列表与业务快照刷新
  - 管理员配置页只读写 `archive_root_path`
- 回归
  - 现有出图、纠错、翻版、教程、字体替代、任务产物详情测试继续通过
  - `npm test` 与 `npm run build` 必跑
  - 最后一轮手工烟测按文档顺序走：登录 -> 创建任务 -> 最近任务 submit -> 一审审批 -> 管理员修复 -> 统计查询 -> 管理员配置

## Assumptions

- 采用“独立路由”而不是继续把账号/工作量塞回首页切面板。
- 采用 React Context 会话层，不引入 Zustand 新 store。
- 以文档后半段的后端新口径为准：`ied_checked_by` 是一审唯一事实源，`ied_discipline_leader` 独立保留。
- `task-groups` 是最近任务与提交流程的数据源，现有 `/jobs/:jobId` 页面继续保留为产物下载详情页。
- 所有鉴权请求统一使用 `Bearer` 头；若后端个别管理接口仍返回普通字符串错误，前端按字符串 `detail` 做兼容分支，未识别时回落通用错误提示。
- 当前前端基线健康：`frontend` 下 `npm test` 78/78 通过，`npm run build` 通过，可从此基线开始改造。
