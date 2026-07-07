# design-014: Watch mode + CI-triggered central indexing

Mirrors [feat-014](../features/feat-014-watch-and-ci-indexing.md). The *how*:
file layout, types, resolved decisions.

## Guiding constraints

- **Framework-free** (ADR-0001): the watch package lives under
  `ingest.watch`, orchestrating the deterministic `CodeGraph.refresh()`. No
  `agentforge` import.
- **The trigger core is pure and clock-injected** so the whole policy matrix is
  unit-tested with no filesystem, no sleeps, no `watchfiles`. The fs-watch loop
  is a thin adapter over that core.
- **The local/central split is enforced in code**, not documented — `ckg watch`
  refuses a central/read-only store before opening anything.

## Package layout

```
src/agentforge_graph/ingest/watch/
  __init__.py       # exports: Event, EventKind, TriggerPolicy, WatchSettings,
                    #          WatchGuardError, ensure_watchable, branch_active,
                    #          WatchRunner, WatchStatus, run_watch
  policy.py         # Event, EventKind, WatchSettings, TriggerPolicy (pure core)
  gitwatch.py       # head_ref(repo) -> str; branch_active(branch, inc, exc)
  guard.py          # WatchGuardError; ensure_watchable(store_cfg, read_only)
  filter.py         # WatchFilter: classify a changed path (ignored/git/source)
  runner.py         # WatchRunner (loop) + WatchStatus + run_watch()
  source.py         # watchfiles-backed async event source (lazy import)

src/agentforge_graph/ci/
  __init__.py       # exports: scaffold_workflow, render_workflow, CiInitResult
  scaffold.py       # provider dispatch + managed-marker write/idempotency
  github.py         # the GitHub Actions workflow template
```

## The trigger core (`policy.py`)

```python
class EventKind(Enum):
    FILE = "file"       # a source file changed (already ignore-filtered)
    GIT = "git"         # .git/HEAD or refs changed (commit / branch switch)

@dataclass(frozen=True)
class Event:
    kind: EventKind
    path: str = ""

@dataclass(frozen=True)
class WatchSettings:               # resolved from WatchConfig + CLI overrides
    trigger: str                    # on-commit | on-idle | on-save | interval | manual
    debounce_ms: int
    idle_ms: int
    interval_ms: int
```

`TriggerPolicy` holds `_pending: bool` and timestamps (`_last_event`,
`_last_git`, `_last_fire`), all in **seconds** (float). Methods, all taking an
injected `now: float`:

- `observe(event, now)` — decide if the event counts for this mode:
  - `manual`: ignore everything.
  - `on-commit`: ignore FILE; on GIT set pending + `_last_git = now`.
  - `on-idle` / `on-save`: FILE and GIT set pending + `_last_event = now`
    (a commit is a real change too).
  - `interval`: any event sets pending + `_last_event = now`.
- `due(now) -> bool` — should a refresh fire now?
  - `on-commit`: pending and `now - _last_git >= debounce_ms` (small debounce
    coalesces a branch-switch storm).
  - `on-idle`: pending and `now - _last_event >= idle_ms`.
  - `on-save`: pending and `now - _last_event >= debounce_ms`.
  - `interval`: pending and `now - _last_fire >= interval_ms`.
  - `manual`: always False.
- `next_due_in(now) -> float | None` — seconds until `due` flips True given
  current pending state, or `None` when nothing is pending (wait indefinitely).
  Drives the loop's timeout so the idle/interval window elapses even with no new
  events.
- `reset(now)` — clear pending, `_last_fire = now`. Called after each refresh.

This is the entire testable surface: feed `observe`/`due`/`next_due_in` a
scripted clock and assert timing, with no I/O.

## The loop (`runner.py`)

`WatchRunner` is constructed with the resolved settings, a `refresh` coroutine,
a `now` callable (default `time.monotonic`), and a `pull` coroutine
(`async (timeout: float | None) -> Event | None`, `None` = timeout elapsed). The
default `pull` wraps `source.py` (watchfiles); tests inject a scripted `pull`.

