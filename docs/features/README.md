# agentforge-graph — feature catalogue

Feature specs for the **agentforge-graph** agent: a Code Knowledge
Graph (CKG) engine + agent toolset built on the AgentForge framework.

Specs follow the workspace template
(`.claude/templates/feature.md`) and the workspace
[development pipeline](../../../../.claude/development-pipeline.md):
one feature = one branch (`feat/NNN-slug`) = one PR.

**Live status & dependencies:** [`TRACKER.md`](TRACKER.md) is the
single board — per-feature status, the dependency DAG, what's ready to
pick now, and the version milestones.

**v0.1 indexed-language scope:** top 10 by usage — Python, TypeScript,
JavaScript, Java, Go, C#, Rust, Ruby, PHP, C++ (C++ ships
structural-only; see feat-002 support tiers).

## Catalogue

| ID | Title | Layer | Status | Depends on |
|---|---|---|---|---|
| [feat-001](feat-001-graph-schema-and-core-contracts.md) | Graph schema & core contracts | 0 — structural core | proposed | none |
| [feat-002](feat-002-tree-sitter-ingestion.md) | Tree-sitter ingestion pipeline | 0 — structural core | proposed | feat-001 |
| [feat-003](feat-003-graph-storage-adapters.md) | Graph & vector storage adapters | 0 — structural core | proposed | feat-001 |
| [feat-004](feat-004-incremental-indexing.md) | Incremental indexing | 2 — incremental & temporal | proposed | feat-002, feat-003 |
| [feat-005](feat-005-ast-chunking-and-embeddings.md) | AST-aware chunking & embeddings | 1 — retrieval & serving | proposed | feat-002, feat-003 |
| [feat-006](feat-006-hybrid-retrieval.md) | Hybrid retrieval (vector + graph) | 1 — retrieval & serving | proposed | feat-005 |
| [feat-007](feat-007-repo-map-summarization.md) | Budget-aware repo map | 1 — retrieval & serving | proposed | feat-002, feat-003 |
| [feat-008](feat-008-mcp-server-and-tool-api.md) | MCP server & agent tool API | 1 — retrieval & serving | proposed | feat-006, feat-007 |
| [feat-009](feat-009-temporal-evolution-layer.md) | Temporal / git evolution layer | 2 — incremental & temporal | proposed | feat-004 |
| [feat-010](feat-010-adr-and-docs-ingestion.md) | ADR & docs ingestion | 3 — differentiator | proposed | feat-005, feat-006 |
| [feat-011](feat-011-framework-extractors.md) | Framework-aware extractors | 3 — differentiator | proposed | feat-002 |
| [feat-012](feat-012-llm-enrichment.md) | LLM enrichment: summaries & pattern tags | 3 — differentiator | proposed | feat-006 |
| [feat-013](feat-013-agent-auto-configuration.md) | Agent auto-configuration & frictionless first run | 4 — adoption | accepted | feat-008 |

## Layering (from the research doc §5)

- **Layer 0 — structural core**: table stakes every surveyed CKG tool
  has. Nodes/edges, parsing, storage. feat-001..003.
- **Layer 1 — retrieval & agent serving**: what makes the graph useful
  to LLM agents. feat-005..008.
- **Layer 2 — incremental & temporal**: re-index cost proportional to
  diff size; history as a first-class dimension. feat-004, feat-009.
- **Layer 3 — differentiators**: the gaps no surveyed open-source tool
  fills — ADRs, framework edges, design patterns. feat-010..012.

## Suggested build order

`001 → 002 → 003 → 005 → 007 → 006 → 008` gives a usable
end-to-end MVP (index a repo, query it from an agent over MCP).
`004 → 009` then make it cheap to keep fresh. `010 → 011 → 012`
add the differentiators.
