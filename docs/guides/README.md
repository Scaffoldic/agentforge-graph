# Guides

Step-by-step, task-oriented guides for using **agentforge-graph**. Start with
**Getting started** (pick the setup that matches how you run CKG), then the
numbered topic guides go deeper. Each guide opens with a **TL;DR** (what + the key
command + prereqs), so you can skim or dive in.

## Getting started — pick your setup

Install once (`pip install agentforge-graph`), then follow the path for your
setup. They build on each other in order.

| # | Guide | When to use it |
|---|---|---|
| — | [Getting started (hub)](01-getting-started.md) | Overview + how to choose between the three setups below. |
| 1 | [A single repo](getting-started/1-single-repo.md) | Index one repository on your laptop — the base case, no infra. |
| 2 | [A workspace](getting-started/2-workspace.md) | Many repos / microservices: one federated endpoint + cross-service tracing. |
| 3 | [A central store](getting-started/3-central-store.md) | Org-level shared knowledge: host the index (dir or DB), consume `--read-only`. |

## Topic guides

| # | Guide | TL;DR |
|---|---|---|
| 02 | [Indexing & retrieval](02-indexing-and-retrieval.md) | How the index → embed → query loop works; vector entry → typed graph expansion returns **connected** context. |
| 03 | [Framework extraction](03-framework-extraction.md) | Routes / ORM models / DI as graph edges across 11 packs. `ckg routes`/`models`/`services`. |
| 04 | [Cross-file framework resolution](04-cross-file-framework-resolution.md) | The pass-2 that composes `include_router` prefixes and grounds DI/handlers across files — operate + troubleshoot. |
| 05 | [Architecture decisions](05-architecture-decisions.md) | Ingest ADRs/docs as `Decision` nodes linked to the code they `GOVERN`. `ckg decisions`. |
| 06 | [Temporal / history](06-temporal-history.md) | Per-symbol git lifecycle (churn/authors) + graph time-travel. `ckg history`, `--as-of`. |
| 07 | [LLM enrichment](07-enrichment.md) | Budgeted design-pattern tags + module summaries, `llm`-provenance. `ckg enrich`. |
| 08 | [Model providers](08-model-providers.md) | Pick embedding + LLM providers (Bedrock/OpenAI/Anthropic) or bring your own. |
| 09 | [Storage backends](09-storage-backends.md) | Embedded by default; switch to Neo4j / pgvector / SurrealDB via config. |
| 10 | [Using over MCP](10-using-over-mcp.md) | Serve the CKG to an agent over 10 read-only tools (stdio/HTTP) or in-process. |

> New here? Start with **[Getting started → a single repo](getting-started/1-single-repo.md)**.
> Building an agent on top? Jump to **[10 — Using over MCP](10-using-over-mcp.md)**.

## Conventions

- **Naming:** topic guides are flat `NN-slug.md` (numbered learning path); the
  setup walkthroughs live under `getting-started/N-slug.md`.
- **Template:** each guide starts with a `> **TL;DR:**` blockquote — the one-line
  what + the key command(s) + any prereqs — before the prose.
