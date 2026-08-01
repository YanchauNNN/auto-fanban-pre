---
name: reinforcement-table-normalizer
description: Use when a calculation-book task preflight has identified a non-standard reinforcement workbook and the user has confirmed AI normalization.
---

# 墙体与楼板配筋表规范化

## 适用边界

仅当计算书任务预检判定为非标准配筋表、并经用户确认后，Worker 才调用模型和本 Skill。标准表不调用，HTTP 预检不调用，也不得把普通 AI 对话当作任务规范化。

输入是后端生成的安全 workbook snapshot。模型只识别规则字段并返回一个 JSON 对象；模型不生成 Excel、不修改工作簿、不输出其他文件。当后端确定性解析器已收敛已确定行且源行严格守恒时，Worker 改用 `deterministic-audit` 模式：模型仍必须执行本 Skill，但只返回 issue patch 与 duplicate 复核行地址，禁止机械回显已确定的整表。其余情况才返回完整 schema v1。

## 硬约束

- `deterministic-audit` 模式的顶层必须是 `{"schema_version":"hybrid-1","source_row_count":N,"patch_rows":[],"review_sources":[]}`；`patch_rows` 只能与后端 issue 来源行一一守恒，`review_sources` 只能引用 duplicate 来源行。

- 非 `deterministic-audit` 模式的顶层必须是对象：`{"schema_version":"1","source_row_count":... ,"rows":[...]}`。禁止解释文字、多个代码块或 JSON 数组。
- `rows` 同时支持 `kind="wall"` 和 `kind="slab"`。`include_slab=false` 时不得杜撰 slab 行。
- 模型禁止返回、计算或解释 `actual_area`。后端确定性解析器使用精确公式产生实际配筋面积。
- 每个输出行只能是 `normalized` 或 `needs_review`。确定字段必须保留；未确定字段必须为 `null`，并在 `blank_fields` 中列出，同时填写有限、可定位的 `reason`。
- 每行必须引用 `source_sheet`、`source_row`、`source_cells`。同一个物理来源 `(source_sheet, source_row)` 只能出现一次，不能跨 kind 复制凑数。
- 行守恒是任务硬约束：完整 schema v1 必须满足 `source_row_count == len(rows)`；`deterministic-audit` 的 `source_row_count` 必须等于预检源行总数，`patch_rows` 必须与 issue 来源行逐一相等。40 个物理数据行不得静默丢行。
- 未知值不得猜测。无效 JSON、schema、来源证据、行守恒，或模型网关失败，才使规范化任务失败。

## Schema v1 完整示例

```json
{
  "schema_version": "1",
  "source_row_count": 2,
  "rows": [
    {
      "kind": "wall",
      "status": "normalized",
      "wall_id": "S7157A",
      "X": "1D36间距200",
      "Y": "1D32间距200",
      "Z": "1C14间距400*400",
      "reason": null,
      "blank_fields": [],
      "source_sheet": "墙体配筋",
      "source_row": 2,
      "source_cells": {"wall": "A2", "X": "B2", "Y": "C2", "Z": "D2"}
    },
    {
      "kind": "slab",
      "status": "needs_review",
      "elevation": "11.2",
      "top_x": "1D36间距200",
      "top_y": "1D36间距200",
      "middle_x": null,
      "middle_y": null,
      "bottom_x": "1D32间距200",
      "bottom_y": null,
      "z": "1D16间距200",
      "reason": "底层 Y 单元格无法唯一识别",
      "blank_fields": ["bottom_y"],
      "source_sheet": "楼板配筋",
      "source_row": 8,
      "source_cells": {
        "elevation": "A8",
        "top_x": "B8",
        "top_y": "C8",
        "middle_x": null,
        "middle_y": null,
        "bottom_x": "D8",
        "bottom_y": "E8",
        "z": "F8"
      }
    }
  ]
}
```

楼板 5 组字段为标高、顶层 X/Y、底层 X/Y、Z；楼板 7 组字段在此基础上增加中层 X/Y。不存在中层配筋时，`middle_x`、`middle_y` 和对应证据地址均为 `null`，这不属于 `needs_review`。

## 识别与提醒规则

- X/Y 使用 D，Z 使用 C；输入 Z 的 A→C，兼容 D/C、空格和 `@` 写法，去除 `#`。
- 括号内值是实际候选；多个可识别候选按后端规则选择，但模型不计算面积。
- `S7157A` 是独立墙号，不能合并到 `S7157`。
- duplicate 墙号保留来源值供审计，但该墙生成字段全部留空并在任务详情提醒；`-1/-2` 后缀以及配筋表与图片墙号数量不一致也作为后续人工提醒。不得因此暂停整个任务，也不得清空其他无关墙体的已确定行。
- `needs_review` 只表示当前行存在留空提醒，不阻塞其他确定值继续生成，也不要求用户先改原工作簿再重启任务。

详细规范见 [references/normalization-rules.md](references/normalization-rules.md)。
