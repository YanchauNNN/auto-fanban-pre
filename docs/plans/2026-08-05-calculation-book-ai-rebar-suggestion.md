# Calculation Book AI Rebar Suggestion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在计算书入口增加“无实配钢筋”模式：无 Excel 压缩包经 OCR 读取 SMX，由可内网部署的通用 Skill 从后端精确候选中选择配筋，后端循环验算直至通过或明确留空，最终生成带 AI 建议说明的 Word、任务提醒和可下载诊断日志。

**Architecture:** 用显式 `reinforcement_source=provided|ai_suggested` 保持现有标准/非标准 Excel 路径不变。业务 YAML 驱动候选和 10% 裕度，后端纯函数生成有限候选；Worker 调用结构化内网模型和独立 Skill 只返回 `candidate_id`，后端负责精确复算、错误码反馈与单调收敛。通过的建议转换成现有内部 Schedule，复用图片匹配、裕度表和 DOCX 渲染；局部失败留空并告警，任务级 JSONL 日志贯穿预检后的正式 Worker 流程。

**Tech Stack:** Python 3.11/3.12, FastAPI, Pydantic v2, pytest, openpyxl, python-docx/docxtpl, existing OpenAI-compatible structured chat client, YAML, React 18, TypeScript, Vite/Vitest, CSS Modules, PowerShell deployment tooling.

---

### Task 1: Freeze the reinforcement-source and YAML contracts

**Files:**
- Modify: `backend/src/calculation_book/models.py`
- Modify: `backend/src/config/mechanism_spec.py`
- Modify: `backend/src/config/runtime_config.py`
- Modify: `documents/参数规范.yaml`
- Modify: `documents/参数规范-3.yaml`
- Modify: `documents/参数规范_运行期.yaml`
- Test: `backend/tests/unit/calculation_book/test_models.py`
- Test: `backend/tests/unit/calculation_book/test_config.py`

**Step 1: Write failing model/config tests**

覆盖以下契约：

```python
assert CalculationBookParams.model_validate(valid_payload).reinforcement_source == "provided"

params = CalculationBookParams.model_validate({
    **valid_payload,
    "reinforcement_source": "ai_suggested",
})
assert params.reinforcement_source is ReinforcementSource.AI_SUGGESTED
```

同时断言：

- `ai_suggested` 不能携带 `confirm_ai_normalization=True`；
- UI 元数据中 `reinforcement_source` 是服务端枚举，默认 `provided`；
- 业务配置完整表达 `margin_ratio=0.10`、X/Y 直径、四个硬优先级、Z 直径、六个硬优先级、`1C14@400x400` 零值构造候选及 Word 声明文本；
- 运行期配置完整表达 Skill 根目录/版本、批大小、超时、输出 token、`temperature=0`、`max_consecutive_base_failures=3` 和日志限制；
- Skill 路径按仓库根目录解析，客户端参数不能覆盖这些服务端配置。

**Step 2: Run tests and verify RED**

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/calculation_book/test_models.py backend/tests/unit/calculation_book/test_config.py -q
```

Expected: FAIL，当前模型和 YAML 配置中没有 `reinforcement_source` 与 `ai_suggestion`。

**Step 3: Implement the minimum typed configuration**

增加：

```python
class ReinforcementSource(StrEnum):
    PROVIDED = "provided"
    AI_SUGGESTED = "ai_suggested"


class CalculationBookParams(BaseModel):
    reinforcement_source: ReinforcementSource = ReinforcementSource.PROVIDED
```

在 `documents/参数规范.yaml` 中使用真实枚举字段保存预设；前端随后隐藏该 select 并渲染成“无实配钢筋”复选框。不要把候选直径、裕度或重试次数放进请求参数。

**Step 4: Run tests and verify GREEN**

运行 Step 2 同一命令。Expected: PASS。

**Step 5: Commit**

```powershell
git add backend/src/calculation_book/models.py backend/src/config/mechanism_spec.py backend/src/config/runtime_config.py documents/参数规范.yaml documents/参数规范-3.yaml documents/参数规范_运行期.yaml backend/tests/unit/calculation_book/test_models.py backend/tests/unit/calculation_book/test_config.py
git commit -m "feat: add explicit calculation reinforcement source"
```

### Task 2: Validate archive and preflight by explicit source

**Files:**
- Modify: `backend/src/calculation_book/archive.py`
- Modify: `backend/src/calculation_book/preflight.py`
- Modify: `API/app/routers/jobs.py`
- Modify: `API/app/runtime.py`
- Test: `backend/tests/unit/calculation_book/test_archive.py`
- Test: `backend/tests/unit/calculation_book/test_preflight.py`
- Test: `backend/tests/unit/test_module7_api.py`

**Step 1: Write failing archive tests**

测试严格分流：

```python
contents = validate_and_extract_archive(
    archive,
    output_dir,
    reinforcement_source=ReinforcementSource.AI_SUGGESTED,
)
assert contents.reinforcement_workbook is None
```

- `provided`：根目录必须且只能有一个 `.xlsx`；
- `ai_suggested`：必须为 0 个 `.xlsx`，发现 Excel 明确报错，不能静默忽略；
- 两种模式继续执行安全解压、`01/02` 独立图选择、墙体 X/Y/Z 完整性、字母后缀独立墙、`-1/-2` 分组和楼板 5/7 组校验。

**Step 2: Run archive tests and verify RED**

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/calculation_book/test_archive.py -q
```

