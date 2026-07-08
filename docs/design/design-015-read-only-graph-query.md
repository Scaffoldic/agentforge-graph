# design-015: Read-only graph query surface (`ckg query --graph` / `ckg_query`)

Mirrors [feat-015](../features/feat-015-read-only-graph-query.md). The *how*:
file layout, exact types, resolved decisions, chunk plan.

| Field | Value |
|---|---|
| **Status** | accepted |
| **Target** | 0.6.4 |
| **Backend scope** | **all three** query-capable at ship — Kuzu + Neo4j (shared Cypher compiler) + SurrealDB (SurrealQL compiler), full 3-backend conformance |

---

## The one idea

**Never execute caller text.** Caller writes a Cypher-subset string → we **parse**
it into our own frozen **query AST** → **validate** the AST against the locked
feat-001 vocabulary + exclusion rules → each backend **compiles** the AST to its
native dialect → **execute** under a read-only, bounded session. The AST is the
single trust boundary; everything portable and everything safe hangs off it.

```
text ──parse──▶ QueryAst ──validate──▶ QueryAst' ──┬─ compile_cypher(kuzu)   ──▶ Kuzu   ─┐
  (parser.py)   (ast.py)   (validator.py)          ├─ compile_cypher(neo4j)  ──▶ Neo4j  ─┼─▶ ResultTable
                                                    └─ compile_surreal        ──▶ Surreal ┘   {columns, rows, truncated}
```

## Guiding constraints

- **Framework-free** (ADR-0001): the entire query engine lives under
  `store.query`, importing only `core` (kinds/models/contracts). No `agentforge`
  import. Only the thin `ckg_query` tool wrapper in `serve/tools.py` is framework
  layer.
- **The locked ABCs are not touched.** `GraphStore` (feat-001/003) stays as-is;
  out-of-tree adapters keep working. Query capability is an **optional protocol**
  (`QueryCapable`) an adapter opts into — a backend without it reports
  `query.enabled: false` and still serves the typed verbs.
- **Parser is hand-written, no new dependency.** The subset is bounded; a small
  tokenizer + recursive-descent parser fits the lean-install ethos (mirrors how
  `[watch]`/`[rerank]` keep the base install lean). No `lark`/`pyparsing`. The
  accepted grammar is a **versioned EBNF spec** (`store/query/GRAMMAR.md`) that
  the parser mirrors production-for-production — the grammar is the source of
  truth and the query-language version number tracks it.

### Extensibility principles (no effort-driven workarounds)

The feature is deliberately built as **seams, not special-cases**, so the *content*
(more constructs, more backends, richer bounds) grows additively without touching
shared code. The 0.6.4 slice ships a small core, but the shape is extension-ready:

- **Add a query construct** → new AST node + one parser production + one validator
  rule + one `visit_*` method per compiler. No edits to existing branches (traversal
  is dispatch-based, §Compilers), so it is O(1) additive, not a shared-code rewrite.
- **Add a backend** → new `QueryCapable` adapter + one `Compiler` subclass + pass
  the conformance suite. No `if backend == …` anywhere — dialects are polymorphic
  classes, selected by the registry, never by flags.
- **Grow the subset** → a **capability-tier** model (below) lets a stronger backend
  advertise more than the common core *without* forking behaviour or breaking the
  "identical results" guarantee. The subset is versioned and grows; it is never a
  frozen lowest-common-denominator.
- **Bounds are a required contract, not best-effort.** Resource bounding
  (`max_rows`, `timeout_ms`, `max_expansions`) is part of the `QueryCapable`
  contract and is *proven on every backend* by a runaway-query conformance test.
  A backend that cannot bound natively must implement a portable fallback — we do
  **not** ship "approximated where the backend doesn't expose it."

### Capability tiers (how the subset grows without divergence)

Every supported construct is tagged with a **capability** (e.g. `core.match`,
`core.where`, `agg.basic`, `path.varlen`, `agg.collect`). A backend adapter
declares the set of capabilities it supports:

```python
class QueryCapable(Protocol):
    capabilities: ClassVar[frozenset[str]]     # what this backend can execute identically
    ...
```

