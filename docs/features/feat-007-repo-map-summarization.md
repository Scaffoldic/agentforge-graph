# feat-007: Budget-aware repo map

## Metadata

| Field | Value |
|---|---|
| **ID** | feat-007 |
| **Title** | Budget-aware repo map (centrality-ranked structural summary) |
| **Status** | proposed |
| **Owner** | kjoshi |
| **Created** | 2026-06-11 |
| **Target version** | 0.1.0 |
| **Languages** | python |
| **Module package(s)** | `agentforge_graph.repomap` |
| **Depends on** | feat-002, feat-003 |
| **Blocks** | feat-008 |

---

## 1. Why this feature

Before an agent can ask good questions of a codebase, it needs
orientation: what are the load-bearing modules, the central types,
the public seams. Dumping a file tree wastes tokens on `__init__.py`
and test fixtures; dumping everything is impossible. Aider's
repo-map proved the effective recipe (research §2.10): rank the
def/ref graph with personalized PageRank, then pack the top symbols'
*signatures* — not bodies — into a fixed token budget. It is the
single most context-efficient repo orientation technique in the
survey, and we already store the graph it needs.

## 2. Why it must ship in the agent core

- The ranking runs over the whole graph (feat-003) — an agent-side
  reimplementation would re-download the graph per call.
- The map is the default *first tool call* of every downstream agent
  session (feat-008 exposes it as `ckg_repo_map`); its cost and
  quality shape every session, so it must be cached and invalidated
  by the core alongside the index (feat-004 dirty hooks).
- Personalization (rank relative to a focus set) needs query-time
  graph access, not a static README.

## 3. How consumers benefit

- A coding agent's first call returns a ~2k-token map of a
  5,000-file repo that names the 50 most structurally important
  symbols with signatures and paths — orientation that otherwise
  costs dozens of exploratory file reads.
- Passing `focus=[files in the current task]` re-ranks the map
  around the working set — Aider's personalization trick — so the
  map stays relevant as the task moves.
- Deterministic and LLM-free: costs milliseconds, works offline,
  never hallucinates structure.

## 4. Feature specifications

### 4.1 User-facing experience

```python
print(await graph.repo_map(budget_tokens=2000))
print(await graph.repo_map(budget_tokens=2000,
                           focus=["src/app/auth.py"]))
```

```bash
ckg map --budget 2000 --focus src/app/auth.py
```

Output shape (per file, ranked):

```
src/app/auth.py:
  class AuthService:
    def login(self, username: str, password: str) -> Session
    def verify(self, token: str) -> Claims
src/app/models.py:
  class User(Base): ...
```

### 4.2 Public API / contract

```python
class RepoMap:
    async def render(
        self,
        budget_tokens: int = 2000,
        focus: list[str] | None = None,     # paths or symbol IDs
        scope: str | None = None,           # subtree restriction
        kinds: list[NodeKind] | None = None # default: Class/Function/Method
    ) -> str

    async def ranked_symbols(self, k: int = 100,
                             focus: list[str] | None = None
                             ) -> list[RankedSymbol]   # structured form
```

### 4.3 Internal mechanics

1. **Graph projection.** Build (and cache) a symbol-level digraph:
   nodes = Class/Function/Method symbols; edge A→B for each
   `CALLS`/`REFERENCES`/`IMPORTS`/`INHERITS` from A's file/symbol to
   B, weighted by provenance (resolved 1.0, parsed 0.5 — consistent
   with feat-006).
2. **Rank.** PageRank; with `focus`, personalized PageRank seeded on
   the focus symbols (and their files' symbols).
3. **Pack.** Descend ranked list; emit each symbol's signature line
   (stored at extract time in `attrs.signature` by feat-002),
   grouped by file, until the token budget is spent. Whole
   signatures only; files with no surviving symbols are dropped.
   A final line notes truncation: `… 4,812 more symbols below
   threshold` — no silent caps.
4. **Cache & invalidate.** Projection cached in `.ckg/`; feat-004
   dirty events invalidate affected nodes' rows; PageRank recomputes
   lazily (it is cheap at our scale: <1s for 100k nodes).

### 4.4 Module packaging

`agentforge_graph.repomap` — default install. `networkx` (or
`rustworkx` if perf demands) as dependency.

### 4.5 Configuration

```yaml
repomap:
  default_budget: 2000
  damping: 0.85
  kinds: [Class, Function, Method]
```

## 5. Plug-and-play & upgrade story

Always installed. Output format is human/LLM-facing prose, marked
experimental (may improve without major bump); `ranked_symbols()` is
the stable structured surface.

## 6. Cross-language parity

n/a.

## 7. Test strategy

- Unit: budget never exceeded (property over random budgets);
  truncation note always present when truncated; focus changes
  ranking (seeded graph fixture with known central node).
- Golden: fixture repo → expected map text at fixed budget.
- Integration: feat-004 edit → projection invalidation → map
  reflects the change without full rebuild.

## 8. Risks & open questions

| Risk / Question | Mitigation / Decision |
|---|---|
| PageRank over heuristic edges may over-rank noisy hubs | Provenance weighting + per-file symbol cap in output; eval against a hand-ranked fixture |
| Signature extraction quality varies by language | Signatures captured by feat-002 packs (golden-tested there); map degrades to `name(...)` if absent |
| Should the map include feat-012 summaries when present? | Yes, post-feat-012: one summary line per top-ranked file, flagged `[llm]`. Specced there, not here |

## 9. Out of scope

- LLM-generated prose summaries (feat-012).
- Query-conditioned retrieval (feat-006 — the map is queryless
  orientation).
- Architecture diagrams / visualization.

## 10. References

- Research §2.10 (Aider repo-map: tree-sitter defs/refs + PageRank +
  token budget — unverified but documented at
  aider.chat/docs/repomap.html), §5 item 7.
- feat-002 (signatures), feat-003 (graph), feat-004 (invalidation),
  feat-008 (exposes as tool).

---

## Implementation status

Not started.
