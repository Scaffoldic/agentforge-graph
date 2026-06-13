# Design Doc: feat-012 LLM enrichment — design-pattern tagging (MVP)

> Per-feature design doc (design stage). Mirrors
> `docs/features/feat-012-llm-enrichment.md`. The spec says *what & why*; this
> doc says *how*, and **scopes the first PR** to pattern tagging.

---

## Metadata

| Field | Value |
|---|---|
| **Title** | feat-012 design-pattern tagging via budgeted LLM judge (MVP) |
| **Status** | accepted |
| **Owner** | kjoshi |
| **Created** | 2026-06-13 |
| **Last updated** | 2026-06-13 |
| **Related features** | feat-012 (this) · consumes feat-002/004/006 · fills feat-008's reserved `ckg_explain` · **first feature to use the AgentForge Agent + budget rails** |
| **Related ADRs** | ADR-0001 (layering), ADR-0004 (provenance), ADR-0005 (locked kinds) |

---

## 1. Context

Differentiator #3 — turning a *code* graph into a *knowledge* graph. Parsed
facts answer "what calls what"; they can't answer "this class is the Repository
for orders". Pattern tagging makes intent queryable ("show me all
Repositories", "is there already a Factory?") — the duplicate-implementation
question agents should ask and none can. `PatternTag`/`Summary` kinds and
`TAGGED`/`SUMMARIZES` edges are reserved (feat-001); feat-008 reserved
`ckg_explain`.

**This is the first feature to invoke the AgentForge `Agent`/LLM runtime.** The
API is clear: `Agent(model="anthropic:claude-haiku-4-5", budget_usd=…).run(task)
→ RunResult(output, cost_usd, finish_reason)`, or the lower-level
`LLMClient.call(system, messages, tools) → LLMResponse(content, usage,
cost_usd)`, with `BudgetPolicy` raising `BudgetExceeded`. The `enrich` package is
therefore a **framework-layer** package (may import `agentforge`, like `serve`;
ADR-0001 lists only core/ingest/store/retrieve as framework-free).

**Why pattern-tagging-first.** The spec's 0.4 target is summaries *and* tags.
Summaries need an LLM call at every node (file→package→repo) + embedding — hard
to test, expensive. **Pattern tagging is the better-scoped, better-tested
slice:** stage-1 candidate nomination is **pure structural heuristics**
(deterministic, golden-testable), and stage-2 is a *thin, budgeted* LLM judge
per candidate (~1–5% of classes). It delivers a clean differentiator and
exercises exactly the framework rails (Agent, budget, `llm` provenance,
DirtySet) that summaries will reuse. Bottom-up summaries are the follow-up.

## 2. Goals

- `agentforge_graph.enrich` (framework-layer). A **two-stage** `PatternTagEnricher`
  (`Enricher` ABC): structural heuristics nominate → LLM judge confirms →
  `TAGGED` edges to a fixed v1 `PatternTag` taxonomy.
- **The LLM is behind an injectable `PatternJudge`** (the Embedder/FakeEmbedder
  pattern): `LLMPatternJudge` wraps the AgentForge Agent/LLM (the *only* class
  importing the agent runtime); `ScriptedJudge` makes the whole enricher
  deterministic and unit-testable. Live judge tests are env-gated
  (`CKG_LIVE_AGENT`).
- **Honest provenance:** every `PatternTag` node / `TAGGED` edge carries
  `source="llm"`, `extractor="pattern-tags@<v>"`, `confidence`, and a one-line
  `rationale`. Below `confidence_floor` → dropped. Never runs implicitly
  (explicit `ckg enrich` / `graph.enrich()` only).
