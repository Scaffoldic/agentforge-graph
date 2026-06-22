# ENH-021: workspace-driven build commands (one manifest, one command)

| Field | Value |
|---|---|
| **ID** | ENH-021 |
| **Value/Impact** | High (the "single command" the workspace UX is built around) |
| **Effort** | M |
| **Status** | proposed |
| **Area** | `cli`, `serve/workspace` |
| **Relates to** | [THEME: org-central-knowledge](THEME-org-central-knowledge.md), ENH-022 (config cascade), ENH-023 (embed flag), ENH-026 (preflight), ENH-020 (federated serve) |

> **One-liner.** Teach the **write** verbs (`index`, `embed`, `enrich`) the
> `--workspace` flag the **read** verbs already have, plus a single
> `ckg build --workspace workspace.yaml` that builds every member (index → embed
> if enabled → enrich if enabled) in one command, with a per-member report.

## Motivation

ENH-020 made the *serve/consume* side workspace-aware: `serve-mcp`,
`services-map`, and `trace` all take `--workspace` and fan across members. But the
*build* side is still one-repo-at-a-time. To stand up a 3-repo workspace today an
operator runs `ckg index` (and `embed`, and `enrich`) **nine** times by hand,
tracking which repo needs which step. The manifest already lists the members; one
command should build them all from it.

## Current behavior

- `ckg index`, `ckg embed`, `ckg enrich` are **per-repo only**: each takes a
  positional `path` and no `--workspace` (`cli.py:580-709`). There is no batch /
  federation mode for the write verbs.
- Only the **read-only** tools take `--workspace`: `serve-mcp` (`cli.py:736-740`),
  `services-map` and `trace` (`cli.py:763-768`, where it is required).
- `WorkspaceConfig.load()` + `member_repo()` (`serve/workspace.py:49-70`) already
  resolve member paths — the iteration machinery exists, only the write verbs
  don't use it.

## Proposed change

Additive CLI surface over the existing per-repo code paths — **no engine-core
change**.

### 1. `--workspace` on the write verbs

`ckg index|embed|enrich --workspace workspace.yaml` iterates the members and runs
the existing per-repo operation for each, using each member's **resolved config**
(ENH-022 cascade) and honoring its **embed flag** (ENH-023). A member that fails
does not abort the rest; failures are collected and reported at the end with a
non-zero exit.

```bash
ckg index --workspace workspace.yaml      # structural graph for every member
ckg embed --workspace workspace.yaml      # vectors for members where embed enabled
```

### 2. `ckg build` — the one command

A new `ckg build --workspace workspace.yaml` runs the **full pipeline per member**
in dependency order: `index` → `embed` (if the member's embed is enabled) →
`enrich` (if `--enrich`/config requests it). Single-repo form `ckg build .` works
too (sugar over index+embed+enrich for one repo).

```bash
ckg build --workspace workspace.yaml          # index + embed(enabled) for all
ckg build --workspace workspace.yaml --enrich # also enrich
```

### 3. A clear per-member report

Each command ends with a summary table: member → steps run → node/vector counts →
store location (in-repo / central slug) → status (ok / skipped / failed + reason).
This is the operator's at-a-glance "is my org's knowledge built and fresh."

### 4. Preflight before any work

`ckg build`/`index`/`embed --workspace` run the ENH-026 **preflight first** across
**all** members (driver installed? creds present?) and refuse up-front with fix
guidance, rather than failing on member 2 of 3 after partial work.

## Implementation sketch

Grounded in `cli.py` and `serve/workspace.py`:

- Factor each write verb's body into a `f(repo_path, resolved_cfg, opts)` callable
  (most already are, behind the positional `path`).
- Add a shared `_each_member(workspace_path, fn)` helper in the CLI that loads the
  `WorkspaceConfig`, resolves each member's config (ENH-022), runs `fn`, and
  aggregates results/errors. The `--workspace` branch of each verb calls it.
- `ckg build` composes index → embed → enrich callables per member, gated by the
  member's embed flag (ENH-023) and the `--enrich` option.
- Reuse the existing `IndexReport` / counts for the summary table.

## Surfaces

- `--workspace` added to `ckg index`, `ckg embed`, `ckg enrich`.
- New `ckg build` (single-repo and `--workspace`).
- New `ckg status --workspace` (per-member freshness + resolved store location).
- Per-member summary report on every workspace write command.

## Suggested chunk plan (one branch, multiple commits)

1. `_each_member` iterator + result/error aggregation; add `--workspace` to
   `ckg index`; tests over a 2-member fixture (one ok, one failing → partial
   success + non-zero exit).
2. `--workspace` on `ckg embed` and `ckg enrich` (honoring ENH-023 embed flag).
3. `ckg build` composite verb (single-repo + workspace); ordering + `--enrich`.
4. `ckg status --workspace` summary + report tables; docs (getting-started
   workspace guide updated to the one-command flow).

## Acceptance criteria

- `ckg build --workspace workspace.yaml` indexes (and embeds where enabled) all
  members in one invocation; output reports each member's result.
- A single failing member does not prevent the others from building; exit code
  reflects the failure and the reason is in the report.
- `--workspace` on `index`/`embed`/`enrich` matches running the per-repo command
  on each member individually (same artifacts).
- Single-repo invocations are unchanged.

## Notes / alternatives / risks

| Concern | Note |
|---|---|
| Depends on ENH-022 | The build commands need a per-member **resolved** config (cascade). Land ENH-022 first. |
| Parallel vs. serial | v1 builds members **serially** for simple, legible output and bounded resource use; parallel build is a follow-on (note it, don't scope-creep). |
| Partial-failure semantics | Continue-on-error with an aggregated report + non-zero exit (don't abort the batch); documented and tested. |
| Read-only members | A member resolved `read_only: true` (ENH-018) is **skipped** by write verbs with a clear "consume-only" note, not an error. |

## 0.6.0 candidacy

Headline feature of the 0.6 "workspace build" epic — the single command the whole
UX is organized around. Depends on ENH-022 (cascade), ENH-023 (embed flag), and
ENH-026 (preflight).
