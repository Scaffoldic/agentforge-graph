# design-016: Grounded documentation generation (`ckg docs …`)

Mirrors [feat-016](../features/feat-016-grounded-doc-generation.md). The *how*:
file layout, exact types, resolved decisions, chunk plan. Grounded in a code
map of the existing enrich / retrieve / repomap / knowledge / incremental /
serve surfaces (verified against source).

| Field | Value |
|---|---|
| **Status** | accepted |
| **Target** | 0.7.0 |
| **Scope** | Phase 1 — four descriptive doc types (ai-context, architecture, component, design) + grounded generation + citations + draft/promote gate + dirty-aware `update` + opt-in `sync`. ADR drafts (Phase 3) and CI-hardened flywheel (Phase 2) deferred. |

## Resolved decisions (approved at design review)

1. **Writer = multi-turn `agentforge.Agent` loop** over a **read-only, grounded
   ckg toolset**, *not* a single-shot `ClaudeClient.invoke`. The recipe seeds the
   context; the Agent expands it by calling the graph tools. Grounding is enforced
   at the **tool boundary** (§Grounding).
2. **Citations = a structured footnote block** (per-section footnote markers +
   a bottom References block), *not* inline `[F#]` links.
3. **`ai-context` is draft-only** to `output_root` (promote + `ckg setup` place
   the accepted file); no `--in-place` in Phase 1.
4. **`doc_lang_version`** is stamped (manifest + `ckg_status`) so a template/
   citation-contract change is detectable, like feat-015's `query_lang_version`.

---

## The one idea

**Documentation is a grounded projection of the graph — the model may only cite
facts a read-only graph tool actually returned.** A doc-type **recipe** assembles
a **seed pack** of the highest-value facts, then an `agentforge.Agent` composes
the doc while **expanding that pack through a read-only, provenance-floored ckg
toolset** (the same `Tool` instances feat-008 serves). We **capture every
`SymbolRef` the tools return** (seed ∪ tool results = the *provenance set*), and
the model attributes claims via a **footnote block**. Post-render we **verify
every footnote resolves to a fact in the provenance set** and flag any section
that cites nothing. The draft lands under `output_root` with the git commit it
was built from + the provenance set as its staleness key, riding the **same
feat-004 dirty-tracking** as embeddings/summaries.

```
DocTarget ─recipe─▶ seed GroundedPack ─┐
            (graph                      │   ┌──────── read-only ckg tools (min_provenance ≥ parsed) ────────┐
           queries)                     ▼   │  ckg_search · ckg_symbol · ckg_neighbors · ckg_impact ·        │
                          agentforge.Agent ◀┤  ckg_repo_map · ckg_decisions  → each result carries SymbolRef │
                          (budget_usd,       └───────────────────────────────────────────────────────────────┘
                           max_iterations)         │  capture transcript → provenance set = seed ∪ results
                                 │                  │
                                 ▼                  ▼
                          draft.md + footnote block ─verify─▶ every footnote ∈ provenance set?  (else reject)
                                 │                              every section has ≥1 footnote?   (require_citations)
                                 ▼
              emit under output_root  +  manifest entry {status:draft, synced_commit,
                                                          source_ids = provenance set, footnotes}
                                 │
             feat-004 DirtySet("docs"): source_ids ∩ dirty ⇒ `ckg docs update` regenerates that doc

  (opt-in) `ckg docs sync`: ACCEPTED docs ─KnowledgeIngestor(feat-010)─▶ DocChunk + DESCRIBES, tagged Provenance.llm
```

**Why the tool boundary keeps it grounded.** The Agent has no way to learn a fact
except by calling a ckg tool, and those tools return only real graph rows, each
with a `SymbolRef`, filtered at `min_provenance ≥ parsed`. So the model cannot
invent a symbol — it can only cite one the graph actually produced, and it can
never cite an llm-sourced fact as ground truth (anti-echo-chamber, §Grounding).
The **honest limit**: the verifier proves a footnote points at a *real retrieved
fact*, not that the fact is the *semantically correct* support — machine-checking
relevance is out of reach, so the **human promote gate stays load-bearing**.
(A single-shot-over-fixed-pack writer would be structurally tighter; we chose the
richer agent-loop and make the tool boundary + verifier + promote gate carry it.)