- The **core tier** (`core.*` + `agg.basic` + bounded `path.varlen`) is
  **mandatory** — every query-capable backend must support it and prove identical
  results in conformance. That is the 0.6.4 subset.
- A construct outside a backend's declared capabilities is rejected *for that
  backend* with a precise "this backend does not support <capability>; supported
  here: …" error — **not** silently degraded, and **not** removed from stronger
  backends. So Neo4j can later expose `agg.collect` or richer predicates that
  SurrealDB lacks, additively, while the conformance suite still guarantees every
  construct is identical across the backends that *do* claim it.

This replaces the naive "intersection forever" rule with a model that (a) ships the
same safe common core today and (b) has a real growth path that never forks
semantics.

## Package layout

```
src/agentforge_graph/store/query/
  __init__.py       # exports: parse_query, validate_query, describe_schema,
                    #          QueryAst, CompiledQuery, QuerySettings, ResultTable,
                    #          QueryCapable, Compiler, QueryError (+ subclasses)
  GRAMMAR.md        # versioned EBNF of the accepted subset — source of truth
  ast.py            # frozen dataclasses: QueryAst + pattern/expr/return nodes
  parser.py         # Cypher-subset text -> QueryAst (tokenizer + recursive descent)
  validator.py      # vocabulary + exclusion + per-backend capability checks
  capability.py     # QueryCapable protocol, QuerySettings, ResultTable, CAPABILITIES
  compile_base.py   # Compiler ABC (singledispatch visitor) + CompiledQuery
  compile_cypher.py # CypherCompiler + KuzuCypherCompiler + Neo4jCypherCompiler
  compile_surreal.py# SurrealCompiler (full AST -> SurrealQL translator)
  execute.py        # shared bounded-cursor driver: timeout + row cap + expansion counter
  schema.py         # describe_schema() -> node/edge kinds + queryable attributes
  errors.py         # QueryError -> ParseError | ValidationError | GuardrailError
                    #            | QueryDisabled | CapabilityError

# extended (not new) files:
  store/kuzu_store.py     # + run_query()  (implements QueryCapable, dialect=cypher/kuzu)
  store/neo4j_store.py    # + run_query()  (QueryCapable, dialect=cypher/neo4j, read-only session)
  store/surreal_store.py  # + run_query()  (QueryCapable, dialect=surrealql)
  store/facade.py         # + Store.query_graph() + Store.query_enabled
  ingest/codegraph.py     # + CodeGraph.query_graph() + CodeGraph.describe_schema()
  serve/engine.py         # + _Engine.query_graph() (folds staleness envelope)
  serve/tools.py          # + CkgQuery tool + QueryInput; registered in ALL_TOOLS
  config.py               # + QueryConfig(_Block, KEY="query")
  cli.py                  # query subcommand: + --graph / --schema / --format / --limit
```

## The AST (`ast.py`)

Frozen dataclasses, `core`-typed (labels are real `NodeKind`/`EdgeKind`, direction
reuses `core.Direction`). Sketch:

```python
@dataclass(frozen=True)
class NodePattern:
    var: str | None
    label: NodeKind | None                 # validated: must be a real NodeKind
    props: tuple[tuple[str, Literal], ...]  # inline {name: "x"} equalities

@dataclass(frozen=True)
class RelPattern:
    var: str | None
    kind: EdgeKind | None                   # validated: must be a real EdgeKind
    direction: Direction                    # "out" | "in" | "both"
    min_hops: int = 1
    max_hops: int = 1                        # None (unbounded [*]) -> ValidationError

@dataclass(frozen=True)
class PathPattern:                          # alternating node (rel node)*
    elements: tuple[NodePattern | RelPattern, ...]

# WHERE expression tree (closed set of node types)
Expr = Compare | BoolOp | Not | InList | StringPred | PatternExists
#   Compare(lhs: PropRef, op: '=|<>|<|<=|>|>=', rhs: Literal)
#   BoolOp(op: 'AND|OR', operands)  /  Not(operand)
#   InList(lhs: PropRef, values: tuple[Literal, ...])
#   StringPred(lhs: PropRef, op: 'STARTS_WITH|ENDS_WITH|CONTAINS', rhs: str)
#   PatternExists(pattern: PathPattern)     # (a)-[:CALLS]->(b) existence

@dataclass(frozen=True)
class ReturnItem:
    expr: PropRef | Aggregate | CountStar   # Aggregate.func in {count,collect,min,max,avg}
    alias: str | None

@dataclass(frozen=True)
class QueryAst:
    match: tuple[PathPattern, ...]
    where: Expr | None
    returns: tuple[ReturnItem, ...]
    distinct: bool
    order_by: tuple[tuple[str, bool], ...]  # (key, descending)
    skip: int | None
    limit: int | None
```

