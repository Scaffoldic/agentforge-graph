# Design Doc: feat-006 hybrid retrieval

> Per-feature design doc (design stage). Mirrors
> `docs/features/feat-006-hybrid-retrieval.md`. The spec says *what & why*;
> this doc says *how* — file layout, exact types, resolved decisions, test
> plan, chunk plan.

---

## Metadata

| Field | Value |
|---|---|
| **Title** | feat-006 hybrid retrieval (vector + graph) |
| **Status** | accepted |
| **Owner** | kjoshi |
| **Created** | 2026-06-12 |
| **Last updated** | 2026-06-12 |
| **Related features** | feat-006 (this) · consumes feat-003, feat-005 · consumed by feat-008, 010, 012 |
| **Related ADRs** | ADR-0001 (layering), ADR-0004 (provenance), ADR-0008 (hybrid retrieval) |

---

## 1. Context

This is the query side of the MVP: NL question → ranked, connected context
(matching chunks + their symbols + 1-hop neighbors), as one typed call. It's
the single retrieval surface feat-008 (MCP tools) and the enrichers
(feat-010/012) ride on. Pieces already in place: `VectorStore.search`
(feat-003), chunks + `CHUNK_OF` edges + an `Embedder` (feat-005),
`GraphStore.neighbors`/`query`/`get`, provenance on every node/edge.

**The one gap.** The retriever must walk *directed* edges and score by the
*edge's* provenance (`resolved` > `parsed` > `llm`) with a "why" trace —
`impact` mode is specifically reverse-dependencies. The shipped
`GraphStore.neighbors` is undirected and returns only nodes (no edge, no
direction). So feat-006 adds one small, backward-compatible primitive to the
store contract: **`adjacent()`** (§4.3). Everything else is new code in
`agentforge_graph.retrieve`.

## 2. Goals

- `agentforge_graph.retrieve` — **zero `agentforge` imports** (ADR-0001);
  the retrieval path makes **no LLM calls** (it may *return* llm-derived
  nodes, flagged).
- `Retriever.retrieve(query|symbol, mode, …) -> ContextPack` with the four
  modes (context / impact / definition / similar).
- Provenance-weighted, decayed scoring; dedupe max-wins; per-hop fan-out cap
  (no silent truncation — recorded in the pack `notes`).
- `ContextPack.render(budget_tokens)` — highest-score first, whole chunks
  only, signature fallback; `to_dict()` for tools.
- `GraphStore.adjacent()` added to the contract + Kuzu + the in-memory
  reference + conformance.
- `CodeGraph.retrieve()` + a `ckg query` CLI.
- ≥90% coverage with the FakeEmbedder; an env-gated live relevance smoke;
  `mypy --strict`; ruff.

## 3. Non-goals

- Concrete cross-encoder reranking — a `Reranker` hook ships (off by
  default); the agentforge-backed impl lands later *outside* the
  deterministic core (keeps ADR-0001 clean).
