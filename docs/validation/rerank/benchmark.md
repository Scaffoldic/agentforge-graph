# ENH-013 — rigorous NL→code retrieval benchmark

**Date:** 2026-06-20 · **Embedder:** Bedrock `cohere.embed-v4:0` (dim 1024) ·
**Reranker:** Bedrock `cohere.rerank-v3-5:0` · **Harness:**
[`scripts/rerank_benchmark.py`](../../../scripts/rerank_benchmark.py)

This is the rigorous follow-up to the [first directional eval](results.md): a
CodeSearchNet-style benchmark with **objective, auto-generated labels** and a
significance test, run live against real Bedrock.

## Method (why the labels are trustworthy)

- **Objective labels, no hand-authoring.** Each documented symbol's **docstring
  is the query** and that symbol is the gold answer. The pairs come straight from
  the engine's `DocChunk --DESCRIBES--> symbol` edges — hundreds per repo.
- **Leakage-free, verified.** The engine embeds code chunks *without* their
  docstrings (docstrings live in separate `DocChunk` nodes — measured 0/60 code
  chunks contained their docstring verbatim). We search the **code-chunk vectors
  only** (`filter={"kind": "Chunk"}`), so the docstring query never trivially
  matches its own doc chunk, and the retriever's doc-seeding path is bypassed.
  This isolates **pure NL-intent → code** matching — the reranker's domain.
- A candidate is **relevant** when its code chunk overlaps the gold symbol's span
  in the same file. Pool = vector top-30 code chunks. Metrics: MRR + recall@1
  over the base (cosine) order vs the Bedrock-reranked order at blend weights.
- **Significance:** paired bootstrap (2000 resamples) on the per-query
  reciprocal-rank delta → 95% CI + one-sided p. **Latency:** p50/p95 of the
  Bedrock rerank call.

## Results — 5 repos, 403 queries

p50 rerank latency **440 ms**, p95 **580 ms**.

| corpus | lang | queries | base MRR | rerank w=0.3 | recall@1 base→w0.3 |
|---|---|---|---|---|---|
| click | py | 100 | 0.954 | **0.995** | 0.920 → 0.990 |
| httpx | py | 100 | 0.906 | 0.913 | 0.840 → 0.850 |
| flask | py | 100 | 0.985 | 0.990 | 0.970 → 0.980 |
| fastapi | py | 88 | 0.966 | 0.989 | 0.932 → 0.977 |
| zod | ts | 15 | 0.225 | 0.189 | 0.133 → 0.067 |
| **pooled (all 5)** | | **403** | **0.925** | **0.942** | 0.886 → 0.916 |

**ΔMRR (rerank w=0.3 − base), paired bootstrap n=403:** mean **+0.017**,
95% CI **[+0.006, +0.028]**, one-sided **p ≈ 0.0000**.

### Python-only headline (click + httpx + flask + fastapi, 388 queries)

Excluding the noisy 15-query TS sample, over **388 NL→code queries**:

| metric | base | rerank w=0.3 |
|---|---|---|
| MRR | **0.952** | **0.971** |
| recall@1 | **0.915** | **0.948** |

**ΔMRR +0.019**, 95% CI **[+0.008, +0.031]**, one-sided **p ≈ 0.0000** (paired
bootstrap, n=388). Rerank latency p50 **436 ms** / p95 **581 ms**.

## Findings

1. **The base hybrid retrieval is already strong.** On the four Python repos,
   base MRR is **0.91–0.99** and recall@1 **0.84–0.97** — the engine puts the
   documented symbol's code at or near rank 1 from the embedding alone. That is
   the headline confidence number: *NL→code retrieval works out of the box.*
2. **Reranking is a small but statistically significant precision gain.** Pooled
   ΔMRR **+0.017 (p < 0.001)**; recall@1 **+3 points**. The lift is real and
   consistent on Python (largest on `click`: recall@1 0.92 → 0.99) but modest —
   there is little headroom over an already-strong base.
3. **Cost:** ~440 ms p50 per query for the rerank call.
4. **TypeScript is inconclusive.** `zod` yielded only 15 labels (TS/JSDoc density
   is far below Python docstrings) with 7/15 gold-in-pool; rerank regressed on
   that tiny, noisy sample. Treat TS coverage as *not yet measured*, not as
   evidence against rerank. (A doc-comment-dense TS/Go corpus is a follow-up.)

## Decision (unchanged, now evidence-backed)

**Rerank stays opt-in.** The gain is significant but small relative to the
+440 ms/query cost, and base retrieval already lands the answer at rank ≈ 1.
Enable it where **top-1 precision** is worth the latency (agent reads). The
recommended config remains the torch-free Bedrock path at `rerank_weight: 0.3`
(see [results.md](results.md) / `ckg.yaml`).

## Reproduce

```bash
for r in click httpx flask fastapi/fastapi; do ckg index /path/$r --embed; done
uv run python scripts/rerank_benchmark.py \
  --repo /path/click --repo /path/httpx --repo /path/flask --repo /path/fastapi/fastapi --cap 100
```
