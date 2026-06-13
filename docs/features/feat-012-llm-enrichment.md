# feat-012: LLM enrichment — summaries & design-pattern tags

## Metadata

| Field | Value |
|---|---|
| **ID** | feat-012 |
| **Title** | LLM enrichment: module summaries & design-pattern tagging |
| **Status** | proposed |
| **Owner** | kjoshi |
| **Created** | 2026-06-11 |
| **Target version** | 0.4.0 |
| **Languages** | python |
| **Module package(s)** | `agentforge_graph.enrich` |
| **Depends on** | feat-006 |
| **Blocks** | none |

---

## 1. Why this feature

Differentiator #3, and the layer that turns a *code* graph into a
*knowledge* graph. Parsed facts answer "what is connected"; they
cannot answer "what is this subsystem *for*" or "this class is the
Repository for orders — change it accordingly". The survey found
design-pattern tagging absent from every tool (§3.3), and prose
summaries only as GraphRAG's community-summary idea — never
incremental, never provenance-tracked. We have the substrate they
lacked: a typed graph (what to summarize, in dependency order),
dirty tracking (what to re-summarize), and provenance (how to keep
LLM output honestly second-class).

## 2. Why it must ship in the agent core

- **Enrichment without provenance discipline poisons the graph.**
  `Summary` nodes and `TAGGED` edges must carry `source="llm"`,
  model, prompt version, and confidence — enforced by the core
  `Enricher` harness (feat-001), not by convention.
- **Incremental economics.** Summaries are the most expensive
  artifact per token; recomputing only dirty subtrees (feat-004
  `DirtySet`) is the difference between dollars-once and
  dollars-per-commit. Only the core pipeline sees dirtiness.
- **Budget rails.** Enrichment runs through AgentForge `Agent` calls
  with `budget_usd` caps — a runaway summarizer on a monorepo must
  trip a breaker, not a credit card.

## 3. How consumers benefit

- feat-007's repo map gains a one-line `[llm]` summary per top
  module: orientation reads like a guided tour, not a symbol dump.
- `ckg_explain <symbol>` (tool reserved in feat-008) answers "what
  is this and what role does it play" from stored, cached knowledge
  — milliseconds and zero marginal cost after the enrichment run.
- Pattern tags make intent queryable: "show me all Repositories",
  "is there already a Factory for clients?" — the
  duplicate-implementation question every agent should ask and none
  can today.

## 4. Feature specifications

### 4.1 User-facing experience

```bash
ckg enrich --summaries --budget-usd 5     # explicit, budgeted, resumable
ckg enrich --patterns  --budget-usd 2
```

```python
expl = await graph.explain("…orders/repo.py OrderRepo#")
# stored Summary + tags + parsed facts, single pack
repos = await graph.tagged("Repository", min_confidence=0.8)
```

### 4.2 Public API / contract

**`Summary` nodes** (kind reserved in feat-001): attrs `text`
(≤120 words), `level` (`symbol|file|package|repo`), `model`,
`prompt_version`. Edge `SUMMARIZES → target`. Embedded into the
vector store (`source_type: summary`) so NL queries can land on a
*concept* and expand to its code — the GraphRAG move.

**`TAGGED` edges** Class/Function → `PatternTag` taxonomy node:
fixed v1 taxonomy (GoF core + architectural roles):
`Singleton, Factory, Builder, Adapter, Facade, Observer, Strategy,
Decorator, Repository, Service, Controller, DTO, ValueObject`.
Attrs: `confidence`, `rationale` (one sentence).

```python
class SummaryEnricher(Enricher):      # feat-001 ABC
    """Bottom-up: file summaries from code+docstrings; package
    summaries from child summaries; repo summary from packages."""

class PatternTagEnricher(Enricher):
    """Candidate filtering (structural heuristics) → LLM judge
    per candidate → TAGGED edges above confidence floor."""
```

### 4.3 Internal mechanics

- **Bottom-up summarization** walks `CONTAINS` leaves-first so each
  level's prompt is built from the level below (bounded context per
  call, no whole-file-tree prompts). Per-call inputs: signatures,
  docstrings, child summaries, top inbound/outbound edges.
- **Pattern tagging is two-stage to control cost:** stage 1 cheap
  structural heuristics nominate candidates (e.g. `Repository`:
  class with CRUD-shaped methods + DataModel references; `Factory`:
  returns-new-instances signature shape); stage 2 an LLM judge
  confirms/rejects with rationale. Heuristics-only and LLM-only are
  both worse (research on detector precision is clear); the
  combination keeps judge calls ~1–5% of classes.
- **Staleness & resume:** enrichers drain
  `DirtySet(consumer="summaries"|"patterns")`; a budget-tripped run
  resumes where it stopped (DirtySet is the work queue). Prompt
  version bump marks all output stale.
- **Honesty surfaces everywhere:** retrieval renders summaries/tags
  with `[llm]` markers; `include_llm_facts=False` excludes them
  wholesale (feat-006 contract); confidence floors configurable.

### 4.4 Module packaging

`agentforge_graph.enrich` — default install; *never runs
implicitly* (explicit `ckg enrich` / `graph.enrich()` only).

### 4.5 Configuration