Expected: FAIL，无 Excel 的批准 RAR 仍会报“缺少墙体配筋表”。

**Step 3: Make the workbook optional only under the explicit mode**

将 `CalculationArchiveContents.reinforcement_workbook` 改为 `Path | None`，并要求所有调用点显式传入来源。不得根据“有没有 Excel”反推模式。

**Step 4: Write failing preflight/API tests**

预检 multipart：

```text
archive=<file>
include_slab_stress=true|false
reinforcement_source=provided|ai_suggested
```

AI 模式响应至少包含：

```json
{
  "reinforcement_source": "ai_suggested",
  "reinforcement_workbook": null,
  "requires_ai_normalization": false
}
```

并返回墙体组数、方向图数、楼板实际 5/7 组、Z 无 SMX/零值数、忽略文件和需复核图组。测试令牌同时绑定 `include_slab_stress` 与 `reinforcement_source`，任一值改变后提交均 422 并要求重新预检。

**Step 5: Run preflight/API tests and verify RED**

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/calculation_book/test_preflight.py backend/tests/unit/test_module7_api.py -k "calculation_book" -q
```

Expected: FAIL，预检仍无来源字段且总会检查工作簿。

**Step 6: Implement the AI-suggested preflight branch**

AI 模式不调用 `inspect_reinforcement_workbook()`，不进入现有非标准 Excel 确认。创建任务时在 `job.options` 分开保存：

```python
{
    "reinforcement_source": "ai_suggested",
    "ai_rebar_suggestion": True,
    "ai_reinforcement_normalization": False,
}
```

标准 Excel 和非标准 Excel 的现有选项语义保持不变。

**Step 7: Run tests and commit**

运行 Step 2 和 Step 5 命令。Expected: PASS。

```powershell
git add backend/src/calculation_book/archive.py backend/src/calculation_book/preflight.py API/app/routers/jobs.py API/app/runtime.py backend/tests/unit/calculation_book/test_archive.py backend/tests/unit/calculation_book/test_preflight.py backend/tests/unit/test_module7_api.py
git commit -m "feat: preflight calculation archives by rebar source"
```

### Task 3: Build exact deterministic candidate profiles

**Files:**
- Create: `backend/src/calculation_book/rebar_candidates.py`
- Modify: `backend/src/calculation_book/reinforcement_input.py`
- Test: `backend/tests/unit/calculation_book/test_rebar_candidates.py`
- Test: `backend/tests/unit/calculation_book/test_reinforcement_input.py`

**Step 1: Write failing exact-formula and boundary tests**

固定精确公式：

```python
linear = layers * math.pi * (diameter / 2) ** 2 * (1000 / spacing)
grid = linear * (1000 / spacing_secondary)
target = smx * 1.10
```

测试所有 X/Y 直径 `16,18,20,25,28,32,36,40`、Z 直径 `6,8,10,12,14,16`，并覆盖每个优先级边界前后值。断言：

- X/Y 硬顺序：`1@200 -> 1@150 -> 2@200 -> 2@150`；
- Z 硬顺序：`1@400x400 -> 1@200x400 -> 1@200x200 -> 2@400x400 -> 2@200x400 -> 2@200x200`；
- `400x200` 始终规范为 `200x400`；
- 只在第一个有合格项的优先级内比较超额，不能跨级；
- 同级选 `actual_area >= target` 且超额最小的候选；
- 面积比较使用未舍入值，显示舍入不得参与选择；
- Z 没有 SMX 时只有固定 `1C14@400x400`；
- 所有候选均不足时返回空集，禁止用最大规格兜底。

**Step 2: Run tests and verify RED**

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/calculation_book/test_rebar_candidates.py backend/tests/unit/calculation_book/test_reinforcement_input.py -q
```

Expected: FAIL，候选模块不存在，旧 `select_rebar()` 还是另一套 20% 规则。

**Step 3: Implement pure candidate generation without changing legacy selection**

定义不可变对象：

```python
@dataclass(frozen=True)
class RebarCandidate:
    candidate_id: str
    profile: Literal["linear", "grid"]
    direction: str
    layers: int
    diameter: int
    spacing_primary: int
    spacing_secondary: int | None
    priority_rank: int
    actual_area: float
    target_area: float
    excess_area: float
    canonical_specification: str
    narrative_specification: str
```

从 `reinforcement_input.py` 提取公开的精确 `build_rebar_configuration()`，让 Excel 解析与新候选共用同一公式和 D/C 规范写法。保留现有 `select_rebar()` 行为，防止破坏 provided 路径。

**Step 4: Run tests and commit**

运行 Step 2 命令。Expected: PASS。

```powershell
git add backend/src/calculation_book/rebar_candidates.py backend/src/calculation_book/reinforcement_input.py backend/tests/unit/calculation_book/test_rebar_candidates.py backend/tests/unit/calculation_book/test_reinforcement_input.py
git commit -m "feat: generate exact SMX rebar candidates"
```

### Task 4: Define the strict model protocol and backend validation codes

