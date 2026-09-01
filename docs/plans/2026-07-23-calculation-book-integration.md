# 计算书任务集成实施计划

> **实施要求：** 按测试驱动开发逐项执行；每个功能先证明测试为 RED，再做最小实现并验证 GREEN。

**目标：** 将 `backend/jisuanshu` 适配为平台原生的计算书异步任务，让用户通过前端提交参数与 ZIP，在任务完成后下载 DOCX。

**架构：** 新增 `calculation_book` 任务类型，复用现有队列、状态、历史、权限和下载机制，但由普通文档执行器运行，不占用 CAD 槽。计算逻辑从 Tkinter 中提取为纯 Python 服务，业务/运行期/机制配置分别进入三个 YAML。

**技术栈：** FastAPI、Pydantic、现有 SQLite 任务队列、docxtpl、Pillow、pytesseract/Tesseract、openpyxl、React、TypeScript、Vite/Vitest、CSS Modules、Windows Word COM。

---

### 任务 1：锁定计算书领域契约和严格失败行为

**文件：**

- 新增：`backend/tests/unit/calculation_book/test_archive.py`
- 新增：`backend/tests/unit/calculation_book/test_reinforcement.py`
- 新增：`backend/tests/unit/calculation_book/test_templates.py`
- 新增：`backend/src/calculation_book/__init__.py`
- 新增：`backend/src/calculation_book/models.py`
- 新增：`backend/src/calculation_book/archive.py`
- 新增：`backend/src/calculation_book/reinforcement.py`
- 新增：`backend/src/calculation_book/templates.py`

**步骤：**

1. 写 ZIP 路径穿越、绝对路径、符号链接、压缩炸弹、缺 X/Y/Z、缺 01/02 的失败测试。
2. 写钢筋表格式、`SM × 1.2` 选型和容量不足必须失败的测试。
3. 写两个 Word 模板变量集合必须与上下文完全一致的测试。
4. 运行 focused pytest 并确认 RED。
5. 实现不可变输入模型、领域错误、安全 ZIP 清单、钢筋表读取和模板变量检查。
6. 运行 focused pytest 并确认 GREEN。

### 任务 2：提取 OCR 和完整计算书处理器

**文件：**

- 新增：`backend/tests/unit/calculation_book/test_ocr.py`
- 新增：`backend/tests/unit/calculation_book/test_processor.py`
- 新增：`backend/src/calculation_book/ocr.py`
- 新增：`backend/src/calculation_book/processor.py`
- 新增：`backend/src/calculation_book/executor.py`
- 复制业务资产到：`documents_bin/calculation_book/`
- 修改：`backend/requirements.txt`

**步骤：**

1. 从 `jinjie.py` 提取图片选择、SM 解析、计算上下文和模板渲染的可观察样例。
2. 写 OCR 进程失败、无 SM、歧义结果、坏图片必须失败的测试。
3. 写处理器阶段顺序、成功摘要、原子产物落盘和失败清理测试。
4. 运行 focused pytest 并确认 RED。
5. 实现可注入 OCR runner，适配 Tesseract 并保留命令、图片和解析诊断。
6. 实现处理器，复用增强版公式和图片/表格映射，不带 GUI 与 `os.startfile`。
7. 用真实模板和钢筋表运行 focused pytest 并确认 GREEN。

### 任务 3：接入三个 YAML 源和配置加载

**文件：**

- 修改：`documents/参数规范.yaml`
- 修改：`documents/参数规范_运行期.yaml`
- 修改：`documents/参数规范-3.yaml`
- 修改：`backend/src/config/runtime_config.py`
- 修改或新增：`backend/src/config/mechanism_spec.py`
- 新增：`backend/tests/unit/calculation_book/test_config.py`
- 修改：`backend/tests/unit/test_config.py`

**步骤：**

1. 写业务字段、运行时资产、ZIP 限制、OCR 参数和 SM 安全系数的配置测试。
2. 运行配置测试并确认 RED。
3. 在三个 YAML 中添加分层配置，并实现路径解析、默认值和结构验证。
4. 确保前端可使用业务 schema 渲染枚举/文案，后端使用同一来源校验。
5. 运行 focused 配置测试并确认 GREEN。

