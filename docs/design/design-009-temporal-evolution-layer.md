# Design Doc: feat-009 temporal / git-evolution layer

> Per-feature design doc (design stage). Mirrors
> `docs/features/feat-009-temporal-evolution-layer.md`. The spec says *what &
> why*; this doc says *how*. **Status: implemented (2026-06-17) — all five
> chunks landed (§10): sidecar+lifecycle (#56), churn/authorship (#57), read
> APIs (#58), backfill (#59), as_of+retention. Still opt-in / default-off.**

---

## Metadata

| Field | Value |
|---|---|
| **Title** | feat-009 temporal / git-evolution layer (commit-validity, churn, as-of) |
| **Status** | accepted |
| **Owner** | kjoshi |
| **Created** | 2026-06-16 |
| **Last updated** | 2026-06-16 |
| **Target version** | 0.2.0 (next minor — the "0.3" in the spec is a stale theme label; feat-004, the "0.2 theme", already shipped inside 0.1.0) |
| **Related features** | feat-009 (this) · consumes feat-004 (the writer that sees old+new state) · feeds feat-006/007 ranking · relates feat-010 (commit-message linkage) |
| **Related ADRs** | ADR-0001 (layering — temporal is a higher layer, must not bloat the deterministic core) · ADR-0004 (provenance) · ADR-0005 (locked v1 vocab — no new core edge kind) · ADR-0006 (schema/version — avoid a forced rebuild) |

---

## 1. Context

The graph today is a snapshot of one commit — it has no memory. feat-004's
refresh is the only writer that sees both the *old* and *new* state of a file
(it diffs content hashes, deletes removed files, re-extracts touched ones), so
it is the natural place to record how the graph evolves. Git already holds the
history; nothing joins it to the code graph.

**What already exists that we build on:**

- `ChangeSet` (`incremental/detect.py`) categorises a diff into
  `added / modified / deleted / renamed`, and **already runs git rename
  detection** (`_git_renames`, `_refine_renames`) — so file-level rename pairs
  are handed to us for free. This is the backbone of rename lineage (§4.8).
- `IncrementalIndexer.refresh(changes)` (`incremental/indexer.py`) is the single
  apply path; it deletes removed files and upserts touched ones. The temporal
  hooks attach here (§4.3).
- `IndexMeta` (`incremental/meta.py`) persists `indexed_commit` + the per-file
  content-hash manifest, saved atomically last in a refresh — the commit cursor
  we need.
- `Node.attrs` / `Edge.attrs` are free-form JSON already serialised into the
  store; enrichment (feat-012) denormalises tags there. We reuse that channel
  for read-friendly temporal fields (no schema bump).
- `RepoSource.root` is a git working tree, so `git log --numstat` / rename
  detection are available without new deps.

**The one real subtlety** (the central decision, §4.2/§4.3): the spec sketched
*bi-temporal columns on every node/edge with `valid_to IS NULL` filtering on the
hot table*. That would change the primary current-graph table (new columns, a
composite `(id, valid_from)` key so a modified symbol can keep a closed row
beside its current row), add a `valid_to IS NULL` predicate to **every** hot-path
query, force a `STORE_SCHEMA_VERSION` bump (→ rebuild, ADR-0006), and ripple
through both the Kuzu and Neo4j adapters + the whole conformance suite. This doc
argues for a **lower-risk model that delivers the same three user wins** by
keeping the current graph untouched and putting all history in a separate,
additive, embedded **evolution log**.

## 2. Goals

- `history(symbol)` → introduced / last-changed / churn / authors, cheaply.
- `changed_since(ref, scope?)` → the debugging agent's first question after a
  regression, answered from the graph, not `git log -p` archaeology.
- `as_of(commit)` → reconstruct a symbol's neighbourhood as it was (bisect-style
  reasoning), retention-bounded.
- Churn / age / authorship available as **ranking signals** to feat-006/007.
- **Zero regression** to the current-graph hot path (the 477 tests + Kuzu/Neo4j
  conformance stay green, unchanged), and **no forced rebuild** on upgrade.
- Refresh overhead with temporal **on** vs **off** < 20% on the scale fixture.

## 3. Non-goals

- True bi-temporal (ingestion-time axis). We track **commit validity only**;
  the second axis matters for belief revision, which parsed facts don't have.
  Revisit if feat-012's LLM facts need it.
- PR / issue / review ingestion (feat-010 territory via commit-message DocChunks).
- Blame-based bug attribution / hotspot prediction analytics.
- Cross-branch graphs (the index tracks one ref).
- Editing the locked v1 node/edge vocab (ADR-0005): rename lineage is an
  **event in the log**, not a new core `EdgeKind`.

## 4. Proposal

### 4.0 The model in one paragraph

Keep the current graph as the authoritative **"now"**, exactly as today (one row
per id, delete-on-refresh). Add a separate, append-only **evolution log**
(`agentforge_graph.temporal.TemporalStore`, an embedded SQLite sidecar under
`.ckg/temporal.db`) that the refresh writes one record to per lifecycle event:
a symbol/edge **opened** (added) or **closed** (removed / modified-out) at a
commit, plus periodic churn/author **aggregates**. `history` / `changed_since`
read the log; `as_of(C)` reconstructs by taking the current graph and replaying
the log backwards to C. A handful of read-friendly fields
(`introduced`, `last_changed`, `churn_90d`, `top_authors`) are **denormalised
onto current node `attrs`** during refresh so `ckg_symbol` gets them with no
join and no schema change.

### 4.1 Package layout (`agentforge_graph.temporal`, default install, activates only for git sources)

```
src/agentforge_graph/temporal/
  __init__.py            # exports: TemporalStore, TemporalIndex, SymbolHistory, Change
  store.py               # TemporalStore — SQLite sidecar (.ckg/temporal.db): events, aggregates
  index.py               # TemporalIndex — history/changed_since/authors/churn/as_of (reads store + graph)
  events.py              # Event/EventKind value types; opened|closed|succeeds records
  mining.py              # git log --numstat → per-file churn/authorship → symbol attribution by span overlap
  backfill.py            # replay last N commits through the incremental pipeline to seed intervals
  config.py              # TemporalConfig (the `temporal:` ckg.yaml block)
```

Layering (ADR-0001): `temporal` is a **higher layer** — it imports `core`,
`store`, `ingest.incremental`; the deterministic engine core never imports
`temporal`. The `IncrementalIndexer` gains an *optional* injected
`recorder: TemporalRecorder | None` (a thin port), so `ingest` depends on a
protocol, not on `temporal` concretely.

### 4.2 Why a sidecar log, not bi-temporal columns (the central decision)

| | **(A) Bi-temporal columns on the hot table** (spec sketch) | **(B) Sidecar evolution log** (recommended) |
|---|---|---|
| Current-graph schema | new `valid_from`/`valid_to` cols; PK → `(id, valid_from)` | **unchanged** |
| Hot-path queries | every query gains `valid_to IS NULL` | **untouched** |
| Schema version | bump → **forced rebuild** (ADR-0006) | **no bump, no rebuild** (purely additive) |
| Adapters touched | Kuzu **and** Neo4j + all conformance | embedded sidecar only; server graph backends untouched |
| Equivalence test (feat-004) | complicated — "the graph" now holds closed rows | **unaffected** |
| `as_of` | direct (filter by interval) | reconstruct from log (bounded compute) |
| Risk | high (hot path + two adapters) | low (isolated, additive) |

All three user wins (history, changed_since, as_of) are served by an append-only
log + the current graph; none *requires* versioning the hot table. (B) gets the
feature with no rebuild and no hot-path risk — decisive for a 0.x release that
just shipped a production bar. We adopt (B). `valid_from`/`valid_to` live as
**event records in the log**, not columns; `introduced`/`last_changed` are
**denormalised onto node `attrs`** for the common single-symbol read.

### 4.3 Interval lifecycle — hooking the refresh (`TemporalRecorder`)

`IncrementalIndexer.__init__` takes `recorder: TemporalRecorder | None`. In
`refresh(changes)`, after the existing steps, when a recorder is present:

```
# new_commit = self.commit  (the HEAD being indexed)
# step (1) already computes `removed` symbol ids; reuse them:
recorder.close(symbol_ids=<symbols in removed ∪ symbols that vanished from modified files>,
               at=new_commit)
recorder.open(symbol_ids=<symbols added in touched files (not present before)>,
              at=new_commit)
recorder.link_renames(changes.renamed, at=new_commit)          # §4.8
recorder.record_churn(mining.attribute(changes, base..new_commit))  # §4.5
recorder.flush()                                                # one SQLite txn
# denormalise onto current nodes:
for nid in opened ∪ modified: node.attrs["introduced"|"last_changed"|...] updated
```

"symbols that vanished from a modified file" and "symbols added" are computed by
diffing the file's symbol-id set before vs after the upsert — the indexer already
holds both (it queries `_symbols_in` pre-delete and re-extracts after). The
recorder is **append-only and idempotent per commit**: re-recording the same
commit is a no-op (guarded by a `(symbol_id, commit, event_kind)` unique index),
so a crashed-then-retried refresh stays consistent — mirroring how `IndexMeta`
is saved last.

**Full index** (`--full`): opens intervals for every symbol at the index commit
(`valid_from = commit`); no closes. **Temporal off**: recorder is `None`, refresh
behaves exactly as today (delete-on-refresh) — the behaviour gate is "is a
recorder injected", set from `temporal.enabled`.

### 4.4 `TemporalStore` (SQLite sidecar, `store.py`)

`.ckg/temporal.db` — chosen over a Kuzu table so server graph backends need no
changes and the log is isolated/prunable. Schema:

```sql
CREATE TABLE events (
  symbol_id TEXT NOT NULL,
  entity    TEXT NOT NULL,         -- 'node' | 'edge'
  event     TEXT NOT NULL,         -- 'opened' | 'closed' | 'succeeds'
  commit_sha TEXT NOT NULL,
  ts        INTEGER NOT NULL,      -- commit author time (epoch s)
  ref       TEXT,                  -- succeeds: the prior/next symbol id
  UNIQUE(symbol_id, commit_sha, event, ref)
);
CREATE INDEX events_by_symbol ON events(symbol_id);
CREATE INDEX events_by_commit ON events(ts);

CREATE TABLE aggregates (        -- periodic, bounded — not per-commit facts
  symbol_id TEXT PRIMARY KEY,
  churn_30d INTEGER, churn_90d INTEGER,
  top_authors TEXT,              -- JSON: [{name, commits}], top 3
  introduced_sha TEXT, introduced_ts INTEGER,
  last_changed_sha TEXT, last_changed_ts INTEGER
);
```

Why SQLite (stdlib `sqlite3`, no new dep): transactional, queryable, file-local,
trivially prunable, and absent for non-git/temporal-off repos. The
`VectorStore`/`GraphStore` contracts are **not** touched — `TemporalStore` is
its own thing.

### 4.5 Churn / authorship mining (`mining.py`)

Per refresh, for the commit range `(base_commit, new_commit]`:
`git log --numstat --format=…` gives per-commit, per-file `(added, deleted,
author, ts)`. Attribute a file's line deltas to symbols by **span overlap** at
that commit (each symbol node carries its `span`); a symbol's churn for a window
is the summed overlapping deltas. Store as **aggregates** (`churn_30d/90d`,
`top_authors`), recomputed for touched symbols only — bounded storage, no
per-commit fact explosion. Span attribution is approximate by design (line ranges
shift); good enough for a ranking signal and "who owns this".

### 4.6 Backfill (`backfill.py`, `ckg index --history N`)

Replay the last `N` commits oldest→newest through the **existing** incremental
pipeline against a throwaway working state: for each commit, compute the
`ChangeSet` vs its parent and feed the recorder (no need to re-embed — backfill
only writes events/aggregates). Cheap because each step is a diff. `N=0` default
(history accrues from adoption); `--history full` walks to the root (documented
as expensive). Resumable: backfill writes a `backfilled_through` cursor in the
sidecar; re-running continues. Uses git plumbing (`git rev-list`,
`git diff --numstat`) — no checkout churn.

### 4.7 `TemporalIndex` API (`index.py`) + `as_of`

```python
class TemporalIndex:
    async def history(self, symbol_id: str) -> SymbolHistory          # introduced, modified[], authors, churn
    async def changed_since(self, ref: str, scope: str | None) -> list[Change]
    async def authors(self, symbol_id: str) -> list[Author]
    async def churn(self, symbol_id: str, window_days: int) -> int
    async def as_of(self, commit: str, anchor: str, mode: str) -> ContextPack  # reconstruct + delegate to Retriever
```

- `history` / `changed_since` / `authors` / `churn` read the sidecar (+ the
  current graph for live spans). `SymbolHistory`, `Change`, `Author` are new
  value types in `temporal/events.py` (pydantic, like the rest of `core`).
- **`as_of(C)` reconstruction** (retention-bounded): start from the current
  graph's node/edge set; using the log, **drop** anything `opened` after `C` and
  **re-include** anything `closed` after `C` (it was alive at `C`). Hand the
  reconstructed id-set to the existing `Retriever`/`repomap` as an allow-filter.
  Requested `C` older than `retention_commits` → `TemporalError("beyond
  retention horizon")` (capability honesty, not a silent wrong answer).
- **No change to `GraphStore.neighbors`/contract** (the spec floated `as_of=` on
  the store; we keep the contract stable and put `as_of` at the temporal/retriever
  layer — server adapters "defer" simply by the sidecar being embedded-only).

`CodeGraph` gains thin convenience methods: `history`, `changed_since`, and an
`as_of=` kwarg on `retrieve` that routes through `TemporalIndex.as_of` when set.

### 4.8 Rename lineage (`succeeds` events — the hard part)

- **File renames:** `ChangeSet.renamed` (already git-detected) gives `(old, new)`
  path pairs. For each, map old→new symbol ids by descriptor-relative-to-file and
  emit a `succeeds` event (old `closed`, new `opened`, linked) — reliable, free.
- **Intra-file symbol renames** (same file, `foo()`→`bar()`): git rename
  detection won't see these. Heuristic (opt-in, `temporal.rename_detection:
  signature`): within a modified file, pair a `closed` symbol with an `opened`
  one when their **signature + span size** are similar above a threshold; emit a
  `succeeds` event flagged `provenance=resolved` (imperfect by design, ADR-0004
  honesty). Default **off** for the first cut — file-rename lineage ships;
  intra-file is a follow-on once the heuristic is measured. `succeeds` is a **log
  event, not a core `EdgeKind`**, so ADR-0005's locked vocab is untouched.

### 4.9 Config, CLI, status, tool surface

```yaml
temporal:
  enabled: false           # 0.2: OPT-IN (accrue from adoption). Revisit default-on after the <20% overhead test.
  history_backfill: 0       # commits to replay at first index
  retention_commits: 1000   # prune closed events/aggregates beyond this (or 1 year, whichever first)
  rename_detection: file    # file | signature (signature adds intra-file lineage, best-effort)
```

- **Default off** for the initial ship — matches the project's "opt-in until
  measured" pattern (cf. ENH-009 rerank). Enabling it has zero effect on existing
  data; intervals start at the current commit.
- **CLI:** `ckg index --history N` (backfill); new `ckg history <symbol>` and
  `ckg changed-since <ref> [--scope GLOB]`; `ckg status` gains
  `temporal: {enabled, events, backfilled_through}`.
- **MCP / tools:** `ckg_symbol` output gains `introduced / last_changed /
  churn_90d / top_authors` (free, read from `attrs`). One new tool
  **`ckg_history`** (`{symbol_id}` → the history record). `as_of` over MCP and a
  `changed_since` tool are deferred to a follow-on (keep the 0.2 tool delta small:
  +1 tool, enriched `ckg_symbol`).

### 4.10 Storage growth control

Closed events and aggregates beyond `retention_commits` (or 1 year) are pruned at
the end of each refresh (`TemporalStore.prune(horizon)`). Churn is stored as
aggregates, not per-commit rows. Edge events are the volume driver (edges churn
more than nodes) — see Risks; retention + node-first reconstruction bound it.

## 5. Alternatives considered

- **(A) Bi-temporal columns on the hot table** — the spec's sketch. Rejected:
  forces a rebuild, adds a `valid_to IS NULL` predicate to every hot query, and
  touches both store adapters + conformance. §4.2.
- **Evolution log as a Kuzu table in the main graph db** — transactional with
  upserts, but couples temporal into the `GraphStore` contract and forces the
  Neo4j adapter to grow a parallel table (or formally decline via a capability
  flag). The SQLite sidecar keeps server backends 100% untouched.
- **Re-derive edges at `as_of` by re-resolving the reconstructed node set** —
  avoids logging edge events (smaller log), but re-running the resolver per
  `as_of` query is expensive and can disagree with what was actually resolved
  then. We log edge events and prune, accepting bounded volume. (Open question Q3.)
- **Mine churn per-question in the consumer** — the per-agent status quo;
  re-walks `git log` every question. Indexing once in core is the whole point
  (spec §2).

## 6. Migration / rollout

- **No schema bump, no forced rebuild** — temporal is purely additive
  (`.ckg/temporal.db` appears only when enabled). `STORE_SCHEMA_VERSION` stays 1.
- Enabling on an existing index starts intervals at the current commit; backfill
  is explicit (`--history N`) and resumable.
- Disabling reverts to delete-on-refresh (feat-004 default); the sidecar is left
  in place (stale but harmless) or removed by `ckg index --full`. No data loss to
  the current graph either way.
- `.ckg/temporal.db` is under the already-gitignored `.ckg/`.

## 7. Risks

| Risk | Mitigation |
|---|---|
| **Edge events bloat the log on hot repos** | Retention pruning; aggregates-not-facts for churn; reconstruct nodes-first; measure on the django scale fixture. Open Q3 (snapshot vs event-log edges). |
| Span-overlap churn attribution is approximate (lines shift) | It's a ranking signal + ownership hint, not a fact; documented as approximate; provenance not asserted. |
| Intra-file rename heuristic mislinks symbols | Off by default; `succeeds` flagged `resolved`-provenance + best-effort; file-rename (exact) ships first. |
| Refresh overhead from mining `git log` each diff | Range is just `(base, new]` (usually 1 commit); numstat is cheap; perf gate < 20% on the scale fixture, else gate behind `enabled`. |
| `as_of` correctness vs retention | Beyond-horizon requests raise, never silently wrong. Equivalence: reconstructed graph at each backfilled commit == a full index of that commit (reuse feat-004's property test per commit). |
| SQLite concurrency with the async store | Single-writer; the recorder flushes one txn at end-of-refresh; reads are separate connections. No cross-store transaction needed (log is advisory, current graph is source of truth). |

## 8. Open questions (decisions for review)

- **Q1 — Default `enabled`?** ✅ **RESOLVED (2026-06-16): off** for 0.2 (opt-in,
  measured); revisit default-on after the overhead gate. (Spec floated `true`.)
- **Q2 — Sidecar (SQLite) vs a table in the graph db?** ✅ **RESOLVED
  (2026-06-16): SQLite sidecar** — server backends untouched, prunable, isolated.
- **Q3 — Edge history: full event log vs periodic snapshots vs re-derive?**
  Recommend **event log + retention**; revisit if django measurements show
  blow-up. This is the main volume lever.
- **Q4 — Intra-file rename detection in v1 or follow-on?** Recommend **follow-on**
  (ship exact file-rename lineage first).
- **Q5 — `as_of` over MCP now or later?** Recommend **later**; 0.2 ships
  `ckg_history` + enriched `ckg_symbol` only, to keep the tool surface delta small.

## 9. Decision log

- **Sidecar evolution log over bi-temporal columns** — delivers all three wins
  with no rebuild and no hot-path risk (§4.2). *Accepted (pending review).*
- **Commit-validity only, not true bi-temporal** — parsed facts have no belief
  revision (spec §8). *Accepted.*
- **Rename lineage as a log `succeeds` event, not a core `EdgeKind`** — keeps
  ADR-0005's locked vocab intact. *Accepted.*
- **Denormalise `introduced/last_changed/churn/authors` onto node `attrs`** —
  free `ckg_symbol` enrichment, no schema change (reuses the feat-012 channel).
  *Accepted.*
- **`as_of` at the temporal/retriever layer, not on `GraphStore`** — stable store
  contract; server backends defer by construction. *Accepted.*

## 10. Chunk plan

One feature, `feat/009-temporal-evolution-layer`, landed as a short stack of
reviewable PRs (each green on its own):

1. **Sidecar + recorder + lifecycle** — `temporal/store.py` (SQLite schema),
   `events.py` value types, `TemporalRecorder` port + wire the optional recorder
   into `IncrementalIndexer.refresh` (open/close on add/delete/modify), config
   block, `temporal.enabled` gate. Tests: scripted-git fixture asserts events;
   refresh-overhead-off==today.
2. **Churn / authorship mining + denormalisation** — `mining.py`, aggregates
   table, `attrs.{introduced,last_changed,churn_90d,top_authors}` on refresh.
   Tests: numstat attribution math; `ckg_symbol` shows the fields. **DONE.**
   Implemented as a single batched `git log -U0` per refresh (hunk new-line
   ranges, not bare numstat totals, so churn lands on the *right* symbol via
   span overlap); a new `GraphStore.set_attrs` (Kuzu + Neo4j) does the
   denormalisation as a partial merge that preserves `origin_path` (a plain
   `add()` would have detached the node from its file). `ContextItem` gained an
   optional `temporal` dict the retriever fills from a whitelist of node attrs.
   **Known limitation (chunk-2 scope):** `introduced` is bounded by the mine
   window — for symbols older than the window it reports the window's earliest
   touching commit, not the true first commit; the accurate anchor comes from
   the sidecar `OPENED` event (chunk 1) / backfill (chunk 4). `--follow` is not
   used (batched multi-path mine), so a pre-rename history is not traced.
3. **`TemporalIndex` + history/changed_since + CLI + `ckg_history` tool** —
   read APIs, `ckg history` / `ckg changed-since`, `status` temporal block.
   Tests: history matches the scripted script; changed_since scoping. **DONE.**
   `TemporalIndex(store, graph, repo_root)` reads the sidecar; `history` prefers
   the chunk-1 `OPENED` event for `introduced` (exact) and falls back to the
   mined aggregate (window-bounded) otherwise. `changed_since(ref, scope)`
   resolves the ref via git (or accepts a raw epoch for testing), unions
   lifecycle events + mined modifications after it, newest first, glob/prefix
   scoped. `CodeGraph.history/changed_since/temporal_status` wrap it; the engine
   adds `ckg_history` (+ a `temporal` block on `ckg_status`). `SymbolHistory` /
   `Change` / `Author` value types in `temporal/events.py`. The locked v1 tool
   set grew by one (`ckg_history`) — the drift guards were updated deliberately.
4. **Backfill (`--history N`)** — `backfill.py`, resumable cursor. Tests:
   backfill N commits then `as_of` each == full index of that commit (reuse
   feat-004 equivalence per commit). **DONE.** Replays commits oldest→newest
   through the incremental pipeline against a **throwaway** kuzu+lance store; a
   `GitBlobSource` (subclasses `RepoSource`) reads file content from a commit via
   `git ls-tree`/`git show` — no checkout, working tree untouched. Per-step diff
   is `git diff --name-status -M <parent> <commit>`; a `_LifecycleOnly` recorder
   wrapper records `OPENED`/`CLOSED` but **skips churn** (replaying it would
   clobber HEAD aggregates). The earliest `OPENED` becomes the true introduction
   commit; symbols deleted before HEAD get `OPENED`+`CLOSED` (for chunk-5
   `as_of`). Resume: oldest covered commit stored as `backfilled_through` (sidecar
   `meta` table) — a re-run whose range is already covered is a no-op; events are
   idempotent so a partial run re-runs safely. `ckg index --history N|full`,
   surfaced in `ckg status`. The per-commit `as_of == full index` equivalence
   test lands with chunk 5 (which adds `as_of`).
5. **`as_of` reconstruction + retention pruning** — `TemporalIndex.as_of`,
   `retrieve(as_of=)`, `prune(horizon)`. Tests: reconstruction equivalence;
   beyond-horizon raises; prune respects retention. **DONE — completes feat-009.**
   `TemporalIndex.alive_at(C)` replays the log over the current node set: a
   symbol is alive iff its *last* lifecycle event at/before `C` is `OPENED`
   (this tolerates the spurious `OPENED` the full-index seed stamps at HEAD,
   since that event is after any historical `C`). `CodeGraph.retrieve(as_of=)`
   /`ckg query --as-of` feed the live set to the Retriever as an `allow_ids`
   filter (drops code symbols added after `C`); deleted-but-alive-at-`C` symbols
   are in the set but not materialisable from the current graph (documented
   approximation). Beyond `retention_commits` → `TemporalError` (never silently
   wrong). Retention pruning of old `CLOSED` events runs at end of index/refresh
   (`_prune_temporal`). The per-commit equivalence `alive_at(C) == full index at
   C` is asserted against a git-blob full-index oracle for every backfilled
   commit. (`as_of` over MCP stays deferred per Q5 — CLI + API only.)
6. *(follow-on, optional)* intra-file rename heuristic; `as_of`/`changed_since`
   over MCP.

Perf gate (django scale fixture, temporal on vs off) runs before merging chunk 1
and again after chunk 2.

## 11. References

- Spec `docs/features/feat-009-temporal-evolution-layer.md`.
- feat-004 design (`design-004-incremental-indexing.md`) — the writer & the
  equivalence property test we reuse per commit.
- Research §2.7 (Graphiti bi-temporal), §3.3 (temporal gap), §5 item 10.
- ADR-0001 (layering), ADR-0004 (provenance), ADR-0005 (locked vocab),
  ADR-0006 (schema/rebuild policy).
