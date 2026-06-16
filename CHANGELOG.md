# Changelog

All notable changes to **agentforge-graph** are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/), and the project aims to
follow [Semantic Versioning](https://semver.org/). Until 1.0 the on-disk index
schema may change between minor versions — the index is derivable, so the policy
on a schema mismatch is **rebuild** (ADR-0006).

## [Unreleased]

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
