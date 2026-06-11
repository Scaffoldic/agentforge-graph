# feat-003: Graph & vector storage adapters

## Metadata

| Field | Value |
|---|---|
| **ID** | feat-003 |
| **Title** | Graph & vector storage adapters (embedded-first, pluggable) |
| **Status** | proposed |
| **Owner** | kjoshi |
| **Created** | 2026-06-11 |
| **Target version** | 0.1.0 |
| **Languages** | python |
| **Module package(s)** | `agentforge_graph.store`, opt-in `agentforge-graph-neo4j`, `agentforge-graph-falkordb` |
| **Depends on** | feat-001 |
| **Blocks** | feat-004, feat-005, feat-006, feat-007 |

---

## 1. Why this feature

The survey showed storage choice is where CKG tools either become
zero-ops local tools (Joern's embedded flatgraph, Codebase-Memory's
single SQLite file) or ops-heavy services (Glean's RocksDB service,
Potpie's Neo4j requirement). For an agent that runs on a laptop or in
CI next to Claude Code, requiring a database server kills adoption.
But teams sharing one graph across agents legitimately want a server
(Neo4j/FalkorDB).

cognee resolved this tension with pluggable adapters behind one
interface (verified: Kuzu, Neo4j, Neptune, Postgres graph adapters;
ChromaDB, LanceDB, pgvector vector adapters). We adopt the same
shape: **embedded by default, server by adapter**.

## 2. Why it must ship in the agent core

- The `GraphStore` ABC is defined in feat-001, but contracts without
  a reference implementation rot. The embedded adapter is the
  conformance baseline every other adapter is tested against.
- Retrieval (feat-006) needs graph and vector queries to compose
  (vector hit → graph expansion in one call path). If graph and
  vector stores were bolted together per deployment, that join would
  be reimplemented everywhere.
- Incremental indexing (feat-004) needs `upsert(FileSubgraph)` /
  `delete_file()` transactional semantics. That atomicity is a store
  responsibility.

## 3. How consumers benefit

- Default experience is zero-ops: `ckg index .` creates
  `.ckg/graph.kuzu` + `.ckg/vectors.lance` in the repo — no daemon,
  no Docker, CI-friendly, gitignored.
- Switching to a shared Neo4j is config-only:
  `store.graph.driver: neo4j` — no code change in any agent.
- Adapter authors implement one ABC and run the shipped conformance
  suite; agents trust any passing adapter equally.

## 4. Feature specifications

### 4.1 User-facing experience

```python
graph = await CodeGraph.open(".")              # embedded default
graph = await CodeGraph.open(".", config="ckg.yaml")  # server adapters
hits = await graph.store.neighbors("ckg py myrepo src/app/auth.py login().",
                                   kinds=["CALLS"], depth=2)
```

### 4.2 Public API / contract

Implements feat-001's `GraphStore` plus a `VectorStore` ABC:

```python
class VectorStore(ABC):
    @abstractmethod
    async def upsert(self, items: list[Embedded]) -> None: ...
    @abstractmethod
    async def search(self, vector: list[float], k: int,
                     filter: dict | None = None) -> list[ScoredRef]: ...
    @abstractmethod
    async def delete_where(self, filter: dict) -> None: ...
    @abstractmethod
    async def close(self) -> None: ...

class Store:
    """Facade owning one GraphStore + one VectorStore, resolved from config."""
    graph: GraphStore
    vectors: VectorStore
    async def expand(self, refs: list[ScoredRef], kinds, depth) -> Subgraph: ...
```

**Adapters at 0.1:**

| Driver | Backend | Notes |
|---|---|---|
| `kuzu` (default) | Kuzu embedded graph DB | columnar, Cypher, single dir |
| `sqlite` | SQLite (edges as tables, WAL) | fallback where kuzu wheel unavailable |
| `lancedb` (default) | LanceDB embedded vectors | |
| `neo4j` | Neo4j 5.x server | opt-in package, also serves vectors (5.x vector index) |
| `falkordb` | FalkorDB server | opt-in package, post-0.1 |

### 4.3 Internal mechanics

- `upsert(FileSubgraph)` is transactional per file: delete prior
  nodes/edges keyed by `path` where `content_hash` differs, insert
  new — the primitive feat-004 builds on. Enrichment nodes attached
  to *symbol IDs* (not files) survive untouched.
- Cross-file resolved edges store `resolved_from: path` so feat-004
  can invalidate exactly the edges a changed file produced.
- Embedded layout: `.ckg/` directory at repo root (configurable);
  contains graph dir, vector dir, and `meta.json` (schema version,
  indexed commit, pack versions) — the handle feat-004 reads.
- Kinds the adapter doesn't recognize are stored generically
  (kind as string property), honoring feat-001's ignore-and-preserve
  rule.

### 4.4 Module packaging

- `agentforge_graph.store` with `kuzu`/`sqlite`/`lancedb` in the
  default install.
- `agentforge-graph-neo4j`, `agentforge-graph-falkordb` as separate
  pip packages registering via entry point
  `agentforge_graph.store_drivers`.

### 4.5 Configuration

```yaml
store:
  path: .ckg                  # embedded root
  graph:
    driver: kuzu              # kuzu | sqlite | neo4j | falkordb
    config: {}                # driver-specific (uri, auth via ${ENV})
  vectors:
    driver: lancedb           # lancedb | neo4j | pgvector(post-0.1)
    config: {}
```

Fail-at-startup: unknown driver, unreachable server, or schema
version mismatch raise at `CodeGraph.open()`, never mid-index.

## 5. Plug-and-play & upgrade story

Adapters are entry-point modules — add later by `pip install` + one
config line. Embedded `meta.json` carries `schema_version`; on
mismatch, 0.x policy is **rebuild the index** (cheap, derivable
data); post-1.0 revisit migrations.

## 6. Cross-language parity

n/a.

## 7. Test strategy

- **Conformance suite** (the centerpiece): one pytest suite —
  upsert/re-upsert idempotency, file-transactionality, enrichment
  survival across re-upsert, neighbor expansion, kind-preservation —
  run against every adapter (server adapters via testcontainers,
  env-gated as live tests per workspace pipeline).
- Unit: config resolution, fail-at-startup paths.
- Scale: 100k-node synthetic graph; assert expansion latency budget.

## 8. Risks & open questions

| Risk / Question | Mitigation / Decision |
|---|---|
| Kuzu API stability (pre-1.0 ecosystem) | sqlite adapter is the boring fallback; conformance suite makes swapping defaults cheap |
| Two stores (graph+vector) drift out of sync on crash | `meta.json` records last fully-committed file batch; feat-004 reconciles on open |
| Neo4j as both graph+vector vs separate LanceDB | Allowed both; facade hides it. Benchmark before making either the recommended server layout |
| Embedded `.ckg/` in-repo vs XDG cache dir | In-repo default (CI cacheable, per-checkout isolation); configurable |

## 9. Out of scope

- Multi-repo federated graphs (one store = one repo at 0.x;
  cross-repo is a post-1.0 feature).
- Access control / multi-tenant serving.
- Cypher passthrough as public API (adapter-specific escape hatch
  only, marked experimental).

## 10. References

- Research §2.6 (cognee pluggable adapters — verified), §2.11
  (SQLite/embedded packaging trend), §2.1 (Joern flatgraph), §5
  storage recommendation.
- feat-001 `GraphStore` ABC; feat-004 (consumes transactional
  upsert); feat-006 (consumes `Store.expand`).
- AgentForge prior art: agentforge-py feat-025 (neo4j vector store)
  for driver conventions.

---

## Implementation status

Not started.
