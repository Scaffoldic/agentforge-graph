# feat-015: Read-only graph query language (`ckg query --graph` / `ckg_query`)

## Metadata

| Field | Value |
|---|---|
| **ID** | feat-015 |
| **Title** | Read-only, guard-railed graph query surface (Cypher-subset) + `ckg_query` verb/tool |
| **Status** | in-progress |
| **Target version** | 0.6.4 |
| **Layer** | 1 serve (retrieval & serving) — escape-hatch complement to the typed verbs |
| **Area** | `store` (query AST, validator, per-backend compilers, execution) · `serve` (`ckg_query` tool) · CLI |
| **Depends on** | feat-001 (locked node/edge vocabulary), feat-003 (storage adapters), feat-008 (tool API) |
| **Graduated from** | [FA-003](../feature-analysis/FA-003-read-only-graph-query-language.md) |
| **Relates to** | feat-006 (hybrid retrieval — the *guided/semantic* path this complements) |

---

## 1. Why this feature

The CKG today answers questions through **fixed, typed verbs**: `ckg search`,
`ckg impact`, `ckg neighbors`, `ckg routes`, `ckg decisions`, `ckg history`, and
so on. Each is excellent for the question it was designed for, and the guided
shape is exactly right for the common case — an agent that just wants "who calls
this" does not want a query language.

But the typed verbs are a **closed set.** Any question that does not map to an
existing verb is **unanswerable without us shipping a new verb**:

- "Find all public methods on classes tagged `Repository` that have no inbound
  CALLS edge."
- "List routes whose handler imports the legacy auth module."
- "Show interfaces implemented by more than five classes."

Power users and sophisticated agents hit this ceiling quickly, and every such
question becomes a feature request. This feature adds a **read-only,
guard-railed query surface** over the typed graph so arbitrary structural
questions can be expressed directly — without weakening the safety or the
guided-verb experience.

## 2. Why it ships in the engine

- **The typed graph already has the answers.** We index nodes, edges, kinds,
  provenance, and attributes; a query surface unlocks data we already store
  instead of gating it behind bespoke verbs.
- **It absorbs verb-sprawl pressure.** feat-008 §8 flags "every feature wants a
  tool" as a real risk. A general query verb is the pressure-relief valve: novel
  questions get a query, not a new tool.
- **Read-only discipline must be enforced centrally.** Letting an LLM emit graph
  queries is only safe if writes, unbounded traversals, and resource-exhausting
  patterns are rejected by *us*, not trusted to the caller — the same stance
  feat-008 takes on `depth`/`k` clamps. The enforcement is a correctness
  boundary, not a preference, so it belongs in the deterministic engine
  (ADR-0001): query AST + validator + per-backend compilers live in `store` with
  no `agentforge` import; only the thin `ckg_query` tool wrapper is framework
  layer.

## 3. How consumers benefit

- **Power user (CLI):** `ckg query --graph 'MATCH (c:Class)-[:TAGGED]->(t) WHERE
  t.name = "Repository" RETURN c.name'` answers an ad-hoc structural question with
  no code change on our side.
- **Agent (MCP):** a new `ckg_query` tool lets a capable agent compose a precise
  structural query when no typed verb fits — then fall back to the guided verbs
  for everything routine.
- **Us:** fewer one-off verb requests; novel needs are expressible today and
  inform which queries deserve to *become* a typed verb later (the promotion
  path, §10).

## 4. Feature specifications

### 4.1 User-facing experience

```bash
# CLI — ad-hoc structural query, read-only
ckg query --graph 'MATCH (f:Function) WHERE NOT (f)<-[:CALLS]-() RETURN f.name, f.path LIMIT 50'

# Output formats
ckg query --graph '<q>' --format table     # default, human-readable
ckg query --graph '<q>' --format json      # machine-readable rows

# Introspect the queryable vocabulary (node/edge kinds + attributes)
ckg query --schema
```

The existing natural-language path — `ckg query "<text>"` (feat-006 hybrid
retrieval) — is untouched. `--graph` selects the structural surface; the two are
documented as complementary (retrieval to *discover*, query to *interrogate*).

