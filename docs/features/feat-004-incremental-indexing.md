# feat-004: Incremental indexing

## Metadata

| Field | Value |
|---|---|
| **ID** | feat-004 |
| **Title** | Incremental indexing (content-hash, git-aware) |
| **Status** | proposed |
| **Owner** | kjoshi |
| **Created** | 2026-06-11 |
| **Target version** | 0.2.0 |
| **Languages** | python |
| **Module package(s)** | `agentforge_graph.ingest.incremental` |
| **Depends on** | feat-002, feat-003 |
| **Blocks** | feat-009 |

---

## 1. Why this feature

A graph that costs a full re-index per commit is a graph nobody
keeps fresh — and a stale CKG is worse than none, because agents
trust it. The survey found incrementality is *the* operational
dividing line: Sourcegraph's launch-time SCIP limitation was exactly
this ("index the entire repository on every commit"), and
stack-graphs' core contribution was making indexing file-incremental
so GitHub could afford precise navigation at scale (both verified).

For our use — an agent's working memory over a repo that changes
many times an hour — re-index cost must be proportional to the diff,
seconds not minutes.

## 2. Why it must ship in the agent core

- It is an architectural property, not a feature bolted on: feat-001
  (stable symbol IDs), feat-002 (file-isolated extraction), and
  feat-003 (per-file transactional upsert) were all shaped so this
  feature is a thin orchestration on top. Leaving it out wastes that
  design.
- Every enrichment feature (005, 010, 011, 012) needs *dirty
  tracking* — "which symbols changed since the enricher last ran" —
  and they must all get it from one place or each will invent its own
  staleness logic.

## 3. How consumers benefit

- `ckg index` on an already-indexed repo touches only changed files:
  edit 3 files in a 5,000-file repo → ~3 files re-extracted, edges
  re-resolved only where the import graph is dirty, done in seconds.
- Embeddings (feat-005) and LLM enrichments (feat-012) — the
  *expensive* artifacts — are recomputed only for dirty symbols,
  cutting embedding/LLM spend by orders of magnitude on typical
  diffs.
- CI usage becomes practical: cache `.ckg/`, re-index the diff,
  query in a PR check.

## 4. Feature specifications

### 4.1 User-facing experience

```bash
ckg index            # detects prior index → incremental by default
ckg index --full     # force rebuild
ckg status           # indexed commit, dirty files, staleness report
```

```python
report = await graph.refresh()        # IndexReport: files re-extracted,
                                      # edges re-resolved, symbols dirtied
```

### 4.2 Public API / contract

```python
class ChangeDetector:
    """Diff the working tree against the indexed state."""
    async def detect(self, repo: RepoSource, meta: IndexMeta) -> ChangeSet
    # ChangeSet: added / modified / deleted / renamed files

class IncrementalIndexer:
    async def refresh(self, changes: ChangeSet) -> IndexReport

class DirtySet:
    """Symbols whose content or neighborhood changed since a named
    consumer last ran. The staleness API for all enrichers."""
    async def dirty_for(self, consumer: str) -> list[str]      # symbol IDs
    async def mark_clean(self, consumer: str, ids: list[str]) -> None
```

### 4.3 Internal mechanics

Pipeline per refresh (stack-graphs design + SCIP stable IDs,
research §3.2):

1. **Detect.** Prefer `git diff --name-status <indexed_commit>..HEAD`
   + working-tree status; fall back to content-hash scan for non-git
   sources. Renames detected via git's rename detection.
2. **Re-extract** changed files only (feat-002 pass 1 is
   file-isolated, so this is embarrassingly parallel).
3. **Transactional swap** per file via feat-003 `upsert` — old
   subgraph out, new in. Stable symbol IDs mean unchanged symbols in
   a changed file keep their identity (and their enrichments) as
   long as their descriptor is unchanged.
4. **Scoped re-resolve.** Re-run the feat-002 resolver only for:
   (a) the changed files' own references, (b) edges whose
   `resolved_from` is a changed file, (c) files importing a changed
   file (one hop in the import graph).
