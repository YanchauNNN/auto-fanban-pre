# 前端弹窗式任务配置实施计划

> **给 Codex：** 必须按任务逐项执行本计划。

**目标：** 把当前首页长表单改造成“按钮选文件 + 主配置弹窗 + 翻版次级弹窗”的任务录入流程，并补齐测试人员使用说明。

**架构：** 保留现有 React 应用和 API adapter 结构，只重组交互与状态：把文件选择、主参数区、高级选项区、次级任务开关、翻版参数弹窗拆开，浏览器侧项目号识别仅作为预览与推荐，不替代后端校验。

**技术栈：** React 18、TypeScript、Vite、React Router、TanStack Query、Zustand、CSS Modules、Vitest、Testing Library

---

### 任务 1：冻结字段分区与推荐规则

**文件：**
- 修改：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\platform\api\types.ts`
- 修改：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\features\schema\schema.ts`
- 测试：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\features\schema\schema.test.ts`

**步骤 1：先写失败测试**

补测试，覆盖：
- `required: false` 字段进入高级选项区
- 当前命中 `required_when` 的字段留在主参数区
- 翻版弹窗推荐项目号由“识别结果 + 枚举值”组成

**步骤 2：运行测试，确认先失败**

运行：

```bash
npx vitest run frontend/src/features/schema/schema.test.ts
```

预期：失败，因为字段分区 helper 和推荐项目号 helper 还不存在。

**步骤 3：写最小实现**

增加：
- 判断字段属于主参数区的 helper
- 判断字段属于高级选项区的 helper
- 生成推荐项目号列表的 helper

这里先只改纯函数，不改页面结构。

**步骤 4：再次运行测试，确认转绿**

运行：

```bash
npx vitest run frontend/src/features/schema/schema.test.ts
```

预期：通过。

**步骤 5：提交**

```bash
git add frontend/src/platform/api/types.ts frontend/src/features/schema/schema.ts frontend/src/features/schema/schema.test.ts
git commit -m "前端：补齐字段分区与项目号推荐规则"
```

---

### 任务 2：把首页入口改成小型上传按钮

**文件：**
- 修改：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\app\App.tsx`
- 修改：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\app\App.module.css`
- 测试：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\app\App.test.tsx`

**步骤 1：先写失败测试**

增加断言：
- 首页显示小型 `上传 DWG` 按钮
- 旧的三张主任务卡不再作为首页入口
- 点击上传入口后能进入主配置弹窗壳层

**步骤 2：运行测试，确认先失败**

运行：

```bash
npx vitest run frontend/src/app/App.test.tsx
```

预期：失败，因为当前页面还是旧入口结构。

**步骤 3：写最小实现**

调整 `App.tsx` 与 `App.module.css`：
- 移除首页三卡式主入口
- 加入小型上传按钮
- 保留健康状态与最近任务
- 把主弹窗状态挂到页面层

**步骤 4：再次运行测试，确认转绿**

运行：

```bash
npx vitest run frontend/src/app/App.test.tsx
```

预期：通过。

**步骤 5：提交**

```bash
git add frontend/src/app/App.tsx frontend/src/app/App.module.css frontend/src/app/App.test.tsx
git commit -m "前端：改为按钮触发的任务配置入口"
```

---

### 任务 3：实现主任务配置弹窗

