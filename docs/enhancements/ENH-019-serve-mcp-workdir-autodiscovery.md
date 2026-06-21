# ENH-019: `serve-mcp` working-directory auto-discovery

| Field | Value |
|---|---|
| **ID** | ENH-019 |
| **Value/Impact** | Medium (removes per-repo friction at org scale) |
| **Effort** | S |
| **Area** | `cli`, `serve`, `config` |
| **Relates to** | [THEME: org-central-knowledge](THEME-org-central-knowledge.md), ENH-006 (CLI path consistency), ENH-020 (federation) |

> **One-liner.** Let `ckg serve-mcp` (and the other verbs) **discover the index
> from the current directory** — walk up from cwd to the nearest `.ckg/` /
> config, like `git` finds `.git` — so an agent or developer working *inside* a
> repo gets the right knowledge with **no `--repo`**.

## Motivation

In a Claude Code session you start *in a repo*. Today you must still tell the MCP
server which repo it serves via `--repo /abs/path`, registered ahead of time. At
one repo that's a paper cut; across an org's many repos it's real friction and a
config-management chore (one MCP registration per repo, each with a hard-coded
absolute path). The natural expectation — "serve the repo I'm in" — should just
work.

## Current behavior

- Every verb resolves the repo path from an explicit arg, defaulting to `"."`:
  ```python
  args.path = positional or --path/--repo alias or "."   # cli.py:41-44
  ```
- `"."` means **literal cwd**, not "the repo containing cwd." If you're in
  `repo/src/pkg/` there's no `.ckg` there, so it fails or builds a stray index in
  the wrong place.
- `serve_mcp(repo_path, …)` opens exactly that path (`serve/server.py:93`). No
  upward search, no discovery.
- `config.resolve_config(config, repo_path)` already discovers `agentforge.yaml`/
  `ckg.yaml` **in `repo_path`** (`config.py:39`) — but only at that one level, not
  by walking up.

## Proposed change

Add **upward discovery** of the repo root, mirroring git, used when no explicit
path is given:

1. New `cli.discover_repo_root(start: Path) -> Path | None`: walk from `start`
   upward to the filesystem root, returning the first dir that contains **any**
   of: `.ckg/`, `agentforge.yaml`, `ckg.yaml`, or `.git/`. Prefer `.ckg/` (an
   actual index) over `.git/` (an un-indexed repo, which yields a clear "run
   `ckg index` first" message).
2. Path resolution precedence becomes:
   **explicit positional > `--path`/`--repo` > discovered-root-from-cwd >
   error** (replacing the silent `"."` default). When discovery succeeds, log the
   resolved root so it's never surprising.
3. Apply uniformly via the existing `_resolve_repo_path` helper so **all** verbs
   (`serve-mcp`, `query`, `map`, `routes`, …) get it at once.

Combined with **ENH-018**'s `central_root`, discovery also covers the central
case: discover the repo root from cwd → derive its `repo_key` → open the central
store for *this* repo. So "I'm in service-A, give me service-A's central
knowledge" needs no flags.

## Implementation sketch

- `discover_repo_root` is ~15 lines, stdlib-only (ADR-0001 ok — it's CLI, not
  engine core).
- `_resolve_repo_path` (cli.py:41) changes its fallback: instead of `"."`, call
  `discover_repo_root(Path.cwd())`; if `None`, emit a precise error
  (`no .ckg/agentforge.yaml/.git found from <cwd> upward — pass a path or run ckg index`).
- For `serve-mcp` specifically: a bare `ckg serve-mcp` (no `--repo`) now serves
  the discovered repo — the common agent registration becomes
  `ckg serve-mcp` with the **working directory** set by the MCP client.
- Tests: cwd in a subdir resolves to the repo root; cwd with no repo errors
  cleanly; explicit `--repo` still wins.

## Surfaces

- `ckg serve-mcp` (no args) → serves the repo containing cwd.
- All verbs gain the same discovery; `ckg status` already prints the resolved
  root (extended by ENH-018) so the chosen repo is visible.
- A one-line note in `01-getting-started.md` and `10-using-over-mcp.md`.

## Acceptance criteria

- `cd repo/src/pkg && ckg serve-mcp` serves `repo` (discovered), not `pkg`.
- No `.ckg`/config/`.git` upward from cwd → a clear, actionable error (never a
  stray index in the wrong dir).
- Explicit `--repo`/positional path is unchanged and still takes precedence.

## Notes / alternatives / risks

| Concern | Note |
|---|---|
| Surprising "which repo am I serving?" | Always log the resolved root; `ckg status` shows it. Discovery never *writes* without a verb that writes. |
| Monorepo with nested `.ckg` | First match walking up wins (nearest index). Document; a future `--repo-root` override exists via the explicit path. |
| Backwards compat of the `"."` default | A bare verb in a repo dir still resolves to that repo (cwd is the repo root → discovery returns it). Behavior only *improves* for subdirs and only *errors* where today it silently misbehaved. |

## 0.4.x / 0.5 candidacy

Cheap, isolated, high daily-ergonomics value; independent of ENH-018/020. Good
quick win — ship whenever.
