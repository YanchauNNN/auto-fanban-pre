---
name: building-structure-standards
description: Search, quote, compare, and explain the locally authorized Chinese building, structural, site-planning, nuclear-safety, atlas, and internal JT/CP standards corpus. Use for questions about exact clauses, standard status, replacement versions, page evidence, cross-standard design checks, or evidence gaps. Answer in Chinese and never treat catalog metadata as clause text.
---

# 建筑结构总图规范离线库

本 skill 以批准目录中的 504 份本地 PDF 和 509 条审计目录为边界，提供标准状态查询、精确条款检索、版本冲突检查、页码证据和保守的设计建议。`full_source_manifest.json` 是全量文件清单；`standards.sqlite` 只包含已经成功解析并通过发布门禁的内容。

## 运行环境与可搬迁性

将 `<skill-root>` 解析为本 `SKILL.md` 所在目录，不依赖当前工作目录或固定安装盘符。

要求：

- Python 3.10 或更高版本；
- Python 自带 SQLite 必须支持 FTS5；
- 解析新 PDF 时需要 PyMuPDF；仅查询已生成的 SQLite 不需要 PyMuPDF；
- 正常查询不需要网络。
- 原始 PDF 不进入 Skill 包或程序部署包。运行时按单文件先查 `<server-root>/documents/规范下载`，未命中时再查 `FANBAN_BUILDING_STANDARDS_FALLBACK_ROOTS` 配置的公共盘；
- 默认公共盘为 `\\10.102.2.7\文件服务器\建筑结构所\14-自开发软件\规范下载`；
- 前端不得接收磁盘路径或 UNC 路径，只能使用后端 `/api/ai/standards/...` 受控路由。

默认数据：

- `assets/data/standards.sqlite`：已授权全文条款、页码和表格索引；
- `assets/data/audit_catalog.json`：509 条语料获取审计目录；
- `assets/data/source_manifest.json`：实际入库源文件及授权声明；
- `assets/data/full_source_manifest.json`：批准目录中全部 PDF 的可搬迁相对路径清单；
- `assets/data/manifest.json`：包内文件 SHA256；
- `assets/data/validation_report.json`：单文档样例使用标准答案验证，全量语料使用数据库结构、来源映射和 SHA256 一致性验证。

## 核心工作流

1. 先识别用户明确提到的标准号、版本、条款号、表号和专业。
2. 涉及具体条款时，优先精确查询：

   ```powershell
   python "<skill-root>/scripts/standards_query.py" clause "HAF 101-2023" 3.1.1
   ```

3. 涉及概念、流程或设计检查时，检索正文：

   ```powershell
   python "<skill-root>/scripts/standards_query.py" search "能动断层"
   python "<skill-root>/scripts/standards_query.py" search "人口分布" --code "HAF 101-2023"
   ```

4. 标准没有正文结果时，查询审计目录，不要凭记忆补条款：

   ```powershell
   python "<skill-root>/scripts/standards_query.py" catalog "GB/T 14684-2022"
   python "<skill-root>/scripts/standards_query.py" catalog-versions "GB/T 18314-2009"
   ```

5. 跨规范设计建议必须同时检查各指定规范是否有已授权全文：

   ```powershell
   python "<skill-root>/scripts/standards_query.py" advice "设计基准地震动" `
     --code "HAF 101-2023" --code "GB/T 50011-2010"
   ```

6. 仅当 `evidence_level` 为 `sufficient` 时，才可把结果整理为有依据的设计建议。`partial` 只能给出初步检查项并列明缺件；`none` 必须停止确定性结论。
7. 用中文回答，逐项给出标准号、版本、条款号、PDF 物理页、印刷页和锚点。
8. 命中记录存在 `links` 时，可输出 `[查看原页](...)`、`[打开规范](...)` 和 `[下载规范](...)`；不得输出本地盘符或公共盘路径。
9. 后端最多向模型附带 2 张命中页 PNG。模型不支持图片时自动退回纯文本证据，不能因此中断回答。

详细命令和结果字段见 [references/query-guide.md](references/query-guide.md)。

## 回答规则

- 将“规范原文事实”“版本/状态事实”“工程建议或推断”分开写。
- 精确引用格式：
  `HAF 101-2023（2023），第3.1.1条，PDF第6页（印刷页8）（...pdf#page=6）`。
- 不把官方搜索摘要、审计目录、文件名或网页标题冒充规范正文。
- 不臆造条款号、数值、强制性用语、表格内容、适用范围或替代关系。
- `official_status` 不是“现行”时，必须先警告；“核验失败”不等于“未找到”。
- 发现多个版本时，优先官方现行版本，并提醒复核项目适用日期、合同版本和过渡条款。
- 表格必须通过 `table` 命令读取，保留表号和页码，不从周边文本重建缺失单元格。
- 图集只在单位提供正版授权副本后回答页图内容；扫描页或公式无法可靠提取时，明确要求视觉复核。
- 内部 JT/CP 按 `受控` 处理，不得在未授权会话、日志或外部服务中披露。

## 设计建议边界

设计建议可以包括：

- 基于已检索条款形成检查清单；
- 指出规范间需要同时核对的接口；
- 标记版本、专业和适用范围冲突；
- 建议补充的勘察、计算、审查或文控证据。

设计建议不能替代：

- 注册执业人员签署；
- 项目适用法规和合同版本确认；
- 结构计算、抗震审查、消防审查或核安全审评；
- 对缺失规范正文作出的确定性结论。

## 新语料入库

只有同时满足以下条件的源文件才能进入 `standards.sqlite`：

1. 标准号、名称、版本和官方状态已核验；
2. 本地源文件可读取且 SHA256 已记录；
3. 离线索引和内部使用授权明确；
4. 保密等级和部署访问控制已确定；
5. PDF/HTML 解析成功并通过页码抽查；
6. 标准答案验证无回归。

全量清单与可断点续建命令：

```powershell
python "<skill-root>/scripts/inventory_sources.py" `
  --source-root "<server-root>/documents/规范下载" `
  --audit-catalog "<skill-root>/assets/data/audit_catalog.json" `
  --output "<skill-root>/assets/data/full_source_manifest.json"

python "<skill-root>/scripts/build_full_corpus.py" `
  --manifest "<skill-root>/assets/data/full_source_manifest.json" `
  --source-root "<server-root>/documents/规范下载" `
  --output "<skill-root>/assets/data/standards.sqlite" `
  --cache-dir "<server-root>/storage/ai/standards-full-build/cache" `
  --report "<skill-root>/assets/data/parse_report.json" `
  --validation-report "<skill-root>/assets/data/validation_report.json"

python "<skill-root>/scripts/validate_skill.py"
```

构建器逐本缓存解析结果。未修改的 PDF 在后续运行中直接命中缓存；任一文件失败时默认不替换现有 `standards.sqlite`。`low_text_page_count` 大于零表示仍需 OCR 或原页图像复核，不能把空文本页视为已掌握。

授权和保密处理见 [references/authorization-boundary.md](references/authorization-boundary.md)。
