# Open-Source Code Knowledge Graph (CKG) Landscape — Research

> Research input for designing our own code-knowledge-graph agent.
> Compiled 2026-06-11 from a multi-source web research sweep (22 sources,
> 110 extracted claims, 17 adversarially verified). Claims marked
> **[verified]** passed 2–3 independent verification votes against the
> cited primary source; claims marked **[unverified]** come from primary
> docs / model knowledge but could not complete verification in this run.

---

## 1. The landscape at a glance

Open-source CKG tooling falls into five rough families. No single tool
covers everything we want; each family optimizes a different axis.

| Family | Representative tools | Optimizes for |
|---|---|---|
| Compiler-grade analysis graphs | Joern (CPG), CodeQL, Glean | Semantic precision (data flow, control flow, types) |
| Code-intelligence indexers | Sourcegraph SCIP, GitHub stack-graphs, LSIF | Fast, precise def/ref navigation at scale |
| Tree-sitter graph builders | code-graph-rag, FalkorDB code-graph, Codebase-Memory, CocoIndex pipelines | Cheap multi-language structural graphs |
| GraphRAG / agent-memory frameworks | cognee, Graphiti, Neo4j GraphRAG recipes | LLM retrieval over graph + vectors |
| Agent platforms with built-in CKG | Potpie, Blar(ify), Aider repo-map | End-to-end agent workflows on a code graph |

---

## 2. Tool profiles

### 2.1 Joern / Code Property Graph (CPG)

- **What it is:** Platform for analyzing source code, bytecode, and binary
  executables by generating Code Property Graphs — a unified graph
  representation for cross-language analysis combining AST, control flow,
  and data flow. **[verified]** (github.com/joernio/joern)
- **Nodes:** `METHOD` (functions/procedures), `TYPE_DECL`, `FILE`, `LOCAL`,
  `MEMBER`, `CALL` (call sites), namespaces, annotations, control
  structures. **[verified]** (cpg.joern.io)
- **Edges:** AST edges; `CALL` (call site → invoked method);
  `INHERITS_FROM` (type hierarchy); `REACHING_DEF` (data flow);
  `CFG`/`CDG`/`DOMINATE` (control flow & dependence). **[verified]**
- **Parsing:** Language-agnostic IR produced by per-language
  compiler/fuzzy-parser frontends (reserved frontends include C, LLVM,
  GHIDRA, PHP) — not tree-sitter, not LSP. **[verified]**
- **Languages:** C, C++, Java, JavaScript, Python, Kotlin, plus binaries.
  **[verified]**
- **Storage:** Custom embedded graph database; v4.0.0 migrated from
  `overflowdb` to `flatgraph`. **[verified]**
- **Higher-level knowledge:** None — no ADRs, design patterns, or
  framework edges. Query language (CPGQL/Scala) could express pattern
  detectors, but nothing ships out of the box.
- **Takeaway for us:** the richest *edge vocabulary* in the ecosystem
  (call + inheritance + data flow + control flow). Heavyweight; aimed at
  security analysis, not LLM retrieval.

### 2.2 CodeQL (GitHub)

- **What it is:** Compiles code into a relational database queried with a
  Datalog-like language (QL). Source-available (queries are MIT; the CLI
  is free for OSS/research but not fully open-source — licensing matters
  if we build on it).
- **Languages:** C/C++, C#, Go, Java/Kotlin, JavaScript/TypeScript,
  Python, Ruby, Swift, Rust, GitHub Actions workflows. **[unverified —
  verifier quota hit; matches official docs]**
- **Parsing:** Compiler-grade for compiled languages — Java via
  javac/Eclipse compiler, C/C++ via instrumenting real compiler
  toolchains, Rust via cargo — i.e., a working build is generally
  required. **[unverified]**