## Guiding constraints

- **Reuse the rails; don't reinvent (project CLAUDE.md).** `docgen` composes over
  the engine using framework rails that already exist: `agentforge.Agent` (which
  wraps `BudgetPolicy` internally, `agent.py:156`) for the budgeted multi-turn
  loop, and the **feat-008 `Tool` instances** (`serve/tools.py`) for the grounded
  toolset — the same read-only tools an MCP client gets. It does **not** rebuild a
  provider/budget/tool stack.
- **Layering.** `docgen` is a **framework-layer** module (imports `agentforge`),
  like `serve/`. It *consumes* the deterministic engine (`CodeGraph`, `Retriever`,
  `RepoMap`, `KnowledgeIngestor`) and adds no coupling back into it. The engine
  core (`core`/`ingest`/`store`/`retrieve`) is untouched (ADR-0001).
- **No locked-vocabulary change (ADR-0005).** Phase 1 adds **no new
  `NodeKind`/`EdgeKind`.** Generated docs are markdown **files** under
  `output_root` + a **sidecar manifest**; opt-in `sync` reuses feat-010's existing
  `DocChunk` + `DESCRIBES`.
- **No-overwrite is an invariant.** Every generator writes **only** under
  `docgen.output_root`. Human files (incl. a real `CLAUDE.md`/`AGENTS.md` at repo
  root) are never touched by generation.
- **Read-only tools only.** The Agent's toolset is the feat-008 read-only set;
  the Agent is never given a write tool, so generation can query but not mutate the
  graph (it only writes doc files). `sync` (which *does* write the graph) is a
  separate, explicit, non-agentic step.

### Extensibility principles (no effort-driven workarounds)

- **Add a doc type** → new `Recipe` subclass + a template + one registry entry. No
  edits to the generator, the Agent runner, the citation verifier, or other
  recipes.
- **Add/adjust the grounded toolset** → change the tool-selection list in one
  place; every recipe inherits it. Tools are the feat-008 instances — no bespoke
  docgen tools.
- **Grounding is a required contract.** Every emitted section must resolve ≥1
  footnote to a fact in the provenance set (`require_citations`), enforced by a
  shared verifier + a load-bearing test.
- **Staleness reuses one mechanism.** Generated docs are a `DirtySet` consumer
  (`"docs"`) like `embeddings`/`patterns`/`summaries`.

## Package layout

```
src/agentforge_graph/docgen/
  __init__.py       # exports: DocGenerator, DocTarget, DocArtifact, DocType,
                    #          GroundedPack, SymbolRef, DocgenError (+ subclasses)
  types.py          # frozen dataclasses: DocType, DocTarget, DocArtifact,
                    #          SymbolRef, GroundedFact, GroundedPack, Footnote, ProvenanceSet
  errors.py         # DocgenError -> UngroundedError | BadCitationError | DocDisabled | PromoteRequired
  manifest.py       # sidecar .ckg-docs.json: per-doc status/synced_commit/
                    #          source_ids/footnotes/doc_lang_version; read/write; list/diff/promote
  recipes/
    base.py         # Recipe ABC: async seed(cg, target) -> GroundedPack; RECIPES registry
    ai_context.py   # repo map + layer topology + entry points + conventions
    architecture.py # layers + top-PageRank + framework topology + repo summary
    component.py    # a module's CONTAINS/IMPORTS/public-API/routes/models/summary
    design.py       # a subsystem's call graph + pattern tags + relevant ADRs/docstrings
  templates/
    base.py         # Template: section skeleton + citation/footnote instructions (data)
    *.md.tmpl       # one section-skeleton per doc type (house style, reviewable)
  toolset.py        # grounded_tools(cg, min_provenance=PARSED) -> list[Tool]  (feat-008 instances, read-only)
  runner.py         # AgentDocRunner: builds agentforge.Agent(tools, budget_usd, max_iterations),
                    #   runs the compose loop, CAPTURES the tool transcript -> ProvenanceSet.
                    #   ScriptedDocModel fake provider for hermetic CI.
  citations.py      # footnote parse + verify against ProvenanceSet; require_citations gate
  generator.py      # DocGenerator: generate() / update() / list() / diff() / promote() / sync()
  staleness.py      # map a doc's source_ids <-> DirtySet("docs")

# extended (not new) files:
  ingest/incremental/dirty.py  # + "docs" in DEFAULT_CONSUMERS
  ingest/codegraph.py          # + docs_generate/docs_update/docs_list/docs_diff/docs_promote/docs_sync
  config.py                    # + DocGenConfig(_Block, KEY="docgen")
  cli.py                       # + `docs` nested subparser (generate/update/list/diff/promote/sync)
  knowledge/ingest.py          # sync path: allow Provenance.llm override for generated docs
```