- Query rewriting / HyDE / any LLM in the retrieval path (spec §8).
- Whole-repo centrality maps (feat-007), multi-repo (post-1.0).
- The other nine languages (ride feat-002's packs).

## 4. Proposal

### 4.1 Package layout

```
src/agentforge_graph/retrieve/
  __init__.py     # Retriever, ContextPack, ContextItem, Mode, Reranker
  pack.py         # ContextItem, ContextPack (render/to_dict)
  scoring.py      # decay, edge weights, dedupe-max
  retriever.py    # Retriever: entry -> expand -> merge
  rerank.py       # Reranker protocol + NoopReranker (default)
src/agentforge_graph/
  core/contracts.py   # + GraphStore.adjacent (additive)
  store/kuzu_store.py # adjacent impl
  config.py           # + RetrieveConfig
tests/retrieve/   (+ store/core conformance additions for adjacent)
```

Layering test asserts `retrieve/` imports no `agentforge*`.

### 4.2 Types (`pack.py`)

```python
class ContextItem(BaseModel):
    id: str                 # symbol or chunk id
    kind: NodeKind
    name: str
    score: float
    path: str
    span: tuple[int, int] | None = None
    code: str | None = None         # chunk text (rendered verbatim)
    provenance: Source              # parsed | resolved | llm | manual
    why: list[str] = []             # "vector hit 0.83", "CALLS of X (hop 1)"

class ContextPack(BaseModel):
    query: str | None = None
    symbol: str | None = None
    mode: str = "context"
    items: list[ContextItem] = []   # ranked, deduped
    notes: list[str] = []           # fan-out caps hit, rerank on/off, …
    def render(self, budget_tokens: int) -> str: ...
    def to_dict(self) -> dict[str, Any]: ...
```

`render`: items already score-sorted; greedily emit whole items until the
running `estimate_tokens` (reuse feat-005's) would exceed budget; a
code-bearing item that doesn't fit is replaced by its signature line
(`<path> <name>`), never split; a `notes` footer lists what was dropped.

### 4.3 `GraphStore.adjacent` — the one contract addition

```python
Direction = Literal["out", "in", "both"]

class GraphStore(ABC):
    @abstractmethod
    async def adjacent(self, node_id: str,
                       kinds: list[EdgeKind] | None = None,
                       direction: Direction = "both") -> list[Edge]:
        """The 1-hop edges touching node_id (out: node is src; in: node is
        dst), optionally filtered by kind. Returns full Edge objects so the
        caller sees kind, direction, attrs and provenance."""
```

- **Kuzu**: `MATCH (a {id})-[e]->(b)` (out) / `<-[e]-` (in) / both; rebuild
  `Edge` from the rel's columns + the two node ids.
- **In-memory reference** (tests): filter `self._edges` by endpoint +
  direction + kinds.
- **Conformance**: a new `test_adjacent_directed` on the sample subgraph
  (File→Class→Method via CONTAINS) — `out` from Class yields Class→Method,
  `in` yields File→Class, `both` yields both. Backward-compatible (new
  method; existing adapters add it — only Kuzu exists today).

The retriever does its own BFS over `adjacent`, so it controls hop count,
edge-provenance weighting, fan-out cap, and the "why" trace per node.

### 4.4 `Retriever` (`retriever.py`) — entry → expand → merge

```python
Mode = Literal["context", "impact", "definition", "similar"]

class Retriever:
    def __init__(self, store: Store, embedder: Embedder,
                 config: RetrieveConfig, reranker: Reranker | None = None): ...
    async def retrieve(self, query=None, symbol=None, mode="context",
                       k=8, depth=1, edge_kinds=None,
                       min_provenance=None, include_llm_facts=True) -> ContextPack: ...
```

**1. Entry.**
- `query`: `embedder.embed([query], "query")` → `vectors.search(k)` →
  scored chunk refs. Each becomes a chunk `ContextItem` (score = similarity,
  why `"vector hit {s:.2f}"`); its owning symbols (`adjacent(chunk,
  [CHUNK_OF], "out")`) become seed symbols inheriting that score.
- `symbol`: `get(symbol)` → seed (score 1.0, why `"symbol entry"`).
- Both may be set (query anchored at a symbol).

**2. Expand.** Mode picks edge kinds + direction (overridable by
`edge_kinds`):
| mode | kinds | direction | needs |
|---|---|---|---|
| context | CALLS, CONTAINS, INHERITS, REFERENCES | both | query and/or symbol |
| impact | CALLS, IMPORTS, IMPLEMENTS | in (reverse) | symbol |
| definition | CONTAINS, CHUNK_OF | out/in | symbol |
| similar | — (no expansion, depth 0) | — | query |

BFS to `depth` over `adjacent`; each new node scored
`parent_score × decay^hop × edge_weight(edge.provenance)`; `why` appends
`"{kind} of {parent.name} (hop {h})"`. Per-hop fan-out capped (config
`fanout_cap`, default 25) — overflow recorded in `notes`, never silent.

**3. Merge & rerank.** Dedupe by id (max score wins, why-traces unioned);
apply `min_provenance` / `include_llm_facts` filters (llm items kept but
flagged in `why` unless excluded); optional `reranker.rerank(query, items)`
over the top finalists (off by default → `NoopReranker`); sort by score.

Pure over the two stores; deterministic given a fixed embedder.

### 4.5 `Reranker` (`rerank.py`)

```python
class Reranker(Protocol):
    async def rerank(self, query: str, items: list[ContextItem]) -> list[ContextItem]: ...

class NoopReranker:  # default — identity
    async def rerank(self, query, items): return items
```

Concrete cross-encoder rerank (agentforge reranker module) is a later
adapter that lives *outside* `retrieve/` so the core stays framework-free;
config `rerank: off` selects Noop at 0.1.

### 4.6 `CodeGraph.retrieve` + CLI

- `CodeGraph.retrieve(query=None, symbol=None, embedder=None, **kw) ->
  ContextPack` — builds the `Retriever` from `RetrieveConfig` + the
  `EmbedConfig` embedder (or a passed one, e.g. fake in tests).
- CLI: **`ckg query [PATH] "QUERY" [--k --depth --mode --symbol --config]`**
  → prints `pack.render(budget)`. Uses the configured embedder (Bedrock
  default; fake via a test ckg.yaml).

### 4.7 Configuration (`config.py`)

```yaml
retrieve:
  k: 8
  depth: 1
  decay: 0.6
  fanout_cap: 25
  rerank: off            # off | <reranker ref>  (off at 0.1)
  edge_weights:
    resolved: 1.0
    parsed: 0.5
    llm: 0.3
    manual: 0.8
```

## 5. Alternatives considered

| Option | Why not |
|---|---|
| Reuse undirected `neighbors` for impact | Can't express reverse-only deps, and returns no edge → no provenance weighting or "why". `adjacent` is the minimal fix. |
| Extend `neighbors` with a `direction` arg instead of new method | `neighbors` returns nodes; the retriever needs *edges*. A node-returning method can't carry edge kind/provenance. Separate primitive is cleaner. |
| Put scoring/expansion in `Store.expand` | `Store.expand` stays the simple vector→neighborhood helper; retrieval scoring/modes/why belong in `retrieve`, not the storage facade. |
| Ship a real cross-encoder reranker now | Pulls agentforge/torch into the core path (ADR-0001) and isn't needed for a correct v0.1; hook + Noop now, adapter later. |
| LLM query rewriting (HyDE) in-path | Spec §8 — not in core at 0.1; agents can rewrite; revisit with eval evidence. |

## 6. Migration / rollout

`adjacent` is an additive `GraphStore` method (only Kuzu + the in-memory
reference exist; both updated + conformance). Modes are a `Literal` — adding
one is a minor bump. `Retriever` is subclassable for custom strategies
(experimental at 0.x). No persisted-data change.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Score fusion is heuristic | Weights/decay in config; the eval smoke set is the arbiter; reranker hook corrects finalists when enabled. |
| Hub-node fan-out explosion | Per-hop `fanout_cap` (default 25), recorded in `notes`. |
| Retrieval quality needs real embeddings; CI has fake | Mechanics tested deterministically with fake; an env-gated live relevance smoke (`CKG_LIVE_BEDROCK`) guards ranking with a behavioral metric. |
| `render` token budget vs real tokenizer | Reuses feat-005's consistent heuristic; never splits a chunk; over-budget items degrade to signatures. |
| `adjacent` correctness across directions | Conformance test pins out/in/both on a known topology; runs against every adapter. |

## 8. Open questions (decisions for review)

1. **Add `GraphStore.adjacent` to the contract?** Proposed: **yes** — it's
   the minimal primitive directed/edge-aware retrieval needs; additive and
   conformance-tested. (The alternative — approximating impact with
   undirected `neighbors` — can't do reverse-only or provenance weighting.)
2. **Reranker now or hook-only?** Proposed: **hook + Noop default**; concrete
   cross-encoder is a later out-of-core adapter (ADR-0001).
3. **Ship a `ckg query` CLI?** Proposed: **yes** — makes v0.1 usable from the
   shell; tests drive it with a fake-embedder ckg.yaml.

## 9. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-12 | Add `GraphStore.adjacent(node_id, kinds, direction) -> list[Edge]` | Directed, edge-returning traversal is required for impact mode + provenance-weighted scoring + why-traces |
| 2026-06-12 | Retriever does Python BFS over `adjacent` | Full control of hop/decay/edge-weight/fan-out/why; store stays a thin primitive |
| 2026-06-12 | Reranker = Protocol + Noop default; concrete impl out-of-core | Keeps `retrieve` framework-free (ADR-0001); rerank off at 0.1 |
| 2026-06-12 | Scoring = score × decay^hop × edge_weight(provenance), dedupe max-wins | ADR-0004 — resolved facts outrank parsed; llm second-class |
| 2026-06-12 | `render` never splits a chunk; signature fallback over budget | Pasteable, whole units (cAST intent at item granularity) |
| 2026-06-12 | No LLM in the retrieval path | Deterministic, fast; llm-derived nodes returned but flagged |

## 10. Chunk plan (the single feat-006 PR)

| Chunk | Commit | Contents |
|---|---|---|
| 0 | `chore(006): retrieve config` | `RetrieveConfig` block; design accepted |
| 1 | `feat(006): GraphStore.adjacent` | ABC method + Kuzu impl + in-memory reference + conformance `test_adjacent_directed` |
| 2 | `feat(006): context pack + scoring` | `pack.py` (ContextItem/ContextPack/render/to_dict), `scoring.py`; unit tests |
| 3 | `feat(006): retriever + modes` | `retriever.py` (entry/expand/merge), `rerank.py` (Protocol + Noop); mode/topology tests on the fixture |
| 4 | `feat(006): CodeGraph.retrieve + ckg query` | facade method + CLI; fake-embedder CLI test |
| 5 | `test(006): scoring, render, zero-hit, layering, live smoke` | edge cases + env-gated live relevance smoke |
| 6 | `docs(006): impl status + tracker; design accepted` | spec status; TRACKER; this doc → accepted |

## 11. References

- Spec: `docs/features/feat-006-hybrid-retrieval.md`
- ADRs: 0001 (layering), 0004 (provenance), 0008 (hybrid retrieval)
- feat-003 (`Store`/`VectorStore`/`GraphStore`/`Edge`), feat-005 (chunks,
  `CHUNK_OF`, `Embedder`, `estimate_tokens`), feat-008 (consumer)
- Prior art: Potpie / cognee hybrid retrieval (research §2.8/§2.6)
