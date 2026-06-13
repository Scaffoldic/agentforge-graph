# BUG-002: Retrieval scores render `0.00`

| Field | Value |
|---|---|
| **ID** | BUG-002 |
| **Severity** | Medium |
| **Status** | fixed |
| **Found** | 2026-06-13 (end-to-end dogfood) |
| **Fixed** | 2026-06-13 (`bug/e2e-eval-fixes`) — `LanceVectorStore.search` now queries with `distance_type("cosine")` and returns `score = max(0, 1 − distance)`, a cosine similarity in `[0,1]`. Verified: `ckg query` now shows scores like `0.52 / 0.49 / 0.44`. |
| **Area** | `store.lance_store` (score conversion) + `retrieve` (decay/render) |
| **Affects** | feat-006 (`ckg query`), feat-008 (`ckg_search` result envelope) |

## Summary

Every item in `ckg query` output shows `score=0.00`, so the ranking signal is
invisible/uninformative to the user (and to an agent reading the JSON).

## Reproduce

```
ckg index . --include "src/**/*.py" && ckg embed .
ckg query "how are incremental changes detected and re-resolved" --k 4
# → every line ends with "score=0.00"
```

## Expected vs actual

- **Expected:** a meaningful, comparable score per item (ideally a cosine
  similarity in `[0,1]`, higher = more relevant), so results are rankable and
  the agent can threshold.
- **Actual:** all items render `0.00`.

## Root cause

Two compounding issues:

1. **Negative, unnormalized vector score.** `LanceVectorStore.search`
   (`store/lance_store.py:127`) sets `score=-float(r["_distance"])` — the raw
   negative LanceDB distance. For close hits the distance magnitude is small, so
   the score is a small negative number (`-0.0x`).
2. **Decay shrinks it to zero.** Expanded items get
   `step_score = parent_score × decay × edge_weight`
   (`retrieve/scoring.py`), which drives the already-tiny magnitude toward 0;
   `ContextItem.signature()` formats `score={…:.2f}` → `0.00` / `-0.00`.

Net: the score is neither a clean similarity nor large enough to survive `:.2f`.

## Proposed fix

- In `lance_store.search`, convert distance to a **cosine similarity in `[0,1]`**
  (for cosine-normalized embeddings, `similarity = 1 - distance`; confirm the
  table's metric and clamp). Return that as `ScoredRef.score` so higher = closer
  and the value is interpretable.
- Re-check the decay so an entry hit and its 1-hop expansion stay in a readable
  range; consider rendering `:.3f` and/or keeping the original vector score on
  the entry item even after expansion.
- Add a retrieval test asserting entry-hit scores are in `(0, 1]` and ordered.

## Workaround

None user-facing; results are still *ordered* correctly — only the printed
number is uninformative.
