# ENH-009: sharpen retrieval precision on dense / comment-sparse codebases

| Field | Value |
|---|---|
| **ID** | ENH-009 |
| **Value/Impact** | High (retrieval is the core agent-facing surface) |
| **Effort** | M |
| **Status** | **partial** (2026-06-17) — seam + lexical + **cross-encoder adapter** all landed (opt-in); the default-on flip still gated on a measurement campaign (needs the `rerank` extra / torch, not runnable in CI) |
| **Area** | `retrieve` (rerank / chunking / embedding inputs) |
| **Relates to** | feat-006 (retrieval), feat-005 (chunking/embeddings), feat-012 (summaries) |

## Motivation

Two creds-enabled validation runs (2026-06-15) showed a consistent pattern:
semantic retrieval returns **topically-correct** code every time, but is
**surgical** (top hit *is* the canonical symbol) only on well-scoped questions
against well-structured files.

- **zod** (`typescript-zod.md`): 1/4 exact (`ZodObject._parse`), 3/4 adjacent.
  zod concentrates most of its surface in one ~2800-line `types.ts` plus locale
  files, so chunk-level search lands *near* the answer.
- **express** (`javascript-express-chalk.md`): 2/4 exact (routing, `res.send`),
  2/4 adjacent. express is terse, comment-sparse, prototype/factory-style — top
  cosine scores only **0.36–0.52**, so there's little prose for the embedder to
  key on.
- **click** (`python-click.md`), by contrast, scored **4/4** — a smaller,
  conventionally-structured, well-documented codebase.

So precision degrades predictably on (a) mega-files where one chunk can't isolate
a symbol and (b) low-comment code where the embedding signal is thin. This isn't a
correctness bug — the context returned is useful — but for an "ask a question, get
the right symbol" tool it's the gap between *fair* and *sharp*.

## Current behavior

- Retrieval is vector hit → graph expansion (feat-006/ADR-0008). `retrieve.rerank`
  is **`off`** at 0.1 (a reranker seam exists but ships disabled).
- Chunks are AST-span based (feat-005). The embedded text is the raw source span;
  it does **not** include the symbol's signature/qualified-name or its
  summary as a prefix.
- Ranking is pure cosine over chunk embeddings (+ provenance-weighted graph
  scoring), with no symbol-name / signature boost for query terms that name a
  symbol.

## Proposed change (menu — measure, don't ship all)

1. **Turn on + tune the reranker** (`retrieve.rerank`) — a cross-encoder rerank of
   the top-k chunks against the query is the highest-leverage lever for "near →
   on". Already has a config seam and a reranker ref (feat-006).
2. **Summary-augmented embedding inputs** — prepend the symbol's signature
   (and, when present, its feat-012 file/symbol summary) to the chunk text before
   embedding, so dense/sparse code gets a prose handle. Re-embed cost only.
3. **Symbol-anchored retrieval mode** — when the query contains an identifier that
   matches a symbol name, blend an exact/fuzzy symbol-name match into the score
   (cheap, deterministic, helps "where is `res.send`"-style questions).
4. **Finer chunking for mega-files** — cap chunk span so a 200-line method isn't
   one opaque chunk; align chunk boundaries to symbol sub-spans.

## Acceptance criteria

- On the seeded questions for zod + express, exact-hit rate improves over the
  2026-06-15 baseline (zod 1/4, express 2/4) without regressing click (4/4).
- The change is config-gated and measured per-repo in the validation docs (not a
  blind default flip).
- No new always-on cost unless it demonstrably moves hit-rate (re-embedding /
  rerank latency called out).

## Progress (2026-06-15) — lever #3 (lexical) landed opt-in; measured

Shipped the **reranker as a real seam** (it was a `NoopReranker` stub): a
deterministic, dependency-free **lexical reranker** (`retrieve.rerank: lexical`,
`rerank_weight`) that blends cosine with query↔candidate **subtoken overlap**
(camelCase/snake split, so `ZodObject._parse` → {zod, object, parse}). Config
resolution wired through `CodeGraph.retrieve`; unit-tested + deterministic.

**Measured it (creds run, off vs lexical@0.5, the seeded questions):**

| Repo | Effect |
|---|---|
| **click** | neutral-to-worse — baseline was ~4/4 (`style`/`invoke`/`UsageError` exact); lexical **regressed** Q3/Q4 (a comment/empty chunk outranked `style`/`UsageError`) |
| **zod** | mixed — Q1 stayed exact (`ZodObject._parse`); Q3 **regressed** to a `*.test.ts` chunk (test body shared query tokens); Q4 arguably better (`handleResults`) |
| **express** | mixed — some queries surfaced a header comment / `File` node instead of code |

**Conclusion:** lexical overlap over chunk *bodies* is too crude — test files,
license/header comments, and `File` nodes that happen to share query tokens get
over-boosted, and the Cohere `embed-v4` baseline is **already strong** on these NL
questions, leaving little upside and real downside. A signature-scoped variant
(name + def line, test-file penalty, lower weight) was also tried — still mixed.

So lexical reranking ships **opt-in (`rerank` default `off`)**: genuinely useful
for **keyword / symbol-naming** queries (`res.send`, `validate_token`,
`ZodObject`), not a safe default for prose questions. **Per the ENH's own
"measure, don't blind-flip" guidance, the default is unchanged.**

## Progress (2026-06-17) — lever #1 (cross-encoder) adapter landed opt-in

Shipped the **cross-encoder reranker** (`retrieve.rerank: cross_encoder`,
`rerank_model`): a real semantic re-score via `sentence-transformers`'
`CrossEncoder` (the `rerank` extra), blended with the base score as
`final = (1-w)·base + w·σ(cross_logit)`. Design highlights:

- **Lazy-loaded model** behind a `CrossScorer` injection seam, so importing the
  module / running CI never pulls torch; the blend logic is tested with a fake
  scorer and the adapter with a stubbed `sentence_transformers`. Third-party
  only — no `agentforge` import (ADR-0001). Missing extra → a clear
  "install `--extra rerank`" error.
- **Fixed a latent bug:** the MCP `_Engine` built its `Retriever` *without* a
  reranker, so `retrieve.rerank` was silently ignored over MCP (only the
  `CodeGraph.retrieve`/CLI path honored it). Both paths now wire
  `reranker_from_config`, so `lexical`/`cross_encoder` work over the agent tool
  surface too.

Still **opt-in** (`rerank` default `off`): per the ENH's "measure, don't
blind-flip" rule, the default-on flip is gated on a precision campaign (off vs
cross_encoder on the seeded zod/express/click questions), which needs the
`rerank` extra + creds and can't run in CI — deferred to a validation run,
exactly as the lexical measurement was.

**Still open:**
- **Cross-encoder *measurement* + default-on decision** (the campaign above).
- **Summary-augmented embedding inputs** (lever #2) — prepend signature/summary to
  chunk text before embedding (re-embed cost); not yet attempted.

## Notes

Pairs with the validation campaign: this is the first *retrieval-quality* (vs
extraction) enhancement, and it's only visible because the creds runs scored
retrieval on diverse real repos. Sequence after the W1 extraction fixes (done) —
the graph must be complete before sharpening how we search it.