```jsonc
// MCP tool
{
  "name": "ckg_query",
  "arguments": {
    "query": "MATCH (c:Class)-[:IMPLEMENTS]->(i:Interface) RETURN i.name, count(c) AS impls ORDER BY impls DESC",
    "limit": 100
  }
}
// → { columns: [...], rows: [...], truncated: false, indexed_commit, dirty }
```

The result carries the same **staleness envelope** as every other tool
(`indexed_commit`, `dirty`, `truncated`) — feat-008's no-silent-caps rule applies
here too.

### 4.2 Public API / contract

- **CLI:** `ckg query --graph '<query>'` (structural) and `ckg query --schema`
  (vocabulary introspection). The `ckg query "<text>"` NL path is unchanged.
- **MCP tool:** `ckg_query { query, limit?, params? }` → columnar result
  (`columns`, `rows`) + staleness envelope. **Read-only** — registered alongside
  feat-008's locked toolset.
- **Query language:** a **read-only subset** over our locked vocabulary
  (feat-001 node/edge kinds). Supported shape (target): `MATCH` patterns, `WHERE`
  (comparisons, `AND/OR/NOT`, `IN`, string predicates, pattern-existence
  `(a)-[:KIND]->(b)`), `RETURN` with projection + aliases, aggregates (`count`,
  `collect`, `min/max/avg`), `ORDER BY`, `SKIP`/`LIMIT`. Provenance/attributes
  are queryable columns (`f.source`, `f.confidence`, `n.attrs.*`).
- **Hard exclusions (rejected at parse):** any write/DDL
  (`CREATE/MERGE/SET/DELETE/DROP/DETACH`), procedure/function calls that touch
  the host, variable-length unbounded paths (`[*]` with no upper bound), and
  Cartesian products without a join predicate. A rejected query returns a
  structured error explaining *why*, not a stack trace.

### 4.3 Internal mechanics

**The portability problem.** The query surface must behave identically across our
pluggable backends (ADR-0006): Kuzu and Neo4j speak openCypher; SurrealDB speaks
SurrealQL. We **never** pass raw user text to a backend. Instead:

1. **Parse** the incoming query into our own read-only **query AST** (validated
   against the locked vocabulary and the exclusion rules in §4.2). This is the
   single trust boundary — anything the AST cannot represent cannot run.
2. **Compile** the AST to each backend's native dialect via a per-backend
   compiler in the `store` adapter (Cypher for Kuzu/Neo4j; SurrealQL for
   SurrealDB). The same conformance discipline that proves storage adapters
   interchangeable (feat-003) extends to a **query-conformance suite**: one query
   set, identical results across backends.
3. **Execute** with enforced guardrails: statement timeout, max rows, max
   expansions/traversal bound, and a read-only transaction/connection. Results
   are normalized to `{columns, rows}` regardless of backend.

- **Read-only enforcement is layered:** AST exclusions (parse-time) + read-only
  DB session (execution-time). Two independent gates.
- **Guardrail defaults mirror feat-008:** row cap, depth/expansion cap,
  wall-clock timeout — all configurable, all reported in `truncated`.

### 4.4 Module packaging

- `agentforge_graph.store` — query AST, validator, per-backend compilers,
  execution. Stays in the **deterministic engine**; no framework import
  (ADR-0001).
- `agentforge_graph.serve` — the `ckg_query` tool wrapper (framework layer).
- Ships in the base install; no new extra. A backend that has no query compiler
  reports `query.enabled: false` and still serves the typed verbs.

### 4.5 Configuration

```yaml
query:
  enabled: true            # the structural surface can be disabled wholesale
  max_rows: 1000           # hard row cap (truncation reported)
  timeout_ms: 5000         # per-query wall-clock budget
  max_expansions: 50000    # traversal/intermediate-row bound
  allow_in_mcp: true       # expose ckg_query as an MCP tool (vs CLI-only)
```

Read via the engine's framework-free config path (ADR-0001): `app.query.*` or a
standalone `ckg.yaml` `query:` block.

## 5. Plug-and-play & upgrade story

- The supported query shape is **versioned**: adding a clause is minor, a
  semantics change is major. `ckg_status` reports the query-language version so
  long-lived clients detect mismatch (as it does for the tool API).
- A new storage backend ships a query compiler and must pass the
  query-conformance suite before it is considered query-capable; until then it
  serves typed verbs but reports `query.enabled: false`.