### 任务 4：接入 Job、队列、运行时和下载 API

**文件：**

- 修改：`backend/src/jobs/models.py`
- 修改：`backend/src/jobs/runtime.py`
- 修改：`backend/src/jobs/queue.py`（仅在任务载荷需要时）
- 修改：`API/app/routers/jobs.py`
- 修改：API 任务序列化/依赖文件
- 新增：`backend/tests/unit/calculation_book/test_job_runtime.py`
- 新增或修改：`backend/tests/integration/test_jobs_api.py`

**步骤：**

1. 写 `JobType.CALCULATION_BOOK`、`calculation_docx` 产物和任务序列化测试。
2. 写 multipart 创建接口、ZIP 落盘、权限、状态、下载和文件名测试。
3. 写运行时不申请 CAD 槽、按五阶段报告进度并持久化错误的测试。
4. 运行 focused pytest 并确认 RED。
5. 实现新任务类型、API、运行时分支、事件字段和安全下载。
6. 运行 focused pytest 并确认 GREEN。

### 任务 5：实现前端计算书工作台

**文件：**

- 新增：`frontend/src/features/calculation-book/CalculationBookWorkspace.tsx`
- 新增：`frontend/src/features/calculation-book/CalculationBookWorkspace.module.css`
- 新增：`frontend/src/features/calculation-book/CalculationBookWorkspace.test.tsx`
- 新增：`frontend/src/features/calculation-book/types.ts`
- 修改：`frontend/src/app/App.tsx`
- 修改：`frontend/src/app/App.module.css`
- 修改：`frontend/src/app/App.test.tsx`
- 修改：`frontend/src/api/types.ts`
- 修改：`frontend/src/api/adapter.ts`
- 修改：对应 API adapter 测试

**步骤：**

1. 写第四个同级“计算书”入口、弹窗焦点、Escape、焦点恢复和响应式结构测试。
2. 写字段校验、ZIP 文件/结构提示、创建中状态、防重复提交和 API FormData 测试。
3. 写后端计算书任务映射、详情摘要和“下载计算书 DOCX”测试。
4. 运行 focused Vitest 并确认 RED。
5. 实现独立工作台，按 280px + 1fr 布局和单列移动端规则完成样式。
6. 接入业务 schema/项目数据、任务创建、路由跳转和下载。
7. 运行 focused Vitest 并确认 GREEN。

### 任务 6：部署包和运行环境适配

**文件：**

- 修改：`backend/src/deploy/terminal_package.py`
- 修改：`backend/tests/unit/test_terminal_deploy_builder.py`
- 修改：部署安装/检查脚本（按现有打包结构确定）
- 修改：`documents/终端实装安装计划.md`

**步骤：**

1. 写部署包必须包含两个模板、钢筋表、Tesseract 可执行文件/eng 数据和 Python 依赖的测试。
2. 运行部署测试并确认 RED。
3. 把计算书资产复制到终端固定目录，并让运行期 YAML 使用部署相对路径。
4. 增加启动前检查，缺失时业务健康检查明确报错。
5. 运行部署测试并确认 GREEN。

### 任务 7：回归、真实任务和 Word 视觉验收

**文件：**

- 新增或更新：真实 smoke fixture 与测试记录
- 验证：所有上述源文件、YAML 和部署资产

**步骤：**

1. 运行计算书全部单元/API 测试。
2. 运行相关后端回归测试及完整后端测试。
3. 运行 `npm test` 和 `npm run build`。
4. 启动正式 API/worker，上传一个包含根 X/Y/Z 和 01/02 的真实 ZIP。
5. 记录源 ZIP、job id、各阶段、输出目录、DOCX 路径和下载响应。
6. 使用 Word COM 打开/导出最终 DOCX，渲染页面并检查页数、图片、替换字段、溢出和空白。
7. 构建终端部署包，核对 `D:\FanBanServer` 布局及计算书健康检查。
8. 运行 `git diff --check`，审查完整 diff，只提交本功能及计划文件。
