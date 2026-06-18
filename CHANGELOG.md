# Changelog

All notable changes to **agentforge-graph** are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/), and the project aims to
follow [Semantic Versioning](https://semver.org/). Until 1.0 the on-disk index
schema may change between minor versions — the index is derivable, so the policy
on a schema mismatch is **rebuild** (ADR-0006).

## [Unreleased]

### Added (unreleased, toward 0.3.0)

- **Commit-message ingestion (feat-010).** With `knowledge.commit_messages: on`, the
  last `commit_messages_limit` (50) git commit subjects that are conventional commits
  (`feat:`/`fix:`/…) or carry an issue ref (`#123`/`PROJ-45`) become `DocChunk`s that
  `DESCRIBES` the in-repo files they touched — so "why did the retry logic change?"
  reaches the commit and its code. Keyed by sha, added idempotently (re-index skips
  known shas). Read via `git log` (no framework import); off by default.

- **Code-vs-doc retrieval weighting (feat-010).** ADR/doc (`source_type: doc`)
  vector hits are scaled by `retrieve.doc_weight` (default 0.7) so code outranks
  equally-similar prose by default — mitigating doc-volume dilution. When the query
  smells architectural (`why`/`decision`/`design`/`convention`/…) the penalty is
  lifted and docs keep their full score. Applies to both the item score and its
  graph-expansion seed.

- **Incremental doc embedding (feat-010).** The doc-embed pass now fingerprints all
  DocChunks (ids + content hashes + embedder) under `.ckg/doc_embed.hash` and skips
  the whole pass when nothing changed — so `ckg embed` after an incremental refresh
  no longer re-embeds unchanged ADR/doc/docstring prose. Any doc change triggers a
  clean re-embed (orphan-safe for the small doc set).

- **General Markdown docs as `DESCRIBES` nodes (feat-010).** Docs matched by
  `knowledge.doc_globs` (e.g. `["**/*.md"]` — READMEs, guides) are sectioned into
  `DocChunk`s that `DESCRIBES` the code each section unambiguously mentions (a
  repo-relative path or a unique symbol name). No `Decision` node — docs *describe*,
  ADRs *govern*; ADR files are excluded (handled by the ADR pass). Each doc is its
  own per-file subgraph, so edits/deletes ride incremental indexing (with GC of
  removed docs); `IndexReport` gains `docs_indexed`/`describes_resolved`. Empty
  (off) by default.

- **Docstrings as `DESCRIBES` doc nodes (Python, feat-010).** A Python symbol's
  leading docstring (the first body string of a class/function/method) is now
  extracted as a `DocChunk` that `DESCRIBES` the symbol. The docstring prose
  becomes its own searchable node (embedded by the doc-chunk pass, `source_type:
  doc`); a vector hit on it seeds the symbol it describes, so a docstring-prose
  query reaches the code. Carried in the code file's subgraph, so it rides
  incremental indexing; symbols without a leading docstring get nothing. (JSDoc /
  Java-C# doc comments / module docstrings are follow-ups.)

- **`infer_governs` LLM pass for ADRs (feat-010).** An optional, budgeted matcher
  proposes `GOVERNS` edges for decisions whose prose names no code — matching the
  decision text against the repo's candidate symbols and writing edges with honest
  `llm` provenance + confidence + rationale. It only considers decisions with
  **zero parsed** GOVERNS (never overrides a deterministic link) and is idempotent
  on re-run. The matcher is injectable (`ScriptedMatcher` for tests,
  `ClaudeGovernsMatcher` over Bedrock/Anthropic via `enrich.provider`). Off by
  default — `ckg enrich --decisions` (or `CodeGraph.infer_governs`); USD-capped by
  `knowledge.infer_budget_usd`.

- **Embed ADR/doc prose for semantic search (feat-010).** The embed pass now embeds
  `DocChunk` prose (ADR sections) into the vector store, tagged `source_type: doc`
  (code chunks tagged `source_type: code`). A doc-chunk vector hit surfaces the
  chunk **and** seeds its containing `Decision`, which expands through `GOVERNS` to
  the code it governs — so an architectural query ("why is auth built this way?")
  reaches the decision and the governed code, not just prose. Clean-replaced by the
  `DocChunk` kind each embed run (GCs vectors for removed ADRs); `EmbedReport.
  doc_chunks` counts them. (Doc-incremental-by-hash and `source_type`-aware
  code-vs-doc retrieval weighting are follow-ups.)

_Work toward 0.3.0 (`0.3.0.dev0`). Open backlog: small BUG-006 resolver residuals
(ESM named-import aliases `import { a as b }` bind the original name; ESM
`export { x }` / re-export chains; C++ implicit-`this` bare calls) and the ENH-009
cross-encoder measurement campaign (on hold — needs the `rerank` extra + creds,
not runnable in CI). A fix-only 0.2.1 can still be cut off a branch if a small
fix lands first._

## [0.2.0] - 2026-06-18

A feature minor: the **temporal / git-evolution layer** (feat-009), a
**cross-encoder reranker** seam (ENH-009), and a deep **resolver-completeness
sweep** that brings intra-type method-call resolution to **all 10 language packs**
(BUG-006 #62–#72). Validated with a full pre-release pass (test suite, real-repo
resolver sweeps, temporal end-to-end, incremental==full, MCP-over-the-wire, a
Neo4j + pgvector server-backend e2e, and an agent dogfood over the 10 tools) —
no product bugs found. The on-disk index schema is unchanged from 0.1.0; the
temporal sidecar (`.ckg/temporal.db`) is opt-in and additive.

### Added (0.2.0)

- **C++ inline method modeling + `this->f()` resolution (BUG-006 residual).** The
  cpp pack now extracts inline struct/class method *definitions* (`double area()
  const { … }`) as `Method` symbols, and the reference query captures member/arrow
  call receivers (`this->f()` / `obj.f()` / `ptr->f()`). So `this->f()` binds to a
  method of the enclosing class — **intra-type method calls now resolve across all
  10 language packs** (C++ was the last with the gap). Any other receiver stays
  unresolved (ADR-0004); a bare implicit-`this` call (`area()` with no receiver)
  is left unresolved to avoid mis-binding to a same-named free function.

- **Aliased / submodule import resolution (Python, BUG-006 residual).** An aliased
  whole-module import (`import pkg.mathutils as mu`) now captures the alias as the
  module's local binding name, and a submodule named-import (`from pkg import
  mathutils`, where `mathutils` is a *module*, not a def of `pkg`) aliases the
  local name to that submodule and points the `IMPORTS` edge at the submodule
  file. Both feed the module-alias map, so `mu.f()` / `mathutils.f()` and
  qualified bases through them resolve. An aliased import of an *external* module
  stays unresolved (never guessed onto a same-named local, ADR-0004).

- **Qualified base resolution (Python / JS / TS, BUG-006 residual).** A qualified
  superclass — `class B extends mod.Base` / `class B(mod.Base)` — now resolves to
  the base class by splitting the receiver and binding it via the importing
  **module alias** (`import mod`, `const mod = require(...)`, `import * as mod from
  …`). This emits the `INHERITS` edge and lets inherited `self.f()`/`this.f()`
  calls resolve through it, where previously a member-expression base was not
  captured at all. ESM namespace imports (`import * as ns from "./m"`) are now
  captured for JS/TS as part of this (they previously produced no IMPORTS edge or
  alias). A qualified base whose receiver is not an imported module stays
  unresolved (never guessed, ADR-0004).

- **Export-member modeling (JavaScript, BUG-006 residual).** Assigned-property
  CommonJS exports whose value is an *anonymous* function are now extracted as
  `Function` symbols: `exports.foo = function(){}` / `= () => {}`,
  `module.exports.foo = …`, and inline-function values in a `module.exports = {
  foo: () => {} }` object literal. The property name is the export name. These
  previously had no symbol to bind to, so `m.foo()`, `const { foo } =
  require(...)`, and direct calls all went unresolved; they now resolve. Non-
  function assignments (`exports.x = someVar`, a re-export of an existing binding)
  do not mint a spurious symbol (ADR-0004). Shorthand object exports (`{ a, b }`
  naming top-level defs) already resolved and are unchanged.

- **Go receiver-method call resolution (BUG-006 residual).** Go's method receiver
  is a named variable (`func (s *Server) …`), not a `self`/`this` keyword, so the
  extractor now records each method's receiver var + type and the resolver indexes
  methods by `(package, type)`. A call on the method's own receiver (`s.f()`) binds
  to a method of that **type** — more precise than the prior bare-name match,
  which could hit another type's same-named method. With this, intra-type method
  calls resolve across all 9 of the 10 packs (C++ pending method modeling).

- **Inherited-method call resolution (Python).** A `self.f()` whose method is
  defined on a base class now resolves by walking the `INHERITS` superclass map —
  binding to the base method when exactly one base defines it (an own-class
  override wins; ambiguous multi-base definers stay unresolved, no MRO guessing).
  Recovers inherited-call edges for the template-method / base-helper patterns.
- **`INHERITS` edges + inherited-method calls (8 languages).** Class inheritance
  is now extracted and resolved — a class's base classes are bound to in-repo
  class nodes, emitting `INHERITS` edges (subclass → base) for same-file and
  imported bases, and `self.f()`/`this.f()` calls to a base method resolve via
  the superclass map. Covers **Python, TypeScript, JavaScript, Java, C#, Ruby,
  and PHP** (each pack captures its own `extends`/`<`/`:` superclass). The edge
  kind was in the locked vocab but never produced — repo-map centrality ranking
  and retrieval expansion already reference it, so this fills a real gap.
  External / by-name-only bases stay unresolved (never guessed, ADR-0004);
  implemented interfaces (a separate relation), qualified bases, and Rust/Go/C++
  (different inheritance models) are follow-ups.

- **Intra-class call resolution (BUG-006 residual).** The reference queries now
  capture the call *receiver*, so the resolver binds `self.f()` / `this.f()` /
  `$this->f()` to a method **of the enclosing class** — recovering the
  intra-class call graph (CALLS edges for impact/neighbors that were previously
  missing) across **Python, TypeScript, JavaScript, Java, C#, Rust, Ruby, and
  PHP**. It also stops a latent mis-bind: a member call on any other receiver
  (`obj.f()`) is left unresolved instead of being guessed onto a same-named
  module-level function (ADR-0004). Go (named-variable receiver), C++ (methods
  not yet modeled), and inherited-method calls remain follow-ups.
- **Module-member call resolution (BUG-006 residual).** `m.f()` where `m` is an
  imported module — a whole-module import (`import m`) or a default require
  (`const m = require("./m")`) — now binds to module `m`'s top-level export `f`,
  via a receiver→module alias map in the resolver. A non-module receiver is still
  never guessed (ADR-0004). Members that aren't top-level defs (object-literal /
  assigned-property exports) still need export-member modeling.
- **Cross-encoder reranker (ENH-009).** `retrieve.rerank: cross_encoder` adds a
  real semantic re-score of the top-k candidates via a `sentence-transformers`
  cross-encoder (the `rerank` extra; `rerank_model` to override), blended with
  the base score. The model is lazy-loaded behind a `CrossScorer` seam so the
  base install and CI stay torch-free. Also **fixes** the MCP engine, which
  built its retriever without a reranker — so `retrieve.rerank` (lexical or
  cross-encoder) was silently ignored over MCP and now applies on both the CLI
  and agent-tool paths. Opt-in; default stays `off` pending a measurement
  campaign.
- **Temporal layer — `as_of` + retention (feat-009, chunk 5, completes feat-009).**
  `CodeGraph.retrieve(as_of=<commit>)` and `ckg query --as-of <commit>`
  reconstruct results as they were at a commit: `TemporalIndex.alive_at(C)`
  replays the log over the current node set (a symbol is alive iff its last
  lifecycle event at/before `C` is `OPENED`), and the Retriever drops code
  symbols added after `C`. A commit older than the `retention_commits` horizon
  raises `TemporalError` rather than answering wrong. Retention pruning of old
  `CLOSED` events runs at the end of each index/refresh. Verified by a
  per-commit equivalence property: `alive_at(C)` equals the symbol set a full
  index at `C` produces, for every backfilled commit.
- **Temporal layer — history backfill (feat-009, chunk 4).** `ckg index
  --history N` (or `--history full`) seeds the evolution log for code that
  predates temporal adoption: it replays the last N commits oldest→newest
  through the incremental pipeline against a **throwaway** store (file content
  read from git via `git ls-tree`/`git show` — no checkout, the HEAD index and
  embeddings are untouched), recording each symbol's `OPENED`/`CLOSED`. A
  symbol's earliest `OPENED` then becomes its **true introduction commit**, so
  `history().introduced` is no longer window-bounded for pre-existing code, and
  symbols deleted before HEAD get their lifecycle recorded (for `as_of`).
  Resumable via a `backfilled_through` cursor (surfaced in `ckg status`); churn
  mining is skipped during replay (a HEAD-time signal).
- **Temporal layer — read APIs (feat-009, chunk 3).** A `TemporalIndex`
  (`history` / `changed_since` / `authors` / `churn`) reads the sidecar to answer
  the questions an agent asks after a regression. New CLI: `ckg history <symbol>`
  (introduced / last-changed / churn / authors / lifecycle events) and
  `ckg changed-since <ref> [--scope GLOB]` (symbols changed since a ref, newest
  first); `ckg status` gains a `temporal:` line. New MCP tool **`ckg_history`**.
  `introduced` prefers the exact chunk-1 `OPENED` event over the window-bounded
  mined estimate. Read-only; still opt-in.
- **Temporal layer — churn / authorship (feat-009, chunk 2).** When `temporal`
  is enabled, a refresh now mines `git log` over a bounded window and attributes
  each diff hunk to the symbol whose span it overlaps, storing bounded
  per-symbol aggregates (`churn_30d/90d`, `top_authors`, `introduced`,
  `last_changed`) in the `.ckg/temporal.db` sidecar and **denormalising** them
  onto each symbol's node `attrs`. `ckg_symbol` / retrieval surface these on the
  item (`temporal: {…}`) for free. New `GraphStore.set_attrs` — a partial-attrs
  merge that preserves file ownership (Kuzu + Neo4j). Still opt-in and off by
  default; chunk 1 (sidecar + lifecycle) shipped earlier in this cycle.

## [0.1.0] — 2026-06-16

First production-grade release: a deterministic **Code Knowledge Graph** engine
plus an agent tool surface, built on the AgentForge framework. The whole pipeline
— `index → embed → enrich → query / map / decisions / routes / explain` — works
end-to-end on real code across ten languages, and a real agent answers real
questions over the tools, unattended.

### Languages (10 packs, each validated on a real OSS repo)

- **Python**, **TypeScript**, **JavaScript**, **Go**, **Ruby**, **PHP**,
  **Java**, **C#**, **Rust**, and **C++** (Tier B). Each pack extracts the
  language's real symbol surface and resolves imports per its actual model:
  file-level (Py/TS/JS), directory-package + `go.mod` (Go), `require_relative`
  wildcard (Ruby), namespace/FQN (PHP/Java), namespace-prefix (C#), path-derived
  modules (Rust), and relative `#include` (C++). Validated on click, zod,
  express/chalk, cobra, thor, monolog, gson, Newtonsoft.Json, fmt, serde_json.

### Engine

- **Two-pass ingestion** (feat-002): file-isolated tree-sitter extraction →
  graph-only import/call resolution. Conservative — an edge is created only on a
  unique match; ambiguous/external refs are tallied, never guessed (ADR-0004).
- **Incremental indexing** (feat-004): content-hash change detection + scoped
  re-extract/re-resolve; `ckg index` is incremental by default (`--full` to force).
  Correctness held by a `refresh == full` equivalence property test.
- **Storage** (feat-003, ENH-004): embedded **Kuzu** (graph) + **LanceDB**
  (vectors) by default; opt-in **Neo4j** and **pgvector** server backends behind
  the driver registry, each passing the same conformance suite (verified in CI
  against live containers).
- **AST chunking + embeddings** (feat-005): Cohere embed-v4 on Bedrock, OpenAI /
  local OpenAI-compatible, or a deterministic fake for CI.
- **Budget-aware repo map** (feat-007): dependency-free personalized PageRank, with
  a public-API orientation bias (ENH-007).
- **Hybrid retrieval** (feat-006): vector entry → typed graph expansion →
  provenance-weighted merge. Optional opt-in lexical reranker (ENH-009).

### Differentiators

- **ADR / decision ingestion** (feat-010): `Decision` nodes with parsed
  `GOVERNS`/`SUPERSEDES`, surfaced in retrieval and via `ckg decisions`.
- **Framework-aware extraction** (feat-011): FastAPI routes → `Route` +
  `HANDLED_BY`, riding the incremental FileSubgraph.
- **LLM enrichment** (feat-012): design-pattern tags + bottom-up summaries via a
  budgeted, resumable, idempotent judge (Claude on Bedrock / Anthropic API),
  pluggable provider registry (ENH-003).

### Serving / consumption

- **MCP server** (feat-008): nine read-only tools (`ckg_search`, `ckg_repo_map`,
  `ckg_symbol`, `ckg_impact`, `ckg_neighbors`, `ckg_status`, `ckg_routes`,
  `ckg_decisions`, `ckg_explain`) over **stdio** and **streamable-HTTP**; the same
  `Tool` instances back `code_graph_tools()` for in-process agents.
- **HTTP auth** (ENH-005): optional bearer-token gate (`401` on mismatch, never
  logged) + bind-safety (a non-loopback bind without a token is refused).
- **`ckg` CLI**: `index`, `status`, `embed`, `query`, `map`, `routes`,
  `decisions`, `enrich`, `summaries`, `tagged`, `serve-mcp` — uniform repo-path
  argument (ENH-006).

### Validation

- Every language pack validated on ≥1 real OSS repo, with a creds-enabled
  (embed + retrieval + enrich) run; bugs found-and-fixed along the way
  (BUG-001…008). A real `Agent` answered questions over the tools unattended,
  on both Python and Go repos (W4 + cross-language dogfood). See `docs/validation/`.
- **Pre-release validation pass** on real repositories: incremental indexing is
  byte-identical to a full re-index on real churn (`pallets/click`, modulo
  provenance — fixed BUG-007, an overload-resolution non-determinism); the MCP
  transports drive a real client over stdio + authed HTTP end-to-end; the
  Neo4j + pgvector server path holds through `index → embed → enrich → query`
  on a real repo (fixed BUG-008, a default-config `ckg query` break); and parse
  coverage holds at scale (`django`, 2922 files, ~100%, no crash).

[Unreleased]: https://github.com/Scaffoldic/agentforge-grpah/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Scaffoldic/agentforge-grpah/releases/tag/v0.1.0
