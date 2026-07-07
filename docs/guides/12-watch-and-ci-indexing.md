# 12 — Watch mode & CI indexing (keep the graph fresh)

> **TL;DR** — Indexing is cheap and incremental (feat-004), but you still have to
> *trigger* it. feat-014 adds the two automatic triggers: **`ckg watch`** keeps
> your local working copy fresh; a **`ckg ci init`** workflow keeps the shared /
> central index fresh. They target different stores and the engine keeps them
> apart — a developer's watch loop can never write the central graph.

This guide is both the how-to and the operational reference. If you only ever
run `ckg index` by hand, you don't need it — reach for it when you want the graph
to track edits without remembering to re-index.

---

## The one-glance mental model

| | Local dev | Central / shared |
|---|---|---|
| Store | embedded `.ckg/` | server backend (`store.central_root`) |
| Writer | you (single) | **CI only** (single authoritative) |
| Trigger | **`ckg watch`** (opt-in, conditional) | **CI workflow** on merge / nightly |
| Reflects | your uncommitted working edits | committed `main` (deterministic) |
| Consumers | your agent | many agents, **read-only** (ENH-018) |
| Cost | incremental, structural-only by default | incremental per run; embeds server-side |

The split is load-bearing: `ckg watch` **refuses** to run against a central or
read-only store. Central freshness must come from CI so every consumer sees a
known commit.

---

## Part A — Local watch mode (`ckg watch`)

### Install & run

Watch needs a cross-platform file watcher, shipped as an optional extra:

```bash
pip install "agentforge-graph[watch]"     # or: uv sync --extra watch
ckg watch                                  # start watching the current repo
```

`ckg watch` re-runs the incremental refresh whenever its **trigger** says a
change is worth re-indexing. It is **off until you run it** (or set
`watch.enabled`), and it only ever writes your local `.ckg/`.

### "Will it re-index on every save?" — no, unless you ask

The default trigger is **`on-commit`**: the graph refreshes when you commit or
switch branches, and ordinary file saves do nothing. Zero churn while you type;
the graph tracks committed state. Pick a different trigger when you want the
agent to see uncommitted work:

| Trigger | Fires when… | Use it for |
|---|---|---|
| `on-commit` *(default)* | you commit / switch branch | predictable, no mid-edit churn |
| `on-idle` | editing goes quiet for `idle_ms` (3s) | reflect WIP without per-save churn |
| `on-save` | saves stop for `debounce_ms` (1s) | aggressively track every saved edit |
| `interval` | periodically, if anything changed | steady cadence regardless of activity |
| `manual` | never (explicit `ckg index` only) | turn the loop off but keep config |

```bash
ckg watch --trigger on-idle --idle-ms 3000
ckg watch --trigger on-save --debounce-ms 500
ckg watch --once            # one refresh if dirty, then exit (handy in scripts)
ckg watch --status          # trigger · store · last indexed commit · dirty?
```

### It stays cheap

A watch refresh does the **structural** re-extract + re-resolve only.
**Embeddings and LLM enrichment are not run on a trigger** — they'd cost money on
every save. The changed symbols are dirty-tracked; drain them when you choose:

```bash
ckg embed .                 # embed what watch dirtied, on your terms
ckg watch --embed           # or: also drain embeddings on each refresh
```

Bursts coalesce (debounce + single-flight): a flurry of saves becomes one
refresh, and events during an in-flight refresh fold into the next one.

### Branch gating

By default watch is active on feature branches and **skips `main` / `release/*`**
— you rarely want to re-index over a protected branch you're not editing. On a
branch switch the gate is re-evaluated; `ckg watch --status` tells you whether
watch is active on the current branch.

### Configuration (`watch:` block)

```yaml
watch:
  enabled: false          # opt-in; LOCAL EMBEDDED STORE ONLY
  trigger: on-commit      # on-commit | on-idle | on-save | interval | manual
  debounce_ms: 1000       # on-save: coalesce burst-saves
  idle_ms: 3000           # on-idle: quiet period before a refresh
  interval_ms: 60000      # interval: periodic refresh if dirty
  branches:
    include: ["*"]
    exclude: ["main", "release/*"]
  ignore: []              # extra globs beyond the indexer's excludes
  embed_on_watch: false   # keep watch cheap: defer embeddings
  enrich_on_watch: false  # never auto-run LLM enrichment on a trigger
```

CLI flags (`--trigger`, `--idle-ms`, `--debounce-ms`, `--interval-ms`,
`--embed`) override the block for one run.

### What it ignores

Watch reacts to exactly what the indexer would ingest — source files a language
pack claims, honoring the same excludes plus `watch.ignore`. It never triggers on
`.ckg/`, `.git/` internals, `node_modules`, `.venv`, or non-source files. It does
watch `.git/HEAD` + refs — that's how `on-commit` sees commits and branch
switches.

---

## Part B — Central indexing in CI (`ckg ci init`)

A shared index that many agents consume `--read-only` must be built by **one
authoritative writer on a deterministic trigger** — CI — never from developers'
machines. Scaffold that:

```bash
ckg ci init                          # write .github/workflows/ckg-index.yml
ckg ci init --print                  # preview, write nothing
ckg ci init --mode full --extra bedrock --enrich
ckg ci init --force                  # replace an existing (unmanaged) file
```

The generated workflow:

- runs on **push to `main`**, a **nightly cron**, and manual dispatch;
- installs `agentforge-graph` and runs `ckg index` (+ `ckg embed`) against your
  central store;
- uses a **`concurrency` group** so exactly one indexing job writes at a time —
  no central write races;
- is **incremental** — the central store's `meta.json` indexed-commit means CI
  refreshes only the diff since the last run.

It opens with a managed-marker comment; re-running `ckg ci init` is idempotent
and won't clobber a workflow you've hand-edited unless you pass `--force`.

### Wiring the central store

1. Configure the shared store in your committed `agentforge.yaml`
   (`store.central_root` + the graph/vectors backend — see
   [guide 09](09-storage-backends.md) and
   [getting started 3](getting-started/3-central-store.md)).
2. Add the provider creds your embed/enrich step needs as repo **secrets**
   (e.g. `AWS_*` for Bedrock, `OPENAI_API_KEY`), plus `CKG_CENTRAL_STORE_URL`
   if your backend uses one.
3. Commit the workflow. On the next merge to `main`, CI refreshes the central
   index and every read-only consumer sees the new commit.

---

## Both at once (the ideal)

Local watch keeps *your* working branch fresh in `.ckg/`; the CI workflow serves
canonical `main` read-only to the team. Neither pollutes the other — the engine
guarantees it. This pairs with [`ckg setup`](11-agent-auto-configuration.md),
which wires your *local* agent to the CKG; `ckg ci init` wires the *central*
pipeline.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `ckg watch` exits 2: "refusing to watch a central store" | Your store is `central_root` — build it in CI (`ckg ci init`), not a watch loop. |
| `ckg watch` exits 2: "read-only store" | `store.read_only` / `--read-only` / `$CKG_READ_ONLY` is set; watch a writable embedded index. |
| `ckg watch` errors asking for the `watch` extra | `pip install "agentforge-graph[watch]"`. |
| Watch seems idle while editing | Default `on-commit` ignores saves — commit, or use `--trigger on-idle`. |
| `--status` says "branch gated out" | You're on `main`/`release/*` (excluded by default); switch branches or edit `watch.branches`. |
| Search returns stale results after a watch refresh | Watch is structural-only by default — run `ckg embed .` (or `--embed`). |
