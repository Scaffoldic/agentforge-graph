<!-- AGENTFORGE-MANAGED: template:minimal@0.2.4 hash:c474ab3012ec -->
<!-- NOTE: customized for agentforge-graph (forked from the scaffold README). -->
# agentforge-graph

[![CI](https://github.com/Scaffoldic/agentforge-grpah/actions/workflows/ci.yml/badge.svg)](https://github.com/Scaffoldic/agentforge-grpah/actions/workflows/ci.yml)

A **Code Knowledge Graph (CKG)** engine + agent toolset, built on the
[AgentForge](https://pypi.org/project/agentforge-py/) framework. It
indexes a repository into a typed, provenance-tracked graph and serves
it to LLM agents (Claude Code, Cursor, custom AgentForge agents) over
MCP.

> **Status:** scaffolded, specs + ADRs written, no features implemented
> yet. Start with feat-001 (see the tracker).

## Documentation map

| Doc | What it is |
|---|---|
| [`docs/open-source-ckg-research.md`](docs/open-source-ckg-research.md) | Research survey of open-source CKG tools that motivates the design |
| [`docs/adr/`](docs/adr/) | 9 architecture decision records (the *why*) |
| [`docs/features/`](docs/features/) | 12 feature specs (feat-001…012) |
| [`docs/features/TRACKER.md`](docs/features/TRACKER.md) | Status board, dependency DAG, build order |
| [`docs/runbooks/`](docs/runbooks/) | AgentForge task runbooks (from the scaffold) |

## Getting started

```bash
uv sync                      # framework + MCP (base)
uv sync --extra engine       # + tree-sitter, kuzu, lancedb, fastembed (graph engine)
cp .env.example .env         # set ANTHROPIC_API_KEY
```

## Configuration

Two files, deliberately separate:

- **`agentforge.yaml`** — framework config (model, budget, modules).
  Validate with `uv run agentforge config validate`.
- **`ckg.yaml`** — this agent's own engine config (store, ingest,
  chunking, embed, retrieve, serve), read by the `agentforge_graph`
  package. The framework validator is strict and rejects unknown keys,
  so engine config lives here, not in `agentforge.yaml`.

## Installed modules & extras

| Install | Provides | Spec |
|---|---|---|
| base (`uv sync`) | `agentforge-py`, `agentforge-anthropic`, `agentforge-mcp` | runtime, enrichment LLM, MCP serving |
| `--extra engine` | tree-sitter (+10 grammars), kuzu, lancedb, fastembed, networkx | feat-002/003/005/007 |
| `--extra rerank` | `agentforge-reranker-sentence-transformers` | feat-006 (off by default) |
| `--extra neo4j` | `agentforge-memory-neo4j` | feat-003 opt-in graph server |
| `--extra voyage` | `agentforge-voyage` | feat-005 hosted embeddings |
| `--extra otel` | `agentforge-otel` | observability |

## Upgrades

```bash
uv run agentforge upgrade
```

Refreshes framework-managed files while preserving customizations.
`pyproject.toml`, `agentforge.yaml`, and `README.md` have been edited
from the scaffold defaults, so the upgrade tool treats them as forked —
review their diffs on upgrade. See `uv run agentforge status`.
