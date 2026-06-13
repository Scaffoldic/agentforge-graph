# agentforge-graph — feature tracker

Single board for all features: status, dependencies, what's ready to
pick, and milestones. Specs live alongside in
[`docs/features/`](.); catalogue in [`README.md`](README.md).

> **How to read this with the pipeline.** The workspace
> [development pipeline](../../../../.claude/development-pipeline.md)
> Stage 1 says: *pick the lowest-numbered `proposed` feature whose
> dependencies are all `shipped`*. The **Ready now** section below is
> that computation, kept current. Active per-feature work state lives
> in `.claude/state/current.md` once the project is scaffolded — this
> tracker is the planning/dependency view, not the live work log.

_Last updated: 2026-06-12 · **v0.1 MVP COMPLETE** — feat-001/002/003/005/006/
007/008 all shipped. `ckg index → embed → query/map`, served over MCP. Next:
the other nine language packs + features 004/009/010/011/012._

---

## Status snapshot

Legend: `proposed` → `accepted` → `in-progress` → `shipped` (also
`deferred` / `dropped`). **Ready** = every dependency is `shipped`.

| ID | Title | Layer | Target | Status | Depends on | Blocks | Ready? |
|---|---|---|---|---|---|---|---|
| [001](feat-001-graph-schema-and-core-contracts.md) | Graph schema & core contracts | 0 core | 0.1 | shipped | — | all | ✅ |
| [002](feat-002-tree-sitter-ingestion.md) | Tree-sitter ingestion (Python; rest follow-up) | 0 core | 0.1 | in-progress (PR pending) | 001 | 004,005,007,011 | 🔨 building |
| [003](feat-003-graph-storage-adapters.md) | Graph & vector storage adapters | 0 core | 0.1 | shipped | 001 | 004,005,007 | ✅ |
| [005](feat-005-ast-chunking-and-embeddings.md) | AST chunking & embeddings | 1 serve | 0.1 | shipped | 002,003 | 006,010 | ✅ |
| [007](feat-007-repo-map-summarization.md) | Budget-aware repo map | 1 serve | 0.1 | in-progress (PR pending) | 002,003 | 008 | 🔨 building |
| [006](feat-006-hybrid-retrieval.md) | Hybrid retrieval (vector+graph) | 1 serve | 0.1 | shipped | 005 | 008,010,012 | ✅ |
| [008](feat-008-mcp-server-and-tool-api.md) | MCP server & tool API | 1 serve | 0.1 | shipped | 006,007 | — | ✅ |
| [004](feat-004-incremental-indexing.md) | Incremental indexing | 2 incr | 0.2 | shipped | 002,003 | 009 | ✅ |
| [009](feat-009-temporal-evolution-layer.md) | Temporal / git evolution | 2 incr | 0.3 | proposed | 004 | — | ⛔ |
| [010](feat-010-adr-and-docs-ingestion.md) | ADR & docs ingestion | 3 diff | 0.3 | proposed | 005,006 | — | ⛔ |
| [011](feat-011-framework-extractors.md) | Framework-aware extractors | 3 diff | 0.4 | proposed | 002 | — | ⛔ |
| [012](feat-012-llm-enrichment.md) | LLM enrichment (summaries, tags) | 3 diff | 0.4 | proposed | 006 | — | ⛔ |

---

## Dependency graph

```mermaid
graph TD
    F001[001 schema & contracts]
    F002[002 ingestion · 10 langs]
    F003[003 storage adapters]
    F004[004 incremental]
    F005[005 chunking & embeddings]
    F006[006 hybrid retrieval]
    F007[007 repo map]
    F008[008 MCP & tools]
    F009[009 temporal]
    F010[010 ADR & docs]
    F011[011 framework extractors]
    F012[012 LLM enrichment]

    F001 --> F002 & F003
    F002 --> F004 & F005 & F007 & F011
    F003 --> F004 & F005 & F007
    F005 --> F006
    F006 --> F008 & F010 & F012
    F007 --> F008
    F005 --> F010
    F004 --> F009

    classDef mvp fill:#def,stroke:#48a;
    classDef incr fill:#efd,stroke:#7a4;
    classDef diff fill:#fed,stroke:#a74;
    class F001,F002,F003,F005,F006,F007,F008 mvp;
    class F004,F009 incr;
    class F010,F011,F012 diff;
```

Text form of the edges (parent → unblocks):

- **001** → 002, 003
- **002** → 004, 005, 007, 011
- **003** → 004, 005, 007
- **005** → 006, 010
- **006** → 008, 010, 012
- **007** → 008
- **004** → 009

---

## Build waves (max parallelism)

Each wave can start once the previous wave's features it depends on are
`shipped`. Within a wave, features are independent and parallelizable.

| Wave | Features | Notes |
|---|---|---|
| 1 | **001** | The only unblocked starting point. Everything waits on the schema. |
| 2 | **002**, **003** | Parallel once 001 ships. 002 is itself 10 parallel language packs. |
| 3 | **005**, **007**, **011**, **004** | All need only {002,003}; 011 needs just 002. |
| 4 | **006**, **009** | 006 needs 005; 009 needs 004. |
| 5 | **008**, **010**, **012** | 008 completes the MVP; 010/012 are differentiators. |

**Critical path to MVP** (feat-008 shippable):
`001 → 002 → 005 → 006 → 008` — 5 features deep. feat-003 and feat-007
ride alongside, not on, this chain.

---

## Version milestones

