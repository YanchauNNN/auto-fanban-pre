---
name: recommend-rebar-from-smx
description: Use when selecting reinforcement candidate IDs for structured SMX wall or slab items, including repair rounds and no-candidate cases.
---

# Recommend Rebar From SMX

Choose only from backend-supplied candidates. Never calculate reinforcement area, invent a specification, inspect an image, or read an Excel/Word/database source.

Operate only on the supplied JSON. Do not import or inspect repository modules, and do not access the network.

## Required workflow

1. Read [references/io-schema.md](references/io-schema.md) and [references/ranking-rules.md](references/ranking-rules.md) completely.
2. Verify `schema_version` is `smx-rebar-1` and preserve every `item_id` exactly once.
3. Ignore every candidate listed in `repair_context.excluded_candidate_ids`.
4. Select the eligible candidate with the smallest `priority_rank`; within that rank select the smallest unrounded `excess_area`. Use `candidate_id` only as a deterministic final tie-breaker.
5. Return `needs_review` only when no eligible candidate remains. Protocol-invalid input is not a reason to invent or select a candidate.
6. Return one plain JSON object only. Do not use Markdown fences, prose outside JSON, or extra fields.

From this Skill directory, run this local protocol check:

```text
python scripts/validate_fixtures.py --request request.json --response response.json
```

## Non-negotiable boundaries

- Treat `actual_area`, `target_area`, `priority_rank`, and `excess_area` as authoritative inputs; do not recompute or round them.
- Return only a supplied `candidate_id`; do not echo specifications, diameters, spacing, layers, or areas.
- Do not depend on repository code, project files, external services, or network access.
- Never select an excluded candidate during a repair round.
- For zero-SMX or Z-direction items, still choose only from the candidates supplied. Do not add a construction candidate yourself.
- Keep `review_reasons` empty for `selected` and non-empty for `needs_review`.
