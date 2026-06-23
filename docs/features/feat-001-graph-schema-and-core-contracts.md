# feat-001: Graph schema & core contracts

## Metadata

| Field | Value |
|---|---|
| **ID** | feat-001 |
| **Title** | Graph schema & core contracts |
| **Status** | proposed |
| **Owner** | kjoshi |
| **Created** | 2026-06-11 |
| **Target version** | 0.1.0 |
| **Languages** | python |
| **Module package(s)** | `agentforge_graph.core` |
| **Depends on** | none |
| **Blocks** | feat-002 … feat-012 (everything) |

---

## 1. Why this feature

Every surveyed CKG tool that grew organically (schema-driven /
pluggable-adapter CKG designs, other graph-server code-graphs, the
Neo4j DIY recipes) ended up with a shallow, ad-hoc
schema — file/class/function nodes, a couple of edge types, no node
identity that survives a commit, no provenance on derived facts. Once
agents start *writing* enrichments into the graph (summaries, pattern
tags, ADR links), an untyped schema rots: you cannot tell a parsed
fact from an LLM guess, and re-indexing orphans every enrichment.

This feature locks the typed node/edge taxonomy, the stable symbol-ID
scheme, the provenance model, and the core ABCs that every later
feature plugs into. It is the agentforge-graph equivalent of
agentforge-py's feat-001: the contracts are the product.

## 2. Why it must ship in the agent core

- **Every other feature is a producer or consumer of this schema.**
  Extractors (feat-002, feat-011), enrichers (feat-010, feat-012),
  stores (feat-003), and retrieval (feat-006, feat-007) only compose
  because they share one typed vocabulary. Without it, each feature
  invents node labels and the graph becomes unqueryable.
- **Stable symbol IDs are a cross-feature invariant.** Incremental
  indexing (feat-004) and the temporal layer (feat-009) only work if
  the same function gets the same node ID across commits. That cannot
  be retrofitted — stable descriptor-based IDs exist precisely because
  earlier opaque numeric-ID index formats made incremental indexing
  impossible (research doc §2.3).
- **Provenance discipline must be enforced centrally.** The
  differentiator features write LLM-derived facts. If `source` and
  `confidence` are optional, derived facts silently masquerade as
  parsed ground truth.

## 3. How consumers benefit

- An agent querying the graph can filter `provenance = parsed` for
  ground truth or accept `provenance = llm AND confidence >= 0.8` —
  one predicate, uniform across all twelve features.
- A new extractor author implements one ABC (`Extractor`) and emits
  typed `Node`/`Edge` values; storage, dedup, identity, and
  incremental bookkeeping are handled for them.
- Re-indexing a changed file preserves every enrichment attached to
  unchanged symbols, because identity is content-addressed by symbol
  descriptor, not by parse order.

## 4. Feature specifications

### 4.1 User-facing experience

```python
from agentforge_graph.core import Node, Edge, SymbolID, Provenance

fn = Node(
    id=SymbolID.for_symbol("py", "myrepo", "src/app/auth.py", "login()."),
    kind="Function",
    name="login",
    span=(42, 78),
    provenance=Provenance.parsed(extractor="tree-sitter-python", commit="a1b2c3"),
)
call = Edge(src=fn.id, dst=other.id, kind="CALLS",
            provenance=Provenance.parsed(extractor="resolver", commit="a1b2c3"))
```

### 4.2 Public API / contract

**Node kinds (locked at 0.1):**

`Repository`, `Package`, `File`, `Class`, `Interface`, `Function`,
`Method`, `Variable`, `TypeAlias` — structural (Layer 0);
`Chunk`, `DocChunk` — retrieval (feat-005, feat-010);
`Decision`, `Route`, `DataModel`, `Service`, `Summary` — higher-level
(feat-010..012). Higher-level kinds are *reserved here* so stores and
queries handle them from day one, even though their producers ship
later.

**Edge kinds (locked at 0.1):**

| Kind | Meaning | Producer |
|---|---|---|
| `CONTAINS` | structural nesting (repo→pkg→file→class→fn) | feat-002 |
| `IMPORTS` | file/module import | feat-002 |
| `CALLS` | call site → callee | feat-002 |
| `INHERITS`, `IMPLEMENTS` | type hierarchy | feat-002 |
| `REFERENCES` | non-call symbol use | feat-002 |
| `CHUNK_OF` | chunk → symbol it covers | feat-005 |
| `DESCRIBES` | doc chunk → code symbol | feat-010 |
| `GOVERNS`, `SUPERSEDES` | ADR → code / ADR → ADR | feat-010 |
| `HANDLED_BY`, `INJECTED_INTO`, `HAS_FIELD`, `RELATES_TO` | framework edges | feat-011 |
| `SUMMARIZES`, `TAGGED` | enrichment | feat-012 |

**Symbol ID scheme (stable descriptor-based, locked):** a human-readable string

```
ckg <lang> <repo> <path> <descriptor>
ckg py  myrepo src/app/auth.py AuthService#login().
```

Descriptors follow the descriptor grammar (`Type#`, `method().`, `term.`).
IDs are deterministic from (lang, repo, path, descriptor) — no global
counters, no ordering constraints, so per-file extraction can run in
any order and merge (research doc §3.2).

**Core types & ABCs (`agentforge_graph/core/contracts.py`):**