- **Framework knowledge:** Ships built-in semantic models for major
  frameworks (Spring/Hibernate for Java, Django/Flask/FastAPI for Python,
  Express/React for JS, Rails for Ruby, Entity Framework for C#) — it
  understands routes, ORM relations, and taint sources/sinks per
  framework. **[unverified]** This is the *only* tool in the survey with
  systematic framework-specific modeling — but it's encoded as query
  libraries, not exported as graph edges.
- **Takeaway for us:** proof that framework-aware modeling is done via
  curated per-framework rule packs, not inference. Build requirement and
  licensing make it a poor foundation; a good *reference* for framework
  edge taxonomy.

### 2.3 Sourcegraph SCIP

- **What it is:** Protobuf-based code indexing format, successor to LSIF,
  centered on human-readable string symbol IDs (def/ref) instead of
  LSIF's opaque numeric graph IDs with monikers/resultSets.
  **[verified]** (sourcegraph.com/blog/announcing-scip)
- **Entities:** symbols (definitions, references, hover docs,
  relationships like implementation/type-definition). File-and-symbol
  granularity; no call graph, no CFG.
- **Languages:** at launch (June 2022): scip-typescript (TS/JS) and
  scip-java (Java, Scala, Kotlin); Python planned. **[verified]** Today
  the indexer family covers most mainstream languages.
- **Parsing:** per-language indexers built on real compilers/type
  checkers (e.g., tsc, javac) — precise, but needs resolvable builds.
- **Incremental:** stable string symbol IDs were explicitly designed to
  enable file-level incremental indexing (stated as future work at
  launch). **[verified]**
- **Takeaway for us:** SCIP is an *interchange format*, not a graph
  store. Its symbol-ID scheme (`scheme manager package version descriptor`)
  is a great design to steal for stable node identity across commits.

### 2.4 GitHub stack-graphs

- **What it is:** Extension of scope graphs (Visser et al.); name binding
  is encoded as a graph where paths represent valid bindings, and
  resolving a reference is path-finding. Powers GitHub Precise Code
  Navigation. **[verified]** (arxiv.org/pdf/2211.01224)
- **Parsing:** purely syntactic — declarative `tree-sitter-graph` DSL on
  top of tree-sitter; per-language rules written once; zero per-project
  configuration and no build step. **[verified]**
- **Incremental:** file-incremental by construction — each file gets an
  isolated disjoint subgraph with no visibility into other files, so a
  commit only reparses changed files. **[verified]**
- **Takeaway for us:** the best incremental-indexing *architecture* in
  the survey: per-file subgraphs + cross-file resolution deferred to
  query time. Note: the project is now in maintenance mode at GitHub, but
  the design is well documented.

### 2.5 Glean (Meta)

- **What it is:** Meta's code indexing system, open-sourced August 2021;
  stores code facts (declarations, references, call/inheritance
  relationships, type signatures, docs) in a schema-flexible fact
  database backed by RocksDB. **[verified]** (engineering.fb.com)
- **Languages:** at Meta: C++, Python, PHP, JavaScript, Rust, Erlang,
  Thrift, Haskell — language-specific indexers feeding a
  language-agnostic store. **[verified]**
- **Schema:** Angle — a typed, declarative schema/query language; each
  language defines fact predicates, with shared cross-language
  abstractions (the `codemarkup` layer).
- **Incremental:** stacked immutable databases — layers non-destructively
  add or hide facts from layers below, making incremental indexing
  proportional to change size. **[unverified — verifier quota hit]**
- **Takeaway for us:** "facts + typed schema + derived predicates" is a
  clean separation between raw extraction and inferred knowledge.
  Operationally heavy (Haskell stack, RocksDB service).

### 2.6 cognee (topoteretes/cognee)

- **What it is:** Open-source "memory for AI agents" — ECL
  (Extract-Cognify-Load) pipelines combining a knowledge graph with
  vector search. Has a dedicated code-graph pipeline.
- **Nodes:** `Repository`, `CodeFile`, `ImportStatement`,
  `FunctionDefinition`, `ClassDefinition`, `CodePart`,
  `SourceCodeChunk`. **Edges:** `part_of` (file→repo), `depends_on`
  (file→imports), `provides_function_definition` /
  `provides_class_definition`. **[verified]** (CodeGraphEntities.py)
- **Parsing:** tree-sitter, shipped as an optional `codegraph` extra that
  pins only `tree-sitter-python` — first-class code-graph support is
  effectively Python-only today. **[verified]**
- **Storage:** pluggable — graph adapters for Kuzu, Neo4j, AWS Neptune,
  Postgres; vector adapters for ChromaDB, LanceDB, pgvector.
  **[verified]**
- **LLM integration:** native — graph-aware retrieval, summarization
  nodes, MCP server.
- **Takeaway for us:** the closest architectural cousin to what we want
  (graph + vectors + LLM enrichment, pluggable stores), but its code
  schema is shallow: no call edges, no inheritance edges, single
  language.

### 2.7 Graphiti (Zep)

- **What it is:** Open-source temporally-aware knowledge graph engine for
  agent memory — bi-temporal model (event time + ingestion time), entity
  extraction via LLM, Neo4j/FalkorDB backends. Not code-specific: no
  parser, no code schema out of the box; you'd define code entities as
  custom Pydantic entity types. **[unverified — model knowledge]**
- **Takeaway for us:** relevant for the *temporal* dimension (how the
  graph evolves across commits, when a fact became true/false) and for
  episodic memory of agent interactions layered over a code graph.

### 2.8 Potpie (potpie-ai/potpie)

- **What it is:** Open-source platform that builds a knowledge graph of a
  repo (Neo4j) and runs specialized agents on it (debugging, Q&A,
  test generation, low-level design). Parses with tree-sitter +
  language-specific resolution; nodes for files/classes/functions with
  call and import relationships; vector embeddings of node content
  for retrieval; agents query the graph as tools. **[unverified — from
  project docs/README, verification not completed]**
- **Takeaway for us:** the best existing example of "agents on top of a
  CKG" packaging — knowledge graph + agent toolset + custom-agent API.

### 2.9 FalkorDB code-graph / Blar (blarify)

- **FalkorDB code-graph:** demo app + `code-graph-backend` that indexes a
  repo into FalkorDB (RedisGraph successor; sparse-matrix Cypher engine)
  using tree-sitter analyzers (Python, Java, more in progress); nodes for
  files/classes/functions, call & define edges; visual exploration UI.
  **[unverified]**
- **Blarify (blar-ai):** open-source layer that builds a graph of a
  codebase (files, classes, functions; relationships like contains,
  calls, inherits) using tree-sitter + LSP servers for reference
  resolution, exporting to Neo4j or FalkorDB. Used as the foundation for
  Blar's debugging agents. **[unverified]**
- **Takeaway for us:** tree-sitter for structure + LSP for resolution is
  a pragmatic two-tier accuracy model worth copying.

### 2.10 Aider repo-map

- **What it is:** Not a persistent graph — an on-the-fly "repo map" fed
  into LLM context. Uses tree-sitter to extract defs/refs per file, then
  ranks symbols with **graph centrality (PageRank over the def/ref
  graph)**, personalized by files currently in the chat, and packs the
  top-ranked signatures into a token budget. **[unverified — from
  aider.chat/docs/repomap.html]**
- **Takeaway for us:** the key idea is *budget-aware graph
  summarization* — ranking the graph to fit a context window. Our agent
  needs this as a retrieval/serving feature regardless of storage design.

### 2.11 Lightweight tree-sitter indexers (code-graph-rag, Codebase-Memory, CocoIndex)

- **code-graph-rag (vitali87):** multi-language repos → graph
  (functions, classes, modules; call/import edges) in Memgraph/Neo4j,
  natural-language Cypher querying via LLM. **[unverified]**
- **Codebase-Memory MCP:** claims 66 languages via tree-sitter grammars
  in a single binary, with LSP-style type resolution (per-file
  TypeRegistry: variable bindings, scope chains, return-type propagation)
  for Go/C/C++, storing the graph in a single SQLite file (WAL); exposed
  to agents over MCP. **[unverified — verifier quota hit]**
  (arxiv.org/html/2603.27277)
- **CocoIndex:** incremental data-pipeline framework with a documented
  recipe for tree-sitter chunking + embedding of codebases (Postgres/
  pgvector), strong on *incremental recomputation* (only changed inputs
  reprocess). **[unverified]**
- **Takeaway for us:** SQLite/Kuzu-style embedded storage + MCP is the
  emerging packaging for "CKG as a local agent tool" — zero-ops, runs in
  CI or on a laptop.

### 2.12 Neo4j codebase-knowledge-graph recipes

- Neo4j developer-blog material shows the common DIY pattern: parse with
  tree-sitter, create `(:File)-[:CONTAINS]->(:Class)-[:HAS_METHOD]->(:Method)`,
  `[:CALLS]`, `[:IMPORTS]` edges, add embeddings on node properties, and
  query via Cypher + vector index. Useful as schema reference, not a
  product. **[unverified]**

---

## 3. Cross-cutting findings

### 3.1 Chunking strategies for embeddings/RAG

- Naive fixed-size/line-based chunking is the baseline everyone is moving
  away from for code.
- **cAST (arxiv 2506.15655):** structure-aware chunking — recursively
  split oversized AST nodes and greedily merge small sibling nodes under
  a size budget, keeping chunks syntactically whole. Reported gains:
  +4.3 Recall@5 on RepoEval retrieval, +2.67 Pass@1 on SWE-bench
  end-to-end. **[unverified — verifier quota hit; numbers from the paper
  abstract]**
- cognee's schema explicitly separates `CodePart` / `SourceCodeChunk`
  from semantic entities **[verified]** — chunks are *linked to* graph
  nodes rather than being the nodes. That "chunk ↔ symbol" bipartite
  linking is the pattern to adopt.
- Aider's repo-map shows the complementary serving-side idea: signatures
  (not bodies) + centrality ranking under a token budget.

### 3.2 Incremental indexing

Three proven designs, in increasing complexity:

1. **File-incremental subgraphs** (stack-graphs): each file's subgraph is
   self-contained; cross-file name resolution happens at query time via
   path-finding. Only changed files re-index. **[verified]**
2. **Stable symbol IDs** (SCIP): deterministic, human-readable global
   symbol names make per-file index merging possible without global ID
   reassignment. **[verified that this was the design intent]**
3. **Stacked immutable fact layers** (Glean): incremental layers
   add/hide facts over a base snapshot; cost proportional to diff size.
   **[unverified]**

For a git-native agent, (1)+(2) combine naturally: per-file extraction
keyed by content hash, stable symbol IDs, cross-file edges resolved in a
separate cheap pass.

### 3.3 The gaps nobody fills (our opportunity)

Across all 15+ tools surveyed, **none** of the following are captured as
first-class graph citizens:

- **ADRs / architecture decisions.** No tool parses `docs/adr/*.md`,
  RFCs, or design docs and links decisions to the code they govern.
  ADR tooling (adr-tools, log4brains, MADR) exists but is completely
  disconnected from code graphs.
- **Design patterns.** Academic detectors exist; no surveyed CKG tool
  tags `Factory`, `Repository`, `Observer`, etc. as nodes/labels.
- **Framework-specific edges.** Only CodeQL models frameworks (routes,
  ORM relations, DI) — and only inside its query libraries, not as an
  exportable graph. No tree-sitter-family tool emits
  `(:Route)-[:HANDLED_BY]->(:Function)` or
  `(:Model)-[:HAS_MANY]->(:Model)` edges.
- **Documentation ↔ code linkage.** READMEs, docstrings, comments, commit
  messages, and issues are at best embedded as text, never structured
  into the graph with provenance.
- **Temporal/evolution layer.** Only Graphiti (not code-specific) models
  time. No CKG answers "when did this dependency appear and why."

---

## 4. Feature comparison matrix

Legend: ● full / ◐ partial / ○ none.  (Unverified cells follow the same
sourcing caveats as §2.)

| Feature | Joern | CodeQL | SCIP | stack-graphs | Glean | cognee | Potpie | Blarify | FalkorDB cg | Aider map | Graphiti |
|---|---|---|---|---|---|---|---|---|---|---|---|
| File/module nodes | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ○ |
| Function/class nodes | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ○ |
| Import edges | ● | ● | ◐ | ● | ● | ● | ● | ● | ◐ | ◐ | ○ |
| Call edges | ● | ● | ○ | ○ | ● | ○ | ● | ● | ● | ◐ | ○ |
| Inheritance edges | ● | ● | ◐ | ○ | ● | ○ | ◐ | ● | ◐ | ○ | ○ |
| Data/control flow | ● | ● | ○ | ○ | ◐ | ○ | ○ | ○ | ○ | ○ | ○ |
| Multi-language (5+) | ● | ● | ● | ● | ● | ○ | ◐ | ◐ | ◐ | ● | n/a |
| No-build parsing (tree-sitter) | ○ | ○ | ○ | ● | ○ | ● | ● | ● | ● | ● | n/a |
| Incremental indexing | ◐ | ◐ | ◐ | ● | ● | ◐ | ◐ | ◐ | ○ | ● | ● |
| Embeddings / vector RAG | ○ | ○ | ○ | ○ | ○ | ● | ● | ◐ | ◐ | ○ | ● |
| LLM/agent integration (MCP/tools) | ○ | ◐ | ○ | ○ | ◐ | ● | ● | ● | ◐ | ● | ● |
| Framework edges (routes/ORM/DI) | ○ | ◐* | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| Design-pattern tagging | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| ADR / decision capture | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| Temporal / evolution model | ○ | ○ | ○ | ○ | ◐ | ○ | ○ | ○ | ○ | ○ | ● |

\* CodeQL models frameworks inside query libraries, not as exported graph edges.

---

## 5. Consolidated feature list for our agent

A candidate scope, layered so we can phase it. (This is the discussion
input — nothing here is decided.)

### Layer 0 — Structural core (table stakes; every tool has this)
1. Nodes: `Repository`, `Package/Module`, `File`, `Class`, `Function/Method`,
   `Variable/Constant`, `Interface/Trait`.
2. Edges: `CONTAINS`, `IMPORTS`, `CALLS`, `INHERITS`, `IMPLEMENTS`,
   `REFERENCES`.
3. Tree-sitter parsing (no build required), multi-language from day one
   via per-language extraction rules (stack-graphs' declarative-DSL
   approach is the model).
4. Stable, human-readable symbol IDs (SCIP-style) for cross-commit node
   identity.

### Layer 1 — Retrieval & agent serving
5. AST-aware chunking (cAST-style split/merge), with chunks *linked to*
   symbol nodes (cognee's pattern), embedded into a vector index.
6. Hybrid retrieval: vector search → graph expansion (neighbors,
   callers/callees) → rerank.
7. Budget-aware repo summarization (Aider-style PageRank over def/ref
   graph, packed to a token budget).
8. MCP server + tool API so any agent (including Claude Code) can query
   the graph.

### Layer 2 — Incremental & temporal
9. File-incremental indexing: per-file subgraphs keyed by content hash;
   cross-file edge resolution as a separate cheap pass (stack-graphs
   design).
10. Git-native temporal layer: nodes/edges carry `valid_from`/`valid_to`
    commits (Graphiti's bi-temporal idea applied to code).

### Layer 3 — Differentiators (the gaps in §3.3 — nobody does these)
11. **ADR ingestion:** parse `docs/adr/`, MADR/log4brains formats, RFCs;
    `(:Decision)-[:GOVERNS]->(:Module|:Dependency)` edges; link
    superseded decisions.
12. **Framework-aware extractors:** pluggable per-framework rule packs
    emitting real edges — `(:Route)-[:HANDLED_BY]->(:Function)`,
    `(:Model)-[:HAS_FIELD|:HAS_MANY]->`, `(:Service)-[:INJECTED_INTO]->`
    (FastAPI/Django/Spring/Express first). CodeQL's framework model
    catalog is the taxonomy reference.
13. **Design-pattern tagging:** LLM-assisted classification of
    classes/modules into pattern roles (`:Singleton`, `:Factory`,
    `:Repository`…), stored as labels with confidence + provenance.
14. **Docs/commit linkage:** docstrings, READMEs, commit messages, and
    PR/issue references attached as `(:DocChunk)-[:DESCRIBES]->` edges
    with provenance.
15. **LLM enrichment pass:** generated summaries per module/subsystem as
    first-class nodes (community-summary idea from GraphRAG), refreshed
    incrementally.

### Storage recommendation (to discuss)
- Embedded-first: **Kuzu** or **SQLite** for zero-ops local/CI use, with
  an optional **Neo4j/FalkorDB** adapter for shared deployments —
  cognee's pluggable-adapter pattern. Vector side: LanceDB or pgvector.

---

## 6. Sources

Primary: [github.com/joernio/joern](https://github.com/joernio/joern) ·
[cpg.joern.io](https://cpg.joern.io/) ·
[sourcegraph.com/blog/announcing-scip](https://sourcegraph.com/blog/announcing-scip) ·
[stack-graphs paper (arxiv 2211.01224)](https://arxiv.org/pdf/2211.01224) ·
[Glean at Meta (engineering.fb.com)](https://engineering.fb.com/2024/12/19/developer-tools/glean-open-source-code-indexing/) ·
[CodeQL supported languages & frameworks](https://codeql.github.com/docs/codeql-overview/supported-languages-and-frameworks/) ·
[github.com/topoteretes/cognee](https://github.com/topoteretes/cognee) ·
[github.com/potpie-ai/potpie](https://github.com/potpie-ai/potpie) ·
[cAST paper (arxiv 2506.15655)](https://arxiv.org/abs/2506.15655) ·
[Codebase-Memory (arxiv 2603.27277)](https://arxiv.org/html/2603.27277v1) ·
[aider.chat/docs/repomap.html](https://aider.chat/docs/repomap.html) ·
[code-graph-rag.com](https://code-graph-rag.com/)

Secondary/blogs: FalkorDB code-graph blog · Neo4j codebase-knowledge-graph
blog · cognee repo-to-knowledge-graph deep dive · CocoIndex tree-sitter
indexing post · rywalker.com code-intelligence tools survey ·
grahambrooks.com building-a-code-knowledge-graph-for-ai-agents ·
andrew.ooo CodeGraph review · Sourcegraph "running code intelligence
in-house".
