# Design Doc: feat-004 incremental indexing

> Per-feature design doc (design stage). Mirrors
> `docs/features/feat-004-incremental-indexing.md`. The spec says *what &
> why*; this doc says *how*.

---

## Metadata

| Field | Value |
|---|---|
| **Title** | feat-004 incremental indexing (content-hash, git-aware) |
| **Status** | accepted |
| **Owner** | kjoshi |
| **Created** | 2026-06-13 |
| **Last updated** | 2026-06-13 |
| **Related features** | feat-004 (this) · consumes feat-002, feat-003 · blocks feat-009; unblocks cheap feat-005/010/011/012 re-enrichment |
| **Related ADRs** | ADR-0001 (layering), ADR-0004 (provenance), ADR-0006 (schema/version) |

---

## 1. Context

A full re-index per commit is the operational dividing line the research
calls out (stack-graphs went file-incremental so GitHub could afford precise
nav; SCIP's early "index everything every commit" was the limitation). For an
agent's working memory over a repo that changes many times an hour, re-index
cost must be proportional to the diff — seconds, not minutes.

**The good news (from the analysis):** the engine was shaped for this. The
pieces already in place —

- `RepoSource` computes a SHA-256 `content_hash` for every file (`source.py`).
- `GraphStore.upsert(FileSubgraph)` and `GraphStore.delete_file(path)` are
  atomic, per-`origin_path` primitives (`kuzu_store.py`); LanceVectorStore has
  `delete_where({"path": …})`.
- `Store.open()` already writes `.ckg/meta.json` with `schema_version` and an
  **`indexed_commit` field that is initialized but never updated** — a
  placeholder left for this feature (`facade.py:71`).
- `ImportResolver.resolve(store, changed_files=…)` **already takes a
  `changed_files` scope parameter that nothing passes today** (`resolver.py:38`).
- `EmbedPipeline` already skips a file whose CHUNK `content_hash` set is
  unchanged (`embed/pipeline.py:60`); the vector store already clean-replaces
  per file.
- `serve/engine.py` already computes a `dirty` flag (HEAD ≠ indexed commit).

So feat-004 is primarily a **coordination layer**: detect the diff, scope
extraction/embedding/resolution to it, and persist enough metadata to do the
diff next time — plus one genuinely new store concern (§4.4).

**The one real subtlety.** Resolver-produced edges (`IMPORTS`, `CALLS`) are
written with `store.add([...])`, *deliberately path-less* so a full re-resolve
rewrites them and they "survive `delete_file` of the code files" (current
contract, `contracts.py`). That design is correct for full re-index but means
**incremental re-resolve has no way to invalidate stale resolved edges**. This
doc's central decision (§4.4) is how to make resolved edges
file-invalidatable without breaking the full-index path.

## 2. Goals

- `agentforge_graph.ingest.incremental` — **zero `agentforge` imports**
  (ADR-0001); pure orchestration over feat-002/003 primitives.
- `ckg index` is **incremental by default** when a prior index exists;
  `ckg index --full` forces a rebuild; `ckg status` reports staleness.
- `CodeGraph.refresh() -> IndexReport` — re-index only what changed; cost
  proportional to the diff.
- **Correctness is the contract:** `refresh(diff)` must produce the *same*
  graph as `full_reindex(repo')` (modulo provenance timestamps). An
  equivalence property test guards this on every PR.
- A `DirtySet` — the single staleness API every enricher (embeddings now;
  feat-010/011/012 later) reads instead of inventing its own.
- Crash-safe: `meta.json` is swapped atomically and **last**; a crashed
  refresh re-runs from the old commit; per-file upserts are idempotent.
- ≥90 % coverage; `mypy --strict`; ruff.

## 3. Non-goals

- Cross-commit history retention (feat-009 owns time; this keeps only the
  *current* graph fresh).
- Watch mode / fs-event daemon (deferred — `refresh()` is cheap enough to call
  per agent turn; spec §8).
- Rename *lineage* (feat-009). At 0.2 a rename = delete + add (spec risk
  table); descriptor-stable IDs preserve identity for in-place edits, not moves.
- Distributed/parallel cross-machine indexing; Glean-style stacked fact layers.

## 4. Proposal

### 4.1 Package layout

```
src/agentforge_graph/ingest/incremental/
  __init__.py        # ChangeSet, ChangeDetector, IncrementalIndexer, DirtySet, IndexMeta
  meta.py            # IndexMeta model + atomic load/save of .ckg/meta.json
  detect.py          # ChangeDetector (git-first, content-hash fallback) -> ChangeSet
  indexer.py         # IncrementalIndexer.refresh(ChangeSet) -> IndexReport
  dirty.py           # DirtySet (.ckg/dirty.json), the enricher staleness API
src/agentforge_graph/
  ingest/codegraph.py   # index() picks full|refresh; + refresh()
  ingest/pipeline.py    # run() gains an optional `paths` scope
  ingest/resolver.py    # tag resolved edges with origin_path (the §4.4 change)
  core/contracts.py     # + GraphStore.clear_resolved(paths)  (the §4.4 change)
  store/kuzu_store.py    # implement clear_resolved; tag added edges' origin_path
  config.py             # IngestConfig += incremental, resolve_scope_hops
  cli.py                # index --full; new `status` subcommand
  serve/engine.py        # status() reads IndexMeta (commit + file count)
tests/ingest/incremental/
```

### 4.2 `IndexMeta` (persisted state, `meta.py`)

Extend the existing `.ckg/meta.json` from `{schema_version, indexed_commit}`
to the full manifest the next diff needs:

```python
class IndexMeta(BaseModel):
    schema_version: int = STORE_SCHEMA_VERSION
    indexed_commit: str = ""                    # git HEAD at last index ("" if non-git)
    pack_versions: dict[str, str] = {}          # lang_slug -> pack version; change forces --full
    files: dict[str, str] = {}                  # repo-rel path -> content_hash (SHA-256)
```

- `load(root)` reads `meta.json`; raises `SchemaVersionError` on
  `schema_version` mismatch (existing behavior, ADR-0006) and forces `--full`
  on `pack_versions` mismatch.
- `save(root, meta)` writes to `meta.json.tmp` then `os.replace` — atomic,
  crash-safe. **Called last**, after the graph + vector swap commits.
- `files` is the source of truth for the non-git fallback and a cross-check
  for git (renames/force-pushes can lie; the hash never does).

### 4.3 `ChangeDetector` → `ChangeSet` (`detect.py`)

```python
class ChangeSet(BaseModel):
    added: list[str]; modified: list[str]
    deleted: list[str]; renamed: list[tuple[str, str]]   # (old, new)
    def is_empty(self) -> bool
    def full_rebuild(self) -> bool          # no prior index / schema|pack bump

class ChangeDetector:
    async def detect(self, source: RepoSource, meta: IndexMeta,
                     registry: PackRegistry) -> ChangeSet: ...
```

Strategy (spec §4.3):

1. **No prior index** (`meta.files` empty and `indexed_commit` == "") →
   `full_rebuild()`; caller does a clean full index.
2. **Git repo with a usable `indexed_commit`:**
   `git diff --name-status -M <indexed_commit> HEAD` for committed changes,
   **plus** `git status --porcelain` for the dirty working tree (uncommitted
   edits the agent is mid-flight on — the common case). Union the two; map
   status letters → added/modified/deleted/renamed; `-M` gives renames.
3. **Fallback (non-git, or `indexed_commit` unreadable):** walk
   `source.iter_files()`, compare each file's fresh `content_hash` to
   `meta.files`; present-and-changed → modified, present-and-new → added,
   in-meta-but-absent → deleted. (No rename detection in fallback; shows as
   delete+add — acceptable per §3.)
4. **Always** filter the result through the registry/excludes so we never act
   on a path the indexer wouldn't have indexed, and **verify git hits against
   `content_hash`** (a path git flags but whose hash matches meta is dropped —
   guards against no-op churn). Renames are recorded but **executed as
   delete(old) + add(new)** by the indexer (§3); SymbolIDs embed the path, so
   a move changes IDs anyway.

### 4.4 Making resolved edges file-invalidatable (the central change)

Today resolved `IMPORTS`/`CALLS` edges are path-less. For incremental
re-resolve to be correct we must be able to remove exactly the resolved edges
that a re-resolve will recreate — no more, no less. Decision:

1. **Tag resolver edges with `origin_path` = the source-side file** (the file
   whose import/call statement produced the edge: the importer for `IMPORTS`,
   the caller's file for `CALLS`). The resolver already groups work by owner
   file, so this is local. `store.add` is extended to accept/write
   `origin_path` on edges (nodes added by the resolver — external `PACKAGE`
   stubs — stay path-less; they're harmless shared sinks, MERGE-idempotent).
2. **`upsert`/`delete_file` already delete edges by `origin_path`**, so a
   changed or deleted file's *outbound* resolved edges are now swept as part
   of its existing transactional swap — for free.
3. For files in the re-resolve scope that are **not** re-extracted (the 1-hop
   importers of a changed/deleted file — they didn't change but their targets
   did), add one small primitive:

   ```python
   # GraphStore (contracts.py)
   async def clear_resolved(self, paths: list[str]) -> None:
       """Delete resolved-provenance edges whose origin_path is in `paths`.
       The inverse of a scoped re-resolve; leaves parsed nodes/edges intact."""
   ```

   Kuzu impl: `MATCH ()-[e:CkgEdge]->() WHERE e.origin_path IN $paths AND
   e.source = 'resolved' DELETE e`.

**Re-resolve scope** = `changed ∪ {importers of changed/deleted, out to
`resolve_scope_hops` hops in the IMPORTS graph}`. Before re-resolving:
`clear_resolved(scope)`, then `resolver.resolve(store, changed_files=scope)`
recreates exactly that scope's edges. The full-index path is unchanged
(`changed_files=None`, path-less behavior preserved except the now-populated
`origin_path`, which full re-resolve simply overwrites).

> Why not give every `add()` fact a path and reuse `delete_file`? Because
> `delete_file` also deletes *nodes* by `origin_path`; resolved edges and the
> shared external `PACKAGE` nodes have different lifetimes. A dedicated
> edge-only, resolved-only `clear_resolved` is the minimal correct primitive.

### 4.5 `IncrementalIndexer.refresh` (`indexer.py`)

```python
class IncrementalIndexer:
    async def refresh(self, changes: ChangeSet) -> IndexReport: ...
```

Per refresh (spec §4.3 pipeline):

1. **Deletes/renamed-old** → `graph.delete_file(p)` +
   `vectors.delete_where({"path": p})` for each.
2. **Added + modified (+ renamed-new)** → run `IngestPipeline` scoped to just
   those paths (§4.6): extract → `upsert` (transactional swap; stable IDs keep
   unchanged symbols' identity *and* their enrichments).
3. **Scoped re-resolve** (§4.4): compute scope, `clear_resolved(scope)`,
   `resolver.resolve(store, changed_files=scope)`.
4. **Dirty propagation** (§4.7): changed/removed symbol IDs + their 1-hop
   neighbors appended to every registered consumer's `DirtySet`.
5. **Commit meta** — recompute `meta.files` for touched paths, set
   `indexed_commit = HEAD`, `IndexMeta.save()` (atomic, **last**).

Empty `ChangeSet` → no-op (return a zero `IndexReport`), the per-agent-turn
hot path.

### 4.6 Pipeline + CodeGraph wiring

- `IngestPipeline.run(..., paths: list[str] | None = None)` — when `paths` is
  given, iterate only those (a scoped `source.iter_files`), else all (today's
  behavior). One-line filter; full path keeps full coverage.
- `CodeGraph.index(..., full: bool = False)`:
  load `IndexMeta`; if `full` or `meta` indicates rebuild (empty / schema|pack
  bump) or `config.ingest.incremental is False` → today's full path, then
  `IndexMeta.save()` with the complete file manifest. Else → `detect()` +
  `IncrementalIndexer.refresh()`.
- `CodeGraph.refresh() -> IndexReport` — the explicit incremental entry the
  spec names (`graph.refresh()`); what `index()` calls under the hood.
- `EmbedPipeline` becomes a `DirtySet` consumer: it drains the dirty files for
  consumer `"embeddings"` instead of walking the whole tree (its existing
  chunk-hash skip stays as the second-line guard). Full index → whole tree.

### 4.7 `DirtySet` (`dirty.py`)

```python
class DirtySet:
    """Per-consumer staleness cursor. Persisted to .ckg/dirty.json as
    {consumer: [symbol_id, ...]}. The one staleness API for all enrichers."""
    async def dirty_for(self, consumer: str) -> list[str]
    async def add(self, ids: list[str]) -> None          # append to all consumers
    async def mark_clean(self, consumer: str, ids: list[str]) -> None
```

Refresh appends dirtied symbol IDs (changed + removed + 1-hop neighbors) to
each registered consumer. Consumers (`embeddings` now; `summaries`,
`pattern-tags`, `routes` later) drain at their own cadence and `mark_clean`.
Persisted separately from `meta.json` so a consumer cursor update never
rewrites the file manifest. At 0.2 the only registered consumer is
`embeddings`; the API is the forward investment §2 of the spec demands so
feat-010/011/012 don't each reinvent it.

### 4.8 Config, CLI, status

- `IngestConfig += incremental: bool = True`, `resolve_scope_hops: int = 1`
  (spec §4.5). `--full` overrides `incremental`.
- CLI: `ckg index [--full]`; new **`ckg status`** → prints
  `engine.status()` (already implemented: indexed vs HEAD commit, dirty flag,
  node counts, store path) now sourced from `IndexMeta` rather than a
  first-node probe.

## 5. Alternatives considered

| Option | Why not |
|---|---|
| Keep resolved edges path-less; on refresh, full re-resolve | Re-resolve scans all nodes regardless, but rewriting *all* edges per tiny diff defeats the point and churns provenance timestamps; scoped re-resolve needs invalidation (§4.4). |
| Give every `add()` fact an `origin_path` and reuse `delete_file` | `delete_file` deletes nodes too; shared external `PACKAGE` nodes and resolved edges have different lifetimes. `clear_resolved` is the minimal correct primitive. |
| Content-hash only, ignore git | Misses cheap, precise rename/commit-range info and the dirty working tree; git-first with a hash cross-check (and hash-only fallback) is strictly better. |
| Store dirty state inside the graph (node attrs) | Couples enricher cursors to graph writes and to re-extraction; a side file (`dirty.json`) is simpler and independently updatable. |
| Watch mode / fs-events now | `refresh()` is cheap per turn; daemon is complexity we don't need at 0.2 (spec §8). |

## 6. Migration / rollout

- `meta.json` grows two fields (`pack_versions`, `files`). An old
  `{schema_version, indexed_commit}` file loads fine (defaults fill in); first
  index after upgrade repopulates `files`. No `schema_version` bump needed
  (additive, same store schema).
- Edges gain a populated `origin_path` on resolved edges. Existing indexes
  predating this have empty `origin_path` on resolved edges → they look
  "un-owned"; first `--full` (or first refresh that touches them) repopulates.
  To be safe, a `pack_versions`/feature flag in meta triggers a one-time
  `--full` on upgrade (correctness over speed, spec §5).
- `ckg index` behavior changes (incremental by default) — documented; `--full`
  restores old behavior exactly.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Scoped re-resolve misses an invalidation (re-export chains, transitive) | `resolve_scope_hops` configurable; the **equivalence property test** is the safety net — widen scope if it ever fails. |
| Resolved-edge `origin_path` tagging wrong → stale/dup edges | Same property test (`refresh == full`); plus a targeted unit asserting `clear_resolved` + re-resolve == full re-resolve. |
| Git lies (rebase, force-push, shallow clone, detached) | Always cross-check git hits against `content_hash`; fall back to hash scan if `indexed_commit` is unreachable. |
| Crash mid-refresh | `meta.json` saved atomically and last; per-file `upsert`/`delete_file` idempotent; re-run resumes from old commit. |
| Rename orphans enrichments | Accepted at 0.2 (delete+add, §3); feat-009 may add lineage. |
| DirtySet unbounded growth if a consumer never drains | Dirty IDs deduped; `mark_clean` trims; only registered consumers tracked. |

## 8. Open questions (decisions for review)

1. **Resolved-edge invalidation via `origin_path` tag + `clear_resolved`
   primitive** (§4.4)? Proposed: **yes** — minimal correct surface; reuses the
   existing per-path delete for the common case. *This is the key call.*
2. **`ckg index` incremental by default, `--full` to override**? Proposed:
   **yes** (spec §4.1).
3. **Ship `DirtySet` now** (only `embeddings` consumes it at 0.2) vs defer to
   the first enricher that needs it? Proposed: **ship now** — spec §2 wants one
   staleness source; wiring embeddings proves it.
4. **Re-resolve scope = changed ∪ 1-hop importers** (`resolve_scope_hops:1`)?
   Proposed: **yes**, configurable; property test widens if needed.
5. **Add a `ckg status` CLI** (surface existing `engine.status()`)? Proposed:
   **yes** (spec §4.1).

## 9. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-13 | Git-first detect (`diff` + `status --porcelain`) with content-hash fallback & cross-check | Cheap precise diffs incl. dirty tree; hash is the truth when git can't be trusted |
| 2026-06-13 | **Implemented** content-hash as the *source of truth*, git only to refine delete+add → rename | Inverts "git-first" for robustness: the hash diff is correct under dirty tree / shallow / detached / rebase and needs no git; git rename detection is a cosmetic overlay (rename = delete+add anyway, §3). Catches the uncommitted working tree for free. |
| 2026-06-13 | **Implemented** `clear_resolved(paths)` also GCs orphan external `PACKAGE` nodes | Folds package cleanup into one primitive (no separate `prune` method); keeps incremental == full when a file drops its last import of an external package — verified by the equivalence test |
| 2026-06-13 | Pack version = auto fingerprint of `.scm` + module_style + descriptor map (not a manual field) | A query change auto-forces `--full`; no version bookkeeping to forget |
| 2026-06-13 | Tag resolved edges with source-file `origin_path`; add `clear_resolved(paths)` | Makes resolved edges file-invalidatable with the minimal new primitive; full path unchanged |
| 2026-06-13 | `IndexMeta` extends `meta.json` (`pack_versions`, `files`); saved atomically last | Crash-safe; enables next diff & forced `--full` on pack/schema bump |
| 2026-06-13 | Incremental by default; `--full` override; `ckg status` | Spec §4.1; keep an escape hatch and a staleness readout |
| 2026-06-13 | Ship `DirtySet` (`dirty.json`), wire embeddings as first consumer | One staleness API for all enrichers (spec §2); avoid each reinventing |
| 2026-06-13 | Equivalence property test (`refresh == full`) on every PR | The correctness contract; safety net for scope heuristics |

## 10. Chunk plan (the single feat-004 PR)

| Chunk | Commit | Contents |
|---|---|---|
| 0 | `chore(004): IngestConfig incremental/scope_hops; design accepted` | config fields; this doc → accepted |
| 1 | `feat(004): IndexMeta + atomic meta.json load/save` | `meta.py`; `Store.open` writes/reads full manifest; unit tests |
| 2 | `feat(004): ChangeDetector + ChangeSet (git + hash fallback)` | `detect.py`; git/dirty-tree/fallback/rename unit tests |
| 3 | `feat(004): resolved-edge origin_path + clear_resolved` | resolver tagging, `clear_resolved` contract + kuzu impl; scoped-resolve == full unit |
| 4 | `feat(004): IncrementalIndexer.refresh + pipeline paths scope` | `indexer.py`, scoped `IngestPipeline.run`; refresh unit + crash-recovery |
| 5 | `feat(004): DirtySet + embeddings consumer` | `dirty.py`; EmbedPipeline drains dirty; enrichment-survival test |
| 6 | `feat(004): CodeGraph full|refresh, ckg index --full, ckg status` | facade wiring + CLI + `status` reads IndexMeta |
| 7 | `test(004): equivalence property (refresh == full) + layering` | randomized edit-script property test; layering test for the new package |
| 8 | `docs(004): impl status + tracker; design accepted` | spec status → Shipped; TRACKER; this doc accepted |

## 11. References

- Spec: `docs/features/feat-004-incremental-indexing.md`
- ADRs: 0001 (layering), 0004 (provenance), 0006 (schema/version)
- feat-001 (stable SymbolIDs), feat-002 (file-isolated extract,
  `resolver.changed_files`), feat-003 (`upsert`/`delete_file`, `meta.json`),
  feat-005 (`EmbedPipeline` chunk-hash skip), feat-009 (temporal, builds on
  the same `ChangeSet`)
- Research §3.2 (stack-graphs file-incremental; SCIP stable IDs), §2.3, §2.4