**Files:**
- Create: `backend/src/calculation_book/ai_rebar_suggestion_schema.py`
- Test: `backend/tests/unit/calculation_book/test_ai_rebar_suggestion_schema.py`

**Step 1: Write failing schema tests**

输入协议固定为 `smx-rebar-1`，每项包含 `item_id/member_kind/member_id/direction/smx/target_area/candidates/repair_context`。输出只允许：

```json
{
  "schema_version": "smx-rebar-1",
  "items": [{
    "item_id": "N5001:Y",
    "status": "selected",
    "selected_candidate_id": "linear-l1-d40-s200",
    "reason": "...",
    "review_reasons": []
  }]
}
```

另一个合法状态仅为 `needs_review`。断言额外字段、重复/缺失 item、未知 candidate、模型返回自算面积或新规格、fenced JSON、Markdown 说明均被拒绝或归为明确错误。

**Step 2: Run tests and verify RED**

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/calculation_book/test_ai_rebar_suggestion_schema.py -q
```

Expected: FAIL，协议模型不存在。

**Step 3: Implement strict Pydantic models and validation results**

禁止 extra fields，守恒校验 `request item ids == response item ids`。实现并测试六个业务/协议错误码：

```text
MARGIN_BELOW_10_PERCENT
PRIORITY_SKIPPED
NOT_MINIMUM_EXCESS
INVALID_CANDIDATE
FORMULA_MISMATCH
SCHEMA_INVALID
```

后端始终按 candidate_id 查回服务端候选并重新计算，不信任模型理由或任何派生数值。

**Step 4: Run tests and commit**

运行 Step 2 命令。Expected: PASS。

```powershell
git add backend/src/calculation_book/ai_rebar_suggestion_schema.py backend/tests/unit/calculation_book/test_ai_rebar_suggestion_schema.py
git commit -m "feat: validate structured SMX rebar selections"
```

### Task 5: Create and independently validate the generic offline Skill

**Files:**
- Create: `tools/ai/recommend-rebar-from-smx/SKILL.md`
- Create: `tools/ai/recommend-rebar-from-smx/agents/openai.yaml`
- Create: `tools/ai/recommend-rebar-from-smx/references/io-schema.md`
- Create: `tools/ai/recommend-rebar-from-smx/references/ranking-rules.md`
- Create: `tools/ai/recommend-rebar-from-smx/scripts/validate_fixtures.py`

**Step 1: Initialize with Skill Creator, not by hand**

先完整阅读 Skill Creator 的 `references/openai_yaml.md`，然后运行：

```powershell
.\backend\.venv\Scripts\python.exe C:\Users\Yan\.codex\skills\.system\skill-creator\scripts\init_skill.py recommend-rebar-from-smx --path .\tools\ai --resources scripts,references --interface display_name="SMX 配筋建议" --interface short_description="从精确候选中选择满足 SMX 裕度规则的配筋" --interface default_prompt="依据结构化 SMX、候选和修正上下文返回严格 JSON 候选引用。"
```

Expected: 创建标准 Skill 目录，不产生 README、安装指南或其他旁支文档。

**Step 2: Write the Skill and fixture validator**

`SKILL.md` 保持简洁且使用命令式语气；详细协议和排序规则只放一级 references。明确：

- 不依赖本仓库模块、Excel、Word、数据库或外网；
- 不接收图片，不自行 OCR；
- 不自行创造规格或计算面积；
- 只能选择传入候选 ID；
- 必须遵守优先级、10% 裕度和同级最小超额；
- 修正时不得再次选择被排除候选；
- 不确定时返回 `needs_review`；
- 只输出严格 JSON。

`validate_fixtures.py` 只用标准库，覆盖正确选择、跳级、同级浪费、Z 规范化、零 SMX 构造候选、修正上下文和无候选。

**Step 3: Run standalone validation**

```powershell
.\backend\.venv\Scripts\python.exe C:\Users\Yan\.codex\skills\.system\skill-creator\scripts\quick_validate.py .\tools\ai\recommend-rebar-from-smx
.\backend\.venv\Scripts\python.exe .\tools\ai\recommend-rebar-from-smx\scripts\validate_fixtures.py
```

Expected: 两个命令均 exit 0，且 fixture 脚本不导入 `backend`、`openpyxl`、`python-docx` 或发起网络请求。

**Step 4: Blind forward-test the Skill**

启动一个不继承当前方案结论的独立子 Agent，只提供 Skill 路径和原始 JSON 用例；验证其返回能被 fixture validator 接收。再给出一个故意错误的上一轮选择，验证修正结果不重复候选。失败则只修改 Skill/refs/validator 后重测。

**Step 5: Commit**

```powershell
git add tools/ai/recommend-rebar-from-smx
git commit -m "feat: add generic SMX rebar recommendation skill"
```

### Task 6: Add the bounded structured-model Skill client

**Files:**
- Create: `backend/src/ai/rebar_suggestion_task.py`
- Modify: `backend/src/ai/chat_client.py`
- Test: `backend/tests/unit/ai/test_rebar_suggestion_task.py`
- Test: `backend/tests/unit/ai/test_chat_client.py`

**Step 1: Write failing client tests**

使用 fake structured client 断言：

- 从运行期路径有界加载 `SKILL.md` 与直接 references；
- 记录 Skill 版本和内容 SHA256；
- system/user message 只包含有界 Skill、结构化请求与关联 ID；
- 使用当前 profile 的 structured model，`temperature=0`，共享 client 内部 `max_retries=0`；
- plain JSON 正常解析；fenced JSON、超时、连接失败、非法 JSON、schema 失败统一产生脱敏基础调用错误；
- 错误或日志中不包含 API key、Authorization、完整系统提示词和 Base64。

**Step 2: Run tests and verify RED**

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/ai/test_rebar_suggestion_task.py backend/tests/unit/ai/test_chat_client.py -q
```

