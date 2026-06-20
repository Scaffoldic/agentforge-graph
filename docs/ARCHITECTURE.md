# agentforge-graph — Architecture & Design

> The canonical high-level overview. For the *why* behind individual decisions
> see [`adr/`](adr/); for per-feature *how* see [`design/`](design/) and
> [`features/`](features/). This document ties them together.

**Status:** living document · **Audience:** contributors, integrators ·
**Last updated:** 2026-06-13

---

## 1. What it is

**agentforge-graph** is a **Code Knowledge Graph (CKG) engine + agent toolset**.
It ingests a repository into a typed graph (symbols, calls, imports, routes,
decisions, summaries, pattern tags), embeds it for semantic search, and serves
that knowledge to coding agents — over an MCP server or as an AgentForge
toolset. It is an *agent project* built on the AgentForge framework
(agentforge-py 0.2.4), not a framework itself.

The product thesis (research-backed): plain code-graph tools answer "what is
connected"; agents also need "what is this *for*", "what decision governs this",
"what's the API surface", "show me all Repositories". agentforge-graph puts
**parsed structure, framework semantics, architecture decisions, and LLM
enrichment in one provenance-tracked graph** an agent can traverse.

---

## 2. Design principles

These are the load-bearing rules; each maps to an ADR.

| Principle | What it means | ADR |
|---|---|---|
| **Deterministic engine core** | `core`/`ingest`/`store`/`retrieve` (and the other engine packages) **never import `agentforge`**. Only the *serve* and *enrich* layers may. Keeps the engine testable, fast, framework-agnostic. | ADR-0001 |
| **Stable symbol identity** | Every node id is a deterministic `SymbolID` derived from `(lang, repo, path, descriptor)` — no counters, no ordering. The same symbol keeps its id across commits. | ADR-0003 |
| **Provenance on everything** | Every node/edge carries `source ∈ {parsed, resolved, llm, manual}` + extractor + commit + confidence. LLM facts are honestly second-class and opt-out-able. | ADR-0004 |
| **Locked vocabulary** | All node/edge *kinds* (incl. ones produced by later features) are fixed up front, so stores/queries handle every kind from day one — no schema migration when a producer lands. | ADR-0005 |
| **Embedded-first, pluggable storage** | Default to a local Kuzu graph + LanceDB vectors under `.ckg/`, no server. Server backends register out-of-tree. | ADR-0006 |
| **Per-file isolation** | Extraction reads one file at a time and upserts a per-file subgraph; cross-file links are a separate graph-only pass. This is what makes incremental indexing a thin layer. | ADR-0002/0003 |
| **Conservative resolution** | A cross-file edge is created only on an *unambiguous* match; ambiguous/unknown is counted, never guessed. | ADR-0004 |
| **Injectable model adapters** | Every model boundary (embedder, pattern judge, summarizer) is an interface with a deterministic fake for CI plus live adapters resolved by a **provider registry** (ENH-003) — Bedrock, OpenAI/local embeddings, direct Anthropic API, or an out-of-tree entry point. The engine/orchestration is tested with no model calls. | ENH-003 |

---

## 3. High-level architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│  CONSUMERS                                                                 │
│     ckg CLI      ·      MCP server (Claude Code / IDE)      ·   Agent      │
└───────────────┬───────────────────────────────┬──────────────────────────┘
                │                                │
┌───────────────▼─────────────────┐   ┌──────────▼─────────────────────────┐
│  serve   (FRAMEWORK LAYER)       │   │  enrich  (FRAMEWORK LAYER)         │
│  • Tool ABC (agentforge-core)    │   │  • BudgetPolicy (agentforge-core)  │
│  • MCP stdio (agentforge-mcp)    │   │  • Bedrock Claude judge/summarizer │
│  • 10 read-only ckg_* tools      │   │  • writes llm-provenance facts     │
└───────────────┬─────────────────┘   └──────────┬─────────────────────────┘
                │ read-only queries               │ enrich (explicit only)
┌───────────────▼─────────────────────────────────▼─────────────────────────┐
│  DETERMINISTIC ENGINE   (zero `agentforge` imports — ADR-0001)             │
│                                                                            │
│   ingest ──┬─ packs/        (language packs: py, ts, js + .scm queries)    │
│            ├─ incremental/   (ChangeDetector, IncrementalIndexer, DirtySet)│
│            └─ resolver       (imports/refs → IMPORTS/CALLS edges)          │
│   frameworks   (FastAPI routes → Route + HANDLED_BY)                       │
│   knowledge    (ADRs → Decision + GOVERNS/SUPERSEDES)                      │
│   chunking ── embed (Cohere/fake) ── retrieve (hybrid) ── repomap (rank)   │
│   config   (ckg.yaml, lenient)                                             │
└───────────────────────────────────┬───────────────────────────────────────┘
                                     │ contracts + value types
