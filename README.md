<!-- NOTE: customized for agentforge-graph (forked from the scaffold README). -->
# agentforge-graph

[![CI](https://github.com/Scaffoldic/agentforge-graph/actions/workflows/ci.yml/badge.svg)](https://github.com/Scaffoldic/agentforge-graph/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/agentforge-graph.svg)](https://pypi.org/project/agentforge-graph/)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://pypi.org/project/agentforge-graph/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green.svg)](https://github.com/Scaffoldic/agentforge-graph/blob/main/LICENSE)

> **Turn any repo — or your whole org — into a knowledge graph your coding agent
> can actually reason over.** Symbols, calls, imports, **API routes, ORM models,
> dependency injection, architecture decisions, git history, LLM summaries** — one
> typed, provenance-tracked graph, served over **MCP** in a single command. Scale
> it from one repo to a **federated workspace** with **cross-service tracing**, on
> a **central** index hosted for the team.

Plain code-graph tools answer *"what is connected."* Agents also need *"what is
this **for**, what decision governs it, what's the API surface, which tables does
this touch, who calls this, what changed."* **agentforge-graph puts parsed
structure, framework semantics, architecture decisions, git evolution, and LLM
enrichment in one graph an agent can traverse — every fact carrying its
provenance.** Built on [AgentForge](https://pypi.org/project/agentforge-py/).

```bash
pip install agentforge-graph        # ← the engine is in the box; nothing else to run
ckg index .                         # repo → typed graph in seconds (no creds, no server)
ckg serve-mcp --repo .              # → 10 read-only tools for your agent
```

<p align="center">
  <img src="https://raw.githubusercontent.com/Scaffoldic/agentforge-graph/main/docs/assets/demo.gif"
       alt="ckg indexes a FastAPI + SQLAlchemy app and surfaces its routes, ORM models, and dependency-injection graph"
       width="820">
  <br>
  <em>Index a FastAPI + SQLAlchemy app → its routes, ORM models (with relations), and DI graph — no creds, no server.</em>
</p>

---

## What you get out of the box

- 🧩 **A typed code graph in one command** — `pip install` → `ckg index .` → files,
  classes, functions, methods with stable descriptor-based ids and `CONTAINS`/`IMPORTS`/
  `CALLS`/`INHERITS` edges. **Embedded Kuzu + LanceDB under `.ckg/` — no server, no
  cloud, no config.** 10 languages: Python, TypeScript, JavaScript, Go, Ruby, PHP,
  Java, C#, C++, Rust.
- 🌐 **Framework semantics as graph edges** *(the differentiator)* — routes, ORM
  models, and DI, not just calls. `ckg routes` is your API surface, `ckg models`
  your data model, `ckg services` your injection map — across **11 packs**:
  FastAPI, Flask, SQLAlchemy, Django (Python); Express, NestJS (JS/TS); Spring
  (Java); Gin (Go); ASP.NET (C#); Laravel (PHP); Rails (Ruby).
- 🏛️ **Decisions ↔ code** *(the differentiator)* — ingests ADRs/docs and links them
  to the code they `GOVERN`. A hit on `payments/` surfaces *"ADR-0012 (accepted):
  idempotency keys must be client-side"* **before** the agent edits.
- 🕰️ **Git evolution built in** — `ckg history <symbol>`, `ckg changed-since <ref>`,
  and `--as-of <commit>` reconstruction. Churn and authorship ride the graph.
- 🔎 **Hybrid retrieval** — vector search **entry** → typed **graph expansion**. Ask
  in natural language, get *connected* context: the symbol, its callers, *and* its
  governing decision.
- ⚡ **Incremental & always-fresh** — re-index only the diff (edit 3 files in a
  5k-file repo → seconds, not minutes; embeddings/enrichment recompute only what
  changed). Keep it fresh automatically: **`ckg watch`** re-indexes your working
  copy on a trigger you choose (commit / idle / save), and **`ckg ci init`**
  scaffolds a workflow that keeps the shared central index fresh on every merge.
- 🤖 **Agent-native, wired in one command** — served read-only over **MCP (10
  tools)** or as a native AgentForge toolset, every response carrying a staleness
  envelope. **`ckg setup`** writes your agent's MCP config for you.
- 🧠 **LLM enrichment, budgeted & opt-in** — design-pattern tags (*"this class is a
  Repository,"* with confidence + rationale) and bottom-up module summaries, all
  `llm`-provenance. **CI needs no model calls or cloud creds.**
- 🏢 **Scales from one repo to a whole org** — host the index **centrally** (shared
  dir or SurrealDB/Neo4j), built once and consumed **read-only** by many; serve a
  multi-repo **workspace** from one federated MCP endpoint; and **trace requests
  across services** — `ckg services-map` / `ckg trace` draw the cross-service call
  graph (HTTP client → route, matched by path or OpenAPI contract).

**Status: 0.6.3 — org-scale, built in one command, wired in one, kept fresh
automatically.** 0.5 added central hosting, a federated multi-repo workspace, and
cross-service tracing; 0.6 adds the **build side** — stand up a multi-repo CKG
from one `workspace.yaml` + one config + `ckg build --workspace` (members local
or by git URL), with fail-fast `ckg doctor` validation and config/CLI-controlled
tracing. 0.6.2 adds **`ckg setup`** — one command wires the graph into your
agent; 0.6.3 adds **`ckg watch`** (local, keep-fresh-on-a-trigger) and **`ckg ci
init`** (a CI workflow that refreshes the central index on every merge).
Published on
[PyPI](https://pypi.org/project/agentforge-graph/). Each language pack validated on
a real OSS repo with a creds-enabled embed/retrieval/enrich run; a real agent
answers questions over the tools unattended. See the [`CHANGELOG`](https://github.com/Scaffoldic/agentforge-graph/blob/main/CHANGELOG.md)
and [`docs/features/TRACKER.md`](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/features/TRACKER.md).

---

## Run it three ways — one repo, a workspace, or a central store

```bash
# 1) a single repo — a typed graph in seconds
ckg index . && ckg routes .

# 2) a central store — host the index outside the repo, consume read-only
#    (set store.central_root in ckg.yaml; built once by CI, read by many)
ckg status . --read-only

# 3) a workspace — build many repos with one command, then the cross-service graph
ckg build --workspace workspace.yaml             # index (+embed) every member, one command
ckg services-map --workspace workspace.yaml      # who calls whom (HTTP → route)
ckg trace payments --workspace workspace.yaml --direction upstream   # blast radius
```

> **Configure once, fail fast.** A `defaults:` block in `workspace.yaml` (store
> location, embedder, read-only) is inherited by every member, with per-member
> overrides; members can be **local paths or git URLs**. `ckg doctor [--workspace]`
> validates the config (drivers installed, credentials present) before you build.

<p align="center">
  <img src="https://raw.githubusercontent.com/Scaffoldic/agentforge-graph/main/docs/assets/setups.gif"
       alt="ckg run three ways: a single repo (index + routes), a central store (hosted + read-only), and a workspace (cross-service call graph + trace)"
       width="820">
  <br>
  <em>Single repo → central store → workspace — the cross-service call graph and blast-radius trace, all creds-free.</em>
</p>

→ pick your path: **[a single repo](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/getting-started/1-single-repo.md)** ·
**[a workspace](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/getting-started/2-workspace.md)** ·
**[a central store](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/getting-started/3-central-store.md)**.

---

## Quick start

> **Prefer a guided walkthrough?** Pick your setup — **[a single repo](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/getting-started/1-single-repo.md)** (~10 min), **[a workspace](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/getting-started/2-workspace.md)** (microservices, one federated endpoint), or **[a central store](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/getting-started/3-central-store.md)** (org-level shared index) — from the **[Getting started hub](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/01-getting-started.md)**. Or browse all [step-by-step guides](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/README.md).

```bash
pip install agentforge-graph                # engine included (tree-sitter + kuzu + lancedb)

# 1) index a repo into the graph — incremental on every run after the first
ckg index .                                 # files/classes/functions/calls (+ ADRs, routes, models…)

# explore the graph — no embeddings, no creds, no server
ckg map --budget 2000                       # centrality-ranked repo orientation
ckg routes                                  # API surface: METHOD PATH → handler
ckg models                                  # ORM data models: table, fields, relations
ckg services                                # dependency-injection map
ckg decisions --status accepted             # ADRs and what they govern
ckg history <symbol-id>                     # when/who/churn for a symbol
ckg status                                  # indexed commit, staleness, node counts
```

Add **semantic search** with any embedding provider (AWS Bedrock, OpenAI, or a
local OpenAI-compatible server — see [Models](#models--pick-a-provider-or-bring-your-own)):

```bash
pip install "agentforge-graph[bedrock]"     # or [openai]
ckg embed .                                 # AST chunks → vectors
ckg query "how are auth tokens validated"   # ranked, *connected* context
ckg query --symbol "<id>" --mode impact     # reverse deps — "who calls this"

# optional: explicit, budgeted LLM enrichment
ckg enrich . --all --budget-usd 2           # design-pattern tags + module summaries
ckg tagged Repository                        # symbols tagged with a design pattern
```

### See it in action

```text
$ ckg index .
indexed 1c2f3a4 · 412 files · 5,290 nodes / 9,133 edges · 3.1s

$ ckg routes
POST  /payments/{pid}/refund   →  refund()    (app/api.py:42)
GET   /health                  →  health()    (app/api.py:16)

$ ckg models
users [users]  (app/models.py:7)
    fields: id, name, email
    relations: posts→posts (relationship)

$ ckg query "how are auth tokens validated"
auth/tokens.py:88  TokenValidator.validate            (cosine 0.71)
  ← called by  api/middleware.py:23  require_auth
  ⚖ governed by ADR-0007 (accepted): signing keys must rotate every 90 days
```

That last block is the whole point: a natural-language question returns the
symbol, **who calls it**, *and* **the decision that governs it** — connected, with
provenance.

### Serve it to an agent

Read-only over MCP — **10 tools**: `ckg_repo_map`, `ckg_search`, `ckg_symbol`,
`ckg_impact`, `ckg_neighbors`, `ckg_status`, `ckg_routes`, `ckg_decisions`,
`ckg_explain`, `ckg_history`:

```bash
ckg setup                                          # wire your agent for you (writes .mcp.json)
claude mcp add ckg -- ckg serve-mcp --repo .       # or do it manually — stdio (subprocess)
ckg serve-mcp --repo . --transport http            # or HTTP → http://127.0.0.1:8765/mcp
```

`ckg setup` auto-writes your agent's MCP config (a committable repo `.mcp.json`
by default), shows a diff first, and is reversible with `--undo` — see
[guide 11](docs/guides/11-agent-auto-configuration.md). Over HTTP, point any MCP
client at the URL: `{"mcpServers": {"ckg": {"url": "http://127.0.0.1:8765/mcp"}}}`.

### Keep it fresh

```bash
ckg watch                              # local: re-index on a trigger (commit/idle/save)
ckg ci init                            # central: scaffold a CI workflow that indexes on merge
```

`ckg watch` (opt-in, `pip install 'agentforge-graph[watch]'`) keeps your working
copy's graph current — `on-commit` by default, so it won't churn on every save —
and refuses a central / read-only store. `ckg ci init` writes a single-writer
`.github/workflows/ckg-index.yml` so the shared index refreshes deterministically
on merge-to-`main`. See [guide 12](docs/guides/12-watch-and-ci-indexing.md).

Or as a native AgentForge toolset:

```python
from agentforge import Agent
from agentforge_graph.serve import code_graph_tools

agent = Agent(model="anthropic:claude-sonnet-4-6", tools=code_graph_tools("."))
```

→ Full guide (tool schemas, client config, guardrails, staleness envelope):
[`docs/guides/10-using-over-mcp.md`](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/10-using-over-mcp.md).

---

## What's in the graph

| Capability | What you get |
|---|---|
| **Typed code graph** | Files, classes, functions, methods with stable descriptor-based ids; `CONTAINS`/`IMPORTS`/`CALLS`/`INHERITS` edges. Conservative, no-guess resolution across 10 language packs. |
| **Framework awareness** *(differentiator)* | `Route → HANDLED_BY → handler`, `DataModel → HAS_FIELD`/`RELATES_TO`, `Service → INJECTED_INTO` — across 11 packs: FastAPI, Flask, SQLAlchemy, Django, Express, NestJS, Spring, Gin, ASP.NET, Laravel, Rails. `ckg routes`/`models`/`services`. |
| **Decisions ↔ code** *(differentiator)* | ADRs/docs ingested and linked to the code they `GOVERN`; doc prose embedded + searchable. |
| **Temporal / git evolution** | Per-symbol history, churn, authorship; `changed-since`, `as-of` reconstruction. |
| **Hybrid retrieval** | Vector entry → typed graph expansion. Connected context, not a flat list. |
| **LLM enrichment** *(differentiator)* | Budgeted design-pattern tags + bottom-up module summaries — `llm`-provenance, opt-out-able. |
| **Agent-native** | Read-only MCP (10 tools) or native AgentForge toolset; every response carries a staleness envelope. |
| **Embedded-first** | Local Kuzu graph + LanceDB vectors under `.ckg/`. No server. Storage + models pluggable. |

---

## Retrieval quality (measured)

Retrieval is the core agent-facing surface, so we measure it — not vibes. On an
**objective** natural-language→code benchmark (each documented symbol's docstring
is the query, that symbol is the gold answer; labels come straight from the
graph's `DESCRIBES` edges, verified leakage-free), over **388 queries across 4
real OSS repos** (click, httpx, flask, fastapi) with Bedrock `cohere.embed-v4`:

| | base hybrid retrieval | + Bedrock cross-encoder rerank (w=0.3) |
|---|---|---|
| **MRR** | 0.952 | 0.971 |
| **recall@1** | 0.915 | 0.948 |

Base retrieval lands the right code at **rank ≈ 1** out of the box. The optional
cross-encoder reranker (Bedrock Rerank — no torch) adds a small but
**statistically significant** precision gain (ΔMRR +0.019, 95% CI [+0.008,
+0.031], p < 0.001 by paired bootstrap) for ~440 ms/query — so it's **opt-in**,
for when top-1 precision is worth the latency. Full method + numbers:
[`docs/validation/rerank/benchmark.md`](docs/validation/rerank/benchmark.md).

---

## Storage — what DB, and can I switch it?

**By default, nothing to run.** The graph lives in an embedded **Kuzu** database
and the vectors in an embedded **LanceDB** index, both under `.ckg/` in your repo
(ADR-0006). Zero config, no server.

Storage is **pluggable** behind two contracts — `GraphStore` and `VectorStore`
([`core/contracts.py`](https://github.com/Scaffoldic/agentforge-graph/blob/main/src/agentforge_graph/core/contracts.py)) — resolved by a
**driver registry** with entry-point groups
([`store/registry.py`](https://github.com/Scaffoldic/agentforge-graph/blob/main/src/agentforge_graph/store/registry.py)):

```yaml
# agentforge.yaml  (engine config lives under app:)
app:
  store:
    graph:   { driver: kuzu }       # built-in
    vectors: { driver: lancedb }    # built-in
```

Three server backends ship first-party as opt-in extras: **Neo4j** (graph),
**Postgres/pgvector** (vectors), and **SurrealDB** — multi-model, so one server is
*both* graph + vectors. Each passes the *same* `GraphStoreConformance` /
`VectorStoreConformance` suite the embedded defaults do (run against live servers
in CI). Anything else (SurrealDB aside) is an **out-of-tree adapter**:
implement the contract, pass the conformance suite, register an entry point — then
it's `pip install + one config line`, no core change.
→ [`docs/guides/09-storage-backends.md`](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/09-storage-backends.md).

## Models — pick a provider, or bring your own

Every model boundary is an **interface** resolved by a provider registry, so
switching providers is a one-line config change (under `app:` in
`agentforge.yaml`) — not a code change:

| Interface | Ships first-party | Select with |
|---|---|---|
| `Embedder` | `bedrock` (Cohere `embed-v4`) · `openai` (incl. **local** OpenAI-compatible) · `fake` (CI) | `embed.driver` |
| `PatternJudge` / `Summarizer` | `bedrock` · `anthropic` (direct API) · `scripted` (CI) | `enrich.provider` |

- **On AWS?** Default `bedrock` (Claude + Cohere) uses your AWS credentials.
- **Not on AWS?** `enrich.provider: anthropic` (set `ANTHROPIC_API_KEY`) + `embed.driver:
  openai` (set `OPENAI_API_KEY`) give a full live path, no AWS.
- **Local / self-hosted?** Point `embed.base_url` at any OpenAI-compatible server
  (Ollama, vLLM, LM Studio) — same `openai` driver.
- **Fully offline?** `embed.driver: fake` + `enrich.provider: scripted`.

CI uses the deterministic fakes, so **no model calls or cloud creds are needed to
build or test**. → [`docs/guides/08-model-providers.md`](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/08-model-providers.md).

---

## Architecture

See **[`docs/ARCHITECTURE.md`](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/ARCHITECTURE.md)** for the full overview (layer
diagram, data model, every pipeline in ASCII, extension points). In one breath: a
`core` of contracts + value types, a **deterministic engine** that never imports the
framework (parse, store, resolve, embed, retrieve, **frameworks**, knowledge), and a
thin **framework layer** (`serve` = MCP/Tools, `enrich` = LLM with budget rails) on top.

```
ckg CLI / MCP server / Agent
        │
  serve · enrich            (framework layer — may import agentforge)
        │
  ingest · store · chunking · embed · retrieve · repomap · frameworks · knowledge · temporal
        │                   (deterministic engine — no agentforge)
  core: contracts · models · SymbolID · provenance · kinds
        │
  Kuzu (graph) + LanceDB (vectors)   under .ckg/
```

---

## Configuration & install extras

One config file: **`agentforge.yaml`**.

- **Framework keys** at the top level (agent model, budget, MCP) — strict.
- **Engine config** under the framework's **`app:`** passthrough: `store`,
  `ingest`, `chunking`, `embed`, `retrieve`, `repomap`, `serve`, `frameworks`,
  `knowledge`, `enrich`, `temporal`. The engine reads `app:` with plain pyyaml,
  never importing the framework (ADR-0001), and is lenient (unknown keys ignored).
- A **standalone `ckg.yaml`** (the same blocks at the top level) is still
  supported for framework-free use; the engine auto-discovers either file.

The base `pip install agentforge-graph` includes the deterministic engine
(tree-sitter, kuzu, lancedb, networkx). Optional extras add providers/backends:

| Install | Adds |
|---|---|
| `pip install agentforge-graph` | base: engine + framework runtime + MCP serving |
| `…[bedrock]` | `boto3` — Bedrock embeddings + Claude enrichment |
| `…[openai]` | `openai` — OpenAI / local OpenAI-compatible embeddings |
| `…[neo4j]` / `…[pgvector]` | opt-in server graph / vector backends |
| `…[surrealdb]` | opt-in single server — graph **and** vectors (multi-model) |
| `…[rerank]` | sentence-transformers cross-encoder (off by default) |

The Anthropic-API enrichment path (`enrich.provider: anthropic`) needs no extra —
the `anthropic` SDK ships with the base install.

---

## Contributing & AI-assisted development

This repo is built to be worked on **with** AI agents. Start here:

- **[`CONTRIBUTING.md`](https://github.com/Scaffoldic/agentforge-graph/blob/main/CONTRIBUTING.md)** — setup, the quality gate, the per-feature
  development pipeline, and step-by-step playbooks (add a language pack, a framework
  pack, a storage backend, a model adapter, an MCP tool, an enricher).
- **[`AGENTS.md`](https://github.com/Scaffoldic/agentforge-graph/blob/main/AGENTS.md)** — read by Claude Code and other AGENTS.md-aware assistants.
  (the [AGENTS.md convention](https://agents.md)); the invariants an AI assistant must respect.
- **[`docs/ARCHITECTURE.md`](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/ARCHITECTURE.md)** — the system map.

## Documentation map

| Doc | What it is |
|---|---|
| [`docs/ARCHITECTURE.md`](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/ARCHITECTURE.md) | High-level architecture + every pipeline (ASCII) |
| [**`docs/guides/`**](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/README.md) | **Step-by-step guides** (each with a TL;DR). **Getting started — pick your setup:** [a single repo](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/getting-started/1-single-repo.md) · [a workspace](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/getting-started/2-workspace.md) · [a central store](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/getting-started/3-central-store.md). **Topic guides:** [02 indexing & retrieval](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/02-indexing-and-retrieval.md) · [03 framework extraction](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/03-framework-extraction.md) · [04 cross-file resolution](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/04-cross-file-framework-resolution.md) · [05 architecture decisions](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/05-architecture-decisions.md) · [06 temporal/history](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/06-temporal-history.md) · [07 enrichment](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/07-enrichment.md) · [08 model providers](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/08-model-providers.md) · [09 storage backends](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/09-storage-backends.md) · [10 using over MCP](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/10-using-over-mcp.md) |
| [`examples/`](https://github.com/Scaffoldic/agentforge-graph/tree/main/examples) | Runnable sample repos (index → routes/models/services/query) |
| [`docs/adr/`](https://github.com/Scaffoldic/agentforge-graph/tree/main/docs/adr/) | 9 architecture decision records (the *why*) |
| [`docs/features/`](https://github.com/Scaffoldic/agentforge-graph/tree/main/docs/features/) + [`TRACKER.md`](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/features/TRACKER.md) | 12 feature specs + status board |
| [`docs/design/`](https://github.com/Scaffoldic/agentforge-graph/tree/main/docs/design/) | Per-feature design docs (the *how*, pre-build) |

## License

[**Apache-2.0**](https://github.com/Scaffoldic/agentforge-graph/blob/main/LICENSE) — permissive, with an explicit patent grant and
patent-retaliation clause. See [`LICENSE`](https://github.com/Scaffoldic/agentforge-graph/blob/main/LICENSE) and [`NOTICE`](https://github.com/Scaffoldic/agentforge-graph/blob/main/NOTICE). Aligns
with AgentForge, which is also Apache-2.0.
