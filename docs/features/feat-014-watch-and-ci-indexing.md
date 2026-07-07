# feat-014: Watch mode (local) + CI-triggered central indexing

## Metadata

| Field | Value |
|---|---|
| **ID** | feat-014 |
| **Title** | Watch mode (local, conditional triggers) + CI-triggered central indexing |
| **Status** | shipped (0.6.3) |
| **Target version** | 0.6.3 |
| **Layer** | 4 adoption (freshness / ops) |
| **Area** | `ingest.watch` (watch loop + trigger policy) · `ci` (workflow scaffolder) · CLI |
| **Depends on** | feat-004 (incremental `refresh()`), feat-003 (store + `meta.json`), ENH-018 (read-only consumers), ENH-019 (store discovery) |
| **Graduated from** | [FA-005](../feature-analysis/FA-005-watch-mode-and-ci-indexing.md) |
| **Relates to** | feat-013 (`ckg setup` wires the *local* agent; `ckg ci init` wires the *central* pipeline) |

---

## 1. Why this feature

feat-004 made re-indexing cheap and incremental, but the **trigger** is still
manual — someone must run `ckg index`. That leaves the graph stale in the two
moments it matters most, one per deployment topology:

- **Local dev:** an agent working a repo wants the graph to track the
  developer's edits without anyone remembering to re-index — but a naive
  "re-index on every save" loop would thrash on burst-saves and burn
  embedding/LLM spend. The real need is **conditional, configurable triggers**.
- **Central / shared:** a server-backed index (`store.central_root`, ENH-018)
  is the authoritative, read-mostly graph many agents consume. Its freshness
  must come from a **deterministic CI trigger** (merge to `main`, nightly),
  *never* from developers' machines.

These are **different freshness mechanisms for different stores** and must not
share a trigger path. feat-014 ships both, with a hard guardrail keeping them
separate.

## 2. Why it ships in the engine

- `refresh()` is already the right primitive (feat-004); only the trigger is
  missing. Watch and CI are thin orchestration over it — building them in each
  consumer would re-invent staleness logic.
- **The local/central split is a correctness boundary, not a preference.**
  Letting watch write a shared store creates write contention and
  non-deterministic graphs; the engine *enforces* the split (§8), so it lives
  in core.
- A deterministic central index (CI-as-sole-writer) is what makes read-only
  consumers (ENH-018) trustworthy.

Watch stays framework-free (ADR-0001): it's `ingest.watch`, orchestrating the
deterministic `CodeGraph.refresh()`; no `agentforge` import.

## 3. How consumers benefit

- **Local developer:** `ckg watch` — the agent's view tracks edits
  automatically, gated by a trigger policy you choose.
- **Team / org:** `ckg ci init` scaffolds a workflow; the central index
  refreshes deterministically on merge-to-`main`, and every agent querying it
  (read-only) sees a known commit.
- **Both at once (ideal):** local watch keeps *your* branch fresh in `.ckg/`;
  the central index serves canonical `main` read-only — neither pollutes the
  other.

## 4. Specification

### 4.1 CLI

```bash
ckg watch                      # start the watch loop (configured trigger policy)
ckg watch --trigger on-idle --idle-ms 3000
ckg watch --trigger on-commit  # refresh on git commit / branch switch only (default)
ckg watch --once               # run one refresh if dirty, then exit (no loop)
ckg watch --status             # trigger mode · store · last indexed commit · dirty?

ckg ci init                    # scaffold .github/workflows/ckg-index.yml
ckg ci init --print            # print the workflow to stdout, write nothing
ckg ci init --mode full --embed --enrich --force
```

### 4.2 Contract

- **`ckg watch`** — runs feat-004 `refresh()` on the configured trigger.
  **Refuses** (clear error, exit 2) when the resolved store is central
  (`store.central_root`) or read-only (`store.read_only` / `--read-only` /
  `$CKG_READ_ONLY`). Requires the `[watch]` extra (`watchfiles`); a missing
  dependency is a clear install hint, not a traceback.
- **`ckg ci init`** — writes a self-contained GitHub Actions workflow (managed
  marker comment; idempotent; refuses to clobber an unmanaged file without
  `--force`). GitHub first; the scaffolder is provider-pluggable like feat-013's
  agent adapters.
- **Trigger policy** is a locked enum (§4.4). Adding a policy is a minor change.

### 4.3 Watch mechanics

1. **Filesystem events** (`watchfiles`, native fs-watch) over the repo,
   filtered by the same excludes the indexer uses (`.gitignore`-style globs +
   `.ckgignore` + `watch.ignore`); `.ckg/`, `.git/`, `node_modules`, `.venv`
   never trigger.