┌────────────────────────────────────▼──────────────────────────────────────┐
│  core   (foundation, no deps)                                              │
│   contracts: Extractor · GraphStore · VectorStore · Enricher (ABCs)       │
│   models:    Node · Edge · FileSubgraph · GraphQuery · Embedded           │
│   identity:  SymbolID (ckg lang repo path descriptor)                     │
│   kinds:     NodeKind / EdgeKind  (locked vocabulary)                      │
│   provenance: Source · Provenance                                         │
└───────────────┬───────────────────────────────────┬───────────────────────┘
                │                                     │
       ┌────────▼─────────┐                  ┌────────▼─────────┐
       │  Kuzu  (graph)   │  .ckg/graph.kuzu │ LanceDB (vectors)│ .ckg/vectors.lance
       │  KuzuGraphStore  │                  │ LanceVectorStore │
       └──────────────────┘                  └──────────────────┘
                                  .ckg/meta.json  (IndexMeta, atomic)
                                  .ckg/dirty.json (DirtySet)
```

**Three layers, one direction of dependency** (top → bottom):

1. **core** — pure contracts + value types. Depends on nothing.
2. **deterministic engine** — all the real work (parse, store, resolve, embed,
   retrieve, frameworks, knowledge). Depends only on `core`. **No `agentforge`.**
3. **framework layer** — `serve` (exposes the engine as MCP/Tools) and `enrich`
   (LLM enrichment with budget rails). May depend on `agentforge`.

---

## 4. Package map

| Package | Layer | Responsibility |
|---|---|---|
| `core` | foundation | Contracts (ABCs), value models, `SymbolID`, provenance, locked kinds, reusable conformance suites. |
| `config` | engine | Typed reader for `ckg.yaml` (this agent's own config; lenient, `extra=ignore`). |
| `ingest` | engine | The pipeline: `RepoSource`, `TreeSitterExtractor` (pass 1), `ImportResolver` (pass 2), `IngestPipeline`, `CodeGraph` facade. |
| `ingest.packs` | engine | Language packs (Python/TS/JS): grammar + `.scm` queries + descriptor rules + module style. |
| `ingest.incremental` | engine | `IndexMeta` manifest, `ChangeDetector`, `IncrementalIndexer`, `DirtySet`. |
| `store` | engine | `KuzuGraphStore`, `LanceVectorStore`, `Store` facade (graph+vector join). |
| `chunking` | engine | cAST chunker over symbol spans; token estimate. |
| `embed` | engine | `Embedder` ABC; `FakeEmbedder` (CI), `BedrockEmbedder` (Cohere), `OpenAIEmbedder` (+ local), registry-resolved. `EmbedPipeline`. |
| `retrieve` | engine | `Retriever` (hybrid vector→graph), `ContextPack`, provenance-weighted scoring. |
| `repomap` | engine | Personalized PageRank ranking + budget-packed text map. |
| `frameworks` | engine | `FrameworkPack` ABC + FastAPI pack (routes → `Route`/`HANDLED_BY`). |
| `knowledge` | engine | ADR parser + mention linking + `KnowledgeIngestor` (Decision/GOVERNS). |
| `enrich` | **framework** | Pattern tagging + summaries: heuristics → injectable LLM judge/summarizer, budget, dirty. |
| `serve` | **framework** | `_Engine` holder + 9 `ckg_*` `Tool`s + MCP stdio server. |
| `cli` | top | `ckg` subcommands; `main` dispatcher. |

---

## 5. The data model

Everything is **nodes and edges**, each id'd and attributed.

```
SymbolID  =  "ckg" · <lang> · <repo> · <path> · <descriptor>     (space-joined, %-escaped)
            e.g.  ckg py myrepo src/app/auth.py  Auth#login().

Node   { id: SymbolID, kind: NodeKind, name, span?, attrs{}, provenance }
Edge   { src, dst, kind: EdgeKind, attrs{}, provenance, origin_path }
                                                         └─ the file that "owns" the
                                                            edge (for incremental invalidation)
