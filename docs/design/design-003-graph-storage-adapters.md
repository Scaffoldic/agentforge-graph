# Design Doc: feat-003 graph & vector storage adapters

> Per-feature design doc (design stage of the pipeline). Mirrors
> `docs/features/feat-003-graph-storage-adapters.md`. The feature spec
> says *what & why*; this doc says *how* — concrete file layout, exact
> types, resolved decisions, test plan, chunk plan.

---

## Metadata

| Field | Value |
|---|---|
| **Title** | feat-003 graph & vector storage adapters |
| **Status** | accepted |
| **Owner** | kjoshi |
| **Created** | 2026-06-12 |
| **Last updated** | 2026-06-12 |
| **Related features** | feat-003 (this) · consumes feat-001 · consumed by feat-002, 004, 005, 006, 007 |
| **Related ADRs** | ADR-0001 (layering), ADR-0006 (embedded-first storage) |

---

## 1. Context

feat-001 shipped the `GraphStore` *ABC* plus an `InMemoryGraphStore`
reference impl that lives only in the test tree. That contract rots
without a persistent implementation behind it. feat-003 delivers the
first real adapters — the **conformance baseline every other store is
measured against** — and the `Store` facade that joins graph + vector
queries so feat-006 doesn't reimplement that join per deployment.

ADR-0006 fixes the strategy: **embedded by default, server by
adapter**. Default `ckg index .` writes `.ckg/graph.kuzu` +
`.ckg/vectors.lance` in-repo (gitignored, CI-cacheable, no daemon);
switching to a shared server is config-only.

Two questions the spec leaves implicit are resolved here: how the typed
property-graph backend (Kuzu) represents our *generic, open-kind*
schema, and how `upsert` preserves enrichment facts attached to a node
that gets re-indexed.

## 2. Goals

- A `agentforge_graph.store` package with **zero `agentforge` imports**
  (ADR-0001 layering) — pure engine code.
- `KuzuGraphStore` passing the feat-001 `GraphStoreConformance` suite
  unchanged (interchangeable with `InMemoryGraphStore`).
- `LanceVectorStore` + a new `VectorStoreConformance` suite.
- A `Store` facade resolved from `ckg.yaml`, owning one `GraphStore` +
  one `VectorStore`, with **fail-at-startup** on bad config.
- Enrichment facts (`add()`-written nodes/edges) survive `upsert` and
  `delete_file` of the code files they annotate.
- ≥90% coverage over `agentforge_graph` (not just `core`);
  `mypy --strict` clean; ruff clean.

## 3. Non-goals

- No SQLite fallback adapter in this PR (fast-follow; see §5/§8).
- No Neo4j adapters (opt-in separate packages, post-0.1 per
  spec §4.4).
- No embedding *production* (feat-005 owns it) — the vector store is
  exercised with synthetic vectors here.
- No `CodeGraph.index()` / language packs (feat-002).
- No incremental change detection (feat-004 reads `meta.json` /
  per-path `content_hash` that this feature writes, but owns the diff).
- No Cypher passthrough as public API (adapter-internal only).

## 4. Proposal

### 4.1 Package layout

```
src/agentforge_graph/
  config.py            # NEW: loads ckg.yaml → typed sections (StoreConfig now)
  core/
    contracts.py       # + VectorStore ABC (additive; feat-001 allowed minor adds)
    models.py          # + Embedded, ScoredRef value models
    conformance.py     # + VectorStoreConformance
    __init__.py        # re-export the three new names
  store/
    __init__.py        # curated re-exports: Store, KuzuGraphStore, LanceVectorStore
    facade.py          # Store: owns graph+vectors, .open(), .expand(), .close()
    registry.py        # driver-name → class; built-ins + entry-point discovery
    kuzu_store.py      # KuzuGraphStore(GraphStore)
    lance_store.py     # LanceVectorStore(VectorStore)
    errors.py          # StoreConfigError, SchemaVersionError, DriverNotFound
tests/
  store/
    conftest.py        # tmp-dir kuzu/lance fixtures
    test_kuzu_conformance.py     # GraphStoreConformance against Kuzu
    test_lance_conformance.py    # VectorStoreConformance against LanceDB
    test_facade.py               # config resolution, expand(), fail-at-startup
    test_kuzu_internals.py       # enrichment survival, kind preservation, attrs round-trip
  core/
    test_vector_contracts.py     # Embedded/ScoredRef validation
```