`PropRef(var, prop)` addresses `f.name`, `f.path`, `f.source`, `f.confidence`,
`n.attrs.<k>` — mapped to the `Node`/`Provenance` fields in the compiler
(`source`/`confidence` live on `provenance`; `attrs.*` on the `attrs` dict; `span`
exposed as `start_line`/`end_line`).

## Validator (`validator.py`) — the trust boundary

Walks the AST and rejects with a structured `ValidationError` (message says *why*,
lists the offending token). Rules:

- Every `NodePattern.label` ∈ `NodeKind`; every `RelPattern.kind` ∈ `EdgeKind`;
  every `PropRef.prop` is a known/queryable attribute (from `schema.py`).
- **Hard exclusions** (also unrepresentable in the AST, so this is belt-and-
  suspenders): write/DDL verbs never parse (grammar has no `CREATE/MERGE/SET/
  DELETE/DETACH/DROP`); no procedure/`CALL`; **unbounded var-length path**
  (`max_hops is None`) rejected; a `MATCH` with ≥2 disconnected patterns and no
  `WHERE`/inline predicate joining them (Cartesian product) rejected.
- `LIMIT`/`SKIP` are non-negative ints; aggregates only in `RETURN`.

Parse-time exclusion is gate #1 of the read-only story; the read-only DB session
(where the backend supports it) is gate #2.

Validation is **two-phase**: (1) a backend-independent phase (vocabulary +
exclusions above) that runs once; (2) a **capability phase** against the target
backend's declared `capabilities` — a construct the backend does not claim raises
`CapabilityError` naming the missing tier and what *is* supported here. Phase 2 is
what lets the subset grow per-backend without ever silently diverging (§Capability
tiers). The `visit`/walk is `@singledispatchmethod`-dispatched so adding an AST
node adds a validator registration, never edits an existing branch.

## Compilers — polymorphic, dispatch-based (no dialect flags)

A compiler is a **class per dialect**, not a function with a `dialect` branch, so
divergences are overridden methods and a new dialect is a new subclass — never an
edit to a shared if/elif:

```python
class Compiler(ABC):                       # store/query/compile_base.py
    dialect: ClassVar[str]
    def compile(self, ast: QueryAst) -> CompiledQuery: ...   # drives the walk
    # one visit_* per AST node — @singledispatchmethod, so adding an AST node
    # is a new registration, never a change to existing branches:
    @singledispatchmethod
    def visit(self, node) -> str: raise NotImplementedError(type(node))
    @visit.register
    def _(self, n: NodePattern) -> str: ...
    @visit.register
    def _(self, n: Compare) -> str: ...
    # …one per node type

class CypherCompiler(Compiler):            # compile_cypher.py — shared Cypher core
    dialect = "cypher"
class KuzuCypherCompiler(CypherCompiler):  # overrides ONLY the few Kuzu deltas
    dialect = "kuzu"                        # (var-length syntax, id() form)
class Neo4jCypherCompiler(CypherCompiler): # overrides ONLY Neo4j deltas
    dialect = "neo4j"                       # (elementId, tx timeout hint)
class SurrealCompiler(Compiler):           # compile_surreal.py — full translator
    dialect = "surrealql"                   # AST -> SELECT … ->kind->node … WHERE …
```

- **Literals are always parameterized** (`$p0`, `$p1`, …) — never string-spliced,
  on every dialect. Single injection-free path.
- **Result shape is compile-fixed:** every compiler returns
  `CompiledQuery(text, params, columns)` where `columns` is the projected RETURN
  order, so `ResultTable.columns` is backend-independent by construction.