Provenance { source: parsed|resolved|llm|manual, extractor, commit, confidence }
```

**Locked vocabulary** (ADR-0005 — every kind handled from day one):

```
NodeKind   structural   Repository File Package Class Interface Function Method Variable TypeAlias
           retrieval    Chunk DocChunk
           higher-level  Decision  Route DataModel Service  Summary PatternTag
EdgeKind   structural   CONTAINS IMPORTS CALLS INHERITS IMPLEMENTS REFERENCES
           retrieval    CHUNK_OF DESCRIBES
           decisions    GOVERNS SUPERSEDES
           framework    HANDLED_BY INJECTED_INTO HAS_FIELD RELATES_TO
           enrichment   SUMMARIZES TAGGED
```

A small graph fragment:

```
   File ──CONTAINS──► Class ──CONTAINS──► Method ──CALLS──► Method
    ▲                  ▲                    ▲
 IMPORTS            TAGGED               CHUNK_OF
    │                  │                    │
  File              PatternTag           Chunk ◄─ vector
                  "Repository"                     (LanceDB)
   ▲
 GOVERNS
   │
 Decision "ADR-0012 (accepted)"          Route "GET /x" ──HANDLED_BY──► Function
```

---

## 6. The harnessing pipelines

### 6.1 Ingestion — two passes (feat-002)

Per-file extraction is file-isolated and parallel; cross-file linking is a
single graph-only pass. This split (ADR-0002/0003) is what makes everything
else — incrementality, framework facts, decisions — a thin rider.

```
 repo
   │  RepoSource: walk → exclude/size filter → language by extension → SourceFile
   │             (path, text, content_hash)
   ▼
┌─ PASS 1 · extract  (CPU-bound, file-isolated, thread-pool) ───────────────┐
│                                                                           │
│   for each file:                                                          │
│     TreeSitterExtractor(pack).extract(sf)                                 │
│        ├─ structure query (.scm) → File▸Class▸Function▸Method (+ CONTAINS) │
│        ├─ import query           → file.attrs["imports"]                  │
│        └─ reference query        → symbol.attrs["refs"]   (call sites)    │
│     + FrameworkExtractor (feat-011)  → Route + HANDLED_BY (merged in)     │
│     store.graph.upsert(FileSubgraph)        ← transactional, per origin_path│
└───────────────────────────────────┬───────────────────────────────────────┘
                                     ▼
┌─ PASS 2 · resolve  (graph-only, idempotent — ImportResolver) ─────────────┐
│   build module index (source roots like `src/` stripped — BUG-001)        │
│   imports attrs ─► IMPORTS edges (in-repo or external Package)            │
│   refs attrs    ─► CALLS edges   (unique match only; else counted)       │
│   all edges: provenance=resolved, origin_path = the import/call-site file │
└───────────────────────────────────┬───────────────────────────────────────┘
                                     ▼
        knowledge pass (feat-010): ADRs ─► Decision (+ DocChunks) + GOVERNS/SUPERSEDES
                                     ▼
                            IndexMeta.save(.ckg/meta.json)   ← atomic, last
```

### 6.2 Incremental indexing (feat-004)

`ckg index` is incremental by default once a prior index exists. The
**content-hash** is the source of truth; git only refines renames.

```
 ckg index (repo already indexed)
   │  ChangeDetector.detect(source, IndexMeta)
   ▼  ChangeSet { added, modified, deleted, renamed }
 IncrementalIndexer.refresh:
   1. record symbols about to vanish        (for DirtySet)
   2. delete removed files                  graph.delete_file + vectors.delete_where
   3. re-extract touched files              scoped IngestPipeline (+ framework facts)
   4. scope = changed ∪ importers(changed)  ; clear_resolved(scope) ; re-resolve(scope)
   5. DirtySet(embeddings, patterns, summaries) += changed symbols + neighbours
   6. IndexMeta.save                        ← atomic, last → crash-safe
```

Correctness is held by an **equivalence property test**: `refresh(diff)` produces
the same graph as a full re-index, over randomized edit scripts. The enabling
mechanic: resolver edges carry `origin_path`, so a re-resolve can invalidate
*exactly* its scope via `clear_resolved`.

### 6.3 Embedding (feat-005)

```
 ckg embed
   │  for each file: pull its symbols → cAST chunker → Chunk nodes (+ CHUNK_OF)
   │  skip if the file's chunk-hash set is unchanged
   ▼  Embedder.embed(texts)   (Bedrock Cohere embed-v4, or FakeEmbedder in CI)
 LanceVectorStore.upsert(Embedded{ref=chunk_id, vector, kind, attrs})
