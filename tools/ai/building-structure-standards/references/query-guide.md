# 查询指南

## 数据层次

1. `standards.sqlite`：可用于条款、表格、页码和设计证据。
2. `audit_catalog.json`：只用于编号、名称、官方状态、替代信息、来源、下载性、授权和保密等级。
3. 未出现在上述两层的数据：视为没有证据。

审计目录记录不等于已拥有全文。

## 命令

### 精确条款

```powershell
python scripts/standards_query.py clause "HAF 101-2023" 4.1.2
```

关键字段：

- `found`
- `evidence_insufficient`
- `results[].text`
- `results[].page_start`
- `results[].printed_page_start`
- `results[].anchor`
- `results[].citation`
- `results[].source_sha256`：证据对应的PDF内容哈希；独立原页核验必须同时匹配它。
- `results[].content_role`：正文 `normative`、目录 `toc`、公告 `announcement`、条文说明 `commentary` 或未确认 `unknown`。
- `results[].page_quality`：覆盖全部物理页的质量记录，而非只看起始页。
- `results[].quality_flags` / `design_advice_allowed`：存在待复核、缺失质量字段或非正文证据时不得放行。
- `results[].links.page`：后端生成的精确原页 PNG；
- `results[].links.document`：浏览器内打开 PDF，并附带页码片段；
- `results[].links.download`：由后端发送原 PDF；
- `warnings`

### 正文检索

```powershell
python scripts/standards_query.py search "设计基准洪水"
python scripts/standards_query.py search "设计基准洪水" --code "HAF 101-2023" --limit 5
```

检索会忽略 PDF 折行造成的空白，但不会进行语义猜测。没有结果时应改用更短的规范术语重试一次；仍无结果就报告证据不足。

### 标准信息

```powershell
python scripts/standards_query.py standard "HAF 101-2023"
```

仅查询已经进入正文索引的标准。

### 表格

```powershell
python scripts/standards_query.py table "标准号" "p12-t1"
```

返回 `rows`、Markdown、页码和锚点。表格抽取结果必须与原页视觉抽查一致后才能用于数值结论。

也支持 `table "标准号" "3.2.2"` 按表号查询。扫描表格只有扁平文字时返回 `quality_status=visual_required`、空 `rows` 和原页链接；该结果不能验证单元格、单位或公式，不得让模型猜测填充。

### 审计目录

```powershell
python scripts/standards_query.py catalog "NB/T 20401-2017"
python scripts/standards_query.py catalog-versions "GB/T 18314-2009"
```

当 `content_evidence_available=false` 时，只能说明元数据和缺件状态。

### 跨规范建议

```powershell
python scripts/standards_query.py advice "设计基准地震动" `
  --code "HAF 101-2023" --code "GB/T 50011-2010"
```

- `sufficient`：每个指定规范都有相关合格正文，且覆盖页质量、内容角色和状态检查通过；
- `partial`：存在命中，但相关正文缺失、质量待复核或状态未确认；
- `none`：没有直接正文证据。

`partial` 和 `none` 都不得输出完整跨规范结论。

可以解释并明确标注待复核的检索结果，给出 `[查看原页]`；不能把“拒绝最终设计结论”误解成禁止提供任何规范帮助。缺失印刷页码时只引用已确认的PDF物理页，不按页序差自行猜测。

## 失败处理

- 数据库不存在：检查包完整性和 `manifest.json`。
- `核验失败`：表示官方站点访问失败，需要重试，不代表标准不存在。
- 解析条款跨页异常：用锚点打开原 PDF 页视觉复核。
- 扫描 PDF 无文本：先按保密要求进行 OCR，再重新入库。
- 页面含图表或公式：优先打开 `links.page` 视觉复核；模型支持图片时后端仅附带少量命中页，失败自动退回文本。
- 原 PDF 不在本地目录：后端按相同相对路径逐文件查找公共盘；两处都不存在时报告 `standard_source_not_found`。
- 版本冲突：保留旧版本证据用于历史项目，但当前设计优先核对官方现行版本。
