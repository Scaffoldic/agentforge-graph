# feat-009: Temporal / git evolution layer

## Metadata

| Field | Value |
|---|---|
| **ID** | feat-009 |
| **Title** | Temporal evolution layer (commit-validity on nodes & edges) |
| **Status** | proposed |
| **Owner** | kjoshi |
| **Created** | 2026-06-11 |
| **Target version** | 0.3.0 |
| **Languages** | python |
| **Module package(s)** | `agentforge_graph.temporal` |
| **Depends on** | feat-004 |
| **Blocks** | none |

---

## 1. Why this feature

Agents constantly ask questions only history can answer: "when did
this dependency appear and why", "is this function new or
ten-years-stable", "what changed around the time this bug appeared",
"who owns this area". No surveyed CKG models time — the research's
explicit gap list (§3.3): only Graphiti is temporal, and it is not
code-aware. Git has the data; nobody joins it to the code graph.

## 2. Why it must ship in the agent core

- Validity intervals are store-level properties on every node/edge —
  they must be written at index time (feat-004's pipeline is the
  only writer that sees both the old and new state of a file).
- Churn/age/authorship become *ranking signals* for feat-006/007
  (stable-and-central beats churning-and-central for orientation;
  recently-changed wins for debugging). Signals must live where the
  rankers live.
- Done per-agent, history mining is re-run per question (expensive
  `git log` walks); done in core, it is indexed once.

## 3. How consumers benefit

- `ckg_symbol` answers include `introduced: 2024-03 (a1b2c3),
  last_changed: 2026-05, churn_90d: 7, top_authors: […]` — free
  context for every lookup.
- New retrieval mode: "what changed near X since <commit>" — the
  debugging agent's first question after a regression, answered from
  the graph instead of `git log -p` archaeology.
- Graphiti-style point-in-time queries: `as_of=<commit>` reconstructs
  the neighborhood as it was — useful for bisect-style reasoning.

## 4. Feature specifications

### 4.1 User-facing experience

```python
hist = await graph.history("…auth.py verify().")
# SymbolHistory: introduced, modified[], authors, churn windows

ctx = await graph.retrieve(symbol=..., mode="impact",
                           as_of="v2.3.0")          # tag/sha
changed = await graph.changed_since("HEAD~20", scope="src/app/")
```

### 4.2 Public API / contract

- Every `Node`/`Edge` gains `valid_from: str` (commit sha) and
  `valid_to: str | None` (None = current) — written by feat-004,
  nullable until this feature ships (schema reserved in feat-001's
  `attrs`, promoted to typed fields here: minor bump).
- `TemporalIndex` API: `history(symbol_id)`, `changed_since(ref,
  scope?)`, `authors(symbol_id)`, `churn(symbol_id, window_days)`.
- `as_of=` parameter on `Retriever.retrieve` and
  `GraphStore.neighbors` (adapters may decline: capability flag
  `temporal`; embedded adapters implement it, server adapters may
  defer).

### 4.3 Internal mechanics

- **Bi-temporal-lite (Graphiti's idea, scoped down):** we track
  *commit validity* only (when was this true in the repo), not
  ingestion time. Refresh (feat-004) closes intervals
  (`valid_to = new_commit`) for removed/changed symbols and opens
  them for added ones, instead of deleting rows. Current-graph
  queries filter `valid_to IS NULL` — index keeps them fast.
- **Backfill:** `ckg index --history N` replays the last N commits
  through the incremental pipeline (cheap: each step is a diff) to
  populate intervals for pre-existing code. Default N=0 (history
  accrues from adoption); `--history full` for the brave.
- **Authorship/churn:** mined from `git log --numstat` per file,
  attributed to symbols by span overlap at each commit; stored as
  periodic aggregates (`attrs.churn_90d`, `attrs.top_authors`), not
  per-commit facts — bounded storage.
- **Storage growth control:** closed intervals are pruned beyond a
  configurable horizon (default: keep 1 year or 1,000 commits).

### 4.4 Module packaging

`agentforge_graph.temporal` — default install; activates only for
git sources.

### 4.5 Configuration

```yaml
temporal:
  enabled: true
  history_backfill: 0        # commits to replay at first index
  retention_commits: 1000
```

## 5. Plug-and-play & upgrade story

Enabling on an existing index starts intervals at the current
commit; backfill is explicit and resumable. Disabling reverts to
delete-on-refresh (feat-004 default) — no data loss for the current
graph.

## 6. Cross-language parity

n/a.

## 7. Test strategy

- Integration on a scripted git fixture (N commits with known
  adds/renames/deletes): `history()` matches the script;
  `as_of` at each commit reconstructs the known graph (reuse
  feat-004's equivalence property per commit).
- Unit: interval closing on delete/modify; pruning respects
  retention; churn aggregation math.
- Perf: refresh overhead with temporal on vs off < 20% on the scale
  fixture.

## 8. Risks & open questions

| Risk / Question | Mitigation / Decision |
|---|---|
| Interval rows bloat the store on hot repos | Retention pruning + aggregates-not-facts for churn; measure on scale fixture |
| Rename lineage (same symbol, new descriptor) breaks history continuity | Git rename detection + signature similarity heuristic writes a `SUCCEEDS` edge between old/new symbol nodes — flagged `resolved` provenance; imperfect by design |
| `as_of` on server adapters (Neo4j) needs different indexing | Capability-flagged; embedded-first per project philosophy |
| Is commit-validity enough, or do we need true bi-temporal (ingestion time)? | Commit-only at 0.3. Graphiti's second axis matters for *belief revision*, which our parsed facts don't have; revisit if LLM facts (feat-012) need it |

## 9. Out of scope

- PR/issue/review ingestion (the *why* behind changes beyond commit
  messages — feat-010 territory via commit-message DocChunks).
- Blame-based bug attribution / hotspot prediction analytics.
- Cross-branch graphs (the index tracks one ref).

## 10. References

- Research §2.7 (Graphiti bi-temporal), §3.3 (temporal gap), §5
  item 10.
- feat-004 (the writer), feat-006/007 (ranking-signal consumers),
  feat-010 (commit-message linkage).

---

## Implementation status

Not started.