```

### 6.4 Enrichment harness (feat-012) — the two-stage LLM layer

Never runs implicitly. Same shape for pattern tags and summaries: a
**deterministic stage 1** nominates, an **injectable, budgeted LLM stage 2**
confirms/produces. The model is behind one interface (`PatternJudge` /
`Summarizer`) so the whole orchestration is tested with a `Scripted*` fake.

```
 ckg enrich [--patterns | --summaries | --all]
   │  candidates = DirtySet(consumer) if dirty else all eligible symbols/files
   ▼
┌─ STAGE 1 · deterministic ──────────────┐
│  PatternHeuristics.nominate            │   (name + base-class + shape signals;
│      → Candidate{patterns, evidence}   │    recall: conservative|broad — ENH-001)
│  (summaries: gather file context)      │
└──────────────────┬─────────────────────┘
                   ▼  concurrent batches (enrich.concurrency — ENH-002)
┌─ STAGE 2 · LLM (budgeted) ─────────────────────────────────────────────┐
│  PatternJudge.judge / Summarizer.summarize_*                          │
│     ├─ ScriptedJudge / ScriptedSummarizer        (CI, deterministic)  │
│     └─ Bedrock* / Anthropic* Claude judge+summarizer (live; registry)│
│  per-batch:  BudgetPolicy.check() → gather(...) → commit(batch cost)  │
│              (overrun bounded to one batch; BudgetExceeded = stop)    │
└──────────────────┬─────────────────────────────────────────────────────┘
                   ▼  confirmed ≥ confidence_floor
   PatternTag + TAGGED{confidence, rationale}   |   Summary + SUMMARIZES (+ embedded)
   provenance = llm                              ─►  store.add ; DirtySet.mark_clean
```

Bottom-up summaries: file summaries (from signatures) → one repo summary
synthesised from them; embedded with `source_type=summary` so a concept query
lands on a summary and expands to the code.

### 6.5 Retrieval — hybrid vector → graph (feat-006)

```
 query string (or a symbol id)
   │  Embedder.embed([query]) → query vector
   ▼
 LanceVectorStore.search(k, cosine)  → ScoredRef[]  (score = 1 − distance, [0,1])
   │  seed = the hit nodes; chunk hits seed their symbols, summary hits seed code
   ▼  expand (mode-specific edge kinds, depth, provenance-weighted decay)
 KuzuGraphStore.adjacent:
     context →  CALLS CONTAINS INHERITS REFERENCES GOVERNS DESCRIBES TAGGED SUMMARIZES
     impact  →  reverse CALLS/IMPORTS/IMPLEMENTS
     definition / similar
   ▼
 ContextPack { items: ranked, deduped; [llm] facts excluded if include_llm_facts=False }
                                          → rendered text  or  JSON (MCP)
```

Repo map (feat-007) is the queryless counterpart: personalized PageRank over the
symbol graph → signatures packed into a token budget, with a one-line `[llm]`
file summary per file when summaries exist.

---

## 7. Storage

```
.ckg/
  graph.kuzu     Kuzu embedded graph DB  (one generic CkgNode table + one CkgEdge
                 table; `kind` is a column, `attrs` is JSON — open schema, ADR-0005)
  vectors.lance  LanceDB embedded vector index (cosine; ref → vector + filterable attrs)
  meta.json      IndexMeta { schema_version, indexed_commit, pack_versions, files{} }
  dirty.json     DirtySet  { consumer → [symbol ids] }
```

- **Kuzu** is synchronous + single-connection → every call runs on a worker
  thread (`asyncio.to_thread`) under one lock; multi-statement writes are atomic.
- **LanceDB** is async-native.
- Both are **embedded** (no server). The `Store` facade owns one of each and
  performs the vector→graph join for retrieval. Server backends (Neo4j, …) can
  register out-of-tree via the driver registry (ADR-0006).

---

## 8. Serving (feat-008)

The engine is exposed read-only to agents, from one tool definition, two ways:

```
 code_graph_tools(repo)  ─►  list[Tool]   ──►  Agent(tools=…)        (in-process)
 build_mcp_server(repo)  ─►  MCPServer    ──►  ckg serve-mcp         (stdio)

 10 tools: ckg_repo_map  ckg_search  ckg_symbol  ckg_impact  ckg_neighbors
           ckg_status    ckg_routes  ckg_decisions  ckg_explain  ckg_history