- Kuzu/Neo4j share the `CypherCompiler` body and override only genuine dialect
  deltas; SurrealDB is a full sibling translator. The conformance suite proves all
  three produce identical `ResultTable`s for the core tier.

Adding a construct = register one `visit_*` on each compiler (three small methods),
guided by the grammar spec. Adding a dialect = one `Compiler` subclass. Neither
touches existing compiler code.

## Capability + execution (`capability.py`, adapter `run_query`)

```python
@runtime_checkable
class QueryCapable(Protocol):
    query_dialect: ClassVar[str]            # "kuzu" | "neo4j" | "surrealql"
    capabilities: ClassVar[frozenset[str]]  # tiers this backend executes identically
    read_only_execution: ClassVar[bool]     # True = backend enforces a read-only session (gate #2)
    async def run_query(self, ast: QueryAst, s: QuerySettings) -> ResultTable: ...

@dataclass(frozen=True)
class QuerySettings:                        # resolved from QueryConfig
    max_rows: int
    timeout_ms: int
    max_expansions: int

@dataclass(frozen=True)
class ResultTable:
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    truncated: bool
    stopped_reason: str | None = None       # None | "row_cap" | "timeout" | "expansion_cap"
```

Each adapter's `run_query` = compile (via its `Compiler`) → execute on its own
driver under bounds → normalize. Guardrails are a **required part of the contract**,
identical in effect on every backend and **proven by a runaway-query conformance
test** (§Conformance). A backend where a bound is not native must implement a
portable fallback — there is no "best-effort where it's hard" path.

- **Read-only** is layered. Gate #1: the AST cannot represent a write (grammar has
  no write verbs), so no compiler can emit one — this holds on *all* backends
  unconditionally. Gate #2: a genuine read-only session where the backend offers
  one (Neo4j `execute_read`). A backend declares which gates it provides via
  `read_only_execution`; a conformance test submits a write-shaped attempt through
  the same session and asserts refusal, so the guarantee is *tested per backend*,
  not asserted in prose.
- **Timeout:** `asyncio.wait_for(…, timeout_ms/1000)` wraps every driver call
  (portable, all backends); Neo4j additionally gets a server-side `tx_timeout`. On
  trip → `stopped_reason="timeout"`.
- **Row cap:** compiler appends `LIMIT min(requested, max_rows) + 1`; `max_rows+1`
  rows ⇒ drop the extra, `truncated=True`, `stopped_reason="row_cap"`.
- **`max_expansions` (intermediate-row budget) — enforced on every backend, no
  approximation.** Where a backend exposes a native budget/profile hook it is used
  directly. Where it does not (embedded Kuzu, SurrealDB), the adapter executes the
  bounded query through a **paged/streamed cursor with an intermediate-row counter**
  in `store.query.execute`: rows are pulled in bounded batches and the running
  count is checked against `max_expansions`; on exceed the cursor is closed and the
  partial result returns with `truncated=True`, `stopped_reason="expansion_cap"`.
  The unbounded-path ban + per-pattern `max_hops` cap keep the intermediate set
  finite so the counter always terminates. This is the portable fallback that makes
  the bound a real, tested guarantee rather than a documented gap.

`store/query/execute.py` holds the shared bounded-cursor driver + normalization so
each adapter supplies only its native "run this compiled statement, yield rows"
primitive — the bounding logic is written once, not re-implemented per backend.

The facade wires it:

```python
# store/facade.py
@property
def query_enabled(self) -> bool:
    return isinstance(self._graph, QueryCapable)

@property
def query_capabilities(self) -> frozenset[str]:
    return self._graph.capabilities if isinstance(self._graph, QueryCapable) else frozenset()

async def query_graph(self, text: str, settings: QuerySettings) -> ResultTable:
    if not isinstance(self._graph, QueryCapable):
        raise QueryDisabled(self._graph_driver_name)
    ast = parse_query(text)                                   # ParseError on bad syntax
    validate_query(ast, backend=self._graph.capabilities)    # ValidationError / CapabilityError
    return await self._graph.run_query(ast, settings)
```

`query_capabilities` is what `serve/engine.py` folds into `engine.capabilities` for
the capability-driven tool registry and what `ckg_status` / `describe_schema`
report, so callers see exactly what the active backend can do.

