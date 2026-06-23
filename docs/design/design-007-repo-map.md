# Design Doc: feat-007 budget-aware repo map

> Per-feature design doc (design stage). Mirrors
> `docs/features/feat-007-repo-map-summarization.md`. The spec says *what &
> why*; this doc says *how*.

---

## Metadata

| Field | Value |
|---|---|
| **Title** | feat-007 budget-aware repo map |
| **Status** | accepted |
| **Owner** | kjoshi |
| **Created** | 2026-06-12 |
| **Last updated** | 2026-06-12 |
| **Related features** | feat-007 (this) · consumes feat-002, feat-003 · consumed by feat-008 |
| **Related ADRs** | ADR-0001 (layering), ADR-0004 (provenance) |

---

## 1. Context

Queryless orientation: rank the symbol graph by structural importance
(a personalized-PageRank repo-map approach) and pack the top symbols'
*signatures* — not bodies — into a token budget. Deterministic, LLM-free,
the default first tool call of a feat-008 session.

**Gap to close.** The spec assumes each symbol carries a `signature` in its
node attrs "stored at extract time by feat-002" — but feat-002 didn't capture
it. So feat-007 amends `TreeSitterExtractor` to store a `signature` attr on
Class/Function/Method nodes (the def/class line), exactly as feat-006 added
chunk `code`. Re-index is needed to populate it (derivable data).

## 2. Goals

- `agentforge_graph.repomap` — **zero `agentforge` imports** (ADR-0001),
  deterministic, LLM-free.
- `RepoMap.ranked_symbols(k, focus)` (structured, stable) and
  `RepoMap.render(budget_tokens, focus, scope, kinds)` (text).
- Personalized PageRank over a provenance-weighted symbol digraph
  (resolved > parsed, consistent with feat-006).
- Budget never exceeded; whole signatures only; truncation always noted.
- `CodeGraph.repo_map()` + `ckg map` CLI.
- ≥90% coverage; `mypy --strict`; ruff.

## 3. Non-goals

- LLM prose summaries (feat-012); query-conditioned retrieval (feat-006).
- feat-004 cache/invalidation of the projection (the map recomputes per
  call at 0.1 — cheap at our scale; caching is feat-004's job).
- The other nine languages (ride feat-002 packs).

## 4. Proposal

### 4.1 Package layout

```
src/agentforge_graph/repomap/
  __init__.py     # RepoMap, RankedSymbol
  rank.py         # build the digraph + (personalized) PageRank
  render.py       # budget packing by file
  repomap.py      # RepoMap facade (ranked_symbols / render)
src/agentforge_graph/
  ingest/extractor.py  # + attrs["signature"] on def nodes
  config.py            # + RepoMapConfig
tests/repomap/
```

### 4.2 Signature capture (extractor amendment)

For each definition node, store `attrs["signature"]` = the source text of the
symbol's first span line, trimmed (e.g. `def login(self, token):`,
`class Circle:`). Multi-line signatures use the first line only (degrades to
`name(...)` if empty — spec §8). Small, additive; the rest of feat-002 is
unchanged.

### 4.3 Ranking (`rank.py`)

```python
class RankedSymbol(BaseModel):
    id: str; name: str; kind: NodeKind; path: str; rank: float; signature: str
```

1. **Project.** Query symbol nodes (`kinds`, default Class/Function/Method).
   For each, `adjacent(sym, [CALLS, REFERENCES, INHERITS], "out")`; keep edges
   whose *both* endpoints are in the symbol set; build a `networkx.DiGraph`
   with `weight = edge_weight(provenance)` (resolved 1.0 / parsed 0.5 / … —
   the feat-006 weights). IMPORTS is file-level; excluded from the symbol
   digraph at 0.1 (noted).
2. **Rank.** `networkx.pagerank(G, alpha=damping, weight="weight")`. With
   `focus` (paths and/or symbol ids), expand to the focus symbol set (a
   path → all its symbols) and pass `personalization={n: 1 if n in focus
   else 0}`; if focus matches nothing, fall back to unpersonalized.
   Isolated/empty graph → uniform rank by node (stable order).
3. Map ranks back to `RankedSymbol` (name/kind/path/signature from the node),
   sorted by rank desc, ties broken by id for determinism.

networkx is already in the `engine` extra (CI has it).

### 4.4 Rendering (`render.py`)