Expected: FAIL，新客户端不存在或共享 factory 尚不能关闭内部重试。

**Step 3: Implement the minimal caller**

复用 `build_chat_client(..., model_kind="structured")`、现有 bounded Skill bundle 和异常脱敏模式，不把该 Worker Skill 注册为网页聊天自动 Skill。

**Step 4: Run tests and commit**

运行 Step 2 命令。Expected: PASS。

```powershell
git add backend/src/ai/rebar_suggestion_task.py backend/src/ai/chat_client.py backend/tests/unit/ai/test_rebar_suggestion_task.py backend/tests/unit/ai/test_chat_client.py
git commit -m "feat: call SMX recommendation skill through internal model"
```

### Task 7: Implement the monotonic backend repair loop

**Files:**
- Create: `backend/src/calculation_book/rebar_recommender.py`
- Test: `backend/tests/unit/calculation_book/test_rebar_recommender.py`

**Step 1: Write failing convergence tests**

至少覆盖：

1. 首次选择正确，单次通过；
2. 选择低于 10% 裕度候选，下一轮只发送失败项和剩余候选；
3. 跳过优先级或未选同级最小超额，返回对应错误码；
4. 被拒候选不会再次出现在 `candidates`，重复返回会被判无效；
5. 每次业务失败后允许集合严格缩小，最终只剩唯一正确候选；
6. 已通过项不会在修正轮重发；
7. `needs_review` 立即留空并告警；
8. timeout/连接/非法 JSON/schema 非法按条目计连续基础失败，达到 YAML 的 3 次后留空；
9. 一次成功调用会重置对应条目的连续基础失败计数；
10. 候选为空时不调用 AI，直接留空；
11. singleton 候选下仍连续返回无效 ID 时不会死循环，转为基础协议失败并在 3 次后停止。

**Step 2: Run tests and verify RED**

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/calculation_book/test_rebar_recommender.py -q
```

Expected: FAIL，收敛服务不存在。

**Step 3: Implement finite-state orchestration**

返回：

```python
@dataclass(frozen=True)
class RebarSuggestionResult:
    selected: tuple[SelectedRebarSuggestion, ...]
    warnings: tuple[RebarSuggestionWarning, ...]
    call_count: int
    repair_round_count: int  # 首次选择为 0，取各批次最大追加轮次
    skill_id: str
    skill_version: str
    skill_sha256: str
    model: str
```

业务修正次数不设随意硬上限，由有限候选严格缩小保证终止；基础调用失败才使用连续 3 次上限。

**Step 4: Run tests and commit**

运行 Step 2 命令。Expected: PASS，测试中额外断言最大调用次数存在有限上界。

```powershell
git add backend/src/calculation_book/rebar_recommender.py backend/tests/unit/calculation_book/test_rebar_recommender.py
git commit -m "feat: converge invalid AI rebar selections"
```

### Task 8: Add one safe diagnostic log per calculation-book task

**Files:**
- Create: `backend/src/calculation_book/diagnostic_log.py`
- Modify: `backend/src/models/job.py`
- Test: `backend/tests/unit/calculation_book/test_diagnostic_log.py`
- Test: `backend/tests/unit/test_models.py`

**Step 1: Write failing JSONL/audit tests**

日志路径固定为：

```text
<job.work_dir>/calculation-book/logs/calculation-book-<job-id>.log
```

测试逐行合法 JSON、关联 ID、归档 SHA256、参数摘要、图片/OCR、候选、每轮输入摘要与结构化输出、错误码、排除项、最终 Word 条目、留空原因、阶段耗时。递归注入 `api_key/authorization/base64/system_prompt` 后断言日志中不存在其值。

测试大小上限、原子创建、flush/close、异常阶段仍能写 `task_failed`。日志创建失败必须使任务失败，不能产生无审计证据的 AI 建议 Word。

**Step 2: Run tests and verify RED**

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/calculation_book/test_diagnostic_log.py backend/tests/unit/test_models.py -q
```

Expected: FAIL，日志对象和 `JobArtifacts.calculation_log` 不存在。

**Step 3: Implement append-only bounded logging**

`job.json/progress.details` 只保存统计摘要；完整候选和轮次只进日志文件。所有计算书任务都创建日志，AI 模式的日志创建/写入失败作为任务失败处理。

**Step 4: Run tests and commit**

运行 Step 2 命令。Expected: PASS。

```powershell
git add backend/src/calculation_book/diagnostic_log.py backend/src/models/job.py backend/tests/unit/calculation_book/test_diagnostic_log.py backend/tests/unit/test_models.py
git commit -m "feat: add calculation task diagnostic logs"
```

### Task 9: Integrate suggestions into OCR, matching, narrative, and Word

