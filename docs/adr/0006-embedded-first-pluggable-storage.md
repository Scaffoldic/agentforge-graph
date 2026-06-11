# ADR-0006: Embedded-first, pluggable graph + vector storage

## Metadata

| Field | Value |
|---|---|
| **Number** | 0006 |
| **Title** | Embedded-first, pluggable graph + vector storage |
| **Status** | Accepted |
| **Date** | 2026-06-11 |
| **Deciders** | kjoshi |
| **Tags** | architecture, storage, packaging |

---

## 1. Context and problem statement

agentforge-graph runs in two very different places: on a developer's
laptop or in CI alongside a coding agent (where a database server is
unwelcome friction), and in shared team deployments where many agents
query one graph (where a server is wanted). The survey showed tools
split on this — Joern and Codebase-Memory are embedded/zero-ops, while
Potpie and Glean require a server. cognee resolved the tension with
pluggable adapters behind one interface. Where do we store the graph
and the vectors so the laptop case stays zero-ops without foreclosing
the shared-server case?

## 2. Decision drivers

- Default experience must be zero-ops: `ckg index .` with no Docker,
  no daemon, CI-cacheable.
- Graph and vector queries must compose in one call path (vector hit →
  graph expansion) for feat-006 retrieval.
- Teams must be able to point many agents at one shared graph without
  changing agent code.
- Per-file transactional upsert/delete is required by ADR-0003 /
  feat-004 incrementality.

## 3. Considered options

1. **Fixed embedded store** (e.g. SQLite only).
2. **Fixed server** (e.g. Neo4j required).
3. **Pluggable adapters, embedded default** — Kuzu + LanceDB in a
   `.ckg/` dir by default; Neo4j / FalkorDB as opt-in adapters.

## 4. Decision outcome

**Chosen: Option 3 — pluggable adapters behind `GraphStore` /
`VectorStore` ABCs, embedded by default.** Default is Kuzu (embedded
graph) + LanceDB (embedded vectors) written to a gitignored `.ckg/`
directory at the repo root, with a `meta.json` carrying schema
version, indexed commit, and pack versions. A SQLite graph adapter is
the boring fallback; Neo4j and FalkorDB are opt-in pip packages
registered via entry point. A `Store` facade owns one graph + one
vector store and provides the `expand()` join that retrieval needs.
The embedded adapter is the conformance baseline every other adapter
is tested against.

### Positive consequences

- Zero-ops default: no server, CI-friendly, per-checkout isolation.
- Switching to shared Neo4j/FalkorDB is config-only — no agent code
  changes.
- One conformance suite guarantees adapters are interchangeable.
- `meta.json` is the handle incremental indexing and staleness
  detection read.

### Negative consequences (trade-offs)

- Two stores (graph + vector) can drift on a crash; reconciled via
  `meta.json` last-committed-batch marker.
- Kuzu is a younger ecosystem; mitigated by the SQLite fallback and
  the swap-cheap conformance suite.
- Maintaining multiple adapters is ongoing surface area.

## 5. Pros and cons of the options

### Option A: Fixed embedded
- + Simplest; zero-ops.
- − No shared-team deployment path; one DB's limits are everyone's.

### Option B: Fixed server
- + Strong for shared/concurrent use.
- − Server required even on a laptop/CI — kills the zero-ops default.

### Option C: Pluggable, embedded default
- + Zero-ops default *and* server option; interchangeable via
  conformance.
- − Adapter maintenance; cross-store consistency to manage.

## 6. References

- feat-003 (adapters, `.ckg/` layout, conformance suite), feat-004
  (transactional upsert), feat-006 (`Store.expand`).
- Research §2.6 (cognee pluggable adapters — verified), §2.1 (Joern
  embedded), §2.11 (SQLite trend), §5 storage recommendation.
- agentforge-py feat-025 (neo4j vector store) for driver conventions.
- Related: ADR-0003, ADR-0007.