## 6. Cross-language parity

n/a at the indexed-language level — the query surface is over the graph, not the
source. The parity that *does* matter: identical results across storage backends,
covered by the query-conformance suite (§4.3, §7).

## 7. Test strategy

- **Parser/validator unit tests:** every excluded construct
  (write/DDL/unbounded-path/host-call) is rejected with a clear error; every
  supported construct parses to the expected AST.
- **Query-conformance suite:** a fixed query set runs against each query-capable
  backend over a shared fixture index; **results must match** (the load-bearing
  test). Structured identically to feat-003's storage-conformance suite so a new
  backend opts in by passing it.
- **Guardrail tests:** a deliberately expensive query hits the row/timeout/
  expansion cap, returns partial results with `truncated: true`, and does not
  exhaust memory.
- **Read-only tests:** a write/DDL query is rejected at parse *and* would be
  rejected by the read-only session (belt-and-suspenders).
- **Tool-contract test:** `ckg_query` JSON-schema snapshot (drift fails CI, per
  feat-008's contract discipline).
- **Agent-in-the-loop (env-gated):** an agent answers a structural question it
  has no typed verb for, using `ckg_query`, and produces a grounded result.

## 8. Risks & open questions

| Risk / Question | Mitigation / Decision |
|---|---|
| LLM emits a resource-exhausting query | Timeout + row cap + expansion bound + unbounded-path ban; all enforced engine-side, reported in result |
| Backend dialect divergence yields different results | Query-conformance suite is mandatory; a backend that fails it is not query-capable (`query.enabled: false`) |
| Re-implementing a query parser is heavy | Scope to a **small read-only subset**, not full Cypher. Kuzu (default backend) is an openCypher engine, so validate-then-near-pass-through; the AST layer is what stays portable |
| Surface area for injection/abuse | No raw pass-through ever; only the validated AST compiles to a backend. Single trust boundary |
| Overlaps with typed verbs / confuses agents | Tool description positions `ckg_query` as the *escape hatch* for questions no typed verb covers; guided verbs remain the default |
| Exposing internal schema to callers | `ckg query --schema` / a schema-introspection helper documents node/edge kinds + queryable attributes so callers query a documented vocabulary |
| **Backend coverage for the 0.6.4 slice** | **Resolved in design (design-015): which backends are query-capable at first ship vs follow-up.** The conformance suite is structured so backends opt in incrementally; non-capable backends report `query.enabled: false` |

## 9. Out of scope

- **Write queries / graph mutation from agents** — needs a provenance + authz
  story (feat-008 defers write tools post-1.0); this feature is strictly
  read-only.
- Full openCypher / SurrealQL surface — we expose a curated, safe subset.
- A visual query builder.
- Stored/parameterized server-side query templates (possible follow-up if common
  queries emerge — those are also the candidates to promote to a typed verb).

## 10. Design notes

**The AST is the whole design.** The portability story (Kuzu/Neo4j Cypher vs
SurrealDB SurrealQL) and the safety story (read-only, bounded) both hang on one
decision: **never execute caller text directly — validate into our own AST, then
compile per backend.** That single trust boundary is what makes the feature safe
to expose to an LLM and portable across ADR-0006 backends at the same time.

**Lean on Kuzu.** Our default backend is already an openCypher engine, so the
Kuzu compiler is close to a pass-through *after* AST validation — the real
engineering is the validator + the SurrealDB compiler + the conformance suite.
This makes the default-backend path cheap and the portability cost explicit.

**Relationship to feat-006.** `ckg_query` is **not** a replacement for hybrid
retrieval — retrieval is the right tool for "find code about X" (semantics,
ranking, provenance weighting). `ckg_query` is for *precise structural* questions
with exact predicates. Document the two as complementary: retrieval to discover,
query to interrogate.

**Promotion path.** Queries that show up repeatedly are evidence for a new typed
verb. Treat `ckg_query` usage as a backlog signal: the most common ad-hoc queries
are the best candidates to graduate into first-class, optimized verbs.

**Resolved decision (reviewed at analysis).** Expose a **Cypher-subset text
syntax** as the caller-facing surface; keep our **structured AST as the internal
trust boundary** (it resembles a JSON DSL, but it is an implementation detail, not
the public language). Callers never have their text executed — it is parsed and
validated into the AST, which each backend compiles from.

Rationale — the industry-standard approach for labeled property graphs: the
ecosystem has standardized on Cypher/openCypher/GQL (Neo4j, Kuzu, Memgraph,
FalkorDB, Neptune all speak Cypher-family syntax; **GQL was published as ISO/IEC
39075 in April 2024**, the first new ISO database query language since SQL, and it
is directly Cypher-lineage). JSON query DSLs are the norm for document/search
engines (key-lookup/filter), not multi-hop graph traversal. And it fits our
backends: Kuzu and Neo4j *are* openCypher engines, so on the common path we
validate-then-near-pass-through rather than translating into a foreign dialect.

Accepted cost: we own a **small, read-only** Cypher-subset parser (the validation
trust boundary), bounded deliberately — not full Cypher — with the
query-conformance suite keeping backends result-identical.

## Implementation status

**Shipped (0.6.4).** All three backends query-capable and result-identical,
proven by a shared conformance suite (Kuzu compiled + Neo4j compiled verified
against live servers; SurrealDB via the interpreter, verified live). Built in 7
chunks on `feat/015-ckg-query`: (1) AST + parser + validator + schema +
capability; (2) Cypher compiler + Kuzu execution + bounded executor + facade/
CodeGraph wiring + conformance; (3) Neo4j execution (read-only session); (4)
portable AST interpreter + SurrealDB; (5) CLI `--graph/--schema/--format/--limit`;
(6) `ckg_query` tool + capability-gated registration; (7) `query:` config block +
docs (guide 13).

**Deviations from design-015 (all deliberate, documented):**

- **SurrealDB uses a portable AST *interpreter* over the `GraphStore` ABC, not a
  native SurrealQL compiler.** Discovered during implementation that SurrealDB
  models edges as a document table (no native graph traversal), making a faithful
  SurrealQL translator of the core tier infeasible without a fragile workaround.
  The interpreter (`store/query/interpret.py`) is a superior universal
  alternative — *compile where the backend has a native query language
  (Kuzu/Neo4j), interpret elsewhere* — so **any** `GraphStore` is query-capable
  for free, and it passes the same conformance suite. User-approved.
- **Compiler expression visitor uses `match` statements, not
  `functools.singledispatchmethod`** — same additive property (one arm per AST
  node), cleaner under `mypy --strict`.
- **`QueryConformance` lives in `store/query/`, not `core/conformance.py`** — core
  must not import `store` (where the query types live).
- **`attrs.*` access is an optional `attrs.access` capability that no v1 backend
  advertises** — Kuzu/Neo4j store `attrs` as a JSON string, not destructurable in
  native Cypher without a workaround that breaks under aggregation. The curated
  columns cover the real use cases; the capability seam reports `attrs.*` as
  unsupported honestly. (The interpreter *can* read `attrs`; a future backend or a
  follow-up may advertise the capability.)
- **`ckg_query` v1 exposes `{query, limit}` only — no `params` argument** (design
  open-Q1 leaned yes). The grammar inlines and parameterizes literals internally
  and has no `$placeholder` syntax, so a caller-facing params map has no binding
  site in v1.
- **CLI formatter is a flat `cli_format.py` module** (the repo has no `cli/`
  package), introduced as a reusable seam wired only to `query` this PR.

**Parser note:** `CONTAINS` is both the string operator and an `EdgeKind`; labels
and relationship types accept reserved words in name position (a shared-parser fix
locked across all three backends).

## 11. References

- [FA-003](../feature-analysis/FA-003-read-only-graph-query-language.md) — source analysis.
- [feat-001](feat-001-graph-schema-and-core-contracts.md) — locked node/edge vocabulary the query surface is typed against.
- [feat-003](feat-003-graph-storage-adapters.md) — storage adapters + conformance-suite discipline this extends.
- [feat-008](feat-008-mcp-server-and-tool-api.md) — tool API, staleness envelope, guardrail/clamp stance.
- [feat-006](feat-006-hybrid-retrieval.md) — the semantic/guided path `ckg_query` complements.
- ADR-0001 (framework-free engine core), ADR-0006 (pluggable storage backends).
- design-015 (the *how*: file layout, AST shape, chunk plan) — written next.
