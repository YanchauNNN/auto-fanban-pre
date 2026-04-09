# AI 工作交接总说明

更新时间：2026-04-08

> 这份文档的目标是：让下一个 AI 只读这一份文件，就能直接接手当前仓库工作。
> 如果本文件与旧计划、旧归档、历史 worktree 讨论冲突，以“当前代码 + 本文件”优先。

---

## 1. 先看这个：三句话总览

1. 当前**正式工作空间**是仓库根目录 `E:\project\auto-fanban-pre`，分支是 `main`，它已经具备完整的“业务模块”前端，且最近重点是**字体预检 / 按类型字体替代 / 同编码多页展示**这一轮联调。
2. 当前还存在一个**测试 worktree**：`E:\project\auto-fanban-pre\.worktrees\codex-frontend-app-shell`，分支是 `codex/frontend-app-shell`。它做了大量“登录 / 会话 / 账号 / 工作量 / task-groups / 管理员配置”的试验性前端改造，但**尚未并入 main**，不能和主工作区混为一谈。
3. 当前用户自己还在主工作区里有未提交改动，尤其是 `documents/*`、`frontend/src/features/schema/*`、`backend/src/config/spec_loader.py`。**不要擅自回滚、覆盖或整理这些用户改动。**

---

## 2. 仓库地图

### 2.1 当前 worktree / 分支

| 类型 | 路径 | 分支 | 用途 | 备注 |
|---|---|---|---|---|
| 主工作区 | `E:\project\auto-fanban-pre` | `main` | 正式主线开发 | 当前应优先在这里工作 |
| 测试 worktree | `E:\project\auto-fanban-pre\.worktrees\codex-frontend-app-shell` | `codex/frontend-app-shell` | 登录壳 / 账号 / 工作量 / task-groups 前端试验线 | 尚未并回主线 |
| 其他 worktree | `E:\project\auto-fanban-pre\.worktrees\codex-algorithm-lab-20260407` | `codex/algorithm-lab-20260407` | 与当前前端交接无关 | 可忽略 |

### 2.2 当前 git 事实

- 主工作区 `main` 当前 HEAD：`a5ef9d7a8cd1638b8a62cae6e173acf4a1cf5026`
- 测试 worktree `codex/frontend-app-shell` 当前 HEAD：`cd90257f929affb28b265669fb7efe0005219cf1`
- `origin/main` 当前也在 `a5ef9d7...`
- `codex/frontend-app-shell` 本地分支比远端 `origin/codex/frontend-app-shell` **ahead 1**

### 2.3 当前未提交改动

#### 主工作区 `main` 当前 dirty 文件

这些文件是用户当前正在进行或已保留的改动，**不要回滚**：

- `backend/src/config/spec_loader.py`
- `documents/前端测试使用说明.md`
- `documents/前端计划.md`
- `documents/参数表.md`
- `documents/参数规范.yaml`
- `documents/后端工作交接总说明.md`
- `documents/架构.md`
- `frontend/src/features/schema/schema.ts`
- `frontend/src/features/schema/schema.test.ts`
- `documents/后端计划.md` 被删除
- `documents/archieve/后端计划.md` 新增
- `test-results/.last-run.json` 被删除
- `tests/font-smoke.spec.js` 被删除

#### 测试 worktree `codex/frontend-app-shell` 当前 dirty 文件

- `.gitignore` 修改
- `.playwright-cli/` 未跟踪

结论：

- 主工作区 dirty 状态不是我误改前端造成的“脏工作区”，而是用户本身还在继续推进文档、schema、spec_loader 等内容。
- 测试 worktree 里残留的 `.playwright-cli/` 是烟测日志类产物，应视为临时文件，不应误当成产品代码。

---

## 3. 这份仓库的真实结构

### 3.1 最重要的目录

- `documents/`
  - 业务与运行期规范、计划文档、架构文档、交接文档
- `API/`
  - FastAPI 对外壳层
- `backend/src/`
  - 核心执行逻辑：CAD、pipeline、font_preflight、accounts、workflow、workload、archive 等
- `frontend/`
  - 当前主工作区前端（正式 UI）
- `storage/`
  - 任务、任务包、运行态持久化
- `documents_bin/`
  - 词库、字体库、模板、背景图等资源

### 3.2 当前源码事实源优先级

建议下一个 AI 始终按这个优先级理解系统：

