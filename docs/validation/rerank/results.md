# ENH-013 — cross-encoder rerank measurement results

**Date:** 2026-06-20 · **Reranker:** AWS Bedrock `cohere.rerank-v3-5:0`
(us-east-1) · **Embedder (base path):** Bedrock `cohere.embed-v4:0`, dim 1024 ·
**Harness:** [`scripts/rerank_eval.py`](../../../scripts/rerank_eval.py)

## Method

Two independent corpora, each with a hand-labelled golden set (NL query → the
source file whose chunk/symbol a human judges relevant), matched on a node-id
path substring:

- `agentforge-graph` (this repo) — 24 queries — [golden](agentforge-graph.yaml)
- `pallets/click` (external) — 20 queries — [golden](click.yaml)

Per query we retrieve **one** candidate pool (vector top-20 + graph expansion),
then compare the **base** order (cosine + graph score) against a
**Bedrock-reranked** order at blend weights `w ∈ {0.3, 0.5, 0.7}`
(`final = (1-w)·base + w·relevance`). One Bedrock Rerank call per query; the
weights re-blend the same relevance scores. Metrics: recall@k (hit-rate, k∈{5,8,16}),
MRR, nDCG@8.

## Numbers

### agentforge-graph (24 queries) — ~525 ms/query rerank latency

| config | recall@5 | recall@8 | recall@16 | MRR | nDCG@8 |
|---|---|---|---|---|---|
| base | 0.917 | 0.958 | 1.000 | 0.799 | **0.625** |
| bedrock w=0.3 | **0.958** | 0.958 | 1.000 | **0.883** | 0.609 |
| bedrock w=0.5 | 0.917 | 0.958 | 1.000 | 0.842 | 0.563 |
| bedrock w=0.7 | 0.917 | 0.917 | 1.000 | 0.810 | 0.524 |

### pallets/click (20 queries) — ~554 ms/query rerank latency

| config | recall@5 | recall@8 | recall@16 | MRR | nDCG@8 |
|---|---|---|---|---|---|
| base | 1.000 | 1.000 | 1.000 | 0.812 | 0.618 |
| bedrock w=0.3 | 1.000 | 1.000 | 1.000 | **0.942** | **0.681** |
| bedrock w=0.5 | 1.000 | 1.000 | 1.000 | 0.925 | 0.673 |
| bedrock w=0.7 | 1.000 | 1.000 | 1.000 | 0.917 | 0.662 |

## Findings

1. **Base retrieval already saturates recall** on both corpora (recall@16 = 1.0,
   recall@5 ≥ 0.92). The relevant file is virtually always *in* the recalled
   pool — so the reranker's job is **ordering**, not finding.
2. **Reranking improves ordering, and `w = 0.3` is the consistent optimum.** MRR
   rises **+10.5%** (agentforge-graph) and **+16%** (click); nDCG@8 +10% on click.
   Higher weights help less or regress (over-trusting the reranker over a strong
   base signal). On click every weight beats base; on the (easier, self-labelled)
   agentforge-graph corpus only `w = 0.3` clearly wins.
3. **Cost: ~+540 ms/query** plus a Bedrock Rerank API call.

## Decision

**Keep cross-encoder rerank opt-in (default `rerank: off`).** The precision lift
is real and consistent, but it is an *ordering* gain on a pool that already
contains the answer, bought at ~540 ms/query — too high a tax to impose on every
retrieval by default. Enable it where **top-1–3 precision** matters (agent reads,
"jump to the answer" UX), not for broad recall.

**Recommended opt-in config (now torch-free — uses the same Bedrock creds as the
embedder):**

```yaml
retrieve:
  rerank: cross_encoder
  rerank_model: bedrock:cohere.rerank-v3-5:0   # ENH-013 Bedrock Rerank, no torch
  rerank_weight: 0.3                            # measured optimum
```

The local sentence-transformers path (`rerank` extra) and the dependency-free
`lexical` mode remain available for non-AWS / offline use.

## Reproduce

```bash
ckg index <repo> --embed                  # Bedrock embed (cohere.embed-v4:0)
uv run python scripts/rerank_eval.py --repo <repo> --golden docs/validation/rerank/<set>.yaml
```