## Key types (`types.py`)

```python
class DocType(StrEnum):
    AI_CONTEXT = "ai-context"; ARCHITECTURE = "architecture"
    COMPONENT = "component"; DESIGN = "design"

@dataclass(frozen=True)
class DocTarget:
    type: DocType
    scope: str | None = None            # repo | package/path | subsystem | symbol id

@dataclass(frozen=True)
class SymbolRef:                        # a citable pointer into the graph
    id: str                             # SymbolID string (core/symbols.py)
    kind: NodeKind
    name: str
    path: str | None
    span: tuple[int, int] | None

@dataclass(frozen=True)
class GroundedFact:
    text: str                           # the fact, phrased for the model
    ref: SymbolRef
    source: Source                      # only >= parsed is ground truth

@dataclass(frozen=True)
class GroundedPack:                     # the SEED — the Agent expands it via tools
    target: DocTarget
    facts: tuple[GroundedFact, ...]
    notes: tuple[str, ...] = ()         # non-citable framing

@dataclass(frozen=True)
class ProvenanceSet:                    # everything the tools surfaced this run
    refs: dict[str, SymbolRef]          # keyed by SymbolID; seed refs ∪ tool-result refs
    def contains(self, symbol_id: str) -> bool: ...

@dataclass(frozen=True)
class Footnote:
    marker: str                         # e.g. "f3"
    ref: SymbolRef                      # must resolve into the ProvenanceSet

@dataclass(frozen=True)
class DocArtifact:
    type: DocType
    path: str                           # under output_root
    status: str                         # "draft" | "accepted"
    synced_commit: str                  # git commit the run was built from
    doc_lang_version: str               # template/citation contract version
    source_ids: tuple[str, ...]         # ProvenanceSet keys — the staleness key
    footnotes: tuple[Footnote, ...]
    stale: bool
```

`SymbolRef` is built from a `core.models.Node` or a `retrieve.pack.ContextItem`
(both already carry `id`/`kind`/`name`/`path`/`span`/`provenance`).

## Recipes — the seed (`recipes/`)

A recipe turns a `DocTarget` into a **seed** `GroundedPack` — the facts worth
handing the Agent up front so it does not start cold. It is pure graph
assembly, **no LLM**, unit-testable against a fixture graph.

```python
class Recipe(ABC):
    doc_type: ClassVar[DocType]
    async def seed(self, cg: CodeGraph, target: DocTarget) -> GroundedPack: ...

RECIPES: dict[DocType, Recipe]          # registry; out-of-tree types via entry points later
```

| Recipe | Seeds from (existing APIs) |
|---|---|
| `architecture` | `cg.ranked_symbols(k)` / `cg.repo_map(...)`, `cg.services()`/`cg.routes()`/`cg.models()`, `cg.summaries(level="repo")` |
| `component` | graph adjacency (CONTAINS/IMPORTS/public API) for the scope, `cg.routes()/models()` filtered, `cg.summaries(level="file")` |
| `design` | `cg.retrieve(mode="context")` over the subsystem, `cg.tagged(pattern)`, `cg.decisions(...)`, docstrings via `DOC_CHUNK`/`DESCRIBES` |
| `ai-context` | `cg.repo_map(...)` + layer topology + entry points + conventions from ingested docs; targets `docgen.ai_context_targets` |

