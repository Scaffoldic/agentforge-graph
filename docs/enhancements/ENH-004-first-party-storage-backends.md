# ENH-004: First-party storage backend adapters (consumer choice of DB)

| Field | Value |
|---|---|
| **ID** | ENH-004 |
| **Value/Impact** | Medium–High (team/server deployments beyond a single embedded repo) |
| **Effort** | M–L (per backend) |
| **Status** | **done** (2026-06-15) |
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

## Resolution (2026-06-15)

Shipped both server backends, each passing the **unchanged** conformance suite:

- **Graph — Neo4j** (`store/neo4j_store.py`, `[neo4j]` extra → `neo4j>=5`). Neo4j
  speaks Cypher like the embedded Kuzu default, so it's a close port: same open
  schema (one `:CkgNode` label + one `:CkgEdge` rel type, `kind` a property,
  `attrs` a JSON string), an `id` uniqueness constraint, and multi-statement
  `upsert` run in one `execute_write` transaction. Passes `GraphStoreConformance`.
- **Vectors — pgvector** (`store/pgvector_store.py`, `[pgvector]` extra →
  `asyncpg` + `pgvector`). One `ckg_vectors` table (dim fixed from the first
  batch), `INSERT … ON CONFLICT` upsert, cosine `<=>` distance exposed as a
  similarity in `[0, 1]` (BUG-002), the same `ref`/`kind`/`path` filter columns.
  Passes `VectorStoreConformance`.

**Enabling work (verifiable, embedded unaffected):** `Store.open` now passes the
`store.{graph,vectors}.config` block to each driver's `open(path, config)`
(embedded drivers ignore it). The pure `Node`/`Edge` ↔ row mapping was extracted to
`store/_rowmap.py` and shared by Kuzu + Neo4j. Both server SDKs are imported
**lazily** inside `open`, so the registry references them unconditionally and the
modules import with no extra installed. Connection coords live in `ckg.yaml`;
passwords come from `$CKG_NEO4J_PASSWORD` / `$CKG_PGVECTOR_DSN`.

**Verified:** the full server conformance (19 tests) runs against live Neo4j 5 +
Postgres/pgvector — locally and **in CI** via a dedicated `server-backends` job
with public service containers (no secrets). End-to-end `ckg index → embed →
query` confirmed against Neo4j + pgvector together. Embedded Kuzu/LanceDB stays
the zero-config default. Guide: `docs/guides/storage-backends.md`. Coverage held
≥90% (server adapters covered by the live job; main gate at ~94%).

## Notes / alternatives

- Watch transactional semantics: incremental indexing relies on per-`origin_path`
  delete + atomic multi-statement upsert and the `clear_*` primitives — these
  must map cleanly onto the backend (the conformance suite covers them, incl. the
  feat-004 equivalence invariant once wired into an integration run).
- SurrealDB as a single graph+vector store is compelling for the embedded story
  too; evaluate after the contract is proven against two independent backends.