**文件：**
- 新建：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\features\deliverable\TaskConfigModal.tsx`
- 新建：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\features\deliverable\TaskConfigModal.module.css`
- 修改：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\features\deliverable\DeliverableWorkspace.tsx`
- 修改：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\features\deliverable\DeliverableWorkspace.module.css`
- 测试：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\features\deliverable\DeliverableWorkspace.test.tsx`

**步骤 1：先写失败测试**

补测试，覆盖：
- 选完文件后弹出主配置弹窗
- 文件清单显示在弹窗内
- 主页面不再直接承载整张表单
- 主参数区与高级选项区分离渲染

**步骤 2：运行测试，确认先失败**

运行：

```bash
npx vitest run frontend/src/features/deliverable/DeliverableWorkspace.test.tsx
```

预期：失败，因为当前仍是页内表单。

**步骤 3：写最小实现**

创建主弹窗组件，并把当前表单渲染迁入弹窗。

必须满足：
- 只允许弹窗内部滚动
- 左侧是文件与识别摘要
- 右侧是参数录入
- 底部操作栏固定
- 高级选项折叠区只显示可选字段

**步骤 4：再次运行测试，确认转绿**

运行：

```bash
npx vitest run frontend/src/features/deliverable/DeliverableWorkspace.test.tsx
```

预期：通过。

**步骤 5：提交**

```bash
git add frontend/src/features/deliverable/TaskConfigModal.tsx frontend/src/features/deliverable/TaskConfigModal.module.css frontend/src/features/deliverable/DeliverableWorkspace.tsx frontend/src/features/deliverable/DeliverableWorkspace.module.css frontend/src/features/deliverable/DeliverableWorkspace.test.tsx
git commit -m "前端：完成主任务配置弹窗"
```

---

### 任务 4：加入项目号预识别与翻版次级弹窗

**文件：**
- 新建：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\features\deliverable\uploadInference.ts`
- 新建：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\features\deliverable\uploadInference.test.ts`
- 新建：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\features\deliverable\ReplaceTaskModal.tsx`
- 新建：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\features\deliverable\ReplaceTaskModal.module.css`
- 修改：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\features\deliverable\TaskConfigModal.tsx`
- 修改：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\features\deliverable\DeliverableWorkspace.test.tsx`

**步骤 1：先写失败测试**

补测试，覆盖：
- 文件名前 4 位的项目号识别
- 多文件混合项目号警示
- `纠错 / 翻版` 互斥
- 勾选 `翻版` 后打开次级弹窗
- `source_project_no` 默认带入但允许编辑
- 推荐项目号标签可点击回填
- `source_project_no != target_project_no`

**步骤 2：运行测试，确认先失败**

运行：

```bash
npx vitest run frontend/src/features/deliverable/uploadInference.test.ts frontend/src/features/deliverable/DeliverableWorkspace.test.tsx
```

预期：失败，因为识别 helper 和翻版次级弹窗尚未存在。

**步骤 3：写最小实现**

实现：
- 浏览器侧 advisory 项目号识别 helper
- 翻版次级弹窗
- `source_project_no / target_project_no` 输入框
- 推荐项目号标签
- 次级任务互斥开关
- 主弹窗与翻版弹窗之间的状态回写

这里不接不存在的后端接口。

**步骤 4：再次运行测试，确认转绿**

运行：

```bash
npx vitest run frontend/src/features/deliverable/uploadInference.test.ts frontend/src/features/deliverable/DeliverableWorkspace.test.tsx
```

预期：通过。

**步骤 5：提交**

```bash
git add frontend/src/features/deliverable/uploadInference.ts frontend/src/features/deliverable/uploadInference.test.ts frontend/src/features/deliverable/ReplaceTaskModal.tsx frontend/src/features/deliverable/ReplaceTaskModal.module.css frontend/src/features/deliverable/TaskConfigModal.tsx frontend/src/features/deliverable/DeliverableWorkspace.test.tsx
git commit -m "前端：预留纠错翻版开关与翻版次级弹窗"
```

---

### 任务 5：接入提交规则，但不伪造后端能力

**文件：**
- 修改：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\features\deliverable\DeliverableWorkspace.tsx`
- 修改：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\platform\api\types.ts`
- 修改：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\platform\api\httpAdapter.ts`
- 测试：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\platform\api\httpAdapter.test.ts`

**步骤 1：先写失败测试**

补测试，覆盖：
- `deliverable` 仍按当前真实 payload 提交
- `audit_check` / `audit_replace` 的任务意图已进入前端状态与 payload builder
- 当对应后端接口未开放时，前端明确阻断并提示，而不是伪造提交成功

**步骤 2：运行测试，确认先失败**

运行：

```bash
npx vitest run frontend/src/platform/api/httpAdapter.test.ts frontend/src/features/deliverable/DeliverableWorkspace.test.tsx
```

预期：失败，因为当前还没有次级任务提交语义。

**步骤 3：写最小实现**

要求：
- 保持 `deliverable` 真实可用
- 增加次级任务意图类型与状态
- 对 `audit_check` / `audit_replace` 做未开放保护
- 保持错误提示清晰

**步骤 4：再次运行测试，确认转绿**

运行：

```bash
npx vitest run frontend/src/platform/api/httpAdapter.test.ts frontend/src/features/deliverable/DeliverableWorkspace.test.tsx
```

预期：通过。

**步骤 5：提交**

```bash
git add frontend/src/features/deliverable/DeliverableWorkspace.tsx frontend/src/platform/api/types.ts frontend/src/platform/api/httpAdapter.ts frontend/src/platform/api/httpAdapter.test.ts
git commit -m "前端：保留次级任务语义并限制未开放提交"
```

---

### 任务 6：补测试说明并做最终验证

**文件：**
- 新建：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\documents\前端测试使用说明.md`
- 修改：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\app\App.test.tsx`
- 修改：`e:\project\auto-fanban-pre\.worktrees\frontend-blueprint\frontend\src\features\deliverable\DeliverableWorkspace.test.tsx`

**步骤 1：先写测试说明**

写清楚：
- 前端启动方法
- 后端/API 启动前提
- 文件选择与主弹窗流程
- 翻版次级弹窗流程
- 当前 `纠错 / 翻版` 的开放状态
- 手工测试清单
- 浏览器自动化测试清单

**步骤 2：补齐遗漏测试**

补最后一轮测试，至少覆盖：
- 弹窗打开 / 关闭
- 高级选项分区
- 推荐项目号回填
- 未开放次级任务的阻断提示

**步骤 3：运行聚焦前端测试**

运行：

```bash
npx vitest run frontend/src/app/App.test.tsx frontend/src/features/deliverable/DeliverableWorkspace.test.tsx frontend/src/features/schema/schema.test.ts frontend/src/platform/api/httpAdapter.test.ts
```

预期：通过。

**步骤 4：运行完整前端验证**

运行：

```bash
cd frontend
npm test -- --run
npm run build
```

预期：测试通过，构建通过。

**步骤 5：运行真实浏览器冒烟测试**

在有头浏览器中验证：
- 小按钮上传入口可用
- 选完文件后打开主配置弹窗
- 翻版次级弹窗可打开、保存、关闭
- 弹窗内部滚动正常，页面背景不承载长滚动
- `deliverable` 的真实提交链路仍可用

**步骤 6：提交**

```bash
git add documents/前端测试使用说明.md frontend/src/app/App.test.tsx frontend/src/features/deliverable/DeliverableWorkspace.test.tsx
git commit -m "前端：补充测试说明与弹窗流程验证"
```
