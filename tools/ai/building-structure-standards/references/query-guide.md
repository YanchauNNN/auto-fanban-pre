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

- `sufficient`：指定规范全文齐全且检索到直接证据；
- `partial`：有部分证据，但一个或多个指定规范没有正文；
- `none`：没有直接正文证据。

`partial` 和 `none` 都不得输出完整跨规范结论。

## 失败处理

- 数据库不存在：检查包完整性和 `manifest.json`。
- `核验失败`：表示官方站点访问失败，需要重试，不代表标准不存在。
- 解析条款跨页异常：用锚点打开原 PDF 页视觉复核。
- 扫描 PDF 无文本：先按保密要求进行 OCR，再重新入库。
- 页面含图表或公式：优先打开 `links.page` 视觉复核；模型支持图片时后端仅附带少量命中页，失败自动退回文本。
- 原 PDF 不在本地目录：后端按相同相对路径逐文件查找公共盘；两处都不存在时报告 `standard_source_not_found`。
- 版本冲突：保留旧版本证据用于历史项目，但当前设计优先核对官方现行版本。
