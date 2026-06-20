# Getting started — index a repo, query it, serve it to an agent

> **TL;DR:** `pip install agentforge-graph` → `ckg index .` builds a typed graph
> in seconds (no creds, no server) → `ckg routes`/`models`/`services` show the
> framework surface → add `--embed` + AWS creds for semantic `ckg query` →
> `ckg serve-mcp --repo .` exposes 10 read-only tools to your agent.
> **Time:** ~10 minutes. **Prereqs:** Python 3.13+. (Semantic search/enrichment
> need an embedding/LLM provider — Bedrock by default; the structural commands
> don't.)

This is the end-to-end walkthrough. Run it on **any repo** — point the commands
at a path instead of `.`.

## 1. Install

```bash
pip install agentforge-graph        # the engine is in the box — Kuzu + LanceDB embedded
ckg --help                          # `ckg` is the CLI; `agentforge-graph` is an alias
```

Nothing else to run: the graph store (Kuzu) and vector store (LanceDB) are
embedded and write to a gitignored `.ckg/` dir in your repo. Server backends and
model providers are opt-in (steps 5–6).

## 2. Index — repo → typed graph (no creds)

```bash
ckg index /path/to/repo
```

Parses the repo into a typed graph: files, classes, functions, methods with
stable ids, and `CONTAINS`/`IMPORTS`/`CALLS`/`INHERITS` edges across 10 language
packs — plus **framework semantics** (routes, ORM models, DI) where detected.
Re-running is incremental (only changed files re-parse). Check it:

```bash
ckg status /path/to/repo            # index commit, node/edge counts, staleness
ckg map /path/to/repo               # a budget-aware, centrality-ranked repo map
```

## 3. See the framework surface (still no creds)

If the repo uses a supported framework (FastAPI, Flask, SQLAlchemy, Django,
Express, NestJS, Spring, Gin, ASP.NET, Laravel, Rails), the structural index
already extracted its architecture as graph edges:

```bash
ckg routes /path/to/repo            # METHOD path → handler (file:line)
ckg models /path/to/repo            # ORM models, fields, relations (RELATES_TO)
ckg services /path/to/repo          # DI providers and where they're injected
```

Try it on the bundled sample with zero setup:

```bash
ckg index examples/fastapi-shop && ckg routes examples/fastapi-shop && ckg models examples/fastapi-shop
```

→ deeper dive: [framework extraction](03-framework-extraction.md).

## 4. Embed + query — natural-language → connected code (needs a provider)

Semantic search embeds the code, so it needs an embedding provider. The default
is **AWS Bedrock** (`cohere.embed-v4`); configure AWS creds the usual way (a
default CLI profile / `AWS_PROFILE` / env vars):

```bash
ckg index /path/to/repo --embed                    # chunk + embed after indexing
ckg query "how are auth tokens validated" --repo /path/to/repo
```

A query returns **connected context** — the symbol, who calls it, and the
architecture decision that governs it — not a flat list. Prefer a different
provider (OpenAI / a local OpenAI-compatible endpoint)? See
[model providers](08-model-providers.md). The retrieval loop in depth:
[indexing & retrieval](02-indexing-and-retrieval.md).

## 5. (Optional) Switch the storage backend

Embedded Kuzu + LanceDB are the default. To point at a server — Neo4j, Postgres
+ pgvector, or SurrealDB (graph + vectors in one) — edit `ckg.yaml`'s `store:`
block and install the matching extra (`pip install agentforge-graph[neo4j]`,
`[pgvector]`, `[surrealdb]`). Same commands, same conformance.
→ [storage backends](09-storage-backends.md).

## 6. (Optional) Enrich with an LLM

Add design-pattern tags and bottom-up module summaries (budgeted, every fact
carries `llm` provenance + confidence):

```bash
ckg enrich /path/to/repo            # Bedrock Claude by default; --budget-usd caps spend
```

→ [enrichment](07-enrichment.md). Decisions/ADR linking: [architecture
decisions](05-architecture-decisions.md). Git history & time-travel:
[temporal/history](06-temporal-history.md).

## 7. Serve it to an agent (MCP)

Expose the graph to any agent over **10 read-only MCP tools**:

```bash
ckg serve-mcp --repo /path/to/repo                 # stdio (default), or --transport http
```

Every response carries a staleness envelope (the index commit + whether it's
behind HEAD). Wire it into Claude Code / any MCP client, or use it in-process via
the native AgentForge toolset. → [using over MCP](10-using-over-mcp.md).

## Where next

The full guide set is indexed in [`docs/guides/`](README.md) — start with
[indexing & retrieval](02-indexing-and-retrieval.md) for how the hybrid
vector→graph retrieval actually works, then the feature guides for the surface
your repo uses.
