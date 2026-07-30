# AI 图纸模板解析规则

更新时间：2026-06-16

## 解析证据

- Office 模板结构清单：`outputs/template-understanding/office_templates.json`
- 封面 docx 嵌入工作簿清单：`outputs/template-understanding/cover_embedded_workbooks.json`
- 厂房索引图元素包：`outputs/template-understanding/factory_index_maps/drawing_elements.json`
- 厂房索引图锚点：`outputs/template-understanding/factory_index_maps/template_anchors.json`
- 规则汇总 JSON：`outputs/template-understanding/template_rules.json`

## Office 模板规则

1. 封面模板不是普通 docx 正文模板。
   6 个封面 docx 的标准正文文本节点和普通表格均为空，可写内容在
   `word/embeddings/Microsoft_Excel_Worksheet.xlsx` 的 `封面` sheet 中。
   因此 AI 层解释封面模板时，必须把嵌入 Excel 作为主结构，不能只读
   docx paragraph/table。

2. 封面写入契约以 `documents/参数规范.yaml` 的 `cover_bindings` 为准。
   通用模板与 1818 模板的落点不同：通用模板使用 `N3:S3`、`N5:P5`、
   `Q5:S5` 等区域；1818 模板使用 `M3:S3`、`M5`、`P5` 等区域。
   封面 docx 可通过 openpyxl 写嵌入工作簿，但可视预览仍需要 Word/Office
   自动化刷新 OLE。

3. 目录模板是 A-I 列的 Excel 模板。
   明细从第 9 行开始，行顺序固定为封面、目录、图纸；图纸行按内部编码尾号排序。
   1818 目录存在中英文标题合并展示规则，必须继续使用 `catalog_bindings`。

4. 设计文件模板从第 2 行写入 A-Z 列。
   行顺序固定为封面、目录、图纸；全局字段来自任务包参数，图纸字段来自图签识别结果。

5. IED 模板使用 `IED导入模板 (修改)` sheet，从第 2 行写入 A-BW 列。
   IED 计划字段来自 Web 表单或导入 Excel；图纸信息仍必须来自 DWG/DXF 读取流程。

## 厂房索引图规则

1. 本轮解析了 `documents_bin/factory_index_maps` 下 8 张 DWG，全部成功转换并生成元素包。
   这些模板不是标准图框图纸，`frame_count = 0` 是符合预期的结果，不应当作为解析失败。

2. 厂房索引图不走通用图框/图签理解规则。
   规则应以罗盘圆、角度文本、模板边界框作为几何锚点，并按现有
   `FactoryIndexMapTemplate.from_dxf` 的锚点结果解释替换行为。

3. 模板选择规则来自 `documents/参数规范_运行期.yaml`：
   1818、1907、1915、2026 按项目号直接选择模板；1916 按 3/4 号岛选择；
   2016 按 1/2 号岛选择。

4. 岛号/机组号区分文本：
   2016-1 需要出现 `QF`，2016-2 禁止出现 `QF`；
   1916-3 需要出现 `KP`，1916-4 禁止出现 `KP`。
   本轮元素包中观察到的文字与该规则一致。

5. 锚点缺口：
   1818 与 1915 模板提取到了罗盘圆，但角度文本为空。后续如果用这两类模板做替换或问答，
   AI 助手需要明确标记“角度锚点缺失”，并优先引用罗盘与边界框证据。

## AI 助手使用规则

1. 回答模板结构问题时，必须引用元素包、模板规则 JSON 或 YAML 参数，不允许只凭模型记忆回答。
2. Office 模板以 YAML 绑定为写入契约，以模板解析结果作为核验依据。
3. 厂房索引图以专用 factory-index 锚点规则理解，不使用普通 titleblock frame 规则。
4. 转换、扫描、解析失败必须作为失败报告，不得解释为空模板或零结果。
5. 模型不得直接修改 DWG、模板或 YAML；只能输出建议、证据和待人工确认的规则变更。
