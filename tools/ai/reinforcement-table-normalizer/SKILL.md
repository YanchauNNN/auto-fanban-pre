---
name: reinforcement-table-normalizer
description: Deterministically read and normalize wall reinforcement XLSX workbooks, including non-standard D/C/A notation, parenthetical actual values, exact reinforcement-area calculations, duplicate-wall detection, and source-cell evidence. Use when a user uploads or asks to inspect, standardize, validate, compare, or calculate a wall reinforcement table.
---

# 墙体配筋表规范化

## 工作流

1. 要求用户提供原始 `.xlsx` 配筋表。没有附件时停止，不得根据文字描述补造表格值。
2. 调用后端确定性解析器读取附件。不得让语言模型自行识别单元格、推算直径、间距或层数。
3. 逐行输出墙号、X/Y/Z 原文、规范写法、精确实际配筋面积、来源工作表、行号和单元格地址。
4. 将重复墙号和解析失败项明确列为人工确认项，不得自动消歧。
5. 仅对已成功解析的证据做解释；缺失或不支持的写法必须原样报告错误。

## 强制规则

- 墙号统一转为大写；`S7157A` 是独立墙体，不与 `S7157` 合并。
- X、Y 方向统一为 `层数D直径间距间距值`，例如 `1 22@200` → `1D22间距200`。
- Z 方向统一为 `层数C直径间距主间距*次间距`；`A` 只能作为输入兼容，输出强制改为 `C`。
- 去除输入中的 `#`。
- 单元格存在括号内配筋时，只在括号内候选中选择实际值；多个候选按未舍入实际面积取最大值。
- X/Y 精确公式：`layers * math.pi * (diameter / 2) ** 2 * (1000 / spacing)`。
- Z 精确公式：`layers * math.pi * (diameter / 2) ** 2 * (1000 / spacing_primary) * (1000 / spacing_secondary)`。
- 计算、排序和包络全程使用未舍入浮点值。只有最终面向人的展示允许按项目规则四舍五入。
- 同一墙号出现多行时保留每一行和每一个来源单元格，并强制人工确认。

## 输出要求

将后端返回的 JSON 视为唯一事实来源。回答时：

- 不修改 `actual_area` 的精确值，不用展示值反推精确值。
- 明确区分“解析成功”“需要人工确认”“解析失败”。
- 引用 `source_name`、`source_sheet`、`source_row` 和 `source_cells`，让用户能够回查。
- 不声称对未知表格格式 100% 自动正确；不支持或有歧义时阻断并交人工确认。

读取详细的业务示例和公式时，使用 [references/normalization-rules.md](references/normalization-rules.md)。