**Files:**
- Modify: `backend/src/calculation_book/processor.py`
- Modify: `backend/src/calculation_book/narrative.py`
- Modify: `backend/src/calculation_book/matching.py`
- Modify: `backend/src/calculation_book/slab.py`
- Modify: `backend/src/calculation_book/templates.py`
- Modify: `documents_bin/calculation_book/内部结构计算书.docx`
- Modify: `documents_bin/calculation_book/核岛厂房计算书.docx`
- Test: `backend/tests/unit/calculation_book/test_processor.py`
- Test: `backend/tests/unit/calculation_book/test_narrative.py`
- Test: `backend/tests/unit/calculation_book/test_matching.py`
- Test: `backend/tests/unit/calculation_book/test_slab.py`
- Test: `backend/tests/unit/calculation_book/test_templates.py`

**Step 1: Write failing processor/narrative tests**

断言 AI 模式执行顺序：

```text
VALIDATE_ARCHIVE -> OCR_REINFORCEMENT -> AI_REBAR_SUGGESTION
-> SELECT_REBAR -> RENDER_CALCULATION_BOOK -> FINALIZE_ARTIFACT
```

并覆盖：

- 每个正常墙体 X/Y/Z 和楼板 TOP/BOTTOM/可选 MIDDLE X/Y/Z 生成 item；
- 单张 OCR 失败只让该方向留空，其他方向和 Word 继续；
- 重复配筋语义、`-1/-2` 图组、未知命名保留图片但方向留空并告警；
- 字母后缀墙（如 `S7157A`）独立处理；
- AI 结果转换为现有 `ReinforcementSchedule`/`SlabReinforcementSchedule` 等价结构，复用 matching 和裕度表；
- 裕度表仍使用每方向最终实际面积，未舍入值用于包络比较；
- finite-element model 始终来自 `02`，不从应力图替代；
- Z 无 SMX 使用 `1C14@400x400`，精确面积；
- AI 文案使用“建议选用钢筋……”，provided 路径仍使用“选用钢筋……”；
- Word 章节前出现精确声明：`以下配筋建议由人工智能根据结果云图 SMX 值并保留不低于 10% 的面积裕度生成，供设计人员复核。`；
- 楼板之后到墙体前的既有过渡文本及 `mm²/m` 上角标不回归；
- 内部结构模板仍不生成“墙体单侧实配钢筋”表，厂房模板使用当前用户修改后的版本再增加声明占位，不覆盖其他模板改动。

**Step 2: Run tests and verify RED**

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/calculation_book/test_processor.py backend/tests/unit/calculation_book/test_narrative.py backend/tests/unit/calculation_book/test_matching.py backend/tests/unit/calculation_book/test_slab.py backend/tests/unit/calculation_book/test_templates.py -q
```

Expected: FAIL，processor 仍强制从 workbook 加载 schedule 且没有 AI 建议阶段/文案。

**Step 3: Implement the source branch and partial-result adapters**

- `provided` 分支保持当前严格 OCR、标准/非标准 Excel 逻辑；
- `ai_suggested` 分支逐图容错 OCR，构造推荐 item，调用 recommender，再将 selected/warnings 适配成现有匹配对象；
- 即使方向留空，也必须生成图片、标题和空字段，不能静默丢图；
- 在两个现有 DOCX 上只增加一个独立 `{{ ai_rebar_disclosure }}` 段落，provided 模式传空字符串。

修改 DOCX 前先使用 `doc` Skill 的读取/渲染流程，修改后重新渲染逐页检查，不通过二进制字符串替换。

**Step 4: Run tests and render both templates**

运行 Step 2 命令。Expected: PASS。再用最小 fixture 分别生成内部结构与厂房 Word，渲染成图片检查声明、楼板过渡、图片、表格和页码无错位。

**Step 5: Commit**

```powershell
git add backend/src/calculation_book/processor.py backend/src/calculation_book/narrative.py backend/src/calculation_book/matching.py backend/src/calculation_book/slab.py backend/src/calculation_book/templates.py documents_bin/calculation_book/内部结构计算书.docx documents_bin/calculation_book/核岛厂房计算书.docx backend/tests/unit/calculation_book/test_processor.py backend/tests/unit/calculation_book/test_narrative.py backend/tests/unit/calculation_book/test_matching.py backend/tests/unit/calculation_book/test_slab.py backend/tests/unit/calculation_book/test_templates.py
git commit -m "feat: render AI rebar suggestions in calculation books"
```

### Task 10: Wire Worker execution, persistence, summary, and log download

**Files:**
- Modify: `backend/src/calculation_book/executor.py`
- Modify: `API/app/runtime.py`
- Modify: `API/app/worker.py`
- Modify: `API/app/routers/jobs.py`
- Test: `backend/tests/unit/calculation_book/test_executor.py`
- Test: `backend/tests/unit/test_worker_runtime.py`
- Test: `backend/tests/unit/test_api_runtime_worker_queue.py`
- Test: `backend/tests/unit/test_module7_api.py`
- Test: `backend/tests/unit/test_job_visibility.py`

**Step 1: Write failing Worker routing tests**

三路调用守恒：

```text
标准 Excel       -> normalizer 0 次, recommender 0 次
非标准 Excel     -> normalizer 1 次, recommender 0 次
ai_suggested     -> normalizer 0 次, recommender >= 1 次
```

AI 局部失败不得 `mark_failed()`；压缩包安全、日志设施、整体 Word 渲染失败仍使任务失败。Worker 重启后从 job JSON 恢复来源和 artifact，不新增队列数据库列。

**Step 2: Write failing API/artifact tests**

任务详情新增：

```json
{
  "calculation_book_output": {
    "reinforcement_source": "ai_suggested",
    "ai_rebar_suggestion": {
      "skill_id": "recommend-rebar-from-smx",
      "skill_version": "...",
      "skill_sha256": "...",
      "model": "...",
      "call_count": 6,
      "suggested_direction_count": 181,
      "blank_direction_count": 1,
      "repair_round_count": 2,
      "validation": "passed_with_warnings"
    }
  },
  "artifacts": {
    "calculation_log_available": true,
    "calculation_log_download_url": "/api/jobs/{job_id}/download/calculation-book-log"
  }
}
```

测试 `GET /api/jobs/{job_id}/download/calculation-book-log` 复用任务可见性检查，返回 `text/plain; charset=utf-8`、`Cache-Control: no-store`、`X-Content-Type-Options: nosniff`，不能下载其他用户日志。

**Step 3: Run tests and verify RED**

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/calculation_book/test_executor.py backend/tests/unit/test_worker_runtime.py backend/tests/unit/test_api_runtime_worker_queue.py backend/tests/unit/test_module7_api.py backend/tests/unit/test_job_visibility.py -q
```

