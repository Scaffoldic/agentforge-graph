<!-- AGENTFORGE-MANAGED: template:minimal@0.2.4 hash:c474ab3012ec -->
<!-- NOTE: customized for agentforge-graph (forked from the scaffold README). -->
# agentforge-graph

[![CI](https://github.com/Scaffoldic/agentforge-grpah/actions/workflows/ci.yml/badge.svg)](https://github.com/Scaffoldic/agentforge-grpah/actions/workflows/ci.yml)

> A **Code Knowledge Graph (CKG) engine + agent toolset.** It turns a
> repository into a typed, provenance-tracked graph — symbols, calls, imports,
> API routes, architecture decisions, design-pattern tags, LLM summaries — and
> serves that knowledge to coding agents over **MCP** or as an AgentForge
> toolset. Built on [AgentForge](https://pypi.org/project/agentforge-py/).

Plain code-graph tools answer *"what is connected"*. Agents also need *"what is
this **for**"*, *"what decision governs this code"*, *"what's the API surface"*,
*"show me all the Repositories"*. **agentforge-graph puts parsed structure,
framework semantics, architecture decisions, and LLM enrichment in one graph an
agent can traverse — every fact carrying its provenance.**

---

## What it brings to the table

| Capability | What you get |
|---|---|
| **Typed code graph** | Files, classes, functions, methods with stable SCIP-style ids; `CONTAINS`/`IMPORTS`/`CALLS` edges. Conservative, no-guess resolution. |
| **Hybrid retrieval** | Vector search **entry** → typed **graph expansion**. Ask in natural language, get *connected* context (the symbol, its callers, its governing decision). |
| **Incremental** | Re-index only the diff. Edit 3 files in a 5k-file repo → seconds, not minutes. Embeddings/enrichment recompute only what changed. |
| **Decisions ↔ code** (differentiator) | Ingests ADRs and links them to the code they `GOVERN`. A search hit on `payments/` surfaces *"ADR-0012 (accepted): idempotency keys must be client-side"* before the agent edits. |
| **Framework awareness** (differentiator) | Extracts API routes (FastAPI) as `Route → HANDLED_BY → handler` edges. `ckg routes` is your API surface in one call. |
| **LLM enrichment** (differentiator) | Budgeted design-pattern tags (*"this class is a Repository"*, with confidence + rationale) and bottom-up module summaries — all `llm`-provenance and opt-out-able. |
| **Agent-native** | Served read-only over MCP (9 tools) or as a native AgentForge toolset. Every response carries a staleness envelope. |
| **Embedded-first** | Local Kuzu graph + LanceDB vectors under `.ckg/`. No server to run. Storage and models are pluggable (see below). |

**Status:** the full pipeline works end-to-end on real code — `index → embed →
enrich → query / map / decisions / routes / explain`, served over MCP. Language
packs: **Python, TypeScript, JavaScript**. Of the 12 planned features, **11 are
at least MVP-shipped**; only the temporal/git-evolution layer (feat-009) is
unstarted. See [`docs/features/TRACKER.md`](docs/features/TRACKER.md).

---

## Quick start

```bash
# install (uv, not pip)
uv sync --extra engine --extra bedrock      # tree-sitter + kuzu + lancedb + boto3

# 1) index a repo into the graph (incremental by default once indexed)
ckg index .                                 # files/classes/functions/calls (+ ADRs if any)

# 2) embed for semantic search
ckg embed .                                 # AST chunks → vectors (Cohere embed-v4 on Bedrock)

# 3) optional: LLM enrichment (explicit, budgeted)
ckg enrich . --all --budget-usd 2           # design-pattern tags + module summaries

# query & explore
ckg map --budget 2000                       # centrality-ranked repo orientation
ckg query "how are tokens validated"        # ranked, connected context (cosine-scored)
ckg query --symbol "<id>" --mode impact     # reverse deps — "who calls this"
ckg decisions --status accepted             # ADRs and what they govern
ckg routes                                  # API surface: METHOD PATH → handler
ckg tagged Repository                        # symbols tagged with a design pattern
ckg status                                  # indexed commit, staleness, node counts
```

### Serve it to an agent

To Claude Code (or any MCP client) — **9 read-only tools**: `ckg_repo_map`,
`ckg_search`, `ckg_symbol`, `ckg_impact`, `ckg_neighbors`, `ckg_status`,
`ckg_routes`, `ckg_decisions`, `ckg_explain`:

```bash
claude mcp add ckg -- ckg serve-mcp --repo .
```

Or as a native AgentForge toolset:

```python
from agentforge import Agent
from agentforge_graph.serve import code_graph_tools

agent = Agent(model="anthropic:claude-sonnet-4-6", tools=code_graph_tools("."))
```

→ Full guide (tool schemas, client config, guardrails, staleness envelope):
[`docs/guides/using-over-mcp.md`](docs/guides/using-over-mcp.md).

---

## Storage — what DB, and can I switch it?

**By default, nothing to run.** The graph lives in an embedded **Kuzu** database
and the vectors in an embedded **LanceDB** index, both under `.ckg/` in your repo
(ADR-0006). Zero config, no server.

Storage is **pluggable** behind two contracts — `GraphStore` and `VectorStore`
([`core/contracts.py`](src/agentforge_graph/core/contracts.py)) — resolved by a
**driver registry** with entry-point groups
([`store/registry.py`](src/agentforge_graph/store/registry.py)):

```yaml
# ckg.yaml
store:
  graph:   { driver: kuzu }       # built-in
  vectors: { driver: lancedb }    # built-in
```

A server backend (Neo4j, FalkorDB, SurrealDB, pgvector, …) is an **out-of-tree
adapter**: implement the contract, pass the reusable `GraphStoreConformance`
suite, register an entry point — then it's `pip install + one config line`, no
core change. **Today only `kuzu` + `lancedb` ship**; the others are a defined
extension point, not bundled. (PRs welcome — see
[`CONTRIBUTING.md`](CONTRIBUTING.md).)

## Models — pick a provider, or bring your own

Every model boundary is an **interface** resolved by a provider registry
(ENH-003), so switching providers is a `ckg.yaml` line — not a code change.
Multiple providers ship first-party:

| Interface | Ships first-party | Select with | Bring-your-own |
|---|---|---|---|
| `Embedder` | `bedrock` (Cohere `embed-v4`) · `openai` (incl. **local** OpenAI-compatible) · `fake` (CI) | `embed.driver` | entry point — a small adapter |
| `PatternJudge` | `bedrock` · `anthropic` (direct API) · `scripted` (CI) | `enrich.provider` | entry point |
| `Summarizer` | `bedrock` · `anthropic` (direct API) · `scripted` (CI) | `enrich.provider` | entry point |

- **On AWS?** Default `bedrock` (Claude + Cohere) uses your AWS credentials.
- **Not on AWS?** `enrich.provider: anthropic` (set `ANTHROPIC_API_KEY`) and
  `embed.driver: openai` (set `OPENAI_API_KEY`) give a full live path, no AWS.
- **Local / self-hosted?** Point `embed.base_url` at any OpenAI-compatible
  server (Ollama, vLLM, LM Studio) — same `openai` driver.
- **Adding a *new* provider** is implementing one small class and registering an
  entry point — `pip install + one config line`, no fork. The engine,
  orchestration, budget rails, and heuristics don't change.

CI uses the deterministic fakes, so **no model calls or cloud creds are needed to
build or test**. Live model tests are env-gated (`CKG_LIVE_BEDROCK`,
`CKG_LIVE_AGENT`, `CKG_LIVE_ANTHROPIC`, `CKG_LIVE_OPENAI`).

→ Full guide: [`docs/guides/model-providers.md`](docs/guides/model-providers.md)
(change a provider, run locally, or add your own). Set `embed.driver: fake` +
`enrich.provider: scripted` for fully offline use.

---

## Architecture

See **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)** for the full overview
(layer diagram, data model, every pipeline in ASCII, extension points). In one
breath: a `core` of contracts + value types, a **deterministic engine** that
never imports the framework (parse, store, resolve, embed, retrieve, frameworks,
decisions), and a thin **framework layer** (`serve` = MCP/Tools, `enrich` = LLM
with budget rails) on top.

```
ckg CLI / MCP server / Agent
        │
  serve · enrich            (framework layer — may import agentforge)
        │
  ingest · store · chunking · embed · retrieve · repomap · frameworks · knowledge
        │                   (deterministic engine — no agentforge)
  core: contracts · models · SymbolID · provenance · kinds
        │
  Kuzu (graph) + LanceDB (vectors)   under .ckg/
```

---

## Configuration

Two files, on purpose:

- **`agentforge.yaml`** — the *framework's* config (agent model, budget, MCP).
  Strict validator. `uv run agentforge config validate`.
- **`ckg.yaml`** — *this engine's* config: `store`, `ingest`, `chunking`,
  `embed`, `retrieve`, `repomap`, `serve`, `frameworks`, `knowledge`, `enrich`.
  Lenient (unknown keys ignored), so a config written for a later feature still
  loads.

## Install extras

| Install | Provides |
|---|---|
| `uv sync` | base: `agentforge-py`, `agentforge-anthropic`, `agentforge-mcp[mcp]` |
| `--extra engine` | tree-sitter (+ grammars), kuzu, lancedb, networkx |
| `--extra bedrock` | `boto3` — Bedrock embeddings + Claude enrichment |
| `--extra openai` | `openai` — OpenAI / local OpenAI-compatible embeddings |
| `--extra rerank` | sentence-transformers reranker (off by default) |

The Anthropic-API enrichment path (`enrich.provider: anthropic`) needs no extra —
the `anthropic` SDK ships with the base install.

---

## Contributing & AI-assisted development

This repo is built to be worked on **with** AI agents. Start here:

- **[`CONTRIBUTING.md`](CONTRIBUTING.md)** — setup, tests, the per-feature
  development pipeline, and step-by-step playbooks (add a language pack, a
  framework pack, a storage backend, a model adapter, an MCP tool, an enricher).
- **[`AGENTS.md`](AGENTS.md)** — read by Claude Code, Cursor, Aider, etc.
  (the [AGENTS.md convention](https://agents.md)); the invariants an AI assistant
  must respect.
- **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)** — the system map.

## Documentation map

| Doc | What it is |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | High-level architecture + every pipeline (ASCII) |
| [`docs/adr/`](docs/adr/) | 9 architecture decision records (the *why*) |
| [`docs/features/`](docs/features/) + [`TRACKER.md`](docs/features/TRACKER.md) | 12 feature specs + status board |
| [`docs/design/`](docs/design/) | Per-feature design docs (the *how*, pre-build) |
| [`docs/bugs/`](docs/bugs/) · [`docs/enhancements/`](docs/enhancements/) · [`docs/known-limitations/`](docs/known-limitations/) | Triaged findings, each with a template |
| [`docs/open-source-ckg-research.md`](docs/open-source-ckg-research.md) | The survey that motivates the design |

## License

[**Apache-2.0**](LICENSE) — permissive, with an explicit patent grant and
patent-retaliation clause. See [`LICENSE`](LICENSE) for the full text and
[`NOTICE`](NOTICE) for attribution. Aligns with AgentForge, which is also
Apache-2.0.
