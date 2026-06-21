# Storage backends — embedded by default, server when you need it

> **TL;DR:** Embedded Kuzu + LanceDB by default (zero setup, under `.ckg/`).
> Switch to Neo4j / pgvector / SurrealDB via `ckg.yaml`'s `store:` block + the
> matching extra (`[neo4j]` / `[pgvector]` / `[surrealdb]`) — same commands, same
> conformance suite.

agentforge-graph is **embedded-first** (ADR-0006): with no configuration it writes
an index under `.ckg/` in your repo (Kuzu for the graph, LanceDB for vectors).
Zero setup, nothing to run, perfect for a single developer or CI.

When a **team** wants a *shared, server-backed* index — many developers or CI jobs
hitting one store — or wants to reuse existing infrastructure, swap in a server
backend with one `ckg.yaml` line. The graph and vector stores are independent, so
you can move either (or both).

## What ships

| Layer | Embedded (default) | Server |
|---|---|---|
| **Graph** | `kuzu` | **`neo4j`** (`[neo4j]`) · **`surrealdb`** (`[surrealdb]`) |
| **Vectors** | `lancedb` | **`pgvector`** (`[pgvector]`) · **`surrealdb`** (`[surrealdb]`) |

**SurrealDB is multi-model** — one `surrealdb` server covers *both* the graph and
the vectors (ENH-010), so `store.graph.driver: surrealdb` +
`store.vectors.driver: surrealdb` is a complete single-server setup.

Every backend passes the **same** `GraphStoreConformance` / `VectorStoreConformance`
suite — they are true drop-ins, verified by the identical tests the embedded
defaults pass (and, for the server backends, run against real Neo4j + Postgres +
SurrealDB
in CI).

## Where the index lives — in-repo vs. central (ENH-018)

Independent of *which* backend you pick is *where* its artifacts live. This is a
deliberate developer choice:

| Shape | Config | Who builds | Who reads |
|---|---|---|---|
| **Laptop** (default) | `store.path: .ckg` | the dev | the dev |
| **Central, embedded** | `store.central_root: /shared/ckg` | a team / CI | many |
| **Central, server** | `store.graph.driver: surrealdb` (or neo4j/pgvector) + a shared host | a team / CI | many |

By default the index is the gitignored `.ckg/` inside the repo — zero infra, it
travels with the working copy. To **host it centrally** (build once, serve many
developers and agents), set a `central_root`:

```yaml
# agentforge.yaml (app:) or a standalone ckg.yaml
store:
  central_root: ~/.agentforge/ckg     # absolute → artifacts live here, not in the repo
```

Each repo is placed in a **stable, collision-free subdir** under that root —
keyed by its git remote (`org/repo`, the same on every machine) or, with no
remote, by `<dirname>-<hash>`. So pointing three repos at one `central_root`
gives three separate indexes, never a clash. `ckg status` prints the resolved
location (with `(central)` when hosting is on). An **absolute** `store.path` still
works for a single relocated repo; `central_root` is the multi-repo, no-collision
way.

**Build once, consume many — read-only consumers.** When a team/CI builds the
central index, hand it to developers and agents **consume-only** so nobody
mutates it by accident:

```yaml
store:
  read_only: true        # or pass --read-only, or set $CKG_READ_ONLY=1
```

A read-only store **refuses** the write verbs (`index`/`embed`/`enrich`) with a
clear error, and opening a *missing* index errors rather than creating one;
`query`/`map`/`routes`/`serve-mcp` work normally. Build where it's writable
(CI/owning team), consume read-only everywhere else.

> This is the first rung of hosting CKG as **org-level central knowledge** —
> see [`docs/enhancements/THEME-org-central-knowledge.md`](../enhancements/THEME-org-central-knowledge.md).

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

## Switch both to SurrealDB (one server)

SurrealDB is multi-model, so a single server is **both** the graph and the
vectors (ENH-010):

```bash
pip install 'agentforge-graph[surrealdb]'   # or: uv sync --extra surrealdb
```
```yaml
# ckg.yaml
store:
  graph:   { driver: surrealdb, config: { url: ws://your-host:8000/rpc } }
  vectors: { driver: surrealdb, config: { url: ws://your-host:8000/rpc } }
```

Password via `CKG_SURREALDB_PASS` (or `config.password`); `namespace`/`database`
default to `ckg`. The graph is two document tables (`ckg_node`/`ckg_edge`, the
same open schema); vectors use brute-force cosine in `[0, 1]`. Local server:
`docker run -p 8000:8000 surrealdb/surrealdb:latest start --user root --pass root memory`.

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

The first-party server backends (Neo4j, pgvector, SurrealDB) are just the start —
the registry is open: a third-party adapter registers via the
`agentforge_graph.graph_drivers` / `agentforge_graph.vector_drivers` entry-point
groups and is selected by the same `driver:` key, with no core change. Implement
`GraphStore` / `VectorStore`, pass the conformance suite, register the entry
point — then it's `pip install your-adapter` + one config line. The SurrealDB
adapter (a multi-model single server) is the worked proof that the contract holds
for an independent third backend.