2. **Trigger policy** decides *when* a batch of events becomes a refresh:
   - `on-commit` **(default)** — refresh only on git events (`.git/HEAD` +
     refs change: a commit or branch switch). Ordinary saves do **not** trigger.
     Zero churn while editing; the graph tracks committed state.
   - `on-idle` — refresh after editing goes quiet for `idle_ms`.
   - `on-save` — refresh after a `debounce_ms` window (coalesce burst-saves).
   - `interval` — periodic refresh if dirty, every `interval_ms`.
   - `manual` — off (explicit `ckg index` only).
3. **Branch gating** — `branches.include`/`exclude` globs decide whether to
   watch on the current branch (default: watch all but `main` / `release/*`).
   Re-evaluated on branch switch.
4. **Cheap by default** — a watch refresh does the **structural** re-extract +
   re-resolve only. Embeddings and LLM enrichment do **not** run per trigger
   (`embed_on_watch` / `enrich_on_watch` off); the dirty set (feat-004) drains
   on the next explicit `ckg embed` or when `embed_on_watch` is enabled.
5. **Single-flight** — the loop refreshes sequentially; events arriving during a
   refresh coalesce into the next batch (no pile-up).

### 4.4 Config (`watch:` block)

```yaml
watch:
  enabled: false          # opt-in; LOCAL EMBEDDED STORE ONLY (refuses central/read_only)
  trigger: on-commit      # on-commit | on-idle | on-save | interval | manual
  debounce_ms: 1000       # on-save: coalesce bursts
  idle_ms: 3000           # on-idle: quiet period before refresh
  interval_ms: 60000      # interval: periodic refresh if dirty
  branches:
    include: ["*"]
    exclude: ["main", "release/*"]
  ignore: []              # extra globs beyond the indexer's excludes
  embed_on_watch: false   # keep watch cheap: defer embeddings
  enrich_on_watch: false  # never auto-run LLM enrichment on a trigger
```

CI behavior is configured by the scaffolded workflow's inputs, not this block.

### 4.5 Central CI indexing

`ckg ci init` scaffolds `.github/workflows/ckg-index.yml`: installs
`agentforge-graph`, runs `ckg index` against the central store, on
push-to-`main` + nightly + manual dispatch. A `concurrency.group` ensures one
writer at a time (no central write races). Incremental works directly — the
central store's `meta.json` indexed-commit lets CI refresh only the diff.
Embedding/enrichment run server-side in CI (creds from secrets) so consumers
read a complete graph.

## 5. Test strategy

- **Trigger-policy units:** simulated event streams + injected clock assert
  `on-save`/`on-idle` debounce, `on-commit` ignores saves and fires on a git
  event, `interval` fires only when dirty, `manual` never fires.
- **Central-refusal (load-bearing):** `ckg watch` against a central / read-only
  store fails fast, writes nothing.
- **Cheap-by-default:** a watch refresh re-extracts structure but does not embed
  unless `embed_on_watch`.
- **Branch-gating:** inactive on an excluded branch; switching to an included
  branch activates it.
- **Single-flight:** a burst during an in-flight refresh coalesces to one
  follow-up refresh.
- **Ignore:** edits under excludes / `watch.ignore` / `.ckg/` trigger nothing.
- **CI scaffold:** renders a valid workflow with the repo's store config;
  idempotent; refuses to clobber unmanaged; `--print` writes nothing.

## 6. Out of scope

- A long-running multi-repo indexing **daemon** (watch is per-repo).
- CI providers beyond GitHub at first (pluggable, like feat-013 adapters).
- A separately-published `agentforge/ckg-index-action` (the scaffolded workflow
  is self-contained via `pip install` + `ckg index`; a versioned Action is a
  follow-up).
- Pushing local watch results *into* the central store — explicitly forbidden.

## 7. The mental model (the feature in one glance)

| | Local dev | Central / shared |
|---|---|---|
| Store | embedded `.ckg/` | server backend (`central_root`) |
| Writer | the developer (single) | **CI only** (single authoritative) |
| Trigger | **`ckg watch`** (opt-in, conditional) | **CI workflow** on merge / nightly |
| Reflects | uncommitted working edits | committed `main` (deterministic) |
| Consumers | that developer's agent | many agents, **read-only** (ENH-018) |
| Cost | incremental, structural-only by default | incremental per run; embeds server-side |

## Implementation status

Shipped in 0.6.3. `agentforge_graph.ingest.watch` (policy · git-watch · branch
gate · guard · watchfiles loop) + `agentforge_graph.ci` (workflow scaffolder);
`ckg watch` / `ckg watch --status` / `ckg ci init`; `watch:` config block;
`[watch]` PyPI extra. See [design-014](../design/design-014-watch-and-ci-indexing.md)
and guide [`12-watch-and-ci-indexing.md`](../guides/12-watch-and-ci-indexing.md).