Expected: FAIL，Worker 没有 recommender 工厂且 artifact 无日志。

**Step 4: Implement executor factory and safe summaries**

`CalculationBookJobExecutor` 为每任务创建日志，按服务端 options 构建唯一 AI 能力，并将逐轮消息更新为“AI 配筋建议第 N 轮修正”。完整请求/候选不得写入 `progress.details`。

**Step 5: Run tests and commit**

运行 Step 3 命令。Expected: PASS。

```powershell
git add backend/src/calculation_book/executor.py API/app/runtime.py API/app/worker.py API/app/routers/jobs.py backend/tests/unit/calculation_book/test_executor.py backend/tests/unit/test_worker_runtime.py backend/tests/unit/test_api_runtime_worker_queue.py backend/tests/unit/test_module7_api.py backend/tests/unit/test_job_visibility.py
git commit -m "feat: expose AI calculation results and task logs"
```

### Task 11: Extend frontend schema, presets, and transport

**Files:**
- Modify: `frontend/src/platform/api/types.ts`
- Modify: `frontend/src/platform/api/httpAdapter.ts`
- Test: `frontend/src/features/schema/schema.test.ts`
- Test: `frontend/src/features/calculation-book/calculationBookPresets.test.ts`
- Test: `frontend/src/platform/api/httpAdapter.test.ts`

**Step 1: Write failing schema/preset tests**

增加：

```ts
export type ReinforcementSource = "provided" | "ai_suggested";
```

断言新预设保存/应用来源；旧预设缺字段时使用 schema 默认 `provided`，不能误开启 AI。

**Step 2: Write failing adapter tests**

断言预检 FormData 同时发送 `include_slab_stress` 和 `reinforcement_source`；正确映射可空 workbook、AI 建议摘要、warnings 和日志 artifact URL。创建任务仍通过 `params_json` 发送来源，不增加第二份冲突字段。

**Step 3: Run tests and verify RED**

```powershell
Set-Location frontend
npm test -- src/features/schema/schema.test.ts src/features/calculation-book/calculationBookPresets.test.ts src/platform/api/httpAdapter.test.ts
```

Expected: FAIL，前端类型和 adapter 尚无来源/日志字段。

**Step 4: Implement the minimum mappings**

生产 `calculationBookPresets.ts` 和 `schema.ts` 已按 schema 驱动，只有测试证明必要时才修改，避免复制另一套默认值。

**Step 5: Run tests and commit**

运行 Step 3 命令。Expected: PASS。

```powershell
git add frontend/src/platform/api/types.ts frontend/src/platform/api/httpAdapter.ts frontend/src/features/schema/schema.test.ts frontend/src/features/calculation-book/calculationBookPresets.test.ts frontend/src/platform/api/httpAdapter.test.ts
git commit -m "feat: transport AI calculation rebar mode"
```

### Task 12: Add the compact “无实配钢筋” creation flow

**Files:**
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.tsx`
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.module.css`
- Test: `frontend/src/features/calculation-book/CalculationBookWorkspace.test.tsx`

**Step 1: Write failing interaction tests**

断言：

- 上传区“无实配钢筋”与“包含楼板应力”紧凑排列，不在通用字段区重复出现；
- 未勾选映射 `provided`，勾选映射 `ai_suggested`；
- 切换任一复选框立即清除旧预检结果/token；
- provided 帮助文案要求唯一 Excel；AI 模式文案明确不得包含 Excel；
- AI 模式第二步标题是“云图核验”；
- 展示墙体组数、方向图数、Z 零值数、楼板 5/7 组和缺失/复核项；
- 隐藏 Excel 文件、实配面积和“配筋表与图片匹配”字段；
- `requiresAiNormalization=false` 时不出现旧“程序将启动人工智能”规范化确认；
- 不增加 AI 二次弹窗，第三步可直接提交 `reinforcement_source: "ai_suggested"`；
- 参数预设能保存、应用和恢复该复选框；
- 下载标准模板按钮保持原行为，仅下载标准配筋模板 Excel。

