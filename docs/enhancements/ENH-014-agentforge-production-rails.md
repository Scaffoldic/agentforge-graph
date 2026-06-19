# ENH-014: leverage AgentForge production rails (observability, Agent, failover)

| Field | Value |
|---|---|
| **ID** | ENH-014 |
| **Value/Impact** | Med (production maturity, ~free via the framework) |
| **Effort** | M (phased) |
| **Status** | proposed (0.4.0/0.5 candidate) |
| **Area** | `enrich`, `serve` |
| **Relates to** | feat-010/012 (enrichment), feat-008 (serve), the `agentforge-py>=0.3` bump |

## Motivation

Now that we're on `agentforge-py 0.3.x`, agentforge-graph uses only a slice of the
framework — the `Tool` ABC, MCP serving, and `BudgetPolicy`. The framework also
ships **production rails** we re-implement or skip: OpenTelemetry tracing,
cross-provider failover, and the `Agent` orchestrator. Adopting them is mostly
*config*, not code — they'd add operational maturity for the enrichment + serving
paths with little surface change.

## Analysis — candidates (from the agentforge-py survey)

1. **Observability (`agentforge-otel`)** — enrichment + retrieval emit no traces.
   Wiring the framework's OpenTelemetry seam gives per-call cost/latency/run-id
   spans (e.g. cost per edge type, cache hits) with **nothing to instrument in our
   code**. *Cheapest, highest operational value.*
2. **`FallbackChain`** — enrichment is single-provider (Anthropic **or** Bedrock).
   The framework's cross-provider failover would add resilience (rate-limit /
   outage → next provider) behind the existing `enrich.provider` config.
3. **`Agent` orchestrator** — our enrichers (`DecisionGovernsInferencer`,
   summarizer) call providers directly. Wrapping them in `Agent(model=…, tools=…)`
   would gain streaming, strategy swap, and run-id tracing — but it's the **largest**
   change and must preserve the budget rails + determinism. *Optional / lowest
   priority.*

## Proposed approach

Phased, smallest-first:

- **Phase 1 — otel** (an opt-in `[otel]` extra + a config switch; lazy, off by
  default so CI/base stay light).
- **Phase 2 — `FallbackChain`** for the enrichment provider (config: an ordered
  provider list; budget breaker unchanged).
- **Phase 3 — (optional) `Agent` wrap** of enrichment, only if Phase 1–2 prove the
  framework integration and there's a clear win.

Keep ADR-0001 (the deterministic engine never imports `agentforge`) — all of this
lives in the **framework layer** (`enrich`/`serve`), which already may import it.

## Risks

| Risk | Mitigation |
|---|---|
| Scope creep (esp. Phase 3) | Phase it; Phase 1 (otel) is independently valuable and stops there if needed |
| Must not weaken the budget ceiling or determinism | Budget breaker + scripted-provider CI path stay authoritative |
| Extra deps | Each behind an opt-in extra, lazy-imported |

## 0.4.0 candidacy

**Phase 1 (otel)** is a clean 0.4.0 candidate — small, opt-in, real value.
Phases 2–3 are better as a deliberate 0.5 effort.