```
run():
  active = branch_active(current_branch, include, exclude)   # may be False → idle-watch for a switch
  while not stopped:
    timeout = policy.next_due_in(now())
    ev = await pull(timeout)          # None on timeout
    t = now()
    if ev and ev.kind is GIT:
      # branch switch may flip the gate
      active = branch_active(current_branch, include, exclude)
    if active and ev:
      policy.observe(ev, t)
    if active and policy.due(t):
      await self._do_refresh()        # CodeGraph.refresh() [+ embed if embed_on_watch]
      policy.reset(now())
```

**Single-flight** falls out of the sequential `await`: events during a refresh
are buffered by watchfiles / the OS and observed on the next `pull`.

`--once` short-circuits the loop: one `CodeGraph.refresh()` (+ optional embed),
print the report, exit — no watcher constructed. `--status` reads `IndexMeta`
(indexed commit + mtime) + git head to print trigger mode · store · last commit
· dirty?, needing no running process (no IPC).

## Guard (`guard.py`)

```python
def ensure_watchable(store_cfg: StoreConfig, read_only: bool) -> None:
    if store_cfg.central_root:
        raise WatchGuardError("central store … build it in CI (ckg ci init)")
    if read_only or store_cfg.read_only:
        raise WatchGuardError("read-only store … watch only a writable embedded index")
```

The CLI handler calls this first and maps `WatchGuardError` to a stderr message
+ exit 2, reusing the ENH-018 read-only wiring already in `cli.py`.

## Ignore filter (`filter.py`)

`WatchFilter.classify(rel_path) -> EventKind | None`:
- path under `.git/` → is it `HEAD` or under `refs/` or `packed-refs`? → `GIT`;
  any other `.git/` churn → `None` (ignored).
- matches an exclude glob (`IngestConfig.exclude` ∪ `DEFAULT_EXCLUDES` ∪
  `watch.ignore`) via `PurePosixPath(rel).full_match(glob)` → `None`.
- otherwise, does a language pack claim the extension? no → `None`; yes → `FILE`.

Reuses the exact `full_match` matching `RepoSource` uses, so what watch reacts to
== what the indexer would ingest. `watchfiles` is given this as its filter so
ignored churn never even wakes the loop.

## `watchfiles` dependency (`source.py`, `[watch]` extra)

`watchfiles` (Rust `notify`, cross-platform, async `awatch`) is a new optional
dependency behind a `[watch]` extra — base install and CI stay lean, mirroring
`[rerank]`. `source.py` lazy-imports it; a missing dep raises a clear
"`pip install agentforge-graph[watch]`" hint (not a traceback). Where events are
unreliable, `watchfiles` already falls back to polling internally.

## CI scaffolder (`ci/`)

`ckg ci init` renders `.github/workflows/ckg-index.yml` from `github.py`: a
self-contained workflow (`pip install agentforge-graph[<extras>]` + `ckg index`
against `${{ secrets.CKG_CENTRAL_STORE_URL }}`), triggered on push-to-`main`,
nightly cron, and manual dispatch, with a `concurrency.group: ckg-central-index`
(single writer). The file opens with a managed marker comment
(`# managed-by: agentforge-graph`); `scaffold.py` refuses to overwrite a file
lacking the marker unless `--force`, is idempotent when the content matches, and
supports `--print` (render to stdout, write nothing) — the same discipline as
feat-013's `_managed_by` merge. A separately-versioned `ckg-index-action` is
explicitly out of scope (feat-014 §6); the self-contained workflow ships today.

## Config (`WatchConfig`, in `config.py`)

A new `_Block` with `KEY = "watch"` and a nested `BranchGate(include, exclude)`
(pydantic sub-model like `GraphCfg`). Auto-discovered by `block_keys()`. CLI
flags (`--trigger`, `--idle-ms`, `--debounce-ms`, `--interval-ms`, `--once`,
`--status`, `--embed`) override the loaded block into a `WatchSettings`.

## Test plan

`tests/watch/`: `test_policy.py` (the full trigger matrix, injected clock),
`test_filter.py` (git-meta vs source vs ignored), `test_gitwatch.py`
(branch_active globs), `test_guard.py` (central/read-only refusal),
`test_runner.py` (scripted `pull` + fake `refresh`: single-flight coalescing,
branch-gate activation, `--once`), `test_cli_watch.py` (flag→settings, guard
exit 2, `--status`). `tests/ci/test_scaffold.py` (render validity, idempotency,
clobber refusal, `--print`). Fake embedder / `asyncio_mode=auto` throughout.