`CodeGraph.query_graph` / `CodeGraph.describe_schema` are thin pass-throughs used
by both CLI and the tool.

## CLI (`cli.py`, `query` subcommand)

Extend the existing `query` parser (keeps the NL/hybrid path intact):

- `--graph '<q>'` — structural query (mutually exclusive with the positional NL
  `query`).
- `--schema` — print the queryable vocabulary (`describe_schema()`), no query.
- `--format {table,json}` (default `table`) — **new to this repo**, introduced as a
  reusable `cli/format.py` helper (`render_table(columns, rows) -> str`,
  `emit(result, fmt)`), *not* inline in the handler. Other verbs can adopt the same
  helper later without a rewrite; this PR only wires it to `query`. `table` mirrors
  `_routes`'s column-width alignment; `json` emits `{columns, rows, truncated,
  stopped_reason}`.
- `--limit N` — caller LIMIT (still clamped to `query.max_rows`).

Handler branches before the existing retrieve dispatch. `QueryError` → stderr
message (the structured "why") + exit 2, reusing the ENH-026 exit-2 convention.

## MCP tool (`serve/tools.py`, `serve/engine.py`)

```python
class QueryInput(_Fed):
    query: str = Field(..., description="Cypher-subset structural query")
    limit: int | None = Field(None, description="row cap (clamped to server max)")
    params: dict[str, Any] | None = Field(None)

class CkgQuery(_CkgTool):
    name = "ckg_query"
    description = "Escape hatch for precise STRUCTURAL questions no typed verb "
                  "covers (e.g. classes tagged X with no inbound CALLS). Read-only. "
                  "Use ckg_search for semantic 'find code about…' questions."
    input_schema = QueryInput
    async def run(self, **kw) -> str:
        data = await eng.query_graph(query, limit, params)   # {columns,rows,truncated,...}
        return json.dumps(data)
```

`_Engine.query_graph` folds the **staleness envelope** onto the table exactly like
the survey methods: `{columns, rows, truncated, **(await self.staleness()),
tool_api_version, query_lang_version}`.

**Capability-driven registration (not always-on-plus-error).** feat-008's toolset
becomes capability-aware rather than a hardcoded list: each tool declares what it
needs and the server includes the tools whose requirements the live config +
backend satisfy.

```python
class _CkgTool(Tool):
    requires: ClassVar[frozenset[str]] = frozenset()   # capability gates, default none
class CkgQuery(_CkgTool):
    requires = frozenset({"query"})                     # needs query.enabled + a QueryCapable backend
```

`code_graph_tools()` filters `ALL_TOOLS` by `tool.requires ⊆ engine.capabilities`,
so `ckg_query` appears exactly when the query surface is actually available and is
cleanly absent otherwise — an agent never discovers a tool that only errors. This
is a reusable gate: future capability-gated tools (write tools post-1.0, backend-
specific verbs) use the same mechanism instead of each inventing an opt-out.

The contract test becomes **profile-parameterized**: `test_schemas.py` asserts the
tool set + schemas for each profile — `{query: enabled}` includes `ckg_query`
(properties = query/limit/params/service), `{query: disabled}` excludes it. Both
are pinned, so drift on either path fails CI. This keeps the snapshot deterministic
*and* honest, without the "register a tool that returns an error" compromise.

## Config (`config.py`)

```python
class QueryConfig(_Block):
    KEY: ClassVar[str] = "query"
    enabled: bool = True
    max_rows: int = 1000
    timeout_ms: int = 5000
    max_expansions: int = 50000
    allow_in_mcp: bool = True