Seed facts are requested at `min_provenance ≥ parsed`
(`Retriever.retrieve(..., min_provenance=Source.PARSED)` already filters
`Source.LLM`), so the seed carries no llm-sourced fact as ground truth.

**Component granularity** (`docgen.component_granularity`): `package` (default),
`file`, or `hybrid` (package doc + drill-down for files above
`hybrid_min_symbols`); `--scope` overrides per run.

## Grounded generation (`toolset.py`, `runner.py`) — the trust boundary

**The toolset is the boundary.** `grounded_tools(cg)` returns the read-only
feat-008 `Tool` instances (`ckg_search`, `ckg_symbol`, `ckg_neighbors`,
`ckg_impact`, `ckg_repo_map`, `ckg_decisions`), each configured to ground at
`min_provenance ≥ parsed`. No write tool is ever included. Every tool result is
captured.

```python
class AgentDocRunner:
    def __init__(self, cg, cfg: DocGenConfig, model=None): ...   # model=None -> real provider
    async def compose(self, pack: GroundedPack, template: Template) -> tuple[str, ProvenanceSet]:
        tools = grounded_tools(self.cg)
        captured = _CaptureProxy(tools)                # wraps each Tool: records returned SymbolRefs
        agent = Agent(tools=captured, budget_usd=self.cfg.budget_usd,
                      max_iterations=self.cfg.max_iterations)   # framework budget + loop bound
        prompt = template.render(seed=pack)            # seed facts + section skeleton + cite rules
        text = await agent.run(prompt)
        return text, captured.provenance_set(seed=pack)
```

- **Budget + loop bound** ride `agentforge.Agent` (wraps `BudgetPolicy`): a per-run
  USD cap and `max_iterations` cap the tool-call sprawl. On budget trip the Agent
  stops; the generator reports `budget_tripped` and leaves already-finished docs
  intact (idempotent resume — the next run regenerates only the unfinished/dirty
  ones).
- **`_CaptureProxy`** is the single place tool results are recorded, so the
  provenance set is complete by construction — a claim can only be grounded if its
  symbol passed through here.
- **Hermetic CI:** `ScriptedDocModel` is a fake framework provider that drives the
  Agent loop deterministically (a fixed sequence of tool calls + a final doc body),
  credential-free — the docgen analog of enrich's `ScriptedJudge`. All unit/
  integration tests use it; a live provider is env-gated.

### Citations (`citations.py`)

The template instructs: *attribute each claim with a footnote marker `[^fN]`;
define every marker in a `## References` block at the end as
`[^fN]: <symbol-id> — <path>:<span>`; if a section has no supporting fact, emit
its header with `<!-- UNGROUNDED -->` rather than inventing prose.*

Verification after the run:

1. Parse the References block → `Footnote`s; parse per-section markers.
2. **Every footnote's symbol must be in the `ProvenanceSet`** (seed ∪ captured
   tool results). A footnote citing a symbol the tools never returned →
   `BadCitationError` (the model fabricated a citation).
3. **Every section must carry ≥1 footnote marker.** A section with none →
   ungrounded → `UngroundedError` when `require_citations: true` (default), else
   emitted with the `UNGROUNDED` marker preserved.
4. Footnote definitions are rendered to human-facing links (path + span) in the
   final artifact.

This is the constructive-grounding stance (feat-015's "validate, don't sanitize"
applied to prose): the doc is trusted because every claim points at a real,
provenance-floored graph fact the tools produced — not because we caught
hallucinations after the fact.

## Persistence & staleness (`manifest.py`, `staleness.py`)

**Artifacts are files; metadata is a sidecar manifest.** Developers review, diff,
and commit markdown under `output_root`. Per-doc metadata lives in
`output_root/.ckg-docs.json` (mirrors the `.ckg/dirty.json` pattern):

