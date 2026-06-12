# Design Doc: feat-001 core contracts module

> Per-feature design doc (design stage of the pipeline). Mirrors
> `docs/features/feat-001-graph-schema-and-core-contracts.md`. The
> feature spec says *what & why*; this doc says *how* — concrete file
> layout, exact types, resolved decisions, test plan, chunk plan.

---

## Metadata

| Field | Value |
|---|---|
| **Title** | feat-001 core contracts module |
| **Status** | accepted |
| **Owner** | kjoshi |
| **Created** | 2026-06-11 |
| **Last updated** | 2026-06-11 |
| **Related features** | feat-001 (this) · consumed by feat-002, 003, 005, 010, 011, 012 |
| **Related ADRs** | ADR-0001, ADR-0003, ADR-0004, ADR-0005 |

---

## 1. Context

feat-001 is the root feature — every other feature is a producer or
consumer of the schema and ABCs it defines. The spec fixes the
vocabulary and contracts; this design pins the implementation so the
contracts are stable on day one and don't need migration when later
producers land. Two questions the spec left open (§8) are resolved
here: the symbol-descriptor disambiguator rule, and the minimal
`GraphQuery` shape.

## 2. Goals

- A `agentforge_graph.core` package with **zero `agentforge` imports**
  (ADR-0001 layering), importable standalone.
- Locked, validated value types and kind enums (full reserved
  vocabulary — ADR-0005).
- Deterministic, order-independent `SymbolID` with a resolved
  descriptor grammar (ADR-0003).
- Provenance enforced at construction so no unattributed fact can
  exist (ADR-0004).
- ABC signatures + reusable conformance suites that feat-002/003 run.
- ≥90% coverage; `mypy --strict` clean.

## 3. Non-goals

- No `Extractor`/`GraphStore`/`Enricher` *implementations* (feat-002/
  003/010+).
- No data-flow/control-flow edges, no query language, no migrations
  (spec §9).
- No config (schema is code).

## 4. Proposal

### 4.1 Package layout

```
src/agentforge_graph/core/
  __init__.py        # curated public re-exports
  kinds.py           # NodeKind, EdgeKind (str enums)
  provenance.py      # Provenance + helper constructors
  symbols.py         # SymbolID, Descriptor, grammar (parse/format)
  models.py          # Node, Edge, FileSubgraph, GraphQuery, QueryResult
  contracts.py       # Extractor, GraphStore, Enricher (ABCs)
  conformance.py     # pytest-importable suites for ABC implementers
tests/core/
  test_kinds.py  test_provenance.py  test_symbols.py  test_models.py
  conftest.py
```

Rule enforced by a unit test: nothing under `core/` imports
`agentforge*` (ADR-0001).

### 4.2 Kinds (`kinds.py`)

```python
class NodeKind(str, Enum):
    # structural (feat-002)
    REPOSITORY="Repository"; PACKAGE="Package"; FILE="File"
    CLASS="Class"; INTERFACE="Interface"; FUNCTION="Function"
    METHOD="Method"; VARIABLE="Variable"; TYPE_ALIAS="TypeAlias"
    # retrieval (feat-005, feat-010)
    CHUNK="Chunk"; DOC_CHUNK="DocChunk"
    # higher-level — RESERVED now, produced later (ADR-0005)
    DECISION="Decision"; ROUTE="Route"; DATA_MODEL="DataModel"
    SERVICE="Service"; SUMMARY="Summary"; PATTERN_TAG="PatternTag"

class EdgeKind(str, Enum):
    CONTAINS="CONTAINS"; IMPORTS="IMPORTS"; CALLS="CALLS"
    INHERITS="INHERITS"; IMPLEMENTS="IMPLEMENTS"; REFERENCES="REFERENCES"
    CHUNK_OF="CHUNK_OF"; DESCRIBES="DESCRIBES"
    GOVERNS="GOVERNS"; SUPERSEDES="SUPERSEDES"
    HANDLED_BY="HANDLED_BY"; INJECTED_INTO="INJECTED_INTO"
    HAS_FIELD="HAS_FIELD"; RELATES_TO="RELATES_TO"
    SUMMARIZES="SUMMARIZES"; TAGGED="TAGGED"
```

### 4.3 Provenance (`provenance.py`)

```python
class Source(str, Enum):
    PARSED="parsed"; RESOLVED="resolved"; LLM="llm"; MANUAL="manual"

class Provenance(BaseModel, frozen=True):
    source: Source
    extractor: str                 # "tree-sitter-python@0.23"
    commit: str                    # git sha, or "" for unstaged/non-git
    confidence: float = 1.0        # validated: must be 1.0 unless source==LLM

    @model_validator(mode="after")
    def _check(self) -> "Provenance":
        if self.source is not Source.LLM and self.confidence != 1.0:
            raise ValueError("confidence<1.0 only valid for source=llm")
        if not 0.0 <= self.confidence <= 1.0: raise ValueError(...)
        return self

    @classmethod
    def parsed(cls, extractor, commit="") -> "Provenance": ...
    @classmethod
    def resolved(cls, extractor, commit="") -> "Provenance": ...
    @classmethod
    def llm(cls, extractor, confidence, commit="") -> "Provenance": ...
```

