# feat-006: Hybrid retrieval (vector + graph)

## Metadata

| Field | Value |
|---|---|
| **ID** | feat-006 |
| **Title** | Hybrid retrieval: vector search → graph expansion → rerank |
| **Status** | proposed |
| **Owner** | kjoshi |
| **Created** | 2026-06-11 |
| **Target version** | 0.1.0 |
| **Languages** | python |
| **Module package(s)** | `agentforge_graph.retrieve` |
| **Depends on** | feat-005 |
| **Blocks** | feat-008, feat-010, feat-012 |

---

## 1. Why this feature

Pure vector search answers "what looks like this question" — it
cannot answer "who calls this", "what breaks if I change this", or
"show me the route handler *and* its model". Pure graph traversal
needs a starting node the user doesn't have. Every agent-facing tool
in the survey that works well (Potpie, cognee) combines them: vector
entry, graph walk, ranked merge. This feature is that combination as
one typed call — the single retrieval surface every agent tool
(feat-008) and enricher (feat-010, feat-012) uses.

## 2. Why it must ship in the agent core

- **The join is the value.** Vector hits carry symbol IDs
  (feat-005's `CHUNK_OF`); only a core component that owns both
  stores can expand hits through typed edges and dedupe/rerank the
  union without N round trips.
- **Provenance-aware ranking must be uniform.** Resolved call edges
  should outrank heuristic references; `llm`-provenance facts must be
  visibly second-class (feat-001's whole point). If each consumer
  ranked ad hoc, that discipline dies.
- **Retrieval quality is measurable centrally** — one component, one
  eval set, one place to improve.

## 3. How consumers benefit

- An agent asks one question and gets a *connected context pack*:
  matching chunks, their symbols, 1-hop callers/callees, the owning
  class/file — instead of 5 disjoint text snippets it must stitch
  itself.
- Tool authors (feat-008) expose retrieval as 3 MCP tools that are
  thin wrappers; zero retrieval logic in the tool layer.
- "Impact" questions become first-class: `mode="impact"` walks
  reverse `CALLS`/`IMPORTS` from a symbol — the question grep cannot
  answer and agents ask constantly.

## 4. Feature specifications

### 4.1 User-facing experience

```python
ctx = await graph.retrieve("how are JWT tokens validated", k=8)
print(ctx.render(budget_tokens=4000))   # ranked, deduped, pasteable

impact = await graph.retrieve(symbol="…auth.py verify().", mode="impact",
                              depth=2)
```

### 4.2 Public API / contract

```python
class Retriever:
    async def retrieve(
        self,
        query: str | None = None,         # NL entry (vector)
        symbol: str | None = None,        # graph entry (exact)
        mode: Literal["context",          # default: hits + neighborhood
                      "impact",           # reverse deps of symbol
                      "definition",       # symbol + its chunks + docs
                      "similar"] = "context",
        k: int = 8,
        depth: int = 1,
        edge_kinds: list[EdgeKind] | None = None,
        min_provenance: Literal["parsed", "resolved"] | None = None,
        include_llm_facts: bool = True,   # Summary/TAGGED nodes, flagged
    ) -> ContextPack

class ContextPack(BaseModel):
    items: list[ContextItem]   # chunk | symbol | edge-fact, each scored
                               # + provenance + why-included trace
    def render(self, budget_tokens: int) -> str
    def to_dict(self) -> dict  # structured form for tools (feat-008)
```

`render()` packs highest-score items first, whole chunks only,
symbol-signature fallbacks when budget is tight (feat-007's
signature trick at item granularity).

### 4.3 Internal mechanics

Three-stage pipeline:

1. **Entry.** `query` → vector search (feat-005) → scored chunks →
   owning symbols via `CHUNK_OF`. `symbol` → direct node lookup.
   Both may be given (query anchored at a symbol).
2. **Expand.** Typed BFS from entry symbols through `edge_kinds`
   (mode-specific defaults: `context` → CALLS/CONTAINS/INHERITS both
   directions; `impact` → reverse CALLS/IMPORTS/IMPLEMENTS). Each
   expanded node carries a decayed score
   (`score × decay^hop × edge_weight`), where `edge_weight` favors
   `resolved` over `parsed` provenance.
3. **Merge & rerank.** Dedupe by symbol ID (max score wins);
   optional cross-encoder rerank of top-N text items via AgentForge's
   reranker module (agentforge-py feat-021) when configured;
   attach `why` traces ("vector hit 0.83", "callee of X, hop 1").

Every stage is pure over the two stores — no LLM calls in the
retrieval path (LLM-derived *nodes* may be returned, flagged; the
retriever itself stays deterministic and fast).

### 4.4 Module packaging

`agentforge_graph.retrieve` — default install. Reranker optional via
AgentForge module config.

### 4.5 Configuration

```yaml
retrieve:
  k: 8
  depth: 1
  decay: 0.6
  rerank: off            # off | agentforge reranker ref
  edge_weights:
    resolved: 1.0
    parsed: 0.5
```

## 5. Plug-and-play & upgrade story

`Retriever` is constructed by `CodeGraph`; modes are an enum —
adding a mode is a minor bump. Custom retrieval strategies subclass
`Retriever` (experimental surface at 0.x).

## 6. Cross-language parity

n/a.

## 7. Test strategy

- Unit: scoring math (decay, edge weights, dedupe max-wins);
  provenance filtering; `render()` budget never exceeded, never
  splits a chunk.
- Integration: fixture repo with known topology — `impact` returns
  exactly the reverse-dependency set; `definition` returns chunk +
  docstring.
- Eval (env-gated): the feat-005 Q→symbol smoke set extended with
  multi-hop questions ("what calls the thing that parses X");
  Recall@k floor tracked over time.
- Adversarial: query with zero vector hits → empty pack, no
  hallucinated expansion from random seeds.

## 8. Risks & open questions

| Risk / Question | Mitigation / Decision |
|---|---|
| Score fusion (vector score × graph decay) is heuristic | Expose weights in config; eval set is the arbiter; reranker (when on) corrects ordering of finalists |
| Expansion explosion on hub nodes (god classes, util modules) | Per-hop fan-out cap (default 25) with `log`-style note in the pack's `why` trace — no silent truncation |
| Should retrieval ever call an LLM (HyDE, query rewriting)? | Not in core path at 0.1. Agents can rewrite queries themselves; revisit with eval evidence |
| Cross-encoder rerank latency | Optional, off by default, finalists-only (N≤32) |

## 9. Out of scope

- Token-budgeted *whole-repo* maps (feat-007 — different shape:
  no query, centrality-ranked).
- Conversational memory of past retrievals.
- Multi-repo retrieval (post-1.0, with feat-003 federation).

## 10. References

- Research §3.1, §5 Layer 1 items 6; Potpie (§2.8), cognee (§2.6).
- agentforge-py feat-021 (reranker), feat-022 (hybrid search), and
  feat-023 (graphrag-hybrid) — framework rails this feature rides on.
- feat-005 (entry), feat-007 (sibling), feat-008 (consumer).

---

## Implementation status

**Shipped (Python)** — design:
`docs/design/design-006-hybrid-retrieval.md` (accepted).
`agentforge_graph.retrieve` ships:

- **`Retriever.retrieve(query|symbol, mode, …)`** — vector entry → typed
  graph BFS → provenance-weighted merge. Four modes: **context** (hits +
  neighborhood), **impact** (reverse CALLS/IMPORTS/IMPLEMENTS), **definition**
  (symbol + chunks/members), **similar** (pure vector). Per-hop
  `decay × edge_weight(provenance)`, fan-out cap (noted, not silent),
  `min_provenance` / `include_llm_facts` filters, dedupe max-wins, why-traces.
- **`ContextPack`** — `render(budget_tokens)` (whole chunks, signature
  fallback, never split) + `to_dict()`.
- **`GraphStore.adjacent(node_id, kinds, direction)`** added to the contract
  (Kuzu + in-memory reference + conformance) — directed, edge-returning
  traversal the retriever's BFS and scoring need.
- **`Reranker`** Protocol + `NoopReranker` (rerank `off` at 0.1; concrete
  cross-encoder is a later out-of-core adapter).
- **`CodeGraph.retrieve()`** + **`ckg query`** CLI.
- ~97% coverage with the FakeEmbedder; an **env-gated live relevance smoke**
  (`CKG_LIVE_BEDROCK`) — verified locally: "compute the area of a circle"
  surfaces the `area` code via real Cohere embeddings. `mypy --strict`, ruff.

**Decisions / deferrals** (design §8/§9): added `GraphStore.adjacent`
(directed/edge-aware traversal); reranker is a hook (concrete impl
out-of-core, ADR-0001); no LLM in the retrieval path (llm-derived nodes
returned but flagged); chunk `code` now stored on CHUNK nodes for rendering.