1. 当前代码
2. `documents/AI工作交接总说明.md`（本文件）
3. `documents/架构.md`
4. `documents/后端工作交接总说明.md`
5. `documents/前端计划.md`
6. `documents/前端任务书_字体与多页联调.md`
7. 其他旧文档
8. `documents/archieve/*`

### 3.3 当前最关键的规范文档

- `documents/参数规范.yaml`
  - 业务字段、前后端提交契约、submission_contracts
- `documents/参数规范_运行期.yaml`
  - AutoCAD / ODA / 并发 / 槽位 / 打印 / 字体预检 / 运行期行为
- `documents/架构.md`
  - 当前主仓架构口径
- `documents/前端计划.md`
  - 当前主仓前端真实状态与后续计划
- `documents/前端任务书_字体与多页联调.md`
  - 当前主仓字体预检 / 替代 / 多页联调的最新前端口径

---

## 4. 系统当前业务架构

### 4.1 当前后端主能力

后端现在已经比较完整，主链路包括：

- 交付出图：`DWG -> DXF/识别 -> 切图/打印 -> PDF/DWG/文档/package`
- 纠错：词库扫描，输出 `report.xlsx`
- 翻版：按项目号做文字替换，输出替换后 DWG
- 管理业务线：
  - 登录认证
  - 账号管理
  - 人员字段补全
  - task-groups
  - workflow monitor / approve / repair
  - workload 统计
  - admin config

### 4.2 当前主工作区前端真实状态

主工作区前端已经正式可用的内容：

- 首页业务工作台
- 顶部状态栏
- 教程入口
- 业务模块 tab
- 出图弹窗
- 纠错弹窗
- 翻版弹窗
- 任务记录列表
- 任务详情页
- 字体预检与字体替代弹窗
- 同编码多页结果展示
- 维护提醒横幅

主工作区前端尚未正式落地的内容：

- 登录页 / 会话层
- 真实账号模块页面
- 真实工作量模块页面
- task-groups 主视图
- workflow 审批页
- admin 配置页

### 4.3 测试 worktree 的真实定位

`codex/frontend-app-shell` 不是“主线已完成功能”，而是**一条前端壳层重构试验线**。它主要做了：

- SessionProvider / token / 当前用户
- 登录页重构
- `/account`
- `/account/admin`
- `/workload`
- `/task-groups/:groupId`
- 真实管理员配置页
- 顶栏与应用壳

但这条线尚未回主线，而且 diff 很大、混杂前后端和文档变动，不能盲目整条合并。

---

## 5. 主工作区 main：当前已完成的关键前端工作

这一节只写**已经在主工作区里真实落地的东西**。

### 5.1 字体预检与按类型字体替代

当前主工作区已经对齐了这一轮新接口口径，关键点如下：

- 上传 DWG 后会先调 `POST /api/jobs/preflight-fonts`
- 创建按钮等待态文案是：`正在执行字体搜索...`
- `ok` 和 `missing_fonts` 已做分流
- 新前端主用：
  - `replacement_options_by_kind`
  - `default_replacement_fonts`
- 提交时主用：
  - `font_replacement_fonts`
- 旧字段只保留兼容：
  - `replacement_options`
  - `default_replacement_font`
  - `font_replacement_font`
- 前端不再自猜 `tssdchn.shx`
- 缺失字体弹窗默认值直接采用后端 `default_replacement_fonts`

主工作区关键文件：

- `frontend/src/platform/api/types.ts`
- `frontend/src/platform/api/httpAdapter.ts`
- `frontend/src/features/deliverable/DeliverableWorkspace.tsx`
- `frontend/src/features/deliverable/DeliverableWorkspace.test.tsx`
- `frontend/src/app/App.tsx`
- `frontend/src/app/App.test.tsx`

后端联调关键文件：

- `backend/src/cad/font_preflight.py`
- `backend/src/pipeline/shared_prep.py`
- `backend/src/pipeline/executor.py`
- `backend/tests/unit/test_font_preflight.py`
- `backend/tests/unit/test_module7_api.py`

### 5.2 同编码多页展示

当前主工作区已经对齐：

- 目录里同编码多页只显示一行
- 结果页显示提示文案：
  - `同编码多页：目录合并为一行，物理文件按页分别输出`
- 物理文件按新命名规则展示：
  - `状态X@Y`
- 不再依赖旧的 `-p1of2`

关键文件：

- `frontend/src/app/App.tsx`
- `backend/src/config/spec_loader.py`

### 5.3 纠错结果显示与弹窗尺寸修复