Layering test (feat-001's pattern) is extended to assert nothing under
`store/` imports `agentforge*` either.

### 4.2 Core additions (contracts stay in `core`)

`VectorStore` is a peer contract to `GraphStore`; feat-005/006 depend
on it. Per feat-001's stated policy ("the locked surface; additions are
minor bumps"), it belongs in `core/contracts.py` alongside `GraphStore`
— **not** in the adapter package. The *implementations* live in
`store/`. Layering is preserved (these are pure ABCs/value types).

```python
# core/models.py
class Embedded(BaseModel):
    ref: str                       # symbol/chunk id this vector represents
    vector: list[float]            # validated non-empty
    kind: NodeKind                 # CHUNK / DOC_CHUNK / SUMMARY …
    attrs: dict[str, Any] = Field(default_factory=dict)

class ScoredRef(BaseModel):
    ref: str
    score: float                   # similarity; higher = closer
    attrs: dict[str, Any] = Field(default_factory=dict)

# core/contracts.py
class VectorStore(ABC):
    @abstractmethod
    async def upsert(self, items: list[Embedded]) -> None: ...
    @abstractmethod
    async def search(self, vector: list[float], k: int,
                     filter: dict[str, Any] | None = None) -> list[ScoredRef]: ...
    @abstractmethod
    async def delete_where(self, filter: dict[str, Any]) -> None: ...
    @abstractmethod
    async def close(self) -> None: ...
```

`core/__init__.py` re-exports `Embedded`, `ScoredRef`, `VectorStore`.

### 4.3 Kuzu graph schema — representing an open-kind graph on a typed DB

Kuzu is a typed property graph: tables have fixed columns. Our schema
is *open* (arbitrary `NodeKind`/`EdgeKind`, free-form `attrs`,
unrecognized kinds must round-trip — ADR-0005). Resolution: **one
generic node table + one generic edge table**, with kind as a string
column and `attrs` as a JSON string. Nothing about a kind is baked into
DDL, so an unknown kind stores and reads back identically.

```cypher
CREATE NODE TABLE CkgNode(
  id STRING, kind STRING, name STRING,
  span_start INT64, span_end INT64,            -- NULL when span is None
  attrs STRING,                                 -- json.dumps(sort_keys=True) or ''
  prov_source STRING, prov_extractor STRING,
  prov_commit STRING, prov_confidence DOUBLE,
  origin_path STRING,                           -- the file that produced it; '' for add()'d facts
  PRIMARY KEY(id))

CREATE REL TABLE CkgEdge(
  FROM CkgNode TO CkgNode,
  kind STRING, attrs STRING,
  prov_source STRING, prov_extractor STRING,
  prov_commit STRING, prov_confidence DOUBLE,
  origin_path STRING,                           -- file that produced it; '' for add()'d / resolved
  resolved_from STRING)                         -- feat-004 hook; '' at 0.1

CREATE NODE TABLE CkgFile(                       -- per-path index state (feat-004 reads this)
  path STRING, content_hash STRING, indexed_commit STRING,
  PRIMARY KEY(path))
```

- `attrs` serialized with `json.dumps(attrs, sort_keys=True)` →
  deterministic; `''` decodes to `{}`.
- `span = (s, e)` → `span_start/span_end`; `None` → SQL NULL → decodes
  back to `None`.
- Provenance flattened to four columns; rebuilt via the same
  validating `Provenance(...)` constructor on read (so a corrupt row
  fails loudly, not silently).
- `origin_path` is how `delete_file` and enrichment-survival work
  (§4.4). For `add()`'d facts it is `''`.
- Store-level metadata (`schema_version`, `indexed_commit`,
  pack versions) lives in `.ckg/meta.json`, written on open/close;
  `schema_version` mismatch raises `SchemaVersionError` at open
  (0.x policy: rebuild the index — derivable data).

Kuzu is a **sync** library; every DB call is wrapped in
`asyncio.to_thread` so the async contract is honest and the event loop
isn't blocked. A single `kuzu.Connection` is guarded by an
`asyncio.Lock` (Kuzu connections are not concurrency-safe).

### 4.4 `upsert` / `add` / `delete_file` semantics (the transactional core)

The subtle requirement (conformance
`test_enrichment_survives_file_reupsert`): an `add()`'d SUMMARY node +
`SUMMARIZES` edge pointing at a class node must survive when that
class's file is re-indexed. A naive delete-then-recreate of file nodes
would `DETACH DELETE` the class node and sever the enrichment edge.
Fix: **MERGE file nodes by id instead of dropping them.**

`upsert(subgraph)` — single Kuzu transaction:
1. `MERGE (n:CkgNode {id})` for each node in the subgraph; `SET` all
   columns incl. `origin_path = subgraph.path`. (Re-indexed nodes keep
   their identity → attached enrichment edges stay valid.)
2. Delete stale file nodes: `MATCH (n) WHERE n.origin_path = $path AND
   n.id NOT IN $new_ids DETACH DELETE n`. (Genuinely-removed symbols
   go, along with their edges — correct.)
3. Replace file-owned edges: `MATCH ()-[e:CkgEdge]->() WHERE
   e.origin_path = $path DELETE e`, then insert the subgraph's edges
   with `origin_path = $path`.
4. `MERGE (f:CkgFile {path})` SET `content_hash`, `indexed_commit`.

`add(items)` — for facts not owned by a file:
- Nodes: `MERGE` by id, `origin_path = ''`.
- Edges: insert with `origin_path = ''`. These are never touched by
  `delete_file`, so enrichment/resolved cross-file edges persist.

`delete_file(path)`:
- `MATCH ()-[e:CkgEdge]->() WHERE e.origin_path = $path DELETE e`
- `MATCH (n:CkgNode) WHERE n.origin_path = $path DETACH DELETE n`
- `MATCH (f:CkgFile {path}) DELETE f`
- Enrichment edges (`origin_path=''`) pointing at a deleted node are
  cascaded by `DETACH` — acceptable and matches the InMemory reference
  (the SUMMARY *node* survives; only its dangling edge to a now-gone
  symbol goes).

`query(GraphQuery)` → translate the flat filter to a `MATCH (n:CkgNode)
WHERE …` with `kind IN`, `name =`, `n.id` path-prefix (the path segment
is parsed via `SymbolID.parse`, but we store enough to filter in
Cypher: `origin_path STARTS WITH $prefix` for file-owned, plus an
id-based fallback for `add()`'d nodes), `prov_source` floor by the
`_SOURCE_RANK` ordering, `LIMIT $limit+1` to compute `truncated`.

`neighbors(node_id, kinds, depth)` → variable-length Cypher:
`MATCH (a {id:$id})-[e:CkgEdge*1..$depth]-(b)` with a `WHERE all(rel in
e WHERE rel.kind IN $kinds)` guard; return distinct `b` nodes. Both
directions (undirected match) to mirror the reference impl.

`get(node_id)` → `MATCH (n {id:$id}) RETURN n`.

`close()` → close connection/db, write `meta.json`; idempotent.

### 4.5 LanceDB vector adapter (`lance_store.py`)

LanceDB has a native async client (`lancedb.connect_async`) — use it
directly, no thread-wrapping. One table `vectors` with columns
`ref` (string, PK-ish), `vector` (fixed-size float32 list), `kind`
(string), and flattened `attrs_json` (string). Vector dimension is
fixed on first `upsert` (from `len(items[0].vector)`) and recorded in
`meta.json`; a mismatched dimension later raises.

- `upsert(items)` → delete existing rows with matching `ref`
  (LanceDB has no native upsert across versions we pin), then `add`.
- `search(vector, k, filter)` → `table.search(vector).limit(k)`; the
  `filter` dict becomes a SQL-ish `where` (`kind = 'Chunk'`); rows map
  to `ScoredRef(ref, score=_distance→similarity, attrs)`.
- `delete_where(filter)` → `table.delete(where_clause)`; used by
  feat-004 to drop a changed file's chunk vectors.
- `close()` → drop the connection handle.

### 4.6 `Store` facade + config (`facade.py`, `config.py`, `registry.py`)

```python
# config.py — OUR file, lenient (extra='ignore'); opposite of agentforge.yaml's strict validator
class GraphCfg(BaseModel):  driver: str = "kuzu";    config: dict[str, Any] = {}
class VectorCfg(BaseModel): driver: str = "lancedb"; config: dict[str, Any] = {}
class StoreConfig(BaseModel):
    path: str = ".ckg"
    graph: GraphCfg = GraphCfg()
    vectors: VectorCfg = VectorCfg()
    @classmethod
    def load(cls, ckg_yaml: str | Path | None = None) -> "StoreConfig": ...
        # reads the `store:` block; missing file → all defaults

# registry.py
GRAPH_DRIVERS = {"kuzu": KuzuGraphStore}        # + entry-point group agentforge_graph.store_drivers
VECTOR_DRIVERS = {"lancedb": LanceVectorStore}  # neo4j/pgvector and other backends register out-of-tree

# facade.py
class Store:
    graph: GraphStore
    vectors: VectorStore
    @classmethod
    async def open(cls, repo_path=".", config: str | None = None) -> "Store": ...
    async def expand(self, refs: list[ScoredRef], kinds: list[EdgeKind],
                     depth: int = 1) -> QueryResult: ...   # vector hits → graph neighborhood
    async def close(self) -> None: ...
```

- `Store.open` resolves drivers from the registry; **unknown driver →
  `DriverNotFound`**, unreachable server / dimension or schema mismatch
  → raise *at open*, never mid-index (spec §4.5).
- `expand(refs, …)` is the graph+vector join feat-006 builds on:
  for each `ScoredRef.ref`, `get` the node and `neighbors(...)`, union
  into one `QueryResult`. Minimal but real, so the join lives in one
  place.
- `CodeGraph.open(".")` from the spec sketch is **deferred to feat-002**
  (where `CodeGraph` + `index()` are introduced); `Store.open` is the
  feat-003 entry point. Logged as a deviation in §9.

### 4.7 Tooling changes

- `pyproject.toml`: coverage scope `--cov=agentforge_graph.core` →
  `--cov=agentforge_graph` (measure the new package); keep
  `--cov-fail-under=90`. Add mypy `ignore_missing_imports` overrides
  for `kuzu`, `lancedb`, `pyarrow` (no shipped stubs).
- `.github/workflows/ci.yml`: `uv sync --extra dev` →
  `uv sync --extra dev --extra engine` (kuzu + lancedb live in
  `engine`). **feat-003 is the first feature that needs native wheels
  in CI** — the memory note pinned this to feat-002, but storage lands
  first. Watch CI wall-clock (onnxruntime/pyarrow are heavy); if it
  bloats, split a lighter `store` extra later.

## 5. Alternatives considered

| Option | Why not |
|---|---|
| Per-kind Kuzu node tables (a table per `NodeKind`) | Breaks ADR-0005 ignore-and-preserve (unknown kinds have no table); schema churns every time a kind is added; cross-kind queries need UNION. Generic table is simpler and honors the open schema. |
| `attrs` as Kuzu `MAP`/`STRUCT` columns | Kuzu typing is rigid for heterogeneous dicts; JSON string round-trips losslessly and is determinism-friendly. |
| Ship SQLite fallback in this PR too | Doubles adapter + conformance surface for a reviewer; Kuzu wheels cover our platforms (CI linux, dev macOS). Fast-follow if a wheel gap appears. |
| Put `VectorStore` ABC in `store/` not `core/` | Splits the contract surface (GraphStore in core, VectorStore elsewhere); feat-005/006 import contracts from one place. Keep all ABCs in core. |
| delete-then-recreate file nodes on upsert | Severs enrichment edges attached to re-indexed nodes (fails conformance intent). MERGE-by-id preserves identity. |
| Run Kuzu sync calls directly in async methods | Blocks the event loop; `asyncio.to_thread` keeps the async contract honest. |

## 6. Migration / rollout

Greenfield — no persisted graphs exist. `meta.json.schema_version`
starts at `1`; on mismatch the 0.x policy is **rebuild** (derivable
data, ADR-0006). Adapters are entry-point discoverable, so neo4j /
other backends / sqlite land later as `pip install` + one config line with no
core change. `store/__init__.py` is the curated public surface.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Kuzu pre-1.0 API churn (we pin `kuzu>=0.6`) | Thin adapter; conformance suite makes swapping the default cheap; SQLite fallback is the boring escape hatch (fast-follow). |
| Native wheels blow up CI time | Measure on first run; carve a lighter `store` extra (kuzu+lancedb only, no fastembed) if `engine` is too heavy for the storage job. |
| `mypy --strict` over untyped `kuzu`/`lancedb` | `ignore_missing_imports` overrides; keep adapter boundaries typed so our code stays strict-clean. |
| 90% coverage hard to hit on native error paths | Keep adapters thin; add targeted tests for close/idempotency/fail-at-startup; conformance covers the happy paths. |
| Variable-length `neighbors` Cypher kind-filtering correctness | Mirror the InMemory reference semantics exactly; the shared conformance `test_neighbors_walks_contains` gates it. |
| LanceDB upsert = delete+add not atomic | Acceptable at 0.1 (single-writer embedded); `meta.json` records last committed batch for feat-004 reconciliation. |

## 8. Open questions (decisions for review)

1. **SQLite fallback now or fast-follow?** Proposed: **fast-follow**
   (kuzu covers our platforms). Flip if you want belt-and-suspenders
   portability in the first storage PR.
2. **`VectorStore` contract in `core`?** Proposed: **yes** (peer of
   `GraphStore`; additive minor bump). Alternative is to keep it in
   `store/`.
3. **Vectors in feat-003 at all, or graph-only now?** Proposed:
   **include vectors** (spec bundles them; feat-006's join wants both
   in one facade). Graph-only would shrink the PR but split the feature
   across two PRs against one spec.

## 9. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-12 | Generic `CkgNode`/`CkgEdge` tables, kind as column, `attrs` as JSON string | Honors ADR-0005 open schema; unknown kinds round-trip without DDL change |
| 2026-06-12 | `upsert` MERGEs file nodes by id (no delete+recreate) | Preserves enrichment edges attached to re-indexed nodes (conformance) |
| 2026-06-12 | `origin_path` column tags file-owned vs `add()`'d facts | Single mechanism for `delete_file` + enrichment survival + feat-004 invalidation |
| 2026-06-12 | `VectorStore`/`Embedded`/`ScoredRef` added to `core` | All contracts in one place; pure types, layering intact |
| 2026-06-12 | Kuzu calls via `asyncio.to_thread` + per-conn `asyncio.Lock` | Honest async; Kuzu is sync and not concurrency-safe |
| 2026-06-12 | Coverage scope widened to `agentforge_graph` | New `store` package must be measured against the 90% floor |
| 2026-06-12 | CI gains `--extra engine` | Native wheels (kuzu/lancedb) needed; storage is the first feature to need them |
| 2026-06-12 | `Store.open` is the entry point; `CodeGraph.open` deferred to feat-002 | Avoid premature top-level facade; `CodeGraph` is introduced with `index()` |
| 2026-06-12 | SQLite / Neo4j / other graph-server backends deferred | Keep the PR reviewable; adapters are entry-point pluggable later |

## 10. Chunk plan (the single feat-003 PR)

| Chunk | Commit | Contents |
|---|---|---|
| 0 | `chore(003): widen coverage + engine deps in CI` | pyproject cov scope → `agentforge_graph`, mypy overrides; CI `--extra engine` |
| 1 | `feat(003): vector-store contracts in core` | `Embedded`, `ScoredRef`, `VectorStore` ABC; `core/__init__` re-exports; `VectorStoreConformance` |
| 2 | `feat(003): kuzu graph adapter` | `store/kuzu_store.py` (schema, MERGE upsert, add, delete_file, query, neighbors, get, close), `errors.py`, `meta.json` |
| 3 | `feat(003): lancedb vector adapter` | `store/lance_store.py` (upsert, search, delete_where, close) |
| 4 | `feat(003): store facade + config` | `config.py` (`StoreConfig.load`), `registry.py`, `facade.py` (`Store.open`, `expand`, `close`) |
| 5 | `test(003): conformance + facade + layering` | Kuzu→`GraphStoreConformance`, Lance→`VectorStoreConformance`, facade/fail-at-startup, store layering test, attrs/kind/enrichment round-trip |
| 6 | `docs(003): impl status + design accepted` | spec Implementation status; this doc → `accepted`; TRACKER feat-003 → shipped-pending |

## 11. References

- Spec: `docs/features/feat-003-graph-storage-adapters.md`
- ADRs: 0001 (layering), 0006 (embedded-first storage)
- feat-001 `GraphStore` ABC + `GraphStoreConformance`; consumed by
  feat-002 (`IngestPipeline`/`ImportResolver` take a `GraphStore`),
  feat-004 (transactional upsert + `meta.json`), feat-006
  (`Store.expand`).
- Prior art: pluggable-adapter CKG designs (research §2.6); Kuzu embedded
  graph DB; agentforge-py neo4j vector store (driver conventions).
</content>
</invoke>
