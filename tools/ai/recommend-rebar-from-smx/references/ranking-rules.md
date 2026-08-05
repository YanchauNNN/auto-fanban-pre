# Candidate ranking rules

Apply these rules independently to every item and in this order:

1. Start only with candidates present in the item's `candidates` array.
2. Remove IDs listed in `repair_context.excluded_candidate_ids`.
3. Keep candidates whose `actual_area >= target_area`.
4. Find the smallest `priority_rank` among the remaining candidates.
5. Within that rank, choose the smallest unrounded `excess_area`.
6. If both values tie exactly, choose the lexicographically smallest `candidate_id` for deterministic output.
7. If no candidate remains, return `needs_review` with a concrete non-empty reason.

Do not trade priority for a smaller excess. For example, a rank-1 candidate with excess `100.0` must beat a rank-2 candidate with excess `10.0`.

Do not round before comparing. Displayed values that look equal may differ in the supplied numeric values.

Do not infer engineering data from `spec`. It is informational only. Never normalize or create a specification; reference the chosen `candidate_id` exactly.

Zero SMX does not authorize a new candidate. If the backend supplies one construction candidate, select it. If it supplies none, return `needs_review`.

During repair, an excluded candidate remains forbidden even if it would otherwise rank first. Choose the best remaining eligible candidate or return `needs_review`.
