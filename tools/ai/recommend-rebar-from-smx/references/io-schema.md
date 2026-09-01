# SMX rebar protocol

## Input

Accept one JSON object with this shape:

```json
{
  "schema_version": "smx-rebar-1",
  "task_id": "job-123",
  "items": [
    {
      "item_id": "N5001:Y",
      "member_kind": "wall",
      "member_id": "N5001",
      "direction": "Y",
      "smx": 4756.0,
      "target_area": 5231.6,
      "candidates": [
        {
          "candidate_id": "linear-l1-d40-s200",
          "spec": "1D40间距200",
          "actual_area": 6283.185307,
          "priority_rank": 1,
          "excess_area": 1051.585307
        }
      ],
      "repair_context": null
    }
  ]
}
```

`repair_context`, when present, contains `round`, `excluded_candidate_ids`, and prior `errors`. Never select an excluded ID. The current `candidates` list is the only allowed selection space.

## Output

Return exactly one plain JSON object. Preserve the input `item_id` set exactly; do not add `task_id`.

Selected item:

```json
{
  "item_id": "N5001:Y",
  "status": "selected",
  "selected_candidate_id": "linear-l1-d40-s200",
  "reason": "选择最高优先级内超额最小的候选",
  "review_reasons": []
}
```

Review item:

```json
{
  "item_id": "N5002:Z",
  "status": "needs_review",
  "reason": "没有可用候选",
  "review_reasons": ["候选列表为空或均不满足目标面积"]
}
```

The top-level output is always:

```json
{
  "schema_version": "smx-rebar-1",
  "items": []
}
```

Insert one selected or review object per input item into `items`.

## Text safety limits

- Strip surrounding whitespace from `reason` and every `review_reasons` entry.
- Keep `reason` at 500 characters or fewer.
- Keep each review reason at 300 characters or fewer.
- Return no more than 20 review reasons, with a combined length of at most 2000 characters.
- Do not include control characters, line breaks, tabs, zero-width format controls, or other Unicode control/format characters.

## Strict exclusions

- Do not return Markdown fences or text before/after JSON.
- Do not return `task_id`, `selections`, `candidate_id`, `spec`, `actual_area`, `diameter`, `spacing`, `layers`, `reason_code`, or any other extra field.
- Do not use `unresolved`; the only statuses are `selected` and `needs_review`.
- Do not omit, duplicate, or invent an `item_id`.
- Do not attach `selected_candidate_id` to `needs_review`.
- Do not use `needs_review` when an eligible candidate exists.