```jsonc
{ "docs/_generated/architecture.md": {
    "type": "architecture", "status": "draft",
    "synced_commit": "a1b2c3d", "doc_lang_version": "1.0",
    "source_ids": ["scip:py …", …],
    "footnotes": [{"marker":"f1","ref":{…}}, …] } }
```

- **`synced_commit`** = `CodeGraph._git_commit(repo_path)` at generation.
- **`source_ids`** = the `ProvenanceSet` keys — everything the run grounded on
  (richer than a fixed pack: it captures whatever the Agent chose to read).
- **Staleness.** Add `"docs"` to `DirtySet.DEFAULT_CONSUMERS`
  (`ingest/incremental/dirty.py:22`). `docs_update` mirrors `CodeGraph.summarize`
  (`codegraph.py:864`): drain `dirty.dirty_for("docs")` → find manifest docs whose
  `source_ids` intersect the dirty set → regenerate only those →
  `dirty.mark_clean("docs", regenerated_ids)`. `stale` = `source_ids ∩
  dirty_for("docs") ≠ ∅` or `synced_commit != HEAD` or `doc_lang_version` bumped.
- **list / diff / promote** are pure manifest ops: `list` = docs + status +
  staleness; `diff` = working file vs last generated bytes; `promote` flips
  `status: draft → accepted` (the human gate; `promote_required: true`).

## Sync flywheel (opt-in) & anti-echo-chamber (`generator.py` + `knowledge/ingest.py`)

`ckg docs sync` re-ingests **accepted** docs into the graph — **opt-in**
(`round_trip: off` default; `sync` refuses when off) and **gated** (refuses
un-promoted docs → `PromoteRequired`).

- **Reuse feat-010.** `sync` runs accepted docs through `KnowledgeIngestor`
  (`knowledge/ingest.py:_ingest_docs`) → `DocChunk` + `DESCRIBES` + embedding.
- **One seam-touch:** `_ingest_docs` currently stamps `Provenance.parsed(
  "doc-ingestor", commit)`; sync must stamp **`Provenance.llm("docgen@<ver>", 1.0,
  commit)`** so generated docs are `Source.LLM`. This makes anti-echo-chamber real:
  the grounded toolset floors at `≥ parsed`, so a synced generated doc can inform
  semantic search but **can never be returned as a citable fact** for a future
  generation. We add a provenance-source parameter (default unchanged), not a fork.
- **Refused on read-only stores** via `_refuse_write_if_read_only` (sync writes the
  graph; `generate`/`update` only write files).

## CLI (`cli.py`) — nested `docs` subparser

Model: the `ci` command (`cli.py:1223`) — a subcommand with sub-subparsers.
Handlers are `async def _docs_*(args) -> int`.

```
ckg docs generate --type {ai-context|architecture|component|design} [--scope P] [--all] [--budget-usd N] [--format text|json]
ckg docs update
ckg docs list
ckg docs diff <doc>
ckg docs promote <doc>
ckg docs sync
```

Reuses `_add_repo_arg`, `_preflight_or_exit`, `_refuse_write_if_read_only` (sync),
and the `cli_format` `render_table`/`render_json` helpers. `DocgenError` → stderr
"why" + exit 2 (ENH-026 convention).

## Facade (`ingest/codegraph.py`)

Thin pass-throughs mirroring `enrich`/`summarize`, constructing a `DocGenerator`
from config (the `AgentDocRunner`, `RECIPES`, and the store/retriever/repomap it
already owns):

```python
async def docs_generate(self, target, *, budget_usd=None) -> DocArtifact
async def docs_update(self) -> list[DocArtifact]
async def docs_list(self) -> list[DocArtifact]
async def docs_diff(self, path) -> str
async def docs_promote(self, path) -> DocArtifact
async def docs_sync(self) -> int
```

## Config (`config.py`)