```

Auto-discovered by `block_keys()` (no registration list). Read via
`QueryConfig.load(config)`. `ckg_status` reports `query_lang_version` ("1.0") +
whether the active backend is query-capable.

## Conformance suite (the load-bearing test)

Extend `core/conformance.py` with `QueryConformance` — a base class (pytest-free at
import, like `GraphStoreConformance`) holding a fixed query set run against a shared
fixture graph (extend `make_sample_subgraph()` with tagged classes, interfaces,
call edges so predicates/aggregates/pattern-existence are all exercised). Each
`test_*` asserts the **normalized `ResultTable` is identical** across backends.

The suite has three mandatory parts, each a *contract every query-capable backend
must pass* — this is what turns the extensibility principles into enforced
guarantees rather than prose:

1. **Result parity** — the fixed query set returns identical normalized
   `ResultTable`s across all backends claiming the core tier.
2. **Bounded execution** — a deliberately runaway query (large fan-out) returns a
   partial result with `truncated=True` and the right `stopped_reason` on *every*
   backend, proving the `max_expansions`/timeout/row-cap fallback actually works
   (no backend is exempt with "not natively supported").
3. **Read-only** — a write-shaped attempt through the same session is refused on
   every backend (belt-and-suspenders with the AST gate).

A new backend added later opts into query support purely by subclassing this suite
and passing — same pattern as feat-003's storage conformance, no bespoke wiring.

Per-backend wiring extends the existing `tests/store/test_*_conformance.py`:

- **Kuzu** — embedded, runs in default CI (the always-on gate).
- **Neo4j / SurrealDB** — env-gated live (needs the running server; colima/docker),
  matching feat-003's existing backend-test gating and the storage-backends
  conformance job. Same three-part suite, must match Kuzu's rows.

## Chunk plan (the feat-015 PR = these commits, in order)

| # | Chunk | Lands |
|---|---|---|
| 1 | **Grammar + AST + parser + validator + schema + capability** (`GRAMMAR.md`, `ast.py`, `parser.py`, `validator.py`, `schema.py`, `capability.py`, `errors.py`) | The whole trust boundary + the capability seam, pure + framework-free. Unit tests: every excluded construct rejected; every supported construct → expected AST; two-phase validation incl. `CapabilityError`; `describe_schema()`. **Heaviest chunk.** |
| 2 | **Compiler base + Cypher + Kuzu execution** (`compile_base.py` visitor, `compile_cypher.py`, `execute.py` bounded cursor, `KuzuGraphStore.run_query`, `Store.query_graph`, `CodeGraph.query_graph`) + Kuzu `QueryConformance` (all 3 parts) | First end-to-end vertical slice on the default backend; the bounded-cursor + parity/bound/read-only conformance land here. |
| 3 | **Neo4j execution** (`Neo4jCypherCompiler`, `Neo4jGraphStore.run_query`, read-only session) + env-gated Neo4j conformance | Proves the Cypher compiler + bounds are backend-portable (subclass only, no shared edits). |
| 4 | **SurrealQL compiler + SurrealDB execution** (`SurrealCompiler`, `SurrealGraphStore.run_query`) + env-gated Surreal conformance | The full translator; closes the 3-backend story, all three conformance parts green. |
| 5 | **CLI** — `cli/format.py` helper + `ckg query --graph / --schema / --format / --limit` + `test_cli_query.py` | Power-user surface + the reusable formatter seam. |
| 6 | **MCP tool + capability registry** — `_CkgTool.requires`, capability-filtered `code_graph_tools()`, `CkgQuery`, `_Engine.query_graph` + staleness envelope, profile-parameterized `test_schemas.py` | Agent surface + the honest, reusable tool-gating seam. |
| 7 | **Config + status + docs** — `QueryConfig`, `query_lang_version` in `ckg_status`, guide + README + changelog | Ship polish. |

Each chunk is a self-contained Conventional Commit; the gate (ruff/mypy/pytest/≥90%)
must pass per chunk. Chunks 1–2 are the bulk (they carry the extension seams); 3–4
add breadth as pure additions behind the conformance suite; 5–7 are the surfaces.

## Extensibility seams (summary)

Every "this might grow later" axis is a declared seam, so growth is additive and
none of it is a future rewrite:

| To add… | You touch | You do **not** touch |
|---|---|---|
| A query construct | new AST node + 1 parser production + 1 validator registration + 1 `visit_*` per compiler + a `GRAMMAR.md` bump | any existing branch (singledispatch), the backends' shared code |
| A storage backend | 1 `QueryCapable` adapter + 1 `Compiler` subclass + subclass the conformance suite | the registry mechanism, other backends, the core |
| A backend-specific capability | declare it in that adapter's `capabilities` + tier-gate it in the validator | other backends' behaviour, the core-tier guarantee |
| A guardrail (e.g. memory cap) | 1 field on `QuerySettings` + enforcement in the shared `execute.py` cursor | per-backend code (bounding is written once) |
| A capability-gated tool | subclass `_CkgTool` with `requires={…}` | the registration/filter logic |
| A CLI output format | 1 branch in `cli/format.py` | every command (they share the helper) |

## Alternatives considered

| Option | Why not |
|---|---|
| JSON query DSL as the public surface | Rejected at analysis — Cypher/openCypher/GQL (ISO 39075) is the field standard for property-graph traversal; JSON DSLs suit doc/search key-lookup, not multi-hop patterns. |
| Parser library (`lark`/`pyparsing`) | New dependency vs a bounded subset that a hand-written recursive-descent parser handles; keeps base install lean. |
| Pass raw text to Kuzu (lean on its parser) | Breaks portability (no SurrealDB path), safety (no validation), and opens an injection surface. The AST-as-trust-boundary is the whole point. |
| Add `run_query` to the `GraphStore` ABC | Breaks out-of-tree adapters + the locked contract (feat-001/003). Optional `QueryCapable` protocol instead — opt-in, non-breaking. |
| Compiler as one function with a `dialect` flag | if/elif on dialect doesn't scale past two backends and mixes their logic. Polymorphic `Compiler` subclasses + singledispatch visitor instead — a new dialect/construct is additive. |
| `ckg_query` always registered, `run()` returns an error when unavailable | A tool that only errors is dishonest discovery and made the contract test config-coupled. Capability-driven registration (`requires ⊆ engine.capabilities`) + profile-parameterized snapshot is the reusable, honest seam. |
| "Subset = intersection of all backends, forever" | Permanently caps stronger backends at the weakest one, with no growth path. Capability tiers ship the same safe core today but let a backend advertise more additively, still conformance-guaranteed identical where claimed. |
| `max_expansions` "approximated where the backend has no native budget" | That's an effort-driven workaround. A shared bounded-cursor with an intermediate-row counter (`execute.py`) makes the bound real and *tested* on every backend. |

## Risks

| Risk | Mitigation |
|---|---|
| SurrealQL can't match Cypher semantics for some construct | The construct lives in a capability tier SurrealDB doesn't claim → `CapabilityError` there, still available (identically) on backends that do claim it. Core tier is conformance-proven identical on all three. Never silently divergent. |
| Hand-written parser bugs / injection | Bounded grammar defined in `GRAMMAR.md`, no `eval`, parameterized literals only on every dialect; property/fuzz tests on the parser; the validator is a second closed-set gate. |
| `max_expansions` enforcement | Real and tested, not approximated: shared bounded-cursor counter (`execute.py`) + unbounded-path ban + `max_hops` cap; the runaway-query conformance test proves the bound trips with `stopped_reason="expansion_cap"` on every backend. |
| Live-backend conformance flakes/omitted in CI | Kuzu conformance is the always-on gate; Neo4j/Surreal env-gated like existing feat-003 backend tests; a backend that skips is reported, not assumed-passing. |
| Capability tiers add complexity we don't use yet | The 0.6.4 ship declares only the core tier on all three backends, so there is no branching in practice today — but the *seam* (declared `capabilities` + phase-2 validation) costs a few lines now and avoids a rewrite when the first backend-specific construct lands. |

## Open questions (resolve before `accepted`)

1. **Parameter passing in the tool** — expose `params` in `ckg_query` v1, or defer
   (literals-in-text only) to keep the first tool contract minimal? *(Lean: include
   `params` — it's the safe way for an agent to pass values; small cost.)*
2. **`--format json` shape** — resolved to a **reusable `cli/format.py` helper**
   wired only to `query` in this PR (other verbs adopt it later without a rewrite),
   rather than either inline one-off code or a full sweep of every command now. Any
   objection to that middle path?
3. **Attribute allow-list granularity** — expose `n.attrs.*` wholesale, or only a
   curated attribute set in `describe_schema()`? *(Lean: curated set the schema
   advertises; unknown `attrs.*` keys pass through as opaque string compares.)*