```python
class Provenance(BaseModel):
    source: Literal["parsed", "resolved", "llm", "manual"]
    extractor: str                  # producer name+version
    commit: str                     # git sha the fact was derived at
    confidence: float = 1.0         # < 1.0 only for source="llm"

class Node(BaseModel):
    id: str                         # SymbolID string
    kind: NodeKind
    name: str
    span: tuple[int, int] | None    # start/end line
    attrs: dict[str, Any] = {}
    provenance: Provenance

class Edge(BaseModel):
    src: str; dst: str
    kind: EdgeKind
    attrs: dict[str, Any] = {}
    provenance: Provenance

class Extractor(ABC):
    name: str
    @abstractmethod
    def extract(self, file: SourceFile) -> FileSubgraph: ...

class GraphStore(ABC):             # implemented in feat-003
    @abstractmethod
    async def upsert(self, subgraph: FileSubgraph) -> None: ...
    @abstractmethod
    async def query(self, q: GraphQuery) -> QueryResult: ...
    @abstractmethod
    async def neighbors(self, node_id: str, kinds: list[EdgeKind] | None,
                        depth: int = 1) -> list[Node]: ...
    @abstractmethod
    async def delete_file(self, path: str) -> None: ...
    @abstractmethod
    async def close(self) -> None: ...

class Enricher(ABC):               # implemented in feat-010/011/012
    name: str
    @abstractmethod
    async def enrich(self, graph: GraphStore) -> list[Node | Edge]: ...
```

`FileSubgraph` is the unit of ingestion and deletion: all nodes/edges
derived from one file, keyed by `(path, content_hash)` — the
file-incremental per-file-subgraph design that makes feat-004 possible.

### 4.3 Internal mechanics

- Unresolved cross-file references are emitted as `REFERENCES` edges
  to *candidate symbol IDs* with `source="parsed"`; a later resolver
  pass (feat-002) upgrades them to `CALLS`/`IMPORTS` with
  `source="resolved"`. The schema therefore never blocks on whole-
  program analysis.
- `NodeKind`/`EdgeKind` are string enums; unknown kinds are rejected
  at the `Node`/`Edge` constructor (fail-at-startup), not at store
  time.

### 4.4 Module packaging

`agentforge_graph.core` — always installed; no optional extra.

### 4.5 Configuration

None. The schema is code, not config. (Schema *extensions* are a
post-1.0 question — see §8.)

## 5. Plug-and-play & upgrade story

Locked surface. Adding a node/edge kind is a minor bump; renaming or
removing one is major. Stores must ignore-and-preserve kinds they do
not understand, so older adapters survive newer producers.

## 6. Cross-language parity

Python only (this agent). The symbol-ID grammar is language-neutral
by design so a future TS port shares IDs.

## 7. Test strategy

- Unit: symbol-ID round-trip (parse ↔ format), determinism, descriptor
  grammar property tests.
- Unit: Node/Edge validation — unknown kinds rejected, `llm`
  provenance requires `confidence < 1.0` or explicit value.
- Conformance suite skeleton for `GraphStore` (run by every feat-003
  adapter) and `Extractor` (run by feat-002/011 extractors).

## 8. Risks & open questions

| Risk / Question | Mitigation / Decision |
|---|---|
| Schema too rigid for unforeseen languages/frameworks | `attrs` dict is the escape hatch; promote recurring attrs to typed fields via minor bumps |
| Reserved higher-level kinds (Decision, Route…) wrong before their features land | They are names only; their attr shapes are specced in feat-010/011/012 and may change until those ship |
| Symbol descriptor collisions (overloads, anonymous fns) | Adopt the overload-disambiguator convention suffix `(+N)`; anonymous symbols use span-derived local descriptors |
| Should provenance live per-fact or per-batch? | Per-fact. Storage overhead is small; query-time filtering is the whole point |

## 9. Out of scope

- Data-flow / control-flow edges (`REACHING_DEF`, `CFG`).
  Deliberately excluded from 0.1 — they require compiler-grade
  frontends and serve security analysis, not agent retrieval. Revisit
  post-1.0.
- A query language. `GraphQuery` is a typed filter object; Cypher
  passthrough is adapter-specific (feat-003).
- Schema migrations (no persisted data exists before feat-003 ships).

## 10. References

- Design: [`../design/design-001-core-contracts-module.md`](../design/design-001-core-contracts-module.md)
  — the *how* (file layout, exact types, resolved §8 questions, chunk plan).
- Prior art: established CPG node/edge vocabularies, stable
  descriptor-based symbol IDs, and incremental-graph designs informed
  the schema (survey notes kept local).

---

## Implementation status

**In progress** on `feat/001-graph-schema-and-core-contracts` (PR pending).

Shipped in `agentforge_graph.core`:
- `NodeKind` / `EdgeKind` — full reserved vocabulary locked at 0.1 (ADR-0005).
- `Provenance` (+ `Source`) — validated at construction; `confidence < 1.0`
  only for `source=llm` (ADR-0004).
- `SymbolID` + `Descriptor` — descriptor-grammar based, deterministic and
  round-tripping, OS-normalized paths, `(+N)` overload disambiguator,
  `local(<hash>)` for anonymous symbols (ADR-0003).
- `Node`, `Edge`, `FileSubgraph`, `SourceFile`, `GraphQuery`, `QueryResult`.
- ABCs `Extractor`, `GraphStore` (incl. `add()` for enrichment/cross-file
  facts), `Enricher`.
- `conformance.py` — `GraphStoreConformance` / `ExtractorConformance` reused
  by feat-002/003.

Validated: ruff + `mypy --strict` clean, 39 tests, 100% coverage on core.
Deviation from design: added `GraphStore.add()` (enrichment write path) — the
design listed enrichment survival as a conformance test but no method to write
non-file-bound facts; recorded in the design decision log.