```python
class DocGenConfig(_Block):
    KEY: ClassVar[str] = "docgen"
    output_root: str = "docs/_generated"
    types: list[str] = ["ai-context", "architecture", "component", "design"]
    ai_context_targets: list[str] = ["CLAUDE.md", "AGENTS.md"]
    component_granularity: str = "package"     # package | file | hybrid
    hybrid_min_symbols: int = 20
    require_citations: bool = True
    round_trip: bool = False
    promote_required: bool = True
    budget_usd: float = 5.0
    max_iterations: int = 24                    # Agent loop bound per doc
    regenerate_on_ci: bool = False
    # provider selection (reuses enrich builders / framework provider):
    provider: str = "bedrock"                  # scripted | bedrock | anthropic
    model: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    region: str | None = None
    assume_role_arn: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
```

Auto-discovered by `block_keys()`. `ckg_status` gains `docgen.{enabled, types,
doc_lang_version}`.

## Test strategy / conformance

- **Grounding/citation (load-bearing):** with a `ScriptedDocModel` over a fixture
  graph — a footnote citing a symbol the tools never returned → `BadCitationError`;
  a section with no footnote → `UngroundedError` under `require_citations`; a valid
  run → every footnote resolves into the `ProvenanceSet` and rewrites to a link.
- **Tool-boundary capture:** the `ProvenanceSet` equals exactly the union of seed
  refs + the SymbolRefs the scripted tool calls returned (no more, no less).
- **No-overwrite:** generation writes only under `output_root`; a repo-root
  `CLAUDE.md` fixture is byte-unchanged after `generate --type ai-context`.
- **Staleness:** edit a module → its doc's `source_ids` intersect
  `dirty_for("docs")` → `docs_update` regenerates that doc only; `mark_clean`
  clears it; a `doc_lang_version` bump marks all docs stale.
- **Draft/promote gate:** docs are `status: draft`; `sync` refuses un-promoted
  (`PromoteRequired`) and refuses when `round_trip: off`; `promote` flips status.
- **Anti-echo-chamber:** a synced generated doc is ingested `Source.LLM`; a later
  grounded run's tools (floored at `≥ parsed`) never return it as a fact.
- **Budget:** a capped `ScriptedDocModel` run trips the Agent's `BudgetPolicy` and
  stops idempotently — no duplicate/partial files; finished docs survive.
- **Determinism/CI:** entire suite on `provider: scripted` (`ScriptedDocModel`) —
  no creds, no SDK import. One env-gated live test end-to-end.
- **Config + status:** `DocGenConfig.load` round-trips; `ckg_status` reports the
  docgen block + `doc_lang_version`.

## Chunk plan

| # | Chunk | Lands |
|---|---|---|
| 1 | **Types + manifest + config + staleness seam** (`types.py`, `errors.py`, `manifest.py`, `DocGenConfig`, `"docs"` in `DEFAULT_CONSUMERS`, `staleness.py`) | Metadata + persistence + dirty-tracking core, LLM-free, fully unit-tested. |
| 2 | **Recipe seam + first seed recipe (`architecture`) + citation verifier** (`recipes/base.py` + registry, `recipes/architecture.py`, `citations.py`) | Deterministic graph→seed pack + the footnote/`ProvenanceSet` verifier, proven against a fixture (no LLM). |
| 3 | **Grounded toolset + Agent runner + `generate`** (`toolset.py`, `runner.py` with `ScriptedDocModel`, `templates/`, `generator.py` generate-path) | First end-to-end slice: `architecture` doc composed via a scripted Agent loop over captured read-only tools, citations verified, budget/iteration-bounded, idempotent write. **Heaviest chunk.** |
| 4 | **Remaining recipes + templates** (`ai_context.py`, `component.py`, `design.py` + templates; component granularity) | All four descriptive types, each with a grounding test. |
| 5 | **Dirty-aware `update` + `list`/`diff`/`promote`** (`generator.py` rest, facade methods) | Freshness loop (feat-004 reuse) + review surface. |
| 6 | **CLI** (`ckg docs …` nested subparser + format wiring + read-only guards) | Power-user + reviewer surface. |
| 7 | **Opt-in `sync` flywheel** (`generator.sync`, `_ingest_docs` provenance override, `round_trip`/promote gates, read-only refusal, CLI `docs sync`) | The graph round-trip, anti-echo-chamber-safe by provenance. |
| 8 | **Status + docs + polish** (`ckg_status` docgen block + `doc_lang_version`, guide 14, README, CHANGELOG `[Unreleased]`, feat-016 Implementation-status) | Ship polish. |