```yaml
enrich:
  model: anthropic:claude-haiku-4-5     # cheap tier default
  summaries: {levels: [file, package, repo], max_words: 120}
  patterns:  {taxonomy: v1, confidence_floor: 0.7}
  budget_usd: 5.0
```

## 6. Cross-language parity

n/a.

## 7. Test strategy

- Unit: bottom-up ordering (child before parent), resume-from-
  DirtySet, budget breaker trips and persists partial progress,
  prompt-version staleness.
- Heuristics: precision/recall of stage-1 candidates on a labeled
  fixture repo (patterns hand-annotated).
- Live (env-gated): end-to-end enrich on fixture repo under budget;
  judge agreement with labels above floor; every output carries
  `llm` provenance + model + prompt_version.
- Integration: `explain` pack composition; tagged query respects
  confidence floor.

## 8. Risks & open questions

| Risk / Question | Mitigation / Decision |
|---|---|
| Hallucinated tags/summaries mislead downstream agents | Provenance + confidence + rationale + opt-out; judge prompt requires citing structural evidence; floor at 0.7 |
| Summary drift vs code (stale prose) | DirtySet-driven refresh; staleness flag rendered when target churned since summary (feat-009 signal) |
| Taxonomy debates (what counts as a pattern) | Fixed v1 list, extensible post-1.0 via config; tags are cheap to regenerate |
| Cost on large repos despite incrementality | Cheap-tier model default, explicit budgets, levels configurable (file-only is fine), resumable runs |

## 9. Out of scope

- Anti-pattern / code-smell detection (linter territory; different
  precision bar).
- Auto-generated documentation sites from summaries.
- Enrichment write-back from *external* agents (feat-008 read-only
  rule; needs authz design post-1.0).

## 10. References

- Research §3.3 (pattern gap), §5 items 13 & 15; GraphRAG
  community-summary prior art (§5).
- agentforge-py feat-001/007 (Agent + budget rails consumed here).
- feat-004 (DirtySet), feat-006 (`include_llm_facts`), feat-007
  (map summaries), feat-008 (`ckg_explain`), feat-009 (staleness
  signal).

---

## Implementation status

**MVP shipped** (branch `feat/012-llm-enrichment`) — **design-pattern tagging**.
New framework-layer package `agentforge_graph.enrich`: a fixed v1 `PatternTag`
taxonomy, deterministic stage-1 structural `PatternHeuristics`, an injectable
`PatternJudge` (`ScriptedJudge` for tests, **`BedrockClaudeJudge`** live — the
first feature to call an LLM), and a budgeted, resumable `PatternTagEnricher`.

Confirmed verdicts ≥ `confidence_floor` become `PatternTag` nodes + `TAGGED`
edges with honest `llm` provenance + confidence + rationale. The judge loop runs
under the framework `BudgetPolicy` (`BudgetExceeded` breaker), drains
`DirtySet("patterns")` (resumable), and re-tags idempotently via a new
`GraphStore.clear_outgoing(src_ids, kind)` primitive. Retrieval: `TAGGED` added
to the default `context` expansion (a retrieved class surfaces its pattern;
`include_llm_facts=False` excludes). Surfaces: `CodeGraph.enrich()`/`tagged()`,
`ckg enrich --patterns --budget-usd`, `ckg tagged <pattern>`, and the reserved
`ckg_explain` MCP tool (symbol → tags + facts; now in `ALL_TOOLS` — 9 tools).
`EnrichConfig` (Bedrock Claude Haiku 4.5 default).

**Anthropic runs on AWS Bedrock** (same credential path as the Cohere embedder).
**Live-verified** end-to-end: Repository (0.95) and Factory (0.85) confirmed, a
name-only Service *rejected* (0.20, dropped by the 0.7 floor) — the precision
the two-stage design buys; ~$0.005 for 3 judgments. Deterministic tests use the
`ScriptedJudge` (no model in CI); live tests gated by `CKG_LIVE_AGENT`. ≥97%
package coverage; `mypy --strict` + ruff clean. Design:
`docs/design/design-012-llm-enrichment.md`.

### Summaries (also shipped)

`SummaryEnricher` (`docs/design/design-012b-summaries.md`): bottom-up **file**
summaries (from a file's signatures + imports) + one **repo** summary
synthesised from them. Injectable `Summarizer` (`ScriptedSummarizer` for CI,
`BedrockClaudeSummarizer` live, sharing a `BedrockClient` with the judge).
`Summary` nodes + `SUMMARIZES` edges (`llm` provenance), **embedded**
(`source_type="summary"`) so a concept query lands on a summary and expands to
the code via `SUMMARIZES` (in the default `context` expansion). Budgeted +
`DirtySet("summaries")`; idempotent by MERGE-node + create-edge-if-missing (no
edge churn — sidesteps a Kuzu forward-rel-scan staleness bug, see
docs/framework). Surfaces: `CodeGraph.summarize()`/`summaries()`,
`ckg enrich --summaries|--all`, `ckg summaries`, a one-line file summary in the
repo map, and the summary in `ckg_explain`. Live-verified on Bedrock Claude.

### Follow-ups
- Per-package (directory) + per-symbol summary tiers.
- Heuristic precision tuning; taxonomy config-extension; staleness rendering
  (feat-009 signal).
