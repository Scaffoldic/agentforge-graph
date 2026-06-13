# ENH-004: First-party storage backend adapters (consumer choice of DB)

| Field | Value |
|---|---|
| **ID** | ENH-004 |
| **Value/Impact** | Medium–High (team/server deployments beyond a single embedded repo) |
| **Effort** | M–L (per backend) |
| **Status** | proposed |
| **Area** | `store` |
| **Relates to** | feat-003 (storage adapters), ADR-0006 (embedded-first, pluggable) |

## Motivation

Storage is **already pluggable** — `GraphStore`/`VectorStore` contracts, a
`GraphStoreConformance`/`VectorStoreConformance` suite, and a driver registry
with entry-point groups (`store/registry.py`). But only **`kuzu` + `lancedb`**
ship. A team that wants a **shared, server-backed** graph (multiple devs/CI hit
one store) or to reuse existing infra (Neo4j, Postgres/pgvector) currently has to
write the adapter themselves. To make "switch your backend" a real consumer
choice — as the README implies — at least one server backend should be
first-party.

## Current behavior

- `_GRAPH_BUILTINS = {"kuzu": KuzuGraphStore}`,
  `_VECTOR_BUILTINS = {"lancedb": LanceVectorStore}` (`store/registry.py`).
- Server adapters are a documented out-of-tree entry-point path — but none exist,
  so the "pluggable" story is currently theoretical for end users.

## Proposed change

Ship one server graph backend and one server vector backend as **optional
extras**, each passing the conformance suite:

- **Graph:** a **Neo4j** `GraphStore` (the framework already has a Neo4j memory
  dep; reuse the driver). Map the generic node/edge model onto Neo4j labels +
  relationship types. Honour `upsert`/`delete_file`/`clear_resolved`/
  `clear_outgoing`/`adjacent` exactly (the conformance suite enforces it).
- **Vectors:** a **pgvector** (Postgres) `VectorStore`, so teams reuse an existing
  Postgres. (SurrealDB — graph **and** vector in one — is an attractive single
  backend; a good follow-up once the contract shapes are proven against Neo4j +
  pgvector.)

Each as `pip install agentforge-graph[neo4j]` / `[pgvector]` + a `ckg.yaml` line:

```yaml
store:
  graph:   { driver: neo4j,   config: { uri: bolt://…, … } }
  vectors: { driver: pgvector, config: { dsn: postgres://… } }
```

## Acceptance criteria

- The new backend **passes `GraphStoreConformance` / `VectorStoreConformance`**
  unchanged — it's a true drop-in, verified by the same suite Kuzu/LanceDB pass.
- `ckg index/embed/enrich/query` all work against it end-to-end (an integration
  test, env-gated where it needs a live server / via a container in CI).
- Embedded (Kuzu/LanceDB) stays the **zero-config default**; server backends are
  strictly opt-in.

## Notes / alternatives

- Watch transactional semantics: incremental indexing relies on per-`origin_path`
  delete + atomic multi-statement upsert and the `clear_*` primitives — these
  must map cleanly onto the backend (the conformance suite covers them, incl. the
  feat-004 equivalence invariant once wired into an integration run).
- SurrealDB as a single graph+vector store is compelling for the embedded story
  too; evaluate after the contract is proven against two independent backends.