5. **Dirty propagation.** Changed/removed symbols + their 1-hop
   neighbors are appended to `DirtySet` per registered consumer
   (embeddings, summaries, pattern tags…). Consumers drain at their
   own cadence.
6. **Commit meta.** `meta.json` updated with new indexed commit —
   atomically, last, making refresh crash-safe (a crashed refresh
   re-runs from the old commit; per-file upserts are idempotent).

### 4.4 Module packaging

`agentforge_graph.ingest.incremental` — default install.

### 4.5 Configuration

```yaml
ingest:
  incremental: true          # --full overrides
  resolve_scope_hops: 1      # import-graph hops to re-resolve
```

## 5. Plug-and-play & upgrade story

Always on once shipped. Pack version or schema version change in
`meta.json` forces `--full` automatically (correctness over speed).

## 6. Cross-language parity

n/a.

## 7. Test strategy

- **Equivalence property (the key test):** for randomized edit
  scripts on fixture repos, `full_reindex(repo') == refresh(diff)`
  graph-isomorphism modulo provenance timestamps. Run in CI on every
  PR.
- Unit: rename handling, delete handling, crash-recovery (kill
  between steps 3–6, re-run, assert convergence).
- Enrichment-survival: enrich a symbol, edit an unrelated function in
  the same file, assert the enrichment survives.
- Perf regression: 1-file edit on the scale fixture must complete
  under a budgeted wall-clock.

## 8. Risks & open questions

| Risk / Question | Mitigation / Decision |
|---|---|
| Resolver scope (1 hop) misses exotic invalidation (re-exports chains) | `resolve_scope_hops` configurable; equivalence property test is the safety net — widen scope if it ever fails |
| Descriptor changes (rename a function) orphan enrichments | Accepted at 0.2: rename = delete+add. feat-009 may add rename lineage via git similarity |
| Non-git sources (tarballs) | Content-hash scan fallback; slower detect, same pipeline |
| Watch mode (fs events) | Deferred — `refresh()` is cheap enough to call per agent turn; revisit if demanded |

## 9. Out of scope

- Cross-commit history retention (feat-009 owns time; this feature
  keeps only the *current* graph fresh).
- Distributed/parallel indexing across machines.
- Glean-style stacked fact layers — over-engineering at our scale;
  per-file swap is sufficient.

## 10. References

- Research §3.2 (three incremental designs — stack-graphs verified
  file-incremental, SCIP verified stable-ID intent, Glean stacked
  layers unverified), §2.3, §2.4.
- feat-001 (symbol IDs), feat-002 (file-isolated extract), feat-003
  (transactional upsert, `meta.json`), feat-009 (temporal layer
  builds on the same ChangeSet).

---

## Implementation status

**Shipped** (branch `feat/004-incremental-indexing`). `agentforge_graph.ingest.incremental`:
`IndexMeta` (atomic `.ckg/meta.json` manifest — commit, per-pack fingerprint,
per-file content-hash map), `ChangeDetector`/`ChangeSet` (content-hash diff as
source of truth, git used to refine renames), `IncrementalIndexer.refresh`
(delete → scoped re-extract → scoped re-resolve), and `DirtySet` (`.ckg/dirty.json`,
the enricher staleness API; embeddings is the first consumer via
`CodeGraph.embed(only_dirty=True)`).

`ckg index` is incremental by default; `ckg index --full` forces a rebuild
(also forced automatically on a pack-fingerprint or schema bump); `ckg status`
reports indexed vs HEAD commit, dirty flag, and node counts.

Enabling change in the engine: resolver edges now carry an `origin_path` (their
source file), and `GraphStore.clear_resolved(paths)` invalidates exactly a
re-resolve scope (and GCs orphaned external packages). Correctness is held by an
**equivalence property test** — `refresh(diff)` produces the same graph as a
full re-index across add/modify/rename/delete edit scripts. ≥97% coverage on the
new package; `mypy --strict` + ruff clean. See
`docs/design/design-004-incremental-indexing.md`.
