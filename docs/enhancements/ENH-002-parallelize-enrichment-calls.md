# ENH-002: Parallelize summary/judge LLM calls

| Field | Value |
|---|---|
| **ID** | ENH-002 |
| **Value/Impact** | Medium |
| **Effort** | S–M |
| **Status** | done |
| **Area** | `enrich.summary_enricher`, `enrich.enricher` |
| **Done** | 2026-06-13 (`enh/e2e-eval-enhancements`) — both enrichers run the per-item LLM calls in **concurrent batches** of `enrich.concurrency` (default 6) via `asyncio.gather`. Cost is accounted **per batch** (`budget.check()`/`commit()` outside the gather), so the shared judge/summarizer cost is read atomically — no per-call race; budget overrun is bounded to one batch; `concurrency=1` reproduces the strict per-call breaker. Bottom-up order preserved (repo summary after all file summaries); output is deterministic (results gathered in candidate order). |
| **Relates to** | feat-012 (summaries + pattern tagging) |

## Motivation

`ckg enrich --all` on this repo took **~3:14**, dominated by **80 sequential**
Bedrock Claude summary calls (the summaries cost was only $0.08 — it's latency,
not money). Each call is independent; wall-clock is ~sum of call latencies.

## Current behavior

`SummaryEnricher.enrich` (`enrich/summary_enricher.py`) loops files and `await`s
`summarizer.summarize_file` one at a time; `PatternTagEnricher.enrich`
(`enrich/enricher.py`) `await`s the judge per candidate serially. The
`BudgetMeter`/`BudgetPolicy` is checked before each call.

## Proposed change

Run the per-item LLM calls with **bounded concurrency** (e.g.
`asyncio.Semaphore(n)`, `n` from config, default ~6) while preserving:

- **Budget correctness:** reserve/commit against the shared `BudgetPolicy`
  before dispatch; stop scheduling once `remaining_usd` is exhausted (a few
  in-flight overruns are acceptable, or use `reserve()`).
- **Determinism of output** (sort results by file/id before writing).
- The bottom-up dependency: file summaries can be fully parallel; the **repo**
  summary still runs after all file summaries complete.

Expose `enrich.concurrency: int`. The Bedrock client is sync-on-thread, so
concurrency maps to the `asyncio.to_thread` pool — confirm boto3 client
thread-safety or use a small client pool.

## Acceptance criteria

- `ckg enrich` wall-clock drops roughly linearly with concurrency on a
  multi-file repo, with identical resulting graph (order-independent).
- Budget cap still honoured (a tripped budget persists partial progress; the
  rest stays dirty).

## Notes / alternatives

Keep concurrency modest to respect Bedrock throttling/quotas; surface throttle
errors as a soft stop (persist progress) rather than a crash.
