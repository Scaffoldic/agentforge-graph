# ENH-015: Postgres graph backend (one Postgres for graph + vectors)

| Field | Value |
|---|---|
| **ID** | ENH-015 |
| **Value/Impact** | Med (Postgres is the most common existing infra) |
| **Effort** | M–L |
| **Status** | proposed (0.4.0/0.5 candidate) |
| **Area** | `store` |
| **Relates to** | ENH-004 (first-party backends), ENH-010 (SurrealDB single-server), feat-003 (contracts) |

## Motivation

Postgres + pgvector already covers the **vector** role (ENH-004). There is no
Postgres **graph** driver — so a team on Postgres still needs Kuzu/Neo4j/SurrealDB
for the graph. A `PostgresGraphStore` would let them run **both graph + vectors on
one Postgres** (the single-server win SurrealDB gives, but on the database most
teams already operate). It also exercises the extension contract against a
relational (non-graph-native) backend.

## Analysis — feasibility

The `GraphStore` contract is satisfiable on plain SQL:

- **Schema:** `ckg_node` (id PK, kind, name, span, `attrs jsonb`, sym_path,
  provenance cols, origin_path) + `ckg_edge` (src, dst, kind, `attrs jsonb`,
  provenance, origin_path) — the same `_rowmap` flatten the property-graph
  adapters use.
- **Reads:** `query` → `SELECT … WHERE`; `get`/`set_attrs` → by id + `jsonb`
  merge; `adjacent` → `SELECT … WHERE src/dst`; **`neighbors`** → a **recursive
  CTE** over `ckg_edge` (the one non-trivial query), or iterative per-hop SELECTs
  (mirroring the Neo4j BFS) to stay simple.
- **Writes:** `upsert` (per-file replace in a tx), `clear_resolved` (+ Package GC
  via a `NOT IN (SELECT dst …)` like SurrealDB), `clear_outgoing`.
- Index `kind`, `src`, `dst`, `origin_path`, `sym_path`.

It passes the **unchanged `GraphStoreConformance`** suite — the same proof Kuzu/
Neo4j/SurrealDB give. Reuses `asyncpg` (already a dep of the `pgvector` extra).

## Proposed approach

- `store/postgres_graph_store.py` mirroring `neo4j_store.py` in SQL; register
  `postgres` (or `pg`) under `_GRAPH_BUILTINS`. Put it in the existing `pgvector`
  extra (or a `postgres` extra) — `asyncpg` is shared.
- `tests/store/test_postgres_graph_conformance.py`, env-gated on a DSN, in the
  `server-backends` CI job (the Postgres service container already exists).
- Doc: storage-backends guide — "one Postgres, graph + vectors."

## Risks

| Risk | Mitigation |
|---|---|
| `neighbors` recursive CTE correctness/perf | Start with the iterative per-hop BFS (proven in the Neo4j adapter); optimise later |
| Another backend to maintain | Conformance suite keeps parity automatic; CI runs it on every PR |

## 0.4.0 candidacy

Solid 0.4.0 candidate — high "meet teams where they are" value, the CI Postgres
service already exists, and the conformance suite de-risks it. Comparable effort
to the SurrealDB adapter (ENH-010), which is now the template.