### 4.4 SymbolID + descriptor grammar (`symbols.py`) — resolves spec §8

A `SymbolID` is a single human-readable string, deterministic from
`(scheme, lang, repo, path, descriptor)`:

```
ckg <lang> <repo> <path> <descriptor>
ckg py myrepo src/app/auth.py `AuthService#login().`
```

**Descriptor grammar (SCIP-derived):**

| Symbol | Suffix | Example |
|---|---|---|
| namespace/package | `/` | `app/` |
| type (class/interface/struct) | `#` | `AuthService#` |
| term (var/const/field) | `.` | `MAX_RETRIES.` |
| method/function | `().` | `login().` |
| type parameter | `[T]` | `[T]` |
| parameter | `(p)` | `(token)` |
| **overload disambiguator** | `(+N)` before `.` | `login(+1)().` |
| **anonymous / local** | `local(<spanhash>)` | `local(3f2a)` |

**Resolved decisions:**

1. **Overloads** (spec §8): nth overload of a name (n≥1 in source
   order) gets `(+n)`; the first gets none — matches SCIP. Source
   order within the file is deterministic (file is parsed in order),
   so the assignment is stable as long as the set of overloads is
   unchanged.
2. **Anonymous functions / lambdas / locals**: no stable name, so the
   descriptor is `local(<h>)` where `<h>` is a short hash of the
   symbol's start-span within its **nearest named ancestor** (not the
   file), so inserting code *above* the ancestor doesn't shift it.
   Accepted limitation: anonymous symbols are inherently unstable
   across edits to their own body — documented, and they rarely carry
   enrichments.

API:

```python
class SymbolID:
    @classmethod
    def for_symbol(cls, lang: str, repo: str, path: str,
                   descriptor: str) -> str: ...          # -> the string
    @classmethod
    def parse(cls, s: str) -> "ParsedSymbol": ...        # round-trips
    # ParsedSymbol(scheme, lang, repo, path, descriptor)
```

Path is normalized (posix separators, repo-relative) before
formatting so the same file yields the same ID on any OS. Spaces in
paths are percent-escaped in the ID and unescaped on parse →
guaranteed round-trip.

### 4.5 Models (`models.py`)

```python
class Node(BaseModel):
    id: str                        # SymbolID string
    kind: NodeKind
    name: str
    span: tuple[int, int] | None = None     # (start_line, end_line), 1-based
    attrs: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance
    # validator: id must parse as a SymbolID; kind must be a NodeKind

class Edge(BaseModel):
    src: str; dst: str
    kind: EdgeKind
    attrs: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance

class FileSubgraph(BaseModel):
    path: str                      # repo-relative, posix
    content_hash: str              # sha256 of file bytes — incremental key
    nodes: list[Node]
    edges: list[Edge]
    # the unit of ingestion AND deletion (ADR-0003); feat-003 upserts it

class GraphQuery(BaseModel):       # minimal 0.1 filter — resolves spec §8
    kinds: list[NodeKind] | None = None
    name: str | None = None        # exact match (substring is post-0.1)
    path_prefix: str | None = None
    edge_kind: EdgeKind | None = None    # when querying edges
    min_source: Source | None = None     # provenance floor
    limit: int = 100

class QueryResult(BaseModel):
    nodes: list[Node]
    edges: list[Edge]
    truncated: bool                # True if limit clipped the result
```

### 4.6 ABCs (`contracts.py`)

Signatures only (per spec §4.2); async where I/O is implied.

```python
class Extractor(ABC):
    name: str
    @abstractmethod
    def extract(self, file: "SourceFile") -> FileSubgraph: ...

class GraphStore(ABC):
    @abstractmethod
    async def upsert(self, subgraph: FileSubgraph) -> None: ...
    @abstractmethod
    async def delete_file(self, path: str) -> None: ...
    @abstractmethod
    async def query(self, q: GraphQuery) -> QueryResult: ...
    @abstractmethod
    async def neighbors(self, node_id: str,
                        kinds: list[EdgeKind] | None = None,
                        depth: int = 1) -> list[Node]: ...
    @abstractmethod
    async def get(self, node_id: str) -> Node | None: ...
    @abstractmethod
    async def close(self) -> None: ...

class Enricher(ABC):
    name: str
    @abstractmethod
    async def enrich(self, store: GraphStore) -> list[Node | Edge]: ...
```

