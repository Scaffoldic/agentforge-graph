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
| **Retrieval quality** | **4/4 NL questions hit the right symbol** (live Bedrock Cohere embed-v4, 1133 chunks) — see creds-run below | ✅ strong |
| **Enrichment — summaries** | live Claude (Haiku): accurate, symbol-grounded, **honestly hedges** when no symbols are visible (no hallucination) | ✅ good |
| **Enrichment — pattern tags** | 34 candidates → 34 judged → **0 tagged**: judge correctly rejects name-based false candidates (click's `Command` ≠ GoF Command) — precise, recall question | ⚠️ precise; recall (ENH-001) |
| **MCP consumption** | tool outputs (retrieval) are strong; full unattended *agent loop* needs an Anthropic API key (the framework Agent uses the API-key provider, not Bedrock) | 🟡 tools ✅ / agent-loop pending |

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

## Creds-enabled run (2026-06-14, live AWS Bedrock)

Ran the full pipeline against real models (Cohere embed-v4 + Claude Haiku on
Bedrock). **Total cost ≈ $0.13** (embed ~free; tags $0.053; summaries $0.079).

**Embeddings** — `ckg embed`: 1133 chunks across 56 files, dim 1024, ~40s. ✅

**Retrieval** — `ckg query`, 4 natural-language questions, top hit each time:

| Question | Top result | Right? |
|---|---|---|
| "how are command line options parsed" | `Parameter._parse_decls` (core.py) | ✅ |
| "how does a command get invoked" | `BaseCommand.invoke(ctx)` (core.py) | ✅ |
| "where is terminal color and styling handled" | `style(text, fg, bg, …)` (termui.py) | ✅ |
| "how are usage errors shown to the user" | `UsageError(ClickException)` (exceptions.py) | ✅ |

Semantic search + graph context returns the architecturally correct symbol for
plain-English questions — the core agent-facing value works on a real repo.

**Enrichment — summaries** (`ckg enrich --summaries`, 71 files + repo): accurate
and symbol-grounded (e.g. *"`AliasedGroup` extends `click.Group` to resolve
abbreviated command names"*), and **honest about uncertainty** — for
symbol-less files (`setup.py`, `conf.py`) it says "not visible in the provided
symbols / likely" instead of inventing behaviour. Validates the no-hallucination
bar (KL-001). ✅

**Enrichment — pattern tags** (`ckg enrich --patterns`): 34 candidates, all
judged, **0 confirmed**. The judge declined to tag click's `Command`/`Context`
as GoF patterns (they're CLI abstractions, not the GoF Command pattern) — i.e.
**no false positives from name-based heuristics**. Good precision; whether recall
should be higher is the open question tracked by ENH-001 (pattern recall tuning).

**MCP consumption (W4)** — the tools themselves return strong results (retrieval
above is what `ckg_search` serves). A full *unattended agent loop* over MCP needs
an **Anthropic API key** (the framework `Agent` uses the API-key provider; our
creds are AWS/Bedrock, which powers embed+enrich but not the framework agent).
Run the agent dogfood from Claude Code, or set `ANTHROPIC_API_KEY`, to close W4.

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
