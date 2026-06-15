# Storage backends — embedded by default, server when you need it

agentforge-graph is **embedded-first** (ADR-0006): with no configuration it writes
an index under `.ckg/` in your repo (Kuzu for the graph, LanceDB for vectors).
Zero setup, nothing to run, perfect for a single developer or CI.

When a **team** wants a *shared, server-backed* index — many developers or CI jobs
hitting one store — or wants to reuse existing infrastructure, swap in a server
backend with one `ckg.yaml` line. The graph and vector stores are independent, so
you can move either (or both).

## What ships

| Layer | Embedded (default) | Server (ENH-004) |
|---|---|---|
| **Graph** | `kuzu` | **`neo4j`** — `pip install agentforge-graph[neo4j]` |
| **Vectors** | `lancedb` | **`pgvector`** — `pip install agentforge-graph[pgvector]` |

Every backend passes the **same** `GraphStoreConformance` / `VectorStoreConformance`
suite — they are true drop-ins, verified by the identical tests the embedded
defaults pass (and, for the server backends, run against real Neo4j + Postgres
in CI).

## Switch the graph to Neo4j

```bash
pip install 'agentforge-graph[neo4j]'      # or: uv sync --extra neo4j
export CKG_NEO4J_PASSWORD=…                 # keep the secret out of ckg.yaml
```

```yaml
# ckg.yaml
store:
  graph:
    driver: neo4j
    config:
      uri: bolt://your-neo4j-host:7687
      user: neo4j                 # password read from $CKG_NEO4J_PASSWORD
      # database: neo4j           # optional (defaults to "neo4j")
```

`ckg index / embed / enrich / query / map / serve-mcp` then read and write that
Neo4j. The model is mapped onto one `:CkgNode` label + one `:CkgEdge` relationship
type (with `kind` as a property), so it round-trips every node/edge kind without
schema migrations.

## Switch the vectors to Postgres + pgvector

```bash
pip install 'agentforge-graph[pgvector]'   # or: uv sync --extra pgvector
export CKG_PGVECTOR_DSN=postgresql://user@host:5432/db
```

```yaml
# ckg.yaml
store:
  vectors:
    driver: pgvector
    config:
      dsn: postgresql://user@your-pg-host:5432/ckg   # or set $CKG_PGVECTOR_DSN
```

The adapter ensures the `vector` extension exists, creates a `ckg_vectors` table
(dimension fixed from your embedder on first write), and uses cosine distance —
exposing a similarity in `[0, 1]` exactly like the embedded default.

## Mix and match

The two are orthogonal — e.g. a shared Neo4j graph with embedded LanceDB vectors,
or embedded Kuzu with a shared pgvector. Anything the config allows, the facade
opens; a bad driver name or unreachable server fails **at `open`**, never
mid-index.

## Secrets

Put **connection coordinates** (uri, dsn, user) in `ckg.yaml`; keep **passwords**
in the environment — `CKG_NEO4J_PASSWORD`, or a full `CKG_PGVECTOR_DSN`. (AuthN/Z
for the *HTTP MCP transport* is a separate concern — see ENH-005.)

## Bring your own backend

The two server backends are first-party, but the registry is open: a third-party
adapter registers via the `agentforge_graph.graph_drivers` /
`agentforge_graph.vector_drivers` entry-point groups and is selected by the same
`driver:` key, with no core change. Implement `GraphStore` / `VectorStore` and pass
the conformance suite. (SurrealDB — graph **and** vector in one — is an attractive
future single backend now that the contract is proven against two independent
servers.)
