# ENH-026: fail-fast config preflight + `ckg doctor`

| Field | Value |
|---|---|
| **ID** | ENH-026 |
| **Value/Impact** | High (turns deep runtime ImportErrors into actionable up-front guidance) |
| **Effort** | S–M |
| **Status** | proposed |
| **Area** | `embed/registry`, `enrich`, `store/registry`, `config`, `cli` |
| **Relates to** | [THEME: org-central-knowledge](THEME-org-central-knowledge.md), ENH-003 (provider registry), ENH-021 (workspace build), ENH-023 (embed flag) |

> **One-liner.** Validate the consumer's resolved config **before** any indexing
> or embedding work — selected driver importable? required credentials present? —
> and **fail fast with the exact fix** (e.g. *"run `pip install
> 'agentforge-graph[bedrock]'`"*), surfaced via a `ckg doctor` command and a
> preflight gate on the write verbs.

## Motivation

A consumer who sets `embed.driver: bedrock` but installs plain
`agentforge-graph` (no `[bedrock]` extra) gets no early warning. The first sign
of trouble is a raw `ModuleNotFoundError` thrown **deep inside an index/embed
run**, after work has begun, with a stack trace and no guidance. The config is
knowable up front; the failure should be too — and it should **teach** the fix,
not just abort.

## Current behavior

- Driver builders **lazy-import** their SDK *inside the builder*, so the failure
  only happens when the provider is first constructed mid-run. E.g.
  `embed/registry.py` builtins are `{fake, bedrock, openai}`
  (`embed/registry.py:56-60`); `_build_bedrock` imports the Bedrock SDK only when
  called; `_build_openai` (`registry.py:44-53`) imports `openai` lazily.
- Missing **credentials** are likewise discovered late — the OpenAI client reads
  `api_key_env` at call time (`embed/openai.py:42-52`); Bedrock fails when the
  AWS chain can't resolve, mid-embed.
- There is **no `ckg doctor` / preflight** verb and no dry-run validation: the
  only way to learn the config is wrong is to run the full pipeline and watch it
  crash.

## Proposed change

A **preflight** validation pass plus a dedicated command — additive, no
engine-core change.

### 1. Provider "availability" probes (cheap, no model call)

Each registry exposes a way to check a selected driver **without constructing the
heavy client or calling the model**:

- **importable?** — can the required module be imported (the extra installed)? If
  not, raise a typed `ProviderUnavailable` carrying the **install command** for
  that extra.
- **credentials present?** — the named env var set (`api_key_env` /
  `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`), or the AWS chain resolvable for
  bedrock. Missing creds are a **clear, fixable** error (or warning for the
  no-op cases), never a stack trace.

These probe the same registries (`embed`, `enrich`, `store` backends) so one pass
covers embedder, judge/summarizer, and storage driver.

### 2. Fail-fast gate on write verbs

`ckg index`/`embed`/`enrich`/`build` run preflight **before** opening the store or
reading files, and refuse with the fix when config is unsatisfiable:

```
✗ embed.driver = "bedrock" but the Bedrock extra is not installed.
  Fix:  pip install 'agentforge-graph[bedrock]'

✗ enrich.provider = "anthropic" but $ANTHROPIC_API_KEY is not set.
  Fix:  export ANTHROPIC_API_KEY=sk-ant-...
```

Only the drivers the run will actually use are checked (an embed run with embed
disabled per ENH-023 skips the embedder probe).

### 3. `ckg doctor` (a.k.a. `ckg check`)

A standalone command that runs the full preflight and prints a readiness report —
**without** indexing anything — for one repo or a whole workspace:

```bash
ckg doctor .                          # validate this repo's resolved config
ckg doctor --workspace workspace.yaml # validate every member, report all at once
```

It reports, per scope: resolved config source, selected drivers, install status,
credential status, store reachability — green/red with the fix for each red.

### 4. Workspace-wide, all-at-once

In workspace mode the preflight checks **every member up front** and reports
**all** problems together (don't fail on member 1 and hide members 2–3). This is
the gate ENH-021's build commands call before doing any work.

## Implementation sketch

- Add a `check(cfg) -> Availability` (import + creds probe) to the embedder,
  judge/summarizer, and store-backend registries, each knowing its extra's
  **pip install string** and required env var(s). Keep it import-light: probe with
  `importlib.util.find_spec`, don't import the heavy SDK.
- A `config.preflight(resolved_cfg, *, need_embed, need_enrich) -> list[Problem]`
  that aggregates the relevant probes for what the run will do.
- CLI: a `_preflight_or_exit(...)` helper called at the top of the write verbs;
  a new `ckg doctor` command rendering the report; `--workspace` aggregates across
  members (reusing ENH-021's `_each_member`).
- A typed `ProviderUnavailable(extra, install_cmd)` raised by registry resolution
  so even a non-preflighted path (in-process API) fails with the fix, not a bare
  ImportError.

## Surfaces

- `ckg doctor` / `ckg check` (single repo + `--workspace`).
- Preflight gate auto-runs on `index`/`embed`/`enrich`/`build`.
- Typed `ProviderUnavailable` with install command (also helps the in-process API).
- `--skip-preflight` escape hatch for advanced users (documented, off by default).

## Suggested chunk plan (one branch, multiple commits)

1. Registry `check()` probes + `ProviderUnavailable(extra, install_cmd)` for the
   embedder registry (bedrock/openai); unit tests with the extra absent (probe
   reports unavailable; resolution raises the typed, install-bearing error).
2. Extend probes to enrich (anthropic/bedrock) + store backends
   (neo4j/pgvector/surrealdb) including the credential checks.
3. `config.preflight()` aggregator + `_preflight_or_exit` gate on the write verbs;
   tests (run refused early with the right fix, no partial work).
4. `ckg doctor` command (single + `--workspace`, all-at-once report); docs +
   getting-started "verify your setup" step.

## Acceptance criteria

- `embed.driver: bedrock` without the extra → `ckg index/embed/build` **refuses
  before any work** with the exact `pip install 'agentforge-graph[bedrock]'` fix.
- Missing required credential for the selected provider → clear, fixable message
  (not a stack trace).
- `ckg doctor` validates config and reports readiness **without** indexing.
- In `--workspace` mode, **all** members' problems are reported in one pass.
- A correctly-configured run is unaffected (preflight passes silently/quickly).

## Notes / alternatives / risks

| Concern | Note |
|---|---|
| Don't make probes expensive | Use `find_spec` and env-var presence, not a live model call. A *connectivity* check (e.g. real Bedrock ping) is opt-in (`ckg doctor --live`), not the default gate. |
| Knowing the install string | Each registry entry owns its extra name → one source of truth for `extra → pip command`, reused by the error and `doctor`. |
| In-process consumers | The typed `ProviderUnavailable` (vs. bare ImportError) means framework agents using `code_graph_tools(...)` also get the fix, not just the CLI. |
| Escape hatch | `--skip-preflight` for users who know better / unusual setups; never on by default. |

## 0.6.0 candidacy

High-value ergonomics that the user explicitly requested ("fail fast + guide them
with a kill switch"). Independent of the others but pairs naturally with ENH-021's
workspace build (all-at-once member preflight). Land early in the epic.
