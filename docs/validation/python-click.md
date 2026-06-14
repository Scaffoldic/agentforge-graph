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
| **Import resolution** | 56 in-repo resolved — but **`utils.py` got only 1 resolved IMPORTS edge** despite `from .utils import …` in 6+ modules | ❌ **relative from-imports under-resolve** → BUG-004 |
| **Call resolution** | 292 resolved (183 same-file, 109 cross-file). Cross-file *does* work. But **`echo` (one definition, called bare 29× in src) resolves 0 callers** | ⚠️ undercount, downstream of BUG-004 |
| **Impact correctness** | `impact(echo)` returns only `echo` itself — 0 callers, though it's one of click's most-called functions | ❌ undercounts (BUG-004) |
| **Repo-map usefulness** | public API present at budget≈4000 (`Command`/`Context`/`Option`/`Group`), but at budget≈1500 private `_compat` helpers fill the budget first | ⚠️ weak orientation → ENH-007 |
| **Routes / decisions** | none (click is a CLI lib, no web routes / no ADRs) — correctly empty | ✅ n/a |
| **Retrieval quality** | not run — `embed` defaults to Bedrock; no model creds in this env | ⬜ pending creds run |
| **Enrichment honesty** | not run — needs a live judge/summarizer | ⬜ pending creds run |
| **MCP consumption** | not run this pass (model-free graph checks only) | ⬜ pending |

## Findings

- **[BUG-004](../bugs/BUG-004-relative-from-import-resolution.md)** — relative
  `from .module import name` imports under-resolve, cascading into missed
  cross-module CALLS to popular utilities (`echo`: 0/29 in-src calls resolved;
  `utils.py`: 1 resolved IMPORTS edge vs 6+ source from-imports). **High value** —
  this is the idiomatic intra-package pattern, and it directly degrades impact
  analysis, the graph's core selling point. Likely adjacent to BUG-001 (which
  fixed *absolute* src-layout imports); this is the *relative* path.
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

1. Fix **BUG-004** and re-run; expect resolved-call count and `echo` impact to
   jump. Re-measure resolution rate.
2. Re-run with **live embedder + enricher** (creds) to score retrieval and
   enrichment, and dogfood the MCP consumption path on this graph.
3. Add the next-language repos (W3 packs gate Java/Go/… first).