- **Budgeted & resumable:** the judge loop runs under a `budget_usd` cap
  (framework `BudgetPolicy`); a tripped budget persists progress and leaves the
  rest dirty. Drains `DirtySet("patterns")` so re-enrich only re-judges changed
  symbols; re-enrich is **idempotent** (clears a symbol's old `TAGGED` first).
- **Retrieval & query:** `TAGGED` added to `context` expansion (a retrieved
  class surfaces its pattern); tags are `llm`-provenance so
  `include_llm_facts=False` already excludes them. `CodeGraph.tagged(pattern,
  min_confidence)`, `CodeGraph.enrich()`, `ckg enrich --patterns`, and the
  reserved `ckg_explain` tool (symbol → tags + facts).
- ≥90% coverage (deterministic core fully tested via `ScriptedJudge`);
  `mypy --strict`; ruff.

## 3. Non-goals (explicit follow-ups)

- **Bottom-up summaries** (`Summary`/`SUMMARIZES`, embedded `source_type:
  summary`, repo-map one-liners) — the next enricher over the same harness.
- **Full `ckg_explain` prose** — MVP `ckg_explain` returns tags + parsed facts;
  the summary line is added when summaries ship.
- Anti-pattern/smell detection; auto-doc generation; external write-back.
- Live-judge precision tuning beyond a labeled-fixture sanity check.

## 4. Proposal

### 4.1 Package layout

```
src/agentforge_graph/enrich/
  __init__.py        # PatternTagEnricher, PatternJudge, ScriptedJudge, EnrichReport, TAXONOMY
  taxonomy.py        # the fixed v1 PatternTag list + PatternTag node ids
  heuristics.py      # stage-1: structural candidate nomination (framework-free, deterministic)
  judge.py           # PatternJudge Protocol + Verdict; ScriptedJudge (tests)
  llm_judge.py       # LLMPatternJudge — the ONLY module importing agentforge
  enricher.py        # PatternTagEnricher(Enricher): orchestrate stages under a budget
  report.py          # EnrichReport (candidates/judged/tagged/cost_usd/budget_tripped)
src/agentforge_graph/
  core/contracts.py      # + GraphStore.clear_outgoing(src_ids, kind)  (idempotent re-tag)
  store/kuzu_store.py    # implement clear_outgoing
  core/conformance.py    # + clear_outgoing conformance test
  config.py              # + EnrichConfig
  ingest/incremental/dirty.py  # default consumers += "patterns"
  ingest/codegraph.py    # + enrich(), tagged()
  retrieve/retriever.py  # context expansion += TAGGED
  serve/tools.py + engine.py   # + CkgExplain (ckg_explain) in ALL_TOOLS
  cli.py                 # + `ckg enrich`
tests/enrich/            # heuristics golden + enricher(ScriptedJudge) + budget/resume + live(gated)
```

### 4.2 Taxonomy & nodes (`taxonomy.py`)

Fixed v1 list (spec §4.2): `Singleton, Factory, Builder, Adapter, Facade,
Observer, Strategy, Decorator, Repository, Service, Controller, DTO,
ValueObject`. Each is a shared `PatternTag` node, id `SymbolID.for_symbol(
"pattern", repo, "<taxonomy>", f"{Name}.")` — created once via `store.add`
(MERGE-idempotent). A `TAGGED` edge goes **code symbol → PatternTag**, with
`attrs={confidence, rationale}` and `Provenance.llm("pattern-tags@<v>",
confidence)`.

### 4.3 Stage 1 — structural heuristics (`heuristics.py`, deterministic)

For each `Class`/`Function` candidate, cheap structural rules nominate zero or
more *candidate* patterns from the node + its graph neighbourhood (no LLM):

- **Repository:** a class whose methods are CRUD-shaped (`get/find/save/add/
  delete/list/update…` by name) and/or which references a `DataModel`
  (feat-011) — gathered via `adjacent(class, [CONTAINS], "out")` → method
  `attrs["signature"]`.
- **Factory:** methods named `create*/make*/build*/new*` whose signature shape
  returns a constructed instance.
- **Service / Controller:** name/suffix (`*Service`, `*Controller`) + method
  shape; Controller boosted if the class owns a `Route` (`HANDLED_BY`, feat-011).
- **Singleton:** `_instance` class attr / `get_instance` classmethod shape.
- **DTO / ValueObject:** data-only class (fields, no behaviour methods).
- (others heuristic-nominated conservatively; recall over precision at stage 1).

Output: `list[Candidate]` = `(symbol_id, [pattern], evidence: list[str])`. The
evidence strings are fed to the judge so it must cite structure (spec §8). This
module is **framework-free and golden-tested** (precision/recall on a labeled
fixture).

### 4.4 Stage 2 — the budgeted judge (`judge.py`, `llm_judge.py`, `enricher.py`)

```python
class Verdict(BaseModel):
    pattern: str
    is_match: bool
    confidence: float          # 0..1
    rationale: str             # one sentence, must cite structural evidence

class PatternJudge(Protocol):
    async def judge(self, candidate: Candidate, ctx: SymbolContext) -> list[Verdict]: ...
    @property
    def cost_usd(self) -> float: ...     # accumulated spend (0 for ScriptedJudge)
```

- **`LLMPatternJudge`** (the only `agentforge` importer): builds one prompt per
  candidate — the symbol's signature, its methods' signatures, the heuristic
  evidence, and the nominated pattern(s) — and asks for a structured `Verdict`
  per nominated pattern (JSON via the provider's tool/json mode). Resolves the
  configured model (`enrich.model`, default `anthropic:claude-haiku-4-5`) the
  same way `Agent` does; records `cost_usd`/tokens from each `LLMResponse`.
- **`ScriptedJudge`** (tests): returns canned verdicts by `(symbol, pattern)`;
  `cost_usd == 0`. Lets the whole enricher be exercised deterministically.

**`PatternTagEnricher(Enricher).enrich(store)`** orchestration:

1. Determine the candidate set: `DirtySet(root, "patterns").dirty_for("patterns")`
   if non-empty (incremental), else all `Class`/`Function` nodes (cold/full).
2. Stage-1 heuristics nominate; symbols with no nomination are skipped (and
   marked clean — nothing to judge).
3. For each nominated candidate, **budget-gate then judge**: a `BudgetMeter`
   wrapping the framework `BudgetPolicy(usd=budget_usd)` — `check()` before,
   `commit(judge.cost_usd_delta)` after. On `BudgetExceeded`, stop: persist what
   we have, leave the unjudged candidates dirty (resumable), set
   `report.budget_tripped`.
4. Build facts: for confirmed verdicts ≥ `confidence_floor`, a `PatternTag`
   node (MERGE) + a `TAGGED` edge (`llm`, confidence, rationale). **Idempotent
   re-tag:** `store.clear_outgoing(judged_ids, TAGGED)` before adding, so a
   re-run replaces rather than duplicates.
5. `mark_clean("patterns", judged_ids)`.

Returns `EnrichReport(candidates, judged, tagged, cost_usd, budget_tripped)`.
Persistence is the caller's `store.add` (the `Enricher` contract), plus the
`clear_outgoing` call the enricher makes directly.

### 4.5 The `clear_outgoing` store primitive

```python
# GraphStore (contracts.py)
async def clear_outgoing(self, src_ids: list[str], kind: EdgeKind) -> None:
    """Delete edges of `kind` whose src is in `src_ids` — lets an enricher
    re-derive a symbol's facts idempotently (re-tag without duplicates)."""
```

Kuzu: `MATCH (a:CkgNode)-[e:CkgEdge]->() WHERE a.id IN $ids AND e.kind = $kind
DELETE e`. Implemented for Kuzu + the in-memory reference; conformance test
added. (Mirrors `clear_resolved`; reused by the summaries enricher later for
`SUMMARIZES`.)

### 4.6 Retrieval, surfaces, config

- **Retriever:** add `TAGGED` to `context` mode's edge list (direction `both`),
  so a retrieved class surfaces its pattern tags. Tags are `Source.LLM`, so the
  existing `include_llm_facts=False` filter already excludes them wholesale
  (feat-006 contract) — no new filter.
- **`CodeGraph.enrich(patterns=True, budget_usd=None) -> EnrichReport`** and
  **`CodeGraph.tagged(pattern, min_confidence=0.7) -> list[TaggedInfo]`** (symbols
  carrying a pattern above the floor).
- **CLI:** `ckg enrich --patterns [--budget-usd N]` → prints the report;
  `ckg tagged <pattern> [--min-confidence]` (or fold listing into `enrich`).
- **MCP:** `CkgExplain` (`ckg_explain`, `ExplainInput{symbol_id}`) → the symbol's
  pattern tags (with confidence/rationale) + its 1-hop parsed facts; added to
  `ALL_TOOLS`. (Summary line added when summaries ship.)
- **`EnrichConfig`** (`KEY="enrich"`): `model: str = "anthropic:claude-haiku-4-5"`,
  `budget_usd: float = 2.0`, `confidence_floor: float = 0.7`, `taxonomy:
  str = "v1"`, `enabled: bool = True`.

### 4.7 Provenance & honesty

`PatternTag` nodes / `TAGGED` edges: `source="llm"`, `extractor="pattern-tags@
<prompt_version>"`, `confidence` from the judge, `rationale` in edge attrs. A
`prompt_version` bump (in the extractor string) means old tags differ → a
`--full` enrich re-tags. Confirmed by the `Provenance` validator (confidence<1.0
only valid for `llm`).

## 5. Alternatives considered

| Option | Why not |
|---|---|
| Summaries first | Every node needs an LLM call + embedding; hard to test, expensive. Pattern tagging is mostly deterministic heuristics with a thin judge — better first slice. |
| Call the framework `Agent`/LLM directly in the enricher | Couples the whole enricher (and its tests) to a live model. The injectable `PatternJudge` isolates the agent to one class and makes the orchestration/budget/heuristics fully unit-testable (Embedder/FakeEmbedder precedent). |
| Heuristics-only (no LLM) | Low precision; "is this *really* a Repository" needs judgment. |
| LLM-only (judge every class) | Cost: judging every class is 20–100× the two-stage cost; heuristics cut judge calls to ~1–5%. |
| Re-tag via `store.add` only | `add` CREATEs edges → duplicates on re-enrich. `clear_outgoing` + add = idempotent. |
| Per-candidate `Agent` with its own budget | One shared `BudgetMeter` across candidates gives true per-run cost control + resumability; per-agent budgets can't. |

## 6. Migration / rollout

Additive: new framework-layer package, new optional `enrich:` config, kinds
reserved (no schema bump). Never runs implicitly — `ckg enrich` only. No model
calls in CI: deterministic tests use `ScriptedJudge`; live tests are
`CKG_LIVE_AGENT`-gated (the existing gate, needs `ANTHROPIC_API_KEY`). Retrieval
gains `TAGGED` expansion — strictly additive (no tags → no new items;
`include_llm_facts=False` hides them). `DirtySet` default consumers gain
`"patterns"` (a json-list addition; harmless when enrich is unused).

## 7. Risks

| Risk | Mitigation |
|---|---|
| Hallucinated tags mislead agents | `llm` provenance + confidence floor (0.7) + rationale citing structure + `include_llm_facts=False` opt-out; judge prompt requires evidence. |
| Cost blowup on a monorepo | Two-stage (judge ~1–5% of classes) + cheap-tier default + `budget_usd` breaker (framework `BudgetPolicy`) + resumable. |
| Re-enrich duplicates tags | `clear_outgoing(ids, TAGGED)` before re-add → idempotent. |
| Stale tags after code edit | DirtySet("patterns") re-dirties changed symbols; a vanished symbol's `TAGGED` is DETACH-DELETEd with it. |
| Framework Agent API surprises | Isolated to `LLMPatternJudge`; everything else tested with `ScriptedJudge`; any framework friction logged to `docs/framework/`. |
| Taxonomy debates | Fixed v1 list, config-extensible later; tags cheap to regenerate. |

## 8. Open questions (decisions for review)

1. **Scope the first PR to pattern tagging** (defer bottom-up summaries + full
   `ckg_explain` prose)? Proposed: **yes**.
2. **Injectable `PatternJudge`** (LLM isolated to one adapter; deterministic core
   + `ScriptedJudge`; live tests `CKG_LIVE_AGENT`-gated)? Proposed: **yes**.
3. **Two-stage heuristics→judge** to control cost? Proposed: **yes**.
4. **Budget via framework `BudgetPolicy`, resumable via `DirtySet`,
   idempotent re-tag via new `clear_outgoing`**? Proposed: **yes**.
5. **`TAGGED` in default context expansion + `ckg_explain` (tags+facts) +
   `CodeGraph.tagged()`/`enrich()` + `ckg enrich` CLI** this PR? Proposed: **yes**.

## 9. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-13 | MVP = pattern tagging; summaries/full-explain deferred | Mostly-deterministic, well-tested slice; exercises the agent/budget rails summaries will reuse |
| 2026-06-13 | Injectable `PatternJudge`; agent isolated to `LLMPatternJudge`; `ScriptedJudge` for tests | Keeps orchestration/heuristics/budget unit-testable; no live model in CI (Embedder precedent) |
| 2026-06-13 | Two-stage: structural heuristics nominate → LLM judge confirms | Heuristics-only = low precision; LLM-only = 20–100× cost; combo keeps judge calls ~1–5% |
| 2026-06-13 | Budget via framework `BudgetPolicy`; resumable via `DirtySet("patterns")` | Honest cost cap (`BudgetExceeded`), partial-progress persistence, incremental re-judge |
| 2026-06-13 | `clear_outgoing(src_ids, kind)` for idempotent re-tag | `add` CREATEs edges (would duplicate); reused by the summaries enricher later |
| 2026-06-13 | `TAGGED` in context expansion; tags are `llm` provenance | Retrieved class surfaces its pattern; existing `include_llm_facts` handles opt-out |
| 2026-06-13 | **Implemented** the live judge on **Bedrock Claude** (boto3) not the Anthropic-API provider | Per the user: Anthropic via AWS (same creds as the Cohere embedder); the injectable judge made this a one-class swap — orchestration unchanged. `BudgetPolicy` still drives the cap. Live-verified: Repository/Factory confirmed, a name-only Service *rejected* (0.20 < floor); ~$0.005 for 3 judgments |
| 2026-06-13 | Default model = `us.anthropic.claude-haiku-4-5-...` (inference profile) | The bare 4.5 id rejects on-demand throughput on Bedrock; the `us.` profile works |
| 2026-06-13 | Dropped the route-based Controller heuristic | feat-011 counts class-method handlers as unresolved (no `HANDLED_BY` to a method), so the signal can't fire; name-suffix Controller detection stands |

## 10. Chunk plan (the single feat-012 PR)

| Chunk | Commit | Contents |
|---|---|---|
| 0 | `chore(012): EnrichConfig + enrich package skeleton; design accepted` | `EnrichConfig`; `enrich/__init__` + `taxonomy.py`; this doc → accepted |
| 1 | `feat(012): clear_outgoing store primitive` | contract + Kuzu + in-memory + conformance test |
| 2 | `feat(012): stage-1 pattern heuristics` | `heuristics.py`; golden precision/recall on a labeled fixture |
| 3 | `feat(012): PatternJudge + ScriptedJudge + PatternTagEnricher` | `judge.py`, `enricher.py`, `report.py`; enricher with `ScriptedJudge`; budget-trip + dirty-resume + idempotent-retag tests |
| 4 | `feat(012): LLMPatternJudge (framework agent adapter)` | `llm_judge.py`; live test `CKG_LIVE_AGENT`-gated (provenance/cost/floor) |
| 5 | `feat(012): CodeGraph.enrich/tagged + ckg enrich CLI + DirtySet patterns` | facade + CLI + DirtySet consumer; report formatting |
| 6 | `feat(012): retrieval TAGGED expansion + ckg_explain tool` | retriever edge; `CkgExplain` + `ALL_TOOLS`; locked tool-set update; integration test |
| 7 | `docs(012): impl status + tracker; design accepted` | spec status; TRACKER; this doc accepted |

## 11. References

- Spec: `docs/features/feat-012-llm-enrichment.md`
- ADRs: 0001 (layering — `enrich` is framework-layer), 0004 (provenance), 0005
  (locked kinds)
- AgentForge: `Agent`/`LLMClient.call`/`BudgetPolicy` (agentforge-py/-core/
  -anthropic 0.2.4); feat-008 serve (the framework-layer precedent)
- feat-002 (signatures/attrs), feat-004 (`DirtySet`), feat-006
  (`include_llm_facts`), feat-008 (`ckg_explain` reserved), feat-011
  (`Route`/`DataModel` evidence)
- Research §3.3 (pattern gap); GraphRAG community-summary prior art
