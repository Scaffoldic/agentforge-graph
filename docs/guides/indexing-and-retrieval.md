# Indexing & retrieval — index → embed → query

The core loop: parse a repo into a typed graph, embed it for semantic search, and
ask questions that return **connected** context (the symbol, its callers, its
governing decision) — not a flat list of files.

## 1. Index (no creds, no server)

```bash
ckg index .
```

Builds the typed graph under `.ckg/` (embedded Kuzu + LanceDB). Files → classes,
functions, methods with stable SCIP-style ids; `CONTAINS`/`IMPORTS`/`CALLS`/
`INHERITS` edges; plus ADRs, routes, ORM models if present. **Incremental on every
run after the first** — edit 3 files in a 5k-file repo and only those re-extract;
a scoped re-resolve keeps cross-file edges correct.

Explore the graph immediately, no embeddings required:

```bash
ckg map --budget 2000      # centrality-ranked repo orientation
ckg routes / models / services / decisions / history
ckg status                 # indexed commit, staleness, node/edge counts
```

## 2. Embed (needs an embedding provider)

```bash
pip install 'agentforge-graph[bedrock]'    # or [openai], or a local OpenAI-compatible server
ckg embed .
```

AST-aware chunks → vectors. Incremental: only changed chunks re-embed (skipped by
content hash). Pick/realize a provider per
[`docs/guides/model-providers.md`](https://github.com/Scaffoldic/agentforge-grpah/blob/main/docs/guides/model-providers.md);
`embed.driver: fake` gives a fully offline path.

## 3. Query — hybrid retrieval

```bash
ckg query "how are auth tokens validated"      # vector entry → graph expansion
ckg query --symbol "<id>" --mode impact        # reverse deps: who calls this
ckg query "payment retry" --mode neighbors     # typed neighbourhood of the best hit
```

```text
$ ckg query "how are auth tokens validated"
auth/tokens.py:88  TokenValidator.validate            (cosine 0.71)
  ← called by  api/middleware.py:23  require_auth
  ⚖ governed by ADR-0007 (accepted): signing keys must rotate every 90 days
```

The retriever does **vector search → typed graph expansion**: the nearest chunks
seed a walk over `CALLS`/`CONTAINS`/`GOVERNS`/`DESCRIBES`/`RELATES_TO`, so you get
the symbol *and* what it connects to.

## Configure

```yaml
# ckg.yaml
retrieve:
  k: 8                 # candidates before expansion
  mode: context        # context | impact | neighbors
  doc_weight: 0.7      # code outranks equally-similar prose by default
  rerank: off          # cross-encoder re-score (ENH-009, needs [rerank])
embed:
  driver: bedrock      # bedrock | openai | fake | <entry-point>
```

## Serve it to an agent

Everything above is also available read-only over **MCP (10 tools)** or as an
in-process AgentForge toolset — see
[`docs/guides/using-over-mcp.md`](https://github.com/Scaffoldic/agentforge-grpah/blob/main/docs/guides/using-over-mcp.md).
Every response carries a **staleness envelope** (indexed commit + whether the
working tree moved), so an agent knows if the graph is behind `HEAD`.
