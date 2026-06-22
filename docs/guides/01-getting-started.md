# Getting started — pick your setup

> **TL;DR:** `pip install agentforge-graph`, then follow the guide for how you
> run CKG: one repo, a multi-repo workspace, or a hosted central store.

Install once — the engine (Kuzu + LanceDB) is in the box, no server required:

```bash
pip install agentforge-graph
ckg --version                       # confirm what you're running
ckg --help
```

> **Validate before you build:** `ckg doctor` (or `ckg doctor --workspace
> workspace.yaml`) checks your config — selected drivers installed, credentials
> present — and prints the exact fix, before any indexing. Add `--debug` / `-v` to
> any command (or `logging: { level: debug }` in ckg.yaml) to trace a run end to
> end.

Then pick the path that matches your setup. They build on each other in order.

| # | Guide | When to use it |
|---|---|---|
| 1 | **[A single repo](getting-started/1-single-repo.md)** | Index one repository on your laptop: `index → routes/models/services → embed + query → serve-mcp` (or `ckg build .` in one step). The base case, ~10 min, no infra. |
| 2 | **[A workspace](getting-started/2-workspace.md)** | Many repos / **microservices**: build them all with one command (`ckg build --workspace`), serve one federated MCP endpoint, and draw the **cross-service call graph** (`ckg_services_map` / `ckg_trace`). Members can be local paths **or git URLs**. |
| 3 | **[A central store](getting-started/3-central-store.md)** | Make CKG **org-level shared knowledge**: host the index outside the repos (shared dir or SurrealDB/Neo4j) — built once by CI, consumed `--read-only` by many. Set it once in the workspace `defaults:`. |

New here? Start with **[1 — a single repo](getting-started/1-single-repo.md)**.
Building an agent on top? Also see [using over MCP](10-using-over-mcp.md).

## After the quickstart — the topic guides

The numbered topic guides go deeper on each capability:
[indexing & retrieval](02-indexing-and-retrieval.md) ·
[framework extraction](03-framework-extraction.md) ·
[cross-file resolution](04-cross-file-framework-resolution.md) ·
[architecture decisions](05-architecture-decisions.md) ·
[temporal / history](06-temporal-history.md) ·
[enrichment](07-enrichment.md) ·
[model providers](08-model-providers.md) ·
[storage backends](09-storage-backends.md) ·
[using over MCP](10-using-over-mcp.md).