最近刚修过一轮 UI：

- `纠错结果摘要` 弹窗增加了专用 dialog class，宽度和内边距不再贴边
- 详情页中的 `Flags / Errors` 区块也做了卡片留白，不再直接贴大面板边框

关键文件：

- `frontend/src/features/audit-check/AuditCheckSummaryModal.tsx`
- `frontend/src/features/audit-check/AuditCheckSummaryModal.module.css`
- `frontend/src/features/audit-check/AuditCheckSummaryModal.test.tsx`
- `frontend/src/app/App.tsx`
- `frontend/src/app/App.module.css`
- `frontend/src/app/App.test.tsx`

### 5.4 创建任务按钮“点不动”问题已修

问题根因：

- 上传后字体预检前移
- `isPreflighting` 曾把“创建任务”按钮连带禁用
- 用户体验上表现为“图纸能上传，但创建任务像点不动”

当前修复后行为：

- 上传后仍会后台跑字体预检
- 按钮不再假死
- 如果预检尚未完成，点击提交会被接住，待预检结束后继续走下一步

关键文件：

- `frontend/src/features/deliverable/DeliverableWorkspace.tsx`
- `frontend/src/features/deliverable/DeliverableWorkspace.test.tsx`

### 5.5 翻版主线

此前已完成的翻版相关正式接入点：

- 首页“翻版”入口接真实弹窗
- 仅翻版 / 翻版后继续出图
- 从翻版进入出图时，项目号传目标项目号
- 出图页里不再保留混淆用的翻版开关
- 翻版页支持源/目标项目号本地草稿保存
- 翻版上传时会继承项目号自动识别能力

关键文件：

- `frontend/src/features/replace/ReplaceWorkspace.tsx`
- `frontend/src/features/deliverable/DeliverableWorkspace.tsx`
- `frontend/src/platform/api/httpAdapter.ts`
- `frontend/src/platform/api/types.ts`

---

## 6. 主工作区 main：最近完成但要记住的业务/UI决策

这些不是单纯代码细节，而是用户已经明确过的**产品决策**。下一个 AI 不要反复改回去。

### 6.1 登录与全局壳层

这些主要发生在测试 worktree 中，但属于明确的用户偏好：

- 标题栏必须永远位于页面最上方
- 切换模块时标题栏不应消失
- 登录页采用“核电站背景图 + 左侧品牌区 + 右侧登录卡”的布局方案
- 登录页大标题：
  - `中核工程-河北分公司-建筑结构所出图平台`
  - 桌面端要求单行，位于页面左上方
- 密码输入区要提醒：
  - `默认密码password`

### 6.2 顶部入口与模块入口

用户明确拒绝过“顶部再做一套账号/工作量入口”的重复导航。

已确认的偏好是：

- 如果页面中已经有模块 tab（业务模块 / 账号模块 / 工作量模块）
- 顶部就不要再重复放一套同义入口
- 顶部操作更适合保留系统级动作，比如退出登录、管理员配置

### 6.3 教程系统

用户明确要求：

- 教程必须尽量复用真实页面
- 不要再维护一套假的仿真页面来冒充真实教学

### 6.4 管理员页面

用户明确要求：

- “现有账号”不要在管理员主页面里长列表平铺
- 应该放进次级窗口
- 次级窗口内部自己滚动
- 主页面尽量不需要大滚动

### 6.5 维护提醒横幅

维护提醒：

- 文案：`后台维护升级中，为您带来的不便十分抱歉（＞人＜；）`
- 之前曾误报，根因是健康检查瞬时失败就直接判维护
- 已修成“如果已有成功健康快照，则优先相信成功快照”

### 6.6 字体替代的产品决策

用户明确否定过这些旧行为：

- 不能把所有缺失字体共用一个全局下拉
- 不能把 `ttf` 缺失错误地绑到 `shx` 候选
- 不能前端自己硬猜默认字体

现行口径：

- 按 `ttf / shx / bigfont` 分类型选择
- 默认值用后端返回的 `default_replacement_fonts`
- 优先传 `font_replacement_fonts`

---

## 7. 当前测试 worktree：`codex/frontend-app-shell`

### 7.1 这条线做了什么

这条线是“前端应用壳 / 管理业务线”的试验场，主要包含：

- 会话层：
  - `frontend/src/shared/session/SessionContext.tsx`
  - `frontend/src/shared/session/sessionRuntime.ts`
