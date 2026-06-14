# pallets/click (Python) — validation run

First W1 validation run: a real, idiomatic mid-size Python package (a CLI
framework, src-layout, relative imports, decorators).

- **repo:** https://github.com/pallets/click @ `8.1.7` (`874ca2b`)
- **date:** 2026-06-14
- **pipeline:** index ✅ · embed ⬜ (no live embedder creds in this env) · enrich ⬜
- **command:** `ckg index /tmp/click` (default config)

## Counts

```
indexed 71 files: 1496 nodes, 1906 edges
  nodes: File=71, Class=108, Function=871, Method=389, Package=57
  edges: CALLS=292, CONTAINS=1368, IMPORTS=246
  imports: 56 in-repo resolved + 190 external
  calls:   292 resolved / 3894 unresolved
```

## Scores

| Dimension | Result | Verdict |
|---|---|---|
| **Parse coverage** | 71/71 files parsed, 0 skipped | ✅ excellent |
| **Symbol extraction** | spot-checked `Command`, `Context`, `Option`, `Group`, `BaseCommand`, `echo`, `style` — all present with correct ids/kinds | ✅ good |
| **Import resolution** | 56 → **109** in-repo after BUG-004 fix (relative `from .utils import …` was being dropped) | ✅ fixed (BUG-004) |
| **Call resolution** | 292 → **404** resolved after fix; cross-file + relative-imported now resolve | ✅ fixed (BUG-004) |
| **Impact correctness** | `impact(echo)` 1 → **19** after fix — callers now found | ✅ fixed (BUG-004) |
| **Repo-map usefulness** | public API present at budget≈4000 (`Command`/`Context`/`Option`/`Group`), but at budget≈1500 private `_compat` helpers fill the budget first | ⚠️ weak orientation → ENH-007 |
| **Routes / decisions** | none (click is a CLI lib, no web routes / no ADRs) — correctly empty | ✅ n/a |
| **Retrieval quality** | not run — `embed` defaults to Bedrock; no model creds in this env | ⬜ pending creds run |
| **Enrichment honesty** | not run — needs a live judge/summarizer | ⬜ pending creds run |
| **MCP consumption** | not run this pass (model-free graph checks only) | ⬜ pending |

## Update — after the BUG-004 fix (same commit, re-indexed)

```
indexed 71 files: 1439 nodes, 2071 edges  (was 1906)
  edges: CALLS=404, CONTAINS=1368, IMPORTS=299
  imports: 109 in-repo resolved (was 56) + 190 external
  calls:   404 resolved (was 292) / 3754 unresolved
```

| Metric | Before | After |
|---|---|---|
| in-repo imports resolved | 56 | **109** |
| resolved CALLS | 292 | **404** |
| `echo` incoming callers | 0 | **18** |
| `impact(echo)` results | 1 (itself) | **19** |

Import resolution and impact for relative-imported symbols now work; the
remaining unresolved calls are dominated by external/stdlib and
attribute/method-on-instance calls (expected, ADR-0004).

## Findings

- **[BUG-004](../bugs/BUG-004-relative-from-import-resolution.md)** ✅ **fixed
  this run** — relative `from .module import name` imports were dropped at
  extraction (the query never matched `relative_import`) and unresolved by
  `resolve_import`. Fixed both; `echo` went 0→18 callers, in-repo imports 56→109.
  High value — it's the idiomatic intra-package pattern and the graph's core
  impact-analysis value depends on it.
- **[ENH-006](../enhancements/ENH-006-cli-path-arg-consistency.md)** — the CLI
  mixes three repo-path conventions: positional `[path]` (`index`/`status`/
  `embed`/`enrich`/…), `--path` (`map`), and `--repo` (`serve-mcp`). Unify.
- **[ENH-007](../enhancements/ENH-007-repomap-public-api-orientation.md)** — the
  repo map ranks private `_`-prefixed helpers above the public API at small
  budgets; for an "orient me" tool, bias toward exported/public symbols.

## What this run validated

- **Parsing + symbol extraction are solid** on a real idiomatic package — no
  systematic misses, 100% parse coverage.
- **The graph is trustworthy where it resolves**, but **relative-import call
  resolution is the first real correctness gap** — and it's a common Python
  shape, so it matters for the production bar.

## Next

1. ✅ **BUG-004 fixed and re-measured** (this run) — imports 56→109, CALLS
   292→404, `echo` impact 1→19.
2. Re-run with **live embedder + enricher** (creds) to score retrieval and
   enrichment, and dogfood the MCP consumption path on this graph.
3. Add the next-language repos (W3 packs gate Java/Go/… first).