Descend the ranked list, grouping by file; under each file header
(`<path>:`) emit each symbol's signature line (indented), spending
`estimate_tokens` (feat-005's heuristic) until the budget is hit. Whole
signatures only; a file with no surviving symbols is dropped. Final line:
`… N more symbols below the budget` when truncated — never a silent cap.

```
src/app/auth.py:
  class AuthService:
  def login(self, username, password):
… 4812 more symbols below the budget
```

### 4.5 Facade + config + CLI

```python
class RepoMap:
    def __init__(self, store: Store, config: RepoMapConfig): ...
    async def ranked_symbols(self, k=100, focus=None) -> list[RankedSymbol]: ...
    async def render(self, budget_tokens=2000, focus=None, scope=None, kinds=None) -> str: ...
```

- `CodeGraph.repo_map(budget_tokens=2000, focus=None, …) -> str` and
  `CodeGraph.ranked_symbols(...)`.
- CLI: `ckg map [--budget --focus --scope --path --config]`.
- `RepoMapConfig`: `default_budget: 2000`, `damping: 0.85`,
  `kinds: [Class, Function, Method]`.
- `scope` restricts to a path subtree (filter symbols by path prefix).

## 5. Alternatives considered

| Option | Why not |
|---|---|
| Re-read source for signatures at map time | Couples repomap to the filesystem; spec wants `attrs.signature`; storing at extract keeps the map pure over the store. |
| Reconstruct signatures from name+kind only | Loses real parameters; the def line is right there at extract time. |
| Include IMPORTS (file-level) in the symbol digraph | Mixes granularities; symbol PageRank wants symbol→symbol edges (CALLS/REFERENCES/INHERITS). File-level ranking is a later refinement. |
| rustworkx for speed | networkx is fine at our scale (<1s/100k) and already a dep. |
| Cache the projection in `.ckg/` now | feat-004 owns invalidation; per-call recompute is cheap at 0.1. |

## 6. Migration / rollout

`signature` is an additive node attr (re-index to populate; derivable).
Output text is experimental (may improve without a major bump);
`ranked_symbols()` is the stable structured surface. No persisted-data
format change.

## 7. Risks

| Risk | Mitigation |
|---|---|
| PageRank over heuristic edges over-ranks noisy hubs | Provenance weighting; per-file grouping in output; golden fixture guards ranking. |
| Signature quality varies / multi-line defs | First span line, trimmed; degrades to `name(...)` if empty (spec §8). |
| Empty/edgeless graph | Uniform rank, deterministic id tiebreak; never errors. |
| Budget math vs real tokenizer | feat-005's consistent heuristic; whole signatures only. |
| `focus` matches nothing | Falls back to unpersonalized rank (no error). |

## 8. Open questions (decisions for review)

1. **Capture `signature` in the extractor (re-index needed)?** Proposed:
   **yes** — matches the spec; keeps the map pure over the store.
2. **Symbol digraph from CALLS/REFERENCES/INHERITS only (exclude IMPORTS)?**
   Proposed: **yes** at 0.1 (symbol→symbol edges); file-level signal later.
3. **`ckg map` CLI?** Proposed: **yes**.

## 9. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-12 | Add `attrs["signature"]` in the extractor | Spec assumes it; map stays pure over the store; additive |
| 2026-06-12 | Personalized PageRank via networkx over symbol→symbol edges | A proven personalized-PageRank repo-map approach; networkx already a dep; symbol granularity for ranking |
| 2026-06-12 | Provenance-weighted edges (reuse feat-006 weights) | Resolved calls outrank parsed (ADR-0004); consistent ranking signal |
| 2026-06-12 | Per-call recompute, no projection cache | Cheap at 0.1; caching/invalidation is feat-004 |
| 2026-06-12 | Whole signatures only, truncation always noted | No silent caps; pasteable orientation |

## 10. Chunk plan (the single feat-007 PR)

| Chunk | Commit | Contents |
|---|---|---|
| 0 | `chore(007): repomap config + signature capture` | `RepoMapConfig`; extractor stores `attrs["signature"]`; design accepted |
| 1 | `feat(007): symbol ranking (PageRank)` | `rank.py` (projection + personalized PageRank), `RankedSymbol`; ranking + focus tests |
| 2 | `feat(007): budget render + RepoMap facade` | `render.py`, `repomap.py`; budget/truncation/golden tests |
| 3 | `feat(007): CodeGraph.repo_map + ckg map` | facade methods + CLI; CLI test |
| 4 | `test(007): layering + edge cases` | layering, empty graph, scope filter |
| 5 | `docs(007): impl status + tracker; design accepted` | spec status; TRACKER; this doc → accepted |

## 11. References

- Spec: `docs/features/feat-007-repo-map-summarization.md`
- ADRs: 0001 (layering), 0004 (provenance)
- feat-002 (symbols/signatures), feat-003 (`Store`/`GraphStore.adjacent`),
  feat-005 (`estimate_tokens`), feat-008 (consumer)
- Research §2.10 (personalized-PageRank repo-map approach)