- 登录页和应用壳：
  - `frontend/src/app/App.tsx`
  - `frontend/src/app/App.module.css`
  - `frontend/src/assets/login-plant-hero.jpg`
- 账号页：
  - `frontend/src/features/account/AccountPage.tsx`
  - `frontend/src/features/account/AccountPage.module.css`
- 管理员页：
  - `frontend/src/features/account/AccountAdminPage.tsx`
  - `frontend/src/features/account/AccountAdminPage.module.css`
- 工作量页：
  - `frontend/src/features/workload/WorkloadPage.tsx`
  - `frontend/src/features/workload/WorkloadPage.module.css`
- task-groups 前端适配
- `/task-groups/:groupId`
- 管理员配置、修复当前节点、审批等页面级试验

### 7.2 这条线为什么不能直接当主线

原因有三点：

1. 与 main 差异过大
   - `git diff --stat main..codex/frontend-app-shell` 超过百文件
2. 混杂后端、前端、文档、烟测文件
3. 有些是试验性结构调整，不代表用户已确认主线接受整套架构

建议：

- 如果下一个 AI 要继续“登录/账号/工作量/task-groups”这条方向，最好**在这个 worktree 中继续开发**，但不要未经选择就整条并回 main。

### 7.3 这条线的最后已知验证状态

最后一次已知结果（来自本次对话，不是本 turn 重新验证）：

- `npm test`：`110/110` 通过
- `npm run build`：通过

但要注意：

- 当前这条线仍有 `.playwright-cli/` 未清理
- 当前 `.gitignore` 有本地变更

---

## 8. 最近一次关于 `PLOT_WINDOW_MISMATCH_SWITCHED:side_overflow` 的深入结论

这是最近一次用户手工测试里重点追问过的问题，下一个 AI 继续沟通时最好沿用这个结论。

### 8.1 这条 flag 代表什么

它不是硬失败，而是一个“打印窗口保护切换”告警。

真实含义：

- 系统发现 `frame_bbox` 比“真实选中实体集合的外包框”更小
- 并且任一边超出阈值 `2.0 mm`
- 所以打印窗口不再用 `frame_bbox`
- 改用 `selection_extents`

相关代码：

- `backend/src/cad/plot_window_strategy.py`
- `backend/src/cad/cad_dxf_executor.py`
- `backend/src/cad/dotnet/Module5CadBridge/SelectionEngine.cs`
- `backend/src/cad/dotnet/Module5CadBridge/PlotEngine.cs`

### 8.2 它在后端分别对应什么情况

统一记成 `side_overflow`，但底层实际是 4 类边溢出：

- left：左边越框
- bottom：下边越框
- right：右边越框
- top：上边越框

当前最终 job flags 不会直接告诉你是哪一边，只会给统一的 `side_overflow`。

### 8.3 它会不会导致 PDF 不完整

结论：

- 更常见的情况：它是为了**避免** PDF 不完整
- 但在少数场景下，仍可能对应 PDF 不完整风险

原因：

1. 它的本意是防止图框 bbox 太小导致裁切
2. 但切到更大的 `selection_extents` 后，打印比例不一定完全跟新窗口同步
3. 某些拿不到 extents 的实体可能被选中但没有进入 `selection_extents`，因此仍可能被裁

所以这条 flag 的风险等级应理解为：

- 不是失败
- 但提示“图框范围与真实内容范围存在偏差”
- 值得继续看运行产物里的 `task.json / result.json / module5_trace.log`

### 8.4 如果要继续深究这条 flag

优先看：

- 任务运行目录中的 `task.json`
- 任务运行目录中的 `result.json`
- 任务运行目录中的 `module5_trace.log`

这些文件里能看到：

- 原始 frame bbox
- selection_extents
- 最终 plot window bbox
- `window_source=selection_extents`

---

## 9. 当前主工作区 main 的已知验证状态

### 9.1 最近一次已知通过

主工作区最近几轮与前端相关的已知通过结果：

- 字体与多页联调：`frontend npm test` 到过 `85/85` 通过，`npm run build` 通过
- 纠错结果弹窗 / Flags-Errors 留白修复后：`frontend npm test` 到过 `87/87` 通过，`npm run build` 通过

### 9.2 当前已知非阻断项

- `frontend` 测试里存在几条旧的 React `act(...)` warning`
- 这些 warning 不是本轮新引入的失败
- 当前没有证据表明它们阻断产品功能

### 9.3 主工作区当前运行方式

当前正式主工作区启动命令是：

```powershell
cd E:\project\auto-fanban-pre
uv run --project backend python -m uvicorn API.app.main:app --host 127.0.0.1 --port 8000