Each chunk is a self-contained Conventional Commit; the gate (ruff/mypy/pytest/
≥90%) passes per chunk. Chunks 1–3 carry the seams + first slice; 4 adds breadth
as pure additions; 5–8 are surfaces + the flywheel.

## Extensibility seams (summary)

| To add… | You touch | You do **not** touch |
|---|---|---|
| A doc type | 1 `Recipe` subclass + 1 template + 1 registry entry | generator, runner, citation verifier, other recipes |
| A grounded tool | the `grounded_tools()` list | recipes, runner, verifier |
| An LLM provider | reuse the `enrich`/framework provider registry | `docgen` (no provider branching) |
| A guardrail (e.g. per-doc token cap) | 1 field on `DocGenConfig` + `runner.py` | recipes, manifest |
| A CLI output format | the shared `cli_format` helper | every `docs` verb |

## Alternatives considered

| Option | Why not (or why chosen) |
|---|---|
| **Single-shot over a fixed pack** (writer sees only pre-assembled facts) | Structurally tighter grounding, but the recipe must anticipate every fact up front; poorer coverage on questions the model realizes it needs mid-write. **Rejected at review in favor of the agent-loop**, whose grounding is preserved at the tool boundary + verifier + promote gate. |
| **Multi-turn `agentforge.Agent` over read-only tools** | **Chosen.** Richer, self-directed fact-gathering; reuses the framework Agent + budget + the feat-008 toolset; grounding enforced because tools are the only fact source and are provenance-floored. |
| Persist docs as graph nodes (new `GeneratedDoc` kind) | Needs an ADR-0005 kinds change; the reviewed/committed artifact is a *file*. Files + sidecar manifest now; a graph kind later if the flywheel needs it. |
| Inline `[F#]` citations | Tighter per-claim locality, but review chose a **footnote block** (cleaner prose, References section a reviewer can scan). Verifier works the same against the `ProvenanceSet`. |
| Auto-sync generated docs into the graph | Echo-chamber risk. Round-trip is opt-in *and* provenance-gated (`Source.LLM`); synced docs never become citable ground truth. |
| Overwrite `CLAUDE.md`/`AGENTS.md` in place | Breaks no-overwrite. Drafts land under `output_root`; promotion + `ckg setup` wire the accepted file. |
| Separate staleness store for docs | Diverges from embeddings/summaries. Docs are one more `DirtySet` consumer. |

## Risks

| Risk | Mitigation |
|---|---|
| Agent cites a real-but-irrelevant fact (semantic mis-grounding) | Verifier proves footnotes are *real retrieved facts*; the **human promote gate** is load-bearing for relevance. Templates constrain sections to the seed's topic. |
| Agent wanders / runs up cost | `Agent(budget_usd, max_iterations)` bounds tokens *and* loop length; grounded toolset is read-only; on trip, finished docs survive, resume is idempotent. |
| Hallucinated citation | Tool-boundary capture: a footnote's symbol must be in the `ProvenanceSet`, else `BadCitationError`. The model can't cite a symbol the tools never returned. |
| Echo chamber (round-trip) | Opt-in + synced as `Source.LLM`; tools floor at `≥ parsed` so generated prose is never a citable fact. |
| Hermetic testing of an Agent loop is heavier than enrich's scripted judge | `ScriptedDocModel` drives a fixed tool-call + final-body sequence; the `_CaptureProxy` is provider-agnostic, so verification is tested without a live model. |
| Design docs over-synthesize | Highest-risk type leans hardest on `require_citations` + promote gate; the verifier is type-agnostic. |
| Provider/credential coupling in CI | `provider: scripted` default test path; live provider env-gated, as enrich tests are. |