```

Every structured response carries a staleness envelope (`indexed_commit`,
`dirty`), a `truncated` flag, and `tool_api_version`. A lazy `_Engine` opens the
store on first call. This is the one place (with `enrich`) that imports
`agentforge`.

---

## 9. Configuration

One file: **`agentforge.yaml`**.

- **Framework keys** at the top level (strict validator; agent model, budget,
  MCP module).
- **Engine config** under the framework's `app:` passthrough (lenient,
  `extra=ignore`): `store`, `ingest`, `chunking`, `embed`, `retrieve`, `repomap`,
  `serve`, `frameworks`, `knowledge`, `enrich`, `temporal`. Each block is a typed
  `_Block` model with `.load()`; `config.resolve_config()` discovers the file and
  `_read_block` reads from `app.<key>` (or a top-level standalone `ckg.yaml`),
  using **plain pyyaml — no `agentforge` import** (ADR-0001).

---

## 10. Cross-cutting patterns

- **Injectable model adapters.** `Embedder` / `PatternJudge` / `Summarizer` are
  interfaces resolved by a **provider registry** (ENH-003). CI uses deterministic
  fakes (`FakeEmbedder`, `ScriptedJudge`, `ScriptedSummarizer`) — **no model calls
  in CI**. Live runs pick a provider from `ckg.yaml`: Bedrock (Claude + Cohere),
  the direct Anthropic API, OpenAI / local OpenAI-compatible embeddings, or an
  out-of-tree entry point. Adding a provider is a one-class change + an entry
  point; the orchestration/budget/heuristics are fully unit-tested. See
  [`guides/08-model-providers.md`](guides/08-model-providers.md).
- **Provenance discipline.** `parsed` < `resolved` < `manual`, and `llm` is
  second-class with a confidence + rationale. Retrieval can exclude all
  `llm`-derived facts wholesale (`include_llm_facts=False`).
- **Budget rails.** LLM enrichment runs under the framework `BudgetPolicy`;
  a tripped budget persists partial progress and leaves the rest dirty
  (resumable). Per-batch accounting keeps it correct under concurrency.
- **Dirty tracking.** `DirtySet` is the one staleness API every enricher reads
  (`embeddings`, `patterns`, `summaries`) — incremental re-enrichment only
  redoes what changed.
- **Conformance suites.** Storage adapters and language/framework packs prove
  they honour a contract by subclassing a reusable `*Conformance` base, so
  implementations are interchangeable.

---

## 11. End-to-end flow

```
  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌───────────────────────────┐
  │  index   │─► │  embed   │─► │  enrich  │─► │  query · map · decisions ·│
  │ (graph)  │   │(vectors) │   │(tags/sum)│   │  routes · explain         │
  └──────────┘   └──────────┘   └──────────┘   └─────────────┬─────────────┘
   parsed +       chunks +        llm facts                  │
   resolved +     summaries       (budgeted)         ckg serve-mcp
   framework +                                              │
   decisions                                     ┌──────────▼──────────┐
        │  incremental by default                │   Claude Code / IDE │
        └────────── re-run cheaply ◄─────────────│   (9 MCP tools)     │
                                                  └─────────────────────┘
```

Dogfood numbers (this 80-file repo): index 3.6 s · embed 512 chunks · enrich all
~$0.10 · query returns the right symbols with cosine scores · all on real code.

---

## 12. Extension points

| Want to add… | Do this |
|---|---|
| A language | A `LanguagePack` (`packs/<lang>/`: grammar + `structure.scm` + `references.scm` + `module_style`). |
| A framework (routes/ORM/DI) | A `FrameworkPack` (detection + `.scm` + facts merged into the `FileSubgraph`). |
| A storage backend | Implement `GraphStore`/`VectorStore`, pass `GraphStoreConformance`, register a driver. |
| An enricher | Drain a `DirtySet` consumer; emit `llm`-provenance facts via `store.add`; ride `BudgetPolicy`; use `clear_outgoing` for idempotent re-derivation. |
| A model provider | Implement `Embedder`/`PatternJudge`/`Summarizer`; the engine doesn't change. |
| A new agent tool | A `_CkgTool` subclass added to `ALL_TOOLS`. |

---

## 13. Map of the docs

```
docs/
  ARCHITECTURE.md     ← you are here (the overview)
  adr/                9 architecture decisions (the WHY)
  features/           feat-001..012 specs + TRACKER (the WHAT)
  design/             design-NNN per feature (the HOW, pre-build)
  bugs/ enhancements/ known-limitations/   (triaged findings, with templates)
  framework/          local-only: AgentForge/Kuzu learnings & workarounds
  open-source-ckg-research.md    the survey that motivates the design
```
