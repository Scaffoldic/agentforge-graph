# Ad-hoc structural queries (`ckg query --graph` / `ckg_query`)

> **TL;DR:** For precise **structural** questions no typed verb answers — "public
> methods on classes tagged `Repository` with no inbound `CALLS`", "interfaces
> implemented by >5 classes" — run a **read-only Cypher subset** query:
> `ckg query --graph 'MATCH … WHERE … RETURN …'` or the `ckg_query` MCP tool. It is
> the escape hatch; for semantic "find code about X" use `ckg_search`.

The typed verbs (`ckg search`, `ckg impact`, `ckg routes`, …) each answer one
question well, but they are a **closed set**. When a question doesn't map to a
verb, the query surface lets you ask it directly against the graph — without us
shipping a new verb — while keeping the same read-only safety and staleness
guarantees (feat-015).

Retrieval vs query, at a glance: **retrieval** (`ckg_search`) discovers code by
meaning (vectors + ranking); **query** interrogates the graph with exact
predicates. Use retrieval to find, query to filter/aggregate.

---

## 1. The surface

```bash
# structural query (read-only)
ckg query --graph 'MATCH (f:Function) WHERE NOT (f)<-[:CALLS]-() RETURN f.name, f.path LIMIT 50'

# output formats
ckg query --graph '<q>' --format table   # default, aligned columns
ckg query --graph '<q>' --format json    # {columns, rows, truncated, stopped_reason}

# see the queryable vocabulary (node/edge kinds + properties)
ckg query --schema
```

The natural-language path — `ckg query "how does auth work"` (hybrid retrieval) —
is unchanged; `--graph` selects the structural surface.

Over MCP, the `ckg_query` tool takes `{ query, limit? }` and returns the columnar
result plus the usual staleness envelope (`indexed_commit`, `dirty`, `truncated`,
`query_lang_version`). It is registered only when the backend is query-capable and
`query.allow_in_mcp` is on.

---

## 2. The language (a bounded, read-only Cypher subset)

Supported (see `ckg query --schema` for the live vocabulary):

- **`MATCH`** node/relationship patterns over the locked node/edge kinds:
  `(c:Class)-[:IMPLEMENTS]->(i:Interface)`, directions `->`/`<-`/`-`, bounded
  variable-length `[:CALLS*1..3]`.
- **`WHERE`** — comparisons (`= <> < <= > >=`), `AND`/`OR`/`NOT`, `IN […]`, string
  predicates (`STARTS WITH` / `ENDS WITH` / `CONTAINS`), and pattern existence
  (`(a)-[:KIND]->(b)`).
- **`RETURN`** — property projections, aliases (`AS`), `DISTINCT`, and aggregates
  `count` / `min` / `max` / `avg` / `collect`.
- **`ORDER BY … [ASC|DESC]`, `SKIP`, `LIMIT`.**

Queryable node properties (mapped identically on every backend): `name`, `kind`,
`path`, `start_line`, `end_line`, `source`, `extractor`, `commit`, `confidence`.

**Rejected** (with a clear reason, never a stack trace): any write/DDL
(`CREATE/MERGE/SET/DELETE/…`), procedure `CALL`, unbounded paths (`[*]`), and
disconnected patterns that would form a Cartesian product.

### Examples

```cypher
-- classes tagged "Repository"
MATCH (c:Class)-[:TAGGED]->(t:PatternTag) WHERE t.name = "Repository" RETURN c.name

-- interfaces by how many classes implement them
MATCH (c:Class)-[:IMPLEMENTS]->(i:Interface)
RETURN i.name, count(c) AS impls ORDER BY impls DESC

-- functions nothing calls (dead-ish code)
MATCH (f:Function) WHERE NOT (f)<-[:CALLS]-() RETURN f.name, f.path

-- what a function reaches within 3 call hops
MATCH (f:Function {name: "handle_login"})-[:CALLS*1..3]->(g:Function) RETURN DISTINCT g.name
```

---

## 3. Safety & bounds

The query is never executed as caller text: it is parsed into a validated
internal AST (the single trust boundary), then either **compiled** to the
backend's native Cypher (Kuzu, Neo4j) or **interpreted** over the storage API
(SurrealDB and any backend without a native query language). Every backend
returns identical rows — proven by a shared conformance suite.

Every run is bounded and the caps are reported (never silently applied):

```yaml
query:
  enabled: true          # disable the structural surface wholesale
  max_rows: 1000         # row cap; a clipped result sets truncated=true
  timeout_ms: 5000       # per-query wall-clock budget
  max_expansions: 50000  # intermediate-row / traversal ceiling
  allow_in_mcp: true     # expose ckg_query as an MCP tool (vs CLI-only)
```

When a bound trips, the result carries `truncated: true` and a `stopped_reason`
(`row_cap` / `expansion_cap` / `timeout`), so a partial answer is never mistaken
for a complete one. `ckg status` reports the query-language version and whether
the active backend is query-capable.

---

## 4. When to use a query vs a verb

Reach for `ckg_query` when the question is **structural and exact** and no verb
fits. If you find yourself writing the *same* query repeatedly, that is a signal
it should become a first-class verb — tell us; the common ad-hoc queries are the
best candidates to promote.
