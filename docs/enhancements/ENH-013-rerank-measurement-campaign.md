# ENH-013: cross-encoder rerank measurement & default-on decision

| Field | Value |
|---|---|
| **ID** | ENH-013 |
| **Value/Impact** | High (retrieval precision is the core agent-facing surface) |
| **Effort** | M |
| **Status** | **done · 0.4.0** — measured (Bedrock Rerank); decision = stay opt-in, recommend `bedrock:cohere.rerank-v3-5:0` @ w=0.3 |
| **Area** | `retrieve` (rerank) |
| **Relates to** | ENH-009 (the rerank seam + adapter), feat-006 (retrieval) |

> **Outcome:** added a torch-free **`BedrockRerankScorer`** (Bedrock Rerank API,
> Cohere Rerank 3.5) behind the existing `CrossScorer` seam, then ran a two-corpus
> campaign ([results](../validation/rerank/results.md), harness
> `scripts/rerank_eval.py`). Base retrieval already saturates recall; the
> reranker is an **ordering** win (MRR +10–16% at w=0.3) costing ~540 ms/query —
> so the decision is **keep opt-in** and document the recommended precision config
> (`rerank: cross_encoder` + `rerank_model: bedrock:cohere.rerank-v3-5:0` +
> `rerank_weight: 0.3`).

## Motivation

ENH-009 shipped the full cross-encoder reranker: a `CrossScorer` seam, a
sentence-transformers adapter (`rerank` extra), and a blended score
(`final = (1-w)·base + w·σ(logit)`) — all **opt-in / default off**. The default-on
flip was deliberately deferred to a **measurement campaign**: we don't want to
blindly enable a heavier path without evidence it improves recall/precision. This
ENH is that campaign + the resulting decision (default, blend weight, model).

## Analysis — what's deferred and why

- The reranker can't run in CI (needs the `rerank` extra → **torch**, plus an
  embedding provider for the base path), so it was never measured at scale.
- "Measure, don't blind-flip" (ENH-009 resolution) — flipping it on by default
  without numbers risks slower retrieval for no precision gain on some repos.

## Proposed approach

1. **Build a small labelled eval set** — a handful of real OSS repos, each with a
   set of natural-language queries → the symbol(s) a human judges relevant
   (golden). Keep it in `docs/validation/` (or a gitignored harness), not the
   package.
2. **Measure base vs reranked** — `recall@k`, `MRR`, `nDCG` for k∈{5,8,16}, over
   several blend weights `w` and ≥1 cross-encoder model. Record latency delta.
3. **Decide**: default on/off, default `w`, default `rerank_model`. If on,
   ensure the lazy-load seam keeps the base/CI path torch-free.
4. Record the campaign + numbers (mirrors `.claude/state/pre-release-*.md`); update
   ENH-009 status and `ckg.yaml` defaults.

## Risks

| Risk | Mitigation |
|---|---|
| Needs torch + an embedder + creds (can't be CI-gated) | Run as a local/manual campaign; keep the default-off path CI-green regardless |
| A labelled eval set is subjective | Small but explicit golden set; report methodology; multiple repos |
| Rerank helps some repos, hurts others | The decision may be "stay opt-in with a documented when-to-enable," which is a valid outcome |

## 0.4.0 candidacy

Candidate, but **gated on resources** (torch + creds + time to label an eval
set). If those are available it's a high-value 0.4.0 item; otherwise it stays the
documented "still WAIT." Could also be folded into the broader 0.4.0 validation
pass.