`SourceFile` (a small frozen value: `path`, `bytes`/`text`,
`language`, `content_hash`) also lives in `models.py` so `Extractor`
has no external dep.

### 4.7 Conformance suites (`conformance.py`)

Importable base test classes so every future implementer runs the same
suite (the agentforge-py pattern):

```python
class GraphStoreConformance:
    """Subclass in feat-003 adapters; provide `store` fixture."""
    async def test_upsert_then_get(self, store): ...
    async def test_reupsert_is_idempotent(self, store): ...
    async def test_delete_file_removes_nodes(self, store): ...
    async def test_enrichment_survives_file_reupsert(self, store): ...
    async def test_unknown_kind_preserved(self, store): ...

class ExtractorConformance:
    """Subclass in feat-002 packs; provide `extractor` + `sample`."""
    def test_output_is_valid_subgraph(self): ...
    def test_extraction_is_deterministic(self): ...
```

In feat-001 these run against tiny in-memory fakes to prove the suites
themselves work; real backends subclass them later.

## 5. Alternatives considered

| Option | Why not |
|---|---|
| Dataclasses instead of Pydantic | Lose construction-time validation (the ADR-0004 enforcement point); Pydantic already in the dep tree |
| Numeric/UUID node ids | ADR-0003 — breaks incrementality & cross-commit identity |
| Put higher-level kinds in later | ADR-0005 — forces migrations at 0.3/0.4 |
| Rich query AST in 0.1 | Premature; `GraphQuery` filter object covers feat-002/003/006 needs, extends by minor bump |
| `confidence` optional/un-validated | Lets llm facts masquerade as parsed — defeats ADR-0004 |

## 6. Migration / rollout

Greenfield — no persisted data exists. Adding a kind later is a minor
bump; stores ignore-and-preserve unknown kinds (tested in conformance).
`__init__.py` is the curated public surface; internal module moves
don't break importers.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Anonymous-symbol IDs unstable across body edits | Documented limitation; span hashed against nearest *named* ancestor to limit churn; anon symbols rarely hold enrichments |
| Descriptor grammar gaps for some languages | Grammar is data-driven per language in feat-002; core only defines the *string* format + parser, language packs map AST→descriptor |
| `GraphQuery` too thin for feat-006 | It's a floor; feat-006 expansion is graph traversal via `neighbors`, not `query` — query is for exact lookups |
| ABC churn breaking early adopters | Locked surface; additions are minor bumps; conformance suite catches drift |

## 8. Open questions

1. ~~Overload disambiguator rule~~ → resolved §4.4 (SCIP `(+N)`).
2. ~~Minimal `GraphQuery` shape~~ → resolved §4.5.
3. ~~`SourceFile` — carry `bytes` or decoded `text`?~~ → resolved:
   `text` + `content_hash` (decoding is the extractor's caller's job;
   tree-sitter takes bytes in feat-002 but core stays text-first).

## 9. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-11 | SCIP `(+N)` overload disambiguator; `local(<hash>)` for anon | Stable for the common case; matches a proven scheme |
| 2026-06-11 | `GraphQuery` = flat filter object, not an AST | Covers 0.1 consumers; extends without breaking |
| 2026-06-11 | Pydantic frozen models, validation in ctor | The ADR-0004 enforcement point |
| 2026-06-11 | Added `GraphStore.add(items)` | Enrichers/cross-file facts need a write path not tied to a file; conformance "enrichment survives re-upsert" requires it |
| 2026-06-11 | `SourceFile` carries `text` (not bytes) | Core stays text-first; feat-002 decodes for tree-sitter |

## 10. Chunk plan (the single feat-001 PR)

| Chunk | Commit | Contents |
|---|---|---|
| 0 | `chore(001): dev gate` | `uv sync --extra dev`, ruff+mypy+pytest config, pre-commit, `.claude/standards/{coding,testing}.md` |
| 1 | `feat(001): kinds, provenance, models` | `kinds.py`, `provenance.py`, `models.py` (+ `SourceFile`) |
| 2 | `feat(001): symbol IDs` | `symbols.py` grammar, format/parse, disambiguator/anon rules |
| 3 | `feat(001): core ABCs` | `contracts.py` |
| 4 | `test(001): conformance + property tests` | `conformance.py`, `tests/core/*`, no-`agentforge`-import test |
| 5 | `docs(001): impl status` | spec Implementation status + this doc → `accepted` |

## 11. References

- Spec: `docs/features/feat-001-graph-schema-and-core-contracts.md`
- ADRs: 0001 (layering), 0003 (symbol IDs), 0004 (provenance),
  0005 (reserved kinds)
- Prior art: SCIP symbol grammar; agentforge-py `conformance` pattern
