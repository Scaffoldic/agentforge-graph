# ADR-0001: Build agentforge-graph on the AgentForge framework

## Metadata

| Field | Value |
|---|---|
| **Number** | 0001 |
| **Title** | Build agentforge-graph on the AgentForge framework |
| **Status** | Accepted |
| **Date** | 2026-06-11 |
| **Deciders** | kjoshi |
| **Tags** | architecture, platform, scope |

---

## 1. Context and problem statement

agentforge-graph is a Code Knowledge Graph engine plus an agent
toolset: it indexes a repository into a typed graph and serves
queries to LLM agents. Several of its features need exactly the
machinery AgentForge already ships — LLM calls with budget caps
(ADR enrichment, summaries, pattern tagging), a `Tool` ABC and MCP
integration (the serving layer), and reranking / hybrid-search
modules (retrieval). How do we obtain that machinery: build
agentforge-graph as a standalone library that rolls its own, or as
an agent project on top of AgentForge?

## 2. Decision drivers

- Avoid re-implementing cost guardrails, run-id propagation,
  provider abstraction, and MCP wiring that AgentForge already owns.
- This workspace's whole premise is that agents are built *on*
  AgentForge; a flagship agent that bypasses it is a bad signal.
- Enrichment features (feat-010, feat-012) make real LLM calls that
  must be budget-capped and observable — exactly AgentForge's
  production rails.
- Keep the graph engine's core (parsing, storage, retrieval) free of
  framework lock-in so it stays usable as a plain library too.

## 3. Considered options

1. **Standalone library** — depend on nothing in this workspace.
2. **Agent project on AgentForge** — scaffold via agentforge-py, reuse
   its Tool/Agent/MCP/reranker rails.
3. **Hybrid** — framework-independent engine core, AgentForge only at
   the LLM-using and serving edges.

## 4. Decision outcome

**Chosen: Option 3 — hybrid, scaffolded on AgentForge.** The project
is scaffolded with agentforge-py and reuses its rails wherever LLM
calls, tools, or MCP are involved (feat-006 reranker, feat-008 Tool +
MCP, feat-010/012 budgeted `Agent` calls). The deterministic engine
core — schema, tree-sitter ingestion, storage adapters, graph
retrieval — has no hard AgentForge dependency, so it remains a usable
library and is testable without a model.

### Positive consequences

- Enrichment and serving inherit budget caps, observability, and
  provider abstraction for free.
- Project gets `.claude/` state, pre-commit gate, and the test
  harness from agentforge-py scaffolding.
- Dogfoods AgentForge; cross-agent debugging skills transfer.

### Negative consequences (trade-offs)

- Couples release cadence to AgentForge for the agent-facing edges.
- Contributors must learn AgentForge's module conventions.
- Requires discipline to keep the engine core framework-independent
  (enforced by import-lint: `core`/`ingest`/`store`/`retrieve` may
  not import `agentforge`).

## 5. Pros and cons of the options

### Option A: Standalone library
- + Zero workspace coupling; smallest dependency surface.
- − Re-implements budget rails, MCP, providers — the anti-pattern
  this workspace exists to avoid.

### Option B: Agent project on AgentForge (fully)
- + Maximum reuse.
- − Forces a model dependency into the deterministic core; harder to
  use the graph engine as a plain library.

### Option C: Hybrid
- + Reuse at the edges, clean core, library-usable.
- − Needs an enforced layering boundary.

## 6. References

- Feature specs: feat-006, feat-008, feat-010, feat-012; TRACKER
  bootstrap section.
- agentforge-py ADR-0010 (production rails), feat-004 (Tool ABC),
  feat-013 (MCP), feat-021 (reranker).
