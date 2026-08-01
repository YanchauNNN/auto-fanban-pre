# 配筋表模型识别规则

## 证据优先

模型只能使用 workbook snapshot 中的单元格值与地址。每条 `wall` 或 `slab` 行必须对应唯一物理来源 `(source_sheet, source_row)`，所有已填写字段都必须有同一行的 `source_cells` 地址；不得跨行、跨工作表或跨 kind 拼接证据。

`source_row_count` 是源物理数据行数，不是非空单元格数。输入 40 行必须返回 40 行，且 `source_row_count == len(rows)`。标题、说明和纯空行不计入业务数据行。

## 墙体规则

- `wall_id` 大写并去除说明性前后缀；`S7157A` 保持独立，不能并入 `S7157`。
- X/Y 规范为 `层数D直径间距间距值`，例如 `1 22@200`、`1D22@200` → `1D22间距200`。
- Z 规范为 `层数C直径间距主间距*次间距`。输入的 A→C；兼容 D/C，但输出 Z 只用 C。
- 去除输入末尾的 `#`。括号内值优先作为实际候选；无法唯一确定时保留可确定字段，其余为 `null` 并列入 `blank_fields`。

## 楼板规则

- 5 组楼板：`elevation`、`top_x`、`top_y`、`bottom_x`、`bottom_y`、`z`；`middle_x`、`middle_y` 为 `null`。
- 7 组楼板：在 5 组基础上增加同时存在的 `middle_x`、`middle_y`。
- 标高与各方向字段必须引用同一物理来源行。`include_slab=false` 时禁止输出任何 slab 行。

## `normalized` 与 `needs_review`

确定字段继续保留。只有无法唯一识别的字段设为 `null`，同时写入 `blank_fields` 并给出 `reason`；不得用猜测值填空。`needs_review` 是后续人工提醒，不暂停整个任务，其他确定值继续生成。

duplicate 墙号、`-1/-2` 后缀、配筋表与图片墙号数量不一致属于后续提醒，不是整任务失败条件，也不能用复制行补足数量。只有无效 JSON/schema、无效来源证据、行守恒失败或网关失败使任务失败。

## 后端计算边界

模型禁止返回 `actual_area`，不计算或解释实际配筋面积，也不生成 Excel。后端在 schema 与证据校验后解析规范字符串，并以未舍入精确公式计算：X/Y 按层数、单根截面积和 `1000/spacing`；Z 再乘 `1000/spacing_secondary`。模型的职责止于字段识别与来源证据。
