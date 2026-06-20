# Guides

Step-by-step, task-oriented guides for using **agentforge-graph**. Numbered as a
learning path — start at the top. Each guide opens with a **TL;DR** (what + the
key command + prereqs), so you can skim or dive in.

| # | Guide | TL;DR |
|---|---|---|
| 01 | [Getting started](01-getting-started.md) | Install → `ckg index` → `routes`/`models`/`services` → `--embed` + `ckg query` → `ckg serve-mcp`. The end-to-end walkthrough on any repo. |
| 02 | [Indexing & retrieval](02-indexing-and-retrieval.md) | How the index → embed → query loop works; vector entry → typed graph expansion returns **connected** context. |
| 03 | [Framework extraction](03-framework-extraction.md) | Routes / ORM models / DI as graph edges across 11 packs. `ckg routes`/`models`/`services`. |
| 04 | [Cross-file framework resolution](04-cross-file-framework-resolution.md) | The pass-2 that composes `include_router` prefixes and grounds DI/handlers across files — operate + troubleshoot. |
| 05 | [Architecture decisions](05-architecture-decisions.md) | Ingest ADRs/docs as `Decision` nodes linked to the code they `GOVERN`. `ckg decisions`. |
| 06 | [Temporal / history](06-temporal-history.md) | Per-symbol git lifecycle (churn/authors) + graph time-travel. `ckg history`, `--as-of`. |
| 07 | [LLM enrichment](07-enrichment.md) | Budgeted design-pattern tags + module summaries, `llm`-provenance. `ckg enrich`. |
| 08 | [Model providers](08-model-providers.md) | Pick embedding + LLM providers (Bedrock/OpenAI/Anthropic) or bring your own. |
| 09 | [Storage backends](09-storage-backends.md) | Embedded by default; switch to Neo4j / pgvector / SurrealDB via config. |
| 10 | [Using over MCP](10-using-over-mcp.md) | Serve the CKG to an agent over 10 read-only tools (stdio/HTTP) or in-process. |

> New here? Read **[01 — Getting started](01-getting-started.md)** first.
> Building an agent on top? Jump to **[10 — Using over MCP](10-using-over-mcp.md)**.

## Conventions

- **Naming:** `NN-slug.md` (numbered learning path).
- **Template:** each guide starts with a `> **TL;DR:**` blockquote — the one-line
  what + the key command(s) + any prereqs — before the prose.
