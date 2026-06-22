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
| ENH-010..013 | SurrealDB · cross-file resolution · more packs · rerank measurement (shipped in 0.4.0 — see each spec file) | — | — | — | done |
| [ENH-017](ENH-017-surface-framework-upgrade-drift.md) | Make `agentforge upgrade` safe (fork/custom data-loss bug) + surface upgrade drift | Med–High | S–M | framework / upstream | filed upstream (agentforge-py#114, #115) |
| [ENH-018](ENH-018-store-location-and-central-hosting.md) | Store-location choice (in-repo vs. central) + read-only consumers | High | S–M | config/store | in progress (central_root done; read-only + server namespacing next) |
| [ENH-019](ENH-019-serve-mcp-workdir-autodiscovery.md) | `serve-mcp` working-directory auto-discovery (zero-config consumption) | Medium | S | cli/serve | done |
| [ENH-020](ENH-020-federated-multi-repo-mcp.md) | Federated multi-repo MCP + cross-service contract edges | High | L | serve/frameworks | done (C-lite federation + C-full: service map, ckg_trace, Python/JS clients incl. instances+base_url, OpenAPI anchoring; only gRPC/proto deferred) |
| [ENH-021](ENH-021-workspace-build-commands.md) | Workspace-driven build commands (`ckg build/index/embed --workspace`) | High | M | cli/serve | proposed (0.6 epic) |
| [ENH-022](ENH-022-workspace-config-cascade.md) | Workspace-level config cascade (configure once) | High | M | config/serve | proposed (0.6 epic) |
| [ENH-023](ENH-023-per-member-embed-toggle.md) | Per-member embed enable/disable | Medium | S | config/cli | proposed (0.6 epic) |
| [ENH-024](ENH-024-remote-repo-sources.md) | Remote repo sources in workspace (git/github URL clone) | Med–High | L | serve/cli | proposed (0.6 epic) |
| [ENH-025](ENH-025-voyage-embedder.md) | First-party Voyage embedder | Medium | S | embed | deferred (raise upstream first) |
| [ENH-026](ENH-026-config-preflight-fail-fast.md) | Fail-fast config preflight + `ckg doctor` | High | S–M | registry/cli | proposed (0.6 epic) |

## Themes

Some enhancements ladder up to a larger goal. See:

- **[THEME: org-level central code knowledge](THEME-org-central-knowledge.md)** —
  CKG as one central, org-wide code brain served to devs *and* agents. Rungs:
  ENH-018 (central hosting) → ENH-019 (discovery) → ENH-020 (federation +
  cross-service edges).

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