cd E:\project\auto-fanban-pre\frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

注意：

- main 当前默认是 `8000 + 5173`
- `codex/frontend-app-shell` 那条测试线曾切过 `8080`
- 以前出现过“用户以为在看 main，实际上 5173 被 worktree 抢占”的混淆
- 如果再次怀疑端口串线，先查端口占用进程实际 cwd

---

## 10. 当前主工作区最重要的前后端入口文件

### 10.1 前端

- 应用入口：
  - `frontend/src/app/App.tsx`
- 出图工作台：
  - `frontend/src/features/deliverable/DeliverableWorkspace.tsx`
- 纠错工作台：
  - `frontend/src/features/audit-check/AuditCheckWorkspace.tsx`
- 纠错摘要弹窗：
  - `frontend/src/features/audit-check/AuditCheckSummaryModal.tsx`
- 翻版工作台：
  - `frontend/src/features/replace/ReplaceWorkspace.tsx`
- API 适配器：
  - `frontend/src/platform/api/httpAdapter.ts`
- API 类型：
  - `frontend/src/platform/api/types.ts`
- schema 归一化：
  - `frontend/src/features/schema/schema.ts`

### 10.2 后端

- API 外壳：
  - `API/app/main.py`
  - `API/app/runtime.py`
- 交付 pipeline：
  - `backend/src/pipeline/executor.py`
  - `backend/src/pipeline/shared_prep.py`
- CAD 主执行：
  - `backend/src/cad/cad_dxf_executor.py`
- 字体预检：
  - `backend/src/cad/font_preflight.py`
- 打印窗口策略：
  - `backend/src/cad/plot_window_strategy.py`
- 图签与识别：
  - `backend/src/cad/titleblock_extractor.py`
- 运行期规范加载：
  - `backend/src/config/spec_loader.py`

---

## 11. 对下一个 AI 的操作建议

### 11.1 接手前第一步

先做这几件事：

1. 看当前自己在哪个 worktree
2. 跑 `git -c core.quotepath=false status --short`
3. 确认用户要继续的是：
   - 主工作区 `main`
   - 还是测试 worktree `codex/frontend-app-shell`

### 11.2 如果用户继续 main 的字体 / 业务模块工作

优先留在：

- `E:\project\auto-fanban-pre`

重点看：

- `documents/前端任务书_字体与多页联调.md`
- `frontend/src/features/deliverable/DeliverableWorkspace.tsx`
- `frontend/src/platform/api/httpAdapter.ts`
- `frontend/src/app/App.tsx`

### 11.3 如果用户继续登录 / 账号 / 工作量 / task-groups

优先切到：

- `E:\project\auto-fanban-pre\.worktrees\codex-frontend-app-shell`

重点看：

- `frontend/src/shared/session/SessionContext.tsx`
- `frontend/src/features/account/AccountPage.tsx`
- `frontend/src/features/account/AccountAdminPage.tsx`
- `frontend/src/features/workload/WorkloadPage.tsx`
- `frontend/src/app/App.tsx`

### 11.4 不要做的事

- 不要默认把测试 worktree 的大 diff 整体并回 main
- 不要把 main 与 worktree 的端口配置混着用
- 不要回滚用户自己的 dirty 文件
- 不要再把字体替代写回“全局单一下拉”旧模式
- 不要把教程重新改回假页面
- 不要把顶部导航做成重复入口

---

## 12. 推荐的续接顺序

如果没有新的用户指令，推荐按下面顺序接手：

1. 先确认用户现在要继续 main 还是 `codex/frontend-app-shell`
2. 如果在 main：
   - 先保护好用户 dirty 状态
   - 再围绕字体 / 多页 / 业务模块继续
3. 如果在 `codex/frontend-app-shell`：
   - 先清理 `.playwright-cli/`
   - 再继续账号 / 工作量 / task-groups
4. 每次开始新的功能或修 bug 前：
   - 先确认分支、端口、服务实际来源
   - 再做修改

---

## 13. 最后一条提醒

当前仓库最大的认知风险，不是代码本身，而是：

- 把 `main` 和 `codex/frontend-app-shell` 混为一谈
- 把历史文档当成现行口径
- 把用户的未提交改动误当成“可以随手清理的噪音”

下一个 AI 只要先守住这三点，就不会一上来把上下文带偏。
