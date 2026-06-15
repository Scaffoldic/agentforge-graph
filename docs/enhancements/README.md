# Enhancements

Things that **work correctly** but could be better — quality, recall, speed,
ergonomics. Distinct from bugs (incorrect) and known-limitations (inherent).

One file per enhancement: `ENH-NNN-short-slug.md`. Keep this index current.

## Index

| ID | Title | Value | Effort | Area | Status |
|---|---|---|---|---|---|
| [ENH-001](ENH-001-pattern-recall-tuning.md) | Improve pattern-tag candidate recall | Medium | M | enrich.heuristics | done |
| [ENH-002](ENH-002-parallelize-enrichment-calls.md) | Parallelize summary/judge LLM calls | Medium | S–M | enrich | done |
| [ENH-003](ENH-003-pluggable-model-provider-registry.md) | Pluggable model-provider registry (consumer LLM/embeddings choice) | High | M | embed/enrich | done (phase 1 + 2) |
| [ENH-004](ENH-004-first-party-storage-backends.md) | First-party storage backends (Neo4j/pgvector) | Med–High | M–L | store | done |
| [ENH-005](ENH-005-http-mcp-transport-auth.md) | AuthN/AuthZ for the HTTP MCP transport | High | M | serve | done |
| [ENH-006](ENH-006-cli-path-arg-consistency.md) | Unify the repo-path arg across `ckg` subcommands | Medium | S | cli | done |
| [ENH-007](ENH-007-repomap-public-api-orientation.md) | Bias the repo map toward the public API | Medium | S–M | repomap | done |
| [ENH-008](ENH-008-typescript-symbol-completeness.md) | Broaden TS/JS symbol extraction (interfaces/enums/types/arrow-consts) | Med–High | M | ingest.packs | done |
| [ENH-009](ENH-009-retrieval-precision-dense-codebases.md) | Sharpen retrieval precision on dense / comment-sparse codebases (rerank/anchoring) | High | M | retrieve | partial (opt-in lexical rerank) |

## Template

```markdown
# ENH-NNN: <title>

| Field | Value |
|---|---|
| **ID** | ENH-NNN |
| **Value/Impact** | High / Medium / Low |
| **Effort** | S / M / L |
| **Status** | proposed / accepted / done |
| **Area** | package / module |
| **Relates to** | feat-NNN |

## Motivation
Why it matters; the observed gap.

## Current behavior
What happens today (with refs).

## Proposed change
Concretely what to do.

## Acceptance criteria
How we know it's done.

## Notes / alternatives
Trade-offs, risks.
```
