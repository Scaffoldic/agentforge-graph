# ENH-022: workspace-level config cascade (configure once)

| Field | Value |
|---|---|
| **ID** | ENH-022 |
| **Value/Impact** | High (the lynchpin of the workspace build experience) |
| **Effort** | M |
| **Status** | proposed |
| **Area** | `config`, `serve/workspace` |
| **Relates to** | [THEME: org-central-knowledge](THEME-org-central-knowledge.md), ENH-018 (store location), ENH-020 (federation), ENH-021 (build commands) |

> **One-liner.** Let a single config block at the workspace level (in
> `workspace.yaml`, or a sibling `ckg.yaml` next to it) supply **defaults every
> member repo inherits** — store location (in-repo vs. central vs. server),
> embed driver + credentials, read-only — so an operator configures the whole
> org **once** instead of dropping a `ckg.yaml` into every repo.

## Motivation

The org-central serve side is done (ENH-018/019/020). The **build/setup** side is
still per-repo: to point three repos at one central store, or pick one embedder
for all of them, you must place an identical `ckg.yaml` in each repo. That is
copy-paste configuration that drifts, and it pollutes repos a consumer may not
even own (ENH-024 clones third-party repos that have no place for our config).
The workspace manifest already names the members; it should also be where their
shared configuration lives.

## Current behavior

- Config discovery is **per-repo and non-cascading**. `resolve_config(config,
  repo_path)` (`config.py:39-53`) looks **only inside `repo_path`** —
  `agentforge.yaml` (with an `app:` block) → `ckg.yaml` → bare `agentforge.yaml`
  — and returns `None` (built-in defaults) if nothing is there. It does not walk
  up and has no notion of a workspace.
- `WorkspaceConfig` members carry an optional per-member `config:` path
  (`serve/workspace.py:29-46`), loaded independently per member. There is **no
  workspace-level config** that members inherit.
- Net effect: every member resolves its config in isolation. Shared settings
  (central_root, embed driver, read_only) must be physically duplicated.

## Proposed change

Introduce a **workspace defaults** layer and a deterministic resolution order.
No engine-core change — this is config plumbing in `config.py` and
`serve/workspace.py`.

### 1. Workspace-level defaults

Allow the workspace manifest to carry a `defaults:` block whose shape is the same
engine config (`store`, `embed`, `enrich`, `serve`, `read_only`):

```yaml
# MyWorkspace/ckg/workspace.yaml
workspace: my-org
defaults:
  store:
    central_root: ~/.agentforge/ckg     # all members → central, slug-namespaced
    read_only: false
  embed:
    driver: bedrock
    model: cohere.embed-v4:0
    region: us-east-1
members:
  - name: repo1
    repo: ../repo1
  - name: repo2
    repo: ../repo2
    embed: false                        # per-member override (see ENH-023)
  - name: repo3
    repo: ../repo3
    config: ../repo3/ckg.yaml           # explicit per-member file still wins
```

Equivalently, the `defaults:` may live in a standalone `ckg.yaml` sitting next to
`workspace.yaml` (the `MyWorkspace/ckg/` folder the operator already creates), so
existing single-repo config files are reused verbatim.

### 2. Resolution order (most specific wins)

For each member, the effective config is a shallow-per-block merge of:

1. **built-in defaults** (today's `_Block` defaults) — base.
2. **workspace `defaults:`** (or the sibling `ckg.yaml`) — org-wide.
3. **member-level inline overrides** in `workspace.yaml` (e.g. `embed: false`,
   or a member `store:`/`embed:` sub-block).
4. **member `config:` file**, if given — the explicit per-repo file, highest
   precedence (a repo that ships its own `ckg.yaml`/`agentforge.yaml`).

Merge is **per top-level block** (a member overriding `embed` replaces the embed
block; it does not deep-merge individual keys) — simple, predictable, matches how
the blocks are already modelled.

### 3. Reuse for single-repo

The cascade is opt-in and additive: with no `defaults:` and no workspace, every
repo resolves exactly as today (ENH-018 behavior unchanged, byte-for-byte).

## Implementation sketch

Grounded in `config.py` and `serve/workspace.py`:

- `WorkspaceConfig` gains an optional `defaults: dict` (raw config blocks) and, if
  a sibling `ckg.yaml` exists next to the manifest, folds it in as the defaults
  source.
- A new `config.resolve_member_config(workspace, member) -> EngineConfig` that
  layers the four sources above into the existing typed `_Block`s. The engine
  already builds typed config from a dict; this assembles the dict in order then
  validates once.
- The per-repo CLI entry points (`load_config`/`resolve_config` callers in
  `cli.py`) gain a path that accepts a pre-resolved config object so ENH-021's
  workspace commands feed each member its merged config without writing temp
  files.
- No change to `StoreConfig`/`EmbedConfig` schemas — they are the merge targets.

## Surfaces

- `workspace.yaml` gains `defaults:` and per-member inline `store:`/`embed:`/
  `embed: bool` overrides.
- A sibling `ckg.yaml` next to `workspace.yaml` is honored as the defaults source.
- `ckg status --workspace` (ENH-021) prints the **resolved** config per member so
  the cascade is debuggable (which source won).

## Suggested chunk plan (one branch, multiple commits)

1. `WorkspaceConfig.defaults` parsing + sibling-`ckg.yaml` discovery; tests for
   load/precedence of the raw dict.
2. `resolve_member_config` layering (built-in → defaults → inline → member file)
   producing a validated `EngineConfig`; unit tests for each precedence rung and
   per-block (not deep) merge semantics.
3. Wire into the config-loading seam used by the CLI so a resolved config object
   can be passed through (prereq for ENH-021); regression test that a lone repo
   with no workspace is unchanged.
4. `ckg status --workspace` resolved-config view + docs.

## Acceptance criteria

- A `defaults: { store: { central_root: … }, embed: { driver: … } }` in
  `workspace.yaml` applies to **every** member with no per-repo `ckg.yaml`.
- A member-level `embed: false` / `store:` block / `config:` file overrides the
  workspace default for that member only.
- A repo used **outside** any workspace resolves config byte-for-byte as today.
- Precedence is deterministic and covered by tests at each rung.

## Notes / alternatives / risks

| Concern | Note |
|---|---|
| Deep vs. shallow merge | Per-block replacement (shallow) is predictable and matches the block model; deep key-merge invites surprising partial states. Documented explicitly. |
| Secrets in `workspace.yaml` | Keep credentials as **env-var references** (`api_key_env`), never raw keys — same rule as today's `ckg.yaml`. The cascade carries the *name*, not the secret. |
| Two defaults sources | If both a `defaults:` block and a sibling `ckg.yaml` exist, define one as authoritative (recommend: inline `defaults:` wins, sibling is the fallback) and document it. |

## 0.6.0 candidacy

Core of the 0.6 "workspace build" epic. Prerequisite for ENH-021 (the build
commands need a per-member resolved config) and the config home for ENH-024's
cloned repos (which have nowhere else to carry our config).