**Step 2: Run test and verify RED**

```powershell
Set-Location frontend
npm test -- src/features/calculation-book/CalculationBookWorkspace.test.tsx
```

Expected: FAIL，当前仅有楼板开关。

**Step 3: Implement the custom checkbox and review branch**

从 schema 找出并过滤 `reinforcement_source`，自定义复选框只改变该字段值。不要根据上传内容自动勾选，不增加动态“实配钢筋规格”输入框。

CSS 保持当前 240px 左栏和既有移动断点，不扩大弹窗高度。

**Step 4: Run test and commit**

运行 Step 2 命令。Expected: PASS。

```powershell
git add frontend/src/features/calculation-book/CalculationBookWorkspace.tsx frontend/src/features/calculation-book/CalculationBookWorkspace.module.css frontend/src/features/calculation-book/CalculationBookWorkspace.test.tsx
git commit -m "feat: add no-rebar calculation creation option"
```

### Task 13: Show suggestion quality, blank reasons, and log download

**Files:**
- Modify: `frontend/src/features/calculation-book/CalculationBookTaskWarnings.tsx`
- Modify: `frontend/src/features/calculation-book/CalculationBookTaskWarnings.module.css`
- Modify: `frontend/src/app/App.tsx`
- Test: `frontend/src/features/calculation-book/CalculationBookTaskWarnings.test.tsx`
- Test: `frontend/src/app/App.test.tsx`

**Step 1: Write failing task-detail tests**

成功任务始终显示：配筋来源、成功建议方向数、留空方向数、最大修正轮次、模型/Skill 摘要和“下载任务日志”。OCR 失败、无候选、三次模型失败、`needs_review`、重复组和 `-1/-2` 使用后端明确原因，不套用“配筋表单元格”文案；无 Excel 时显示“仅图片证据”。

**Step 2: Run tests and verify RED**

```powershell
Set-Location frontend
npm test -- src/features/calculation-book/CalculationBookTaskWarnings.test.tsx src/app/App.test.tsx
```

Expected: FAIL，结果卡只暴露 DOCX 和旧 AI normalization 摘要。

**Step 3: Implement source-aware presentation**

扩展现有计算书结果卡和 warning 组件，不创建第二套任务详情页。日志按钮使用后端 artifact URL，保持现有鉴权下载方式。

**Step 4: Run tests and commit**

运行 Step 2 命令。Expected: PASS。

```powershell
git add frontend/src/features/calculation-book/CalculationBookTaskWarnings.tsx frontend/src/features/calculation-book/CalculationBookTaskWarnings.module.css frontend/src/app/App.tsx frontend/src/features/calculation-book/CalculationBookTaskWarnings.test.tsx frontend/src/app/App.test.tsx
git commit -m "feat: present AI rebar suggestion audit details"
```

### Task 14: Package the Skill and extend inner-network diagnostics

**Files:**
- Modify: `backend/src/deploy/terminal_package.py`
- Modify: `tools/ai/test_ai_model_connectivity.ps1`
- Test: `backend/tests/unit/test_terminal_deploy_builder.py`
- Test: `backend/tests/unit/ai/test_ai_connectivity_script.py`

**Step 1: Write failing package tests**

仿照现有 reinforcement-table-normalizer materializer，断言部署目录包含 Skill 的五个必要文件、运行期 YAML 引用可解析、SHA256 稳定、fixture validator 可在包内运行。缺任一文件时 builder 明确失败。

连接诊断测试应验证：profile `terminal_cnpe_intranet_qwen_fast`、structured model readiness、Skill 快速校验/哈希和一次最小严格 JSON 选择；不得访问外网。

**Step 2: Run tests and verify RED**

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_terminal_deploy_builder.py backend/tests/unit/ai/test_ai_connectivity_script.py -q
```

Expected: FAIL，新 Skill 未进入包且诊断脚本不认识它。

**Step 3: Implement packaging and readiness checks**

新增 `_materialize_rebar_suggestion_skill()` 并在完整包构建路径调用；不要把 Worker Skill 注册为聊天自动触发 Skill。保持部署目录 `D:\FanBanServer` 的路径约定。

**Step 4: Run tests and build a deploy tree**

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_terminal_deploy_builder.py backend/tests/unit/ai/test_ai_connectivity_script.py -q
.\backend\.venv\Scripts\python.exe .\tools\build_terminal_deploy.py --output-root .\build\fanban-terminal-deploy
```

Expected: PASS；构建目录同时含后端代码、配置、Skill、validator 和连接诊断脚本。

**Step 5: Commit**

```powershell
git add backend/src/deploy/terminal_package.py tools/ai/test_ai_model_connectivity.ps1 backend/tests/unit/test_terminal_deploy_builder.py backend/tests/unit/ai/test_ai_connectivity_script.py
git commit -m "chore: package SMX rebar recommendation skill"
```

### Task 15: Prove the formal API/Worker flow with the approved RAR

