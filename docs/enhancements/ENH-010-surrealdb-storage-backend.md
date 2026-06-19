# ENH-010: SurrealDB storage backend (graph + vectors in one)

| Field | Value |
|---|---|
| **ID** | ENH-010 |
| **Status** | shipped |
| **Depends on** | ENH-004 (first-party storage backends), feat-003 (store contracts) |
| **Target** | 0.4.x |

## Motivation

ENH-004 proved the `GraphStore` / `VectorStore` contracts against **two
independent server backends** (Neo4j graph + Postgres/pgvector). The storage
guides and ENH-004 itself name **SurrealDB** as the obvious next backend:
*"SurrealDB — graph **and** vector in one — is an attractive future single
backend now that the contract is proven against two independent servers."*

This enhancement delivers that, and — just as importantly — makes the
*"day-one, a consumer can plug in a different DB"* promise **provable end to end
in CI** for a third, independent backend (one that is multi-model, unlike
Neo4j/pgvector which each cover one half).

## Goals

1. A first-party **SurrealDB `GraphStore`** + **`VectorStore`** that pass the
   *unchanged* `GraphStoreConformance` / `VectorStoreConformance` suites — the
   same proof Kuzu, Neo4j, LanceDB and pgvector give.
2. One backend serves **both** roles (graph + vectors), so `store.graph.driver:
   surrealdb` + `store.vectors.driver: surrealdb` is a complete, single-server
   setup.
3. Ship as an **opt-in extra** (`pip install agentforge-graph[surrealdb]`) +
   built-in registry entries; the SDK is lazy-imported so the base install is
   unaffected.
4. **CI service container** running a real SurrealDB, conformance run gated on
   `$CKG_SURREALDB_URL` (mirrors the Neo4j/pgvector `server-backends` job).

## Design

### Schema (same open schema as the property-graph adapters — ADR-0005)

Reuse the shared `_rowmap` flatten (kind/name/span/attrs-JSON/provenance/
`origin_path`). Two document tables + one vector table, keyed by the symbol id
(SurrealDB record id, the id portion backtick-quoted):

- `ckg_node` — one record per node; fields = the `node_params(...)` dict.
- `ckg_edge` — one record per edge; fields = `edge_params(...)` + `src`/`dst`.
  **A plain edge table** (not `RELATE` graph edges): edges are property-bearing
  objects we filter by `kind` and return whole, and ids are arbitrary external
  strings — a `SELECT … WHERE src/dst/kind` model is simpler and reliable for
  bidirectional, kind-filtered traversal than RELATE's per-edge-table sugar.
- `ckg_vector` — `ref` (id), `embedding`, `kind`, `path`, `attrs_json`; the same
  first-class filter columns (`ref`/`kind`/`path`) as LanceDB/pgvector.

### SurrealQL mapping (mirrors neo4j_store / pgvector_store behavior)

- **upsert(subgraph):** transaction — `UPSERT ckg_node:⟨id⟩ CONTENT {…}` per node;
  `DELETE ckg_node WHERE origin_path = $p AND id NOT IN $keep`; `DELETE ckg_edge
  WHERE origin_path = $p`; insert edges. (Per-file replace, transactional.)
- **add(items):** id-keyed `UPSERT` for nodes / inserts for edges (file-agnostic).
- **delete_file(path):** `DELETE ckg_edge WHERE origin_path=$p`; `DELETE ckg_node
  WHERE origin_path=$p`.
- **clear_resolved(paths):** delete `ckg_edge` where `origin_path IN $paths AND
  prov_source = 'resolved'`; then GC `ckg_node` of kind `Package` with no inbound
  edge (so incremental == full).
- **clear_outgoing(src_ids, kind):** `DELETE ckg_edge WHERE src IN $ids AND
  kind = $kind`.
- **query(q):** `SELECT * FROM ckg_node WHERE` kind∈/name=/`string::starts_with
  (sym_path,$prefix)`/source-floor, `LIMIT q.limit+1` (truncation detect).
- **neighbors(id,kinds,depth):** BFS — per hop, `SELECT src,dst FROM ckg_edge
  WHERE (src IN $frontier OR dst IN $frontier) [AND kind IN $kinds]`.
- **get(id):** `SELECT * FROM ckg_node WHERE id=$id`.
- **set_attrs(id,attrs):** read attrs, merge, `UPDATE ckg_node:⟨id⟩ SET attrs=…`
  (no-op if absent; `origin_path` untouched).
- **adjacent(id,kinds,direction):** `SELECT * FROM ckg_edge WHERE` src=/dst=/both
  `[AND kind IN $kinds]` → full `Edge` rows.
- **Vectors:** `DEFINE INDEX … HNSW DIMENSION <d> DIST COSINE` lazily on first
  upsert (dim fixed from first batch, like pgvector); `search` via the
  brute-force KNN form `embedding <|k,COSINE|> $v` + optional equality `WHERE`
  on `ref/kind/path`, cosine **similarity in [0,1]** via
  `vector::similarity::cosine` (BUG-002 parity); `delete_where` filtered on the
  same columns.

### Connection

`open(path, config)` ignores the embedded `path`; reads `url` (→
`$CKG_SURREALDB_URL`, default `ws://localhost:8000/rpc`), `namespace`/`database`
(default `ckg`/`ckg`), `username`/`password` (→ `$CKG_SURREALDB_PASS`). The
`surrealdb` SDK (`AsyncSurreal`, v2.x) is imported lazily. `signin` key form is
verified at runtime (SDK 2.x uses `username`/`password`).

### Packaging

`surrealdb = ["surrealdb>=2,<3"]` extra (pin `<3` — the 3.0 SDK has breaking
API + multi-statement result changes). Registry built-ins gain
`surrealdb` under both `_GRAPH_BUILTINS` and `_VECTOR_BUILTINS`.

## Test strategy

- `tests/store/test_surreal_conformance.py`: `TestSurrealGraphStore
  (GraphStoreConformance)` + `TestSurrealVectorStore(VectorStoreConformance)`,
  **env-gated on `$CKG_SURREALDB_URL`** (skipped in the base CI job).
- CI `server-backends` job: add a `surrealdb/surrealdb` service container; run
  the surreal conformance file alongside neo4j/pgvector.
- Out-of-tree proof rides along: the same suite a third party would subclass now
  passes for a multi-model backend, end to end.

## Risks

| Risk | Mitigation |
|---|---|
| KNN + scalar `WHERE` filter unreliable on some server versions | Use the **brute-force** `<|k,COSINE|>` form (evaluates the full WHERE as a normal predicate); over-fetch+filter fallback if needed |
| SDK 2.x → 3.0 breaking changes | Pin `surrealdb>=2,<3`; conformance re-run on bump |
| `signin` key naming (`username` vs `user`) varies by version | Verified at runtime against the pinned image |
| Record-id quoting for SCIP ids (special chars) | Backtick-quote the id portion; bind values as params |