| Version | Theme | Features | Exit criterion |
|---|---|---|---|
| **0.1** | MVP: index any repo, query from an agent | 001, 002, 003, 005, 006, 007, 008 | `ckg index .` then drive the graph from Claude Code over MCP across the 10 languages |
| **0.2** | Keep it fresh cheaply | 004 | Re-index cost proportional to the diff; embeddings recompute only for dirty symbols |
| **0.3** | History + decisions | 009, 010 | Point-in-time queries; ADRs/docs govern code as graph edges |
| **0.4** | Framework & semantic knowledge | 011, 012 | Routes/ORM/DI edges; module summaries + design-pattern tags |

---

## v0.1 language scope (feat-002)

Top 10 by usage, two support tiers:

- **Tier A — structure + import resolution:** Python, TypeScript,
  JavaScript, Java, Go, C#, Rust, Ruby, PHP.
- **Tier B — structure + heuristic refs:** C++ (resolution best-effort
  via opt-in LSP-assist; ships `parsed`-only refs, never fake
  `resolved` edges).

Each language pack is an **independently mergeable unit** under
feat-002 — they share the pipeline and the `Extractor` conformance
suite, so packs can land on separate PRs (`feat/002-pack-go`, etc.)
without serializing the whole feature. **v0.2 candidates:** Kotlin,
Swift, C, Scala.

**Shipped packs:** Python (with feat-002), **TypeScript**
(`feat/002-pack-ts` — added `LanguagePack.module_style` so the resolver
handles relative path imports, not just dotted modules), **JavaScript**
(`feat/002-pack-js` — reuses the TS `relative` module style; only grammar
delta is the class-name node, and `.jsx`/`.mjs`/`.cjs` parse under the same
`javascript` grammar). Remaining v0.1 packs: java, go, c#, rust, ruby, php
(Tier A), c++ (Tier B).

---

## Project bootstrap (pre-feature, not numbered)

Scaffolded **on agentforge-py** via `agentforge new agentforge-graph
--template minimal --provider anthropic`. Status:

- ✅ Project scaffolded (`src/agentforge_graph/`, `agentforge.yaml`,
  `pyproject.toml`, AI-rules files, `docs/runbooks/`,
  `.agentforge-state/` for upgrades).
- ✅ Modules wired in `pyproject.toml`: **base** = `agentforge-py` +
  `agentforge-anthropic` + `agentforge-mcp`; **extras** = `engine`
  (tree-sitter + 10 grammars, kuzu, lancedb, fastembed, networkx),
  `rerank`, `neo4j`, `voyage`, `otel`. All resolve in `uv.lock`.
- ✅ Engine config in `ckg.yaml` (framework validator rejects unknown
  keys, so engine config is kept out of `agentforge.yaml`);
  `agentforge config validate` → OK.
- ✅ Import smoke passes (`from agentforge import Agent;
  import agentforge_graph`).
- ⬜ `git init` + first branch `feat/001-graph-schema-and-core-contracts`.
- ⬜ Project `.claude/` state (`current.md`, `log.md`) + pre-commit gate
  (set up when feat-001 work starts).

This is setup, not a graph feature, so it has no `feat-NNN` spec — it
follows the workspace pipeline's scaffold step.

---

## Change log

- **2026-06-12** — **v0.1 MVP COMPLETE.** feat-007 shipped; feat-008 (MCP
  server & tool API) implemented and in PR: six read-only tools
  (repo_map/search/symbol/impact/neighbors/status) bound as AgentForge
  `Tool`s + an MCP stdio server from one definition, `ckg serve-mcp`. Found
  and fixed a LanceDB reopen bug in feat-003. The 0.1 exit criterion is met
  for Python: `ckg index → embed → query/map`, driven from an agent over MCP.
- **2026-06-12** — feat-006 shipped. feat-007 (budget-aware repo map)
  implemented and in PR: personalized PageRank (dependency-free), budget
  render, `RepoMap`, `CodeGraph.repo_map`, `ckg map`. Extractor now stores
  symbol signatures. **Only feat-008 (MCP server) remains for the MVP.**
- **2026-06-12** — feat-005 shipped. feat-006 (hybrid retrieval) implemented
  and in PR: `Retriever` (context/impact/definition/similar modes),
  `ContextPack`, `GraphStore.adjacent` (directed traversal added to the
  contract), `CodeGraph.retrieve`, `ckg query`. Live relevance verified on
  real Bedrock. MVP critical path now only needs feat-008 (MCP server).
- **2026-06-12** — feat-002 shipped. feat-005 (AST chunking & embeddings)
  implemented and in PR: `CASTChunker`, `Embedder` (fake + AWS Bedrock
  Cohere embed-v4), `EmbedPipeline`, `CodeGraph.embed`, `ckg embed`. Chunk↔
  symbol linking via `CHUNK_OF`; vector hit → graph expansion. Embeddings
  default to Bedrock (fake for CI; live test env-gated). Next ready: feat-006
  (hybrid retrieval), feat-007 (repo map).
- **2026-06-12** — feat-001 + feat-003 shipped. feat-002 (tree-sitter
  ingestion) implemented for **Python** and in PR: RepoSource + language
  packs, two-pass extractor/resolver, `IngestPipeline`, `CodeGraph` facade,
  `ckg index` CLI. The other nine language packs are follow-up PRs over the
  same harness.
- **2026-06-12** — feat-001 shipped (PR #1 merged). feat-003 (graph &
  vector storage adapters) implemented and in PR: Kuzu + LanceDB embedded
  adapters, `Store` facade, `VectorStore` contract added to core.
- **2026-06-11** — Tracker created. 12 specs drafted (`proposed`).
  v0.1 indexed-language scope set to top 10 (Python, TS, JS, Java, Go,
  C#, Rust, Ruby, PHP, C++) with A/B support tiers. Decision to
  scaffold on agentforge-py recorded in bootstrap.