**Files:**
- Create: `backend/tests/integration/test_calculation_book_ai_suggestion.py`
- Create: `tools/smoke_calculation_book_ai_suggestion.py`
- Modify: `backend/tests/integration/test_calculation_book_ai_normalization.py`

**Step 1: Add a fake-model end-to-end integration test**

从登录/预检/创建任务/Worker 执行/任务详情走完整链路，断言：

- provided 标准 Excel 不调用任一 Skill；
- provided 非标准 Excel 只调用旧 normalizer；
- ai_suggested 只调用新 recommender；
- 一次错误选择触发针对性第二轮并收敛；
- 一项连续三次基础失败后留空但 Word 成功；
- Word 与日志两个下载端点均可用，方向总数等于建议数加留空数。

**Step 2: Run integration tests**

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_calculation_book_ai_suggestion.py backend/tests/integration/test_calculation_book_ai_normalization.py -q
```

Expected: PASS。

**Step 3: Implement the formal real-smoke CLI**

脚本必须接受 API URL、凭据/现有会话、archive 和 output dir，不硬编码密钥。执行登录、预检、正式创建、Worker 轮询、Word 下载、日志下载，并在开始前校验固定文件 SHA256：

```text
B3593CBEB654D8FF3D9350D4C93FBD4311D83F87138B0123CD7816D6BACDE466
```

输出任务 ID、模型、Skill 版本/哈希、归组守恒、建议/留空、修正轮次、Word 路径和日志路径。

**Step 4: Run backend and frontend regressions**

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q
.\backend\.venv\Scripts\python.exe -m compileall -q backend/src API/app
.\backend\.venv\Scripts\python.exe -m ruff check backend/src backend/tests API
Set-Location frontend
npm test
npm run build
```

Expected: 全部 PASS；如仓库没有配置 mypy，不临时引入新的全局门禁。

**Step 5: Run the approved real archive through API and Worker**

启动完整 API 和独立 Worker 后运行：

```powershell
.\backend\.venv\Scripts\python.exe .\tools\smoke_calculation_book_ai_suggestion.py --api-base-url http://127.0.0.1:8080 --archive "E:\project\auto-fanban-pre\test\文档\6层11.45~15\6层11.45~15.95m 结果云图 - 副本.rar" --reinforcement-source ai_suggested --include-slab-stress --output-dir .\build\ai-rebar-rar-smoke
```

验收守恒：

```text
0 Excel
59 wall groups
177 wall direction images
5 slab images (no MIDDLE)
182 recommendation directions = suggested + blank-with-reason
184 archive image files including 01/02
```

每个方向必须有有效建议或明确留空原因；不能静默遗漏。真实内网模型不可达时，不得以 mock 冒充烟测通过，应记录为环境阻塞并保留单元/集成结果。

**Step 6: Render and inspect the real DOCX**

按 `doc` Skill 使用 bundled renderer 将真实 Word 渲染为逐页图片/contact sheet，人工检查：

- 独立有限元模型图来自 `02`；
- 楼板五组在墙体之前，过渡文本和 `mm²/m` 上角标正确；
- AI 声明和“建议选用”文案正确；
- 图片/标题/方向/规格逐项对应；
- 裕度表实际面积与日志精确值一致；
- 无重叠、裁切、空白页、表格越界或字体异常。

**Step 7: Review the frontend at desktop and mobile sizes**

使用真实浏览器检查 1366x768 与 375px：两个复选框、预设、云图核验、底部按钮、任务详情和下载按钮均无遮挡；尽量无需额外纵向滚动。按用户此前要求，额外启动一个新的子 Agent，只给页面与需求，让其独立审查美感和可用性；对明确问题补测试后修复。

**Step 8: Commit acceptance assets and smoke code**

只提交测试/脚本，不提交真实业务 RAR、生成 Word、日志、凭据或临时截图：

```powershell
git add backend/tests/integration/test_calculation_book_ai_suggestion.py backend/tests/integration/test_calculation_book_ai_normalization.py tools/smoke_calculation_book_ai_suggestion.py
git commit -m "test: verify AI rebar calculation workflow"
```

### Task 16: Final branch audit and handoff

**Files:**
- Review only: all files changed since `4a972cc`

**Step 1: Run diff hygiene and targeted review**

```powershell
git diff --check 4a972cc..HEAD
git status --short
git log --oneline 4a972cc..HEAD
```

检查没有业务 RAR、模型密钥、完整 prompts、生成产物或无关 main 改动进入提交。

**Step 2: Request independent code review**

使用 `requesting-code-review` Skill，让独立子 Agent 重点检查：候选边界、收敛终止、模式隔离、方向守恒、日志脱敏、任务可见性、Word 局部留空和前端预检失效。

**Step 3: Re-run affected tests after review fixes**

先重跑每个修复对应的定向测试，再跑 Task 15 的完整 backend/frontend 门禁。Expected: 全部 PASS。

**Step 4: Prepare the handoff**

分别报告：

1. 已实现代码；
2. 通过的单元/集成/构建；
3. 指定 RAR 的真实 API/Worker/模型烟测证据；
4. Word 与前端视觉检查；
5. 尚未覆盖或受内网环境阻塞的风险；
6. 当前 branch/HEAD/worktree 状态和后续合并选择。
